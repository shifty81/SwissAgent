"""SwissAgent HTTP API server (FastAPI)."""
from __future__ import annotations
import asyncio
import datetime
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from core.config_loader import ConfigLoader
from core.logger import get_logger, setup_logging
from core.module_loader import ModuleLoader
from core.permission import PermissionSystem
from core.plugin_loader import PluginLoader
from core.task_runner import TaskRunner
from core.tool_registry import ToolRegistry

logger = get_logger(__name__)

# Directories the GUI file browser is allowed to expose.
_BROWSER_ROOTS = {"workspace", "projects", "plugins", "templates"}

# Directories allowed as working directories for terminal/build commands.
_BUILD_ROOTS = {"workspace", "projects"}

# Directories to skip when searching files.
_SEARCH_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".swissagent", "build", "dist"}

# File extensions to skip when searching (binary/media files).
_SEARCH_SKIP_EXTS = {".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".ttf"}

# Build-system detection table: (marker_file, system_name, build_cmd, test_cmd)
_BUILD_DETECTORS: list[tuple[str, str, str, str]] = [
    ("CMakeLists.txt",  "cmake",  "cmake -B build -DCMAKE_BUILD_TYPE=Debug && cmake --build build", "ctest --test-dir build --output-on-failure"),
    ("package.json",    "npm",    "npm install && npm run build",      "npm test"),
    ("Cargo.toml",      "cargo",  "cargo build",                       "cargo test"),
    ("pyproject.toml",  "python", f'"{sys.executable}" -m build',      f'"{sys.executable}" -m pytest -v'),
    ("setup.py",        "python", f'"{sys.executable}" setup.py build', f'"{sys.executable}" -m pytest -v'),
    ("Makefile",        "make",   "make",                              "make test"),
    ("requirements.txt","python", f'"{sys.executable}" -m pip install -r requirements.txt', f'"{sys.executable}" -m pytest -v'),
]


class RunRequest(BaseModel):
    prompt: str
    llm_backend: str = "ollama"


class RunResponse(BaseModel):
    result: str


class ToolCallRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = {}


class FileWriteRequest(BaseModel):
    path: str
    content: str


class FileImportRequest(BaseModel):
    source_path: str
    destination_name: str = ""
    overwrite: bool = False


class FileRenameRequest(BaseModel):
    old_path: str
    new_path: str


class FileDeleteRequest(BaseModel):
    path: str


class RoadmapTaskUpdate(BaseModel):
    status: str
    notes: str = ""


class GitCloneRequest(BaseModel):
    url: str
    destination: str = ""
    branch: str = ""


class GitCommitRequest(BaseModel):
    path: str
    message: str
    files: list[str] = []  # empty = stage all


class GitStageRequest(BaseModel):
    path: str
    files: list[str]
    unstage: bool = False


class KnowledgeFetchRequest(BaseModel):
    url: str
    project_path: str = ""
    label: str = ""


class KnowledgeRemoveRequest(BaseModel):
    source_id: str
    project_path: str = ""


class ProfileSetRequest(BaseModel):
    project_path: str = ""
    project_name: str = ""
    description: str = ""
    tech_stack: list[str] = []
    ai_persona: str = ""
    coding_standards: str = ""
    llm_backend: str = ""
    knowledge_sources: list[str] = []


class RulesAddRequest(BaseModel):
    rule: str
    rule_type: str
    project_path: str = ""


class RulesRemoveRequest(BaseModel):
    rule_id: str
    project_path: str = ""


class ScaffoldModuleRequest(BaseModel):
    name: str
    description: str
    tools: list[dict[str, Any]] = []


class ScaffoldPluginRequest(BaseModel):
    name: str
    description: str
    tools: list[dict[str, Any]] = []


class ScaffoldTestsRequest(BaseModel):
    module_name: str
    output_path: str = ""


class IdePushRequest(BaseModel):
    path: str
    content: str
    open_in_editor: bool = True


# ── Phase 9: Plugin ecosystem request models ───────────────────────────────────

class PluginInstallRequest(BaseModel):
    url: str


class PluginGenerateRequest(BaseModel):
    name: str
    description: str
    llm_backend: str = ""


# ── Phase 11: Sandbox run request model ───────────────────────────────────────

class SandboxRunRequest(BaseModel):
    command: str
    working_dir: str = "workspace"
    timeout: int = 30
    use_docker: bool = False
    docker_image: str = "python:3.11-slim"


# ── Phase 10/11: Chat history + session memory request models ──────────────────

class ChatMessageRequest(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str
    project_path: str = ""


class SessionMemoryRequest(BaseModel):
    key: str
    value: str
    project_path: str = ""


# ── Phase 11: Model download request model ────────────────────────────────────

class ModelDownloadRequest(BaseModel):
    model_name: str
    url: str = ""
    backend: str = "ollama"  # "ollama" | "localai"


# ── Phase 13: Self-build request model ────────────────────────────────────────

class SelfBuildRequest(BaseModel):
    task_id: str = ""
    llm_backend: str = ""


# ── Phase 15: Templates & toolchain request models ────────────────────────────

class TemplateApplyRequest(BaseModel):
    name: str                          # template name (dir under templates/)
    dest: str                          # destination relative to workspace/
    context: dict[str, str] = {}       # variable substitution map


class SnippetRunRequest(BaseModel):
    code: str
    language: str = "python"           # python | javascript | bash | lua
    timeout: int = 15                  # seconds


class TemplateSaveRequest(BaseModel):
    source: str   # relative path inside workspace/ to snapshot
    name: str     # new template name
    description: str = ""


# ── Phase 16: Utility module request models ───────────────────────────────────

class ArchivePackRequest(BaseModel):
    src: str
    dst: str
    format: str = "zip"          # "zip" | "tar" | "7z"

class ArchiveExtractRequest(BaseModel):
    src: str
    dst: str

class ArchiveAddFileRequest(BaseModel):
    archive: str
    file: str

class DocGenerateRequest(BaseModel):
    src: str
    output: str
    format: str = "markdown"     # "markdown" | "json" | "html"
    title: str = ""

class NetworkDownloadRequest(BaseModel):
    url: str
    dst: str

class NetworkHttpRequest(BaseModel):
    url: str
    method: str = "GET"
    body: dict = {}
    headers: dict = {}

class PackageInstallRequest(BaseModel):
    name: str
    version: str = ""
    manager: str = ""            # "pip" | "npm" | "gem" | "cargo" | "go"
    cwd: str = ""

class PackageUninstallRequest(BaseModel):
    name: str
    manager: str = ""
    cwd: str = ""

class ImageResizeRequest(BaseModel):
    path: str
    width: int
    height: int
    dst: str = ""

class ImageConvertRequest(BaseModel):
    path: str
    format: str
    dst: str = ""

class AudioConvertRequest(BaseModel):
    src: str
    dst: str
    codec: str = ""

class AudioTrimRequest(BaseModel):
    src: str
    dst: str
    start_ms: int = 0
    end_ms: int = -1             # -1 = end of file


# ── Phase 17: Notes & Tasks models ────────────────────────────────────────────

class NoteCreateRequest(BaseModel):
    title: str
    content: str = ""
    file_path: str = ""


class NoteUpdateRequest(BaseModel):
    title: str = ""
    content: str = ""
    file_path: str = ""


class TaskCreateRequest(BaseModel):
    title: str
    description: str = ""
    status: str = "todo"   # todo | in_progress | done
    priority: str = "medium"


class TaskUpdateRequest(BaseModel):
    title: str = ""
    description: str = ""
    status: str = ""
    priority: str = ""


# ── Phase 18: Git Advanced models ─────────────────────────────────────────────

class GitBranchCreateRequest(BaseModel):
    name: str
    base: str = ""


class GitCheckoutRequest(BaseModel):
    target: str
    is_file: bool = False


class GitStashPushRequest(BaseModel):
    message: str = ""


class GitStashPopRequest(BaseModel):
    index: int = 0


# ── Phase 19: Refactoring models ──────────────────────────────────────────────

class RefactorFindReplaceRequest(BaseModel):
    find: str
    replace: str = ""
    glob_pattern: str = "**/*"
    is_regex: bool = False
    dry_run: bool = True


class RefactorRenameRequest(BaseModel):
    old_name: str
    new_name: str
    glob_pattern: str = "**/*"


class RefactorExtractRequest(BaseModel):
    file: str
    start_line: int
    end_line: int
    new_name: str


class FormatRequest(BaseModel):
    content: str
    language: str = "python"  # python | javascript | json
    path: str = ""


class LintRequest(BaseModel):
    content: str
    language: str = "python"
    path: str = ""


class DiffApplyRequest(BaseModel):
    path: str        # relative path under workspace/
    patch: str       # unified diff text


# ── Phase 7: AI editor request models ─────────────────────────────────────────

class AiCompleteRequest(BaseModel):
    file_content: str = ""
    cursor_offset: int = 0
    language: str = ""
    path: str = ""
    llm_backend: str = ""


class AiActionRequest(BaseModel):
    action: str  # explain | refactor | tests | fix | docstring
    selection: str = ""
    file_content: str = ""
    language: str = ""
    path: str = ""
    llm_backend: str = ""


class AiProposeRequest(BaseModel):
    instruction: str
    file_content: str = ""
    language: str = ""
    path: str = ""
    llm_backend: str = ""


# ── Phase 7: AI action prompt templates ───────────────────────────────────────

# Context window sizes sent to the LLM.  Prefix is longer because the model
# needs more "before" context to produce a relevant completion; suffix only
# needs enough to understand what follows the cursor.
_AI_COMPLETE_PREFIX_CHARS = 800
_AI_COMPLETE_SUFFIX_CHARS = 300

_AI_ACTION_PROMPTS: dict[str, str] = {
    "explain": (
        "Explain the following code in clear, concise terms. "
        "Describe what it does, how it works, and any notable patterns:"
    ),
    "refactor": (
        "Refactor the following code to improve readability, efficiency, and "
        "maintainability. Return ONLY the refactored code without extra explanation:"
    ),
    "tests": (
        "Generate comprehensive unit tests for the following code. "
        "Cover happy-path and edge cases:"
    ),
    "fix": (
        "Fix any bugs or issues in the following code. "
        "Return the fixed code followed by a brief explanation of what was changed:"
    ),
    "docstring": (
        "Add comprehensive docstrings/comments to the following code. "
        "Return the complete code with docstrings added:"
    ),
}


def _safe_path(base_dir: Path, rel: str) -> Path:
    """Resolve *rel* under *base_dir* and reject path-traversal attempts."""
    resolved = (base_dir / rel).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    return resolved


def create_app(config_dir: str = "configs") -> FastAPI:
    setup_logging(log_file="logs/swissagent.log")
    app = FastAPI(
        title="SwissAgent API",
        description="Offline AI-powered development platform API",
        version="0.2.0",
    )
    base_dir = Path(__file__).resolve().parent.parent
    gui_dir = base_dir / "gui"

    config = ConfigLoader(config_dir)
    config.load()
    registry = ToolRegistry()
    ModuleLoader(base_dir / "modules", registry).load_all()
    plugin_loader = PluginLoader(base_dir / "plugins", registry)
    plugin_loader.load_all()
    permissions = PermissionSystem()
    runner = TaskRunner()

    # ── Optional HTTP Basic Auth (t10-1) ───────────────────────────────────
    _auth_enabled: bool = bool(config.get("auth.enabled", False))
    _auth_username: str = str(config.get("auth.username", ""))
    _auth_password: str = str(config.get("auth.password", ""))
    _http_basic = HTTPBasic(auto_error=False)

    def _require_auth(credentials: Optional[HTTPBasicCredentials] = Depends(_http_basic)) -> None:
        if not _auth_enabled:
            return
        if credentials is None:
            raise HTTPException(
                status_code=401,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Basic"},
            )
        ok_user = secrets.compare_digest(
            credentials.username.encode(), _auth_username.encode()
        )
        ok_pass = secrets.compare_digest(
            credentials.password.encode(), _auth_password.encode()
        )
        if not (ok_user and ok_pass):
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Basic"},
            )

    logger.info("SwissAgent API server initialized. %d tools loaded.", len(registry.list_tools()))

    # ── Plugin hot-reload watcher ──────────────────────────────────────────
    _plugins_dir = base_dir / "plugins"
    _watcher_state: dict[str, Any] = {"active": True}
    # Set initial mtime BEFORE starting the thread to avoid a false-trigger on first tick
    _watcher_state["mtime"] = _plugins_dir.stat().st_mtime if _plugins_dir.exists() else 0.0

    def _watch_plugins() -> None:
        """Background thread: reload plugins when plugins/ directory changes."""
        while _watcher_state["active"]:
            try:
                mtime = _plugins_dir.stat().st_mtime if _plugins_dir.exists() else 0.0
                if mtime != _watcher_state["mtime"]:
                    _watcher_state["mtime"] = mtime
                    if mtime:
                        logger.info("Plugins directory changed — reloading plugins.")
                        plugin_loader.load_all()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Plugin watcher error: %s", exc)
            time.sleep(2)

    _watcher_thread = threading.Thread(target=_watch_plugins, daemon=True, name="plugin-watcher")
    _watcher_thread.start()

    # ── Serve GUI static assets ────────────────────────────────────────────
    if gui_dir.is_dir():
        app.mount("/gui", StaticFiles(directory=str(gui_dir)), name="gui")

    # ── GUI root redirect ─────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def serve_gui() -> FileResponse:
        index = gui_dir / "index.html"
        if not index.is_file():
            return HTMLResponse("<h1>SwissAgent API</h1><p>GUI not found.</p>")
        return FileResponse(str(index))

    # ── Health ────────────────────────────────────────────────────────────
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "SwissAgent"}

    # ── Tools ─────────────────────────────────────────────────────────────
    @app.get("/tools")
    async def list_tools() -> dict[str, Any]:
        return {"tools": registry.list_tools()}

    # ── Run agent (HTTP, blocking) ─────────────────────────────────────────
    @app.post("/run", response_model=RunResponse)
    async def run_agent(req: RunRequest) -> RunResponse:
        from core.agent import Agent
        from llm.factory import create_llm
        llm = create_llm(req.llm_backend, config)
        agent = Agent(llm, registry, permissions, runner, config)
        result = await asyncio.get_event_loop().run_in_executor(
            None, agent.run, req.prompt
        )
        return RunResponse(result=result)

    # ── Run agent (WebSocket, streaming) ──────────────────────────────────
    @app.websocket("/ws/run")
    async def ws_run(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            prompt = data.get("prompt", "")
            backend = data.get("llm_backend", "ollama")
            project_path = data.get("project_path", "")

            from core.agent import Agent
            from llm.factory import create_llm

            llm = create_llm(backend, config)

            # Use a queue so the agent thread can push LLM tokens to the WS
            token_queue: queue.Queue[str | None] = queue.Queue()

            def _stream_callback(token: str) -> None:
                token_queue.put(token)

            agent = Agent(llm, registry, permissions, runner, config, project_path)

            loop = asyncio.get_event_loop()

            def _run() -> str:
                result = agent.run(prompt, project_path)
                token_queue.put(None)  # sentinel
                return result

            future = loop.run_in_executor(None, _run)

            # Drain token queue until sentinel
            while True:
                try:
                    token = token_queue.get(timeout=0.05)
                except Exception:
                    token = None
                if token is None:
                    # Check if future is done (sentinel received or future finished)
                    if future.done():
                        break
                    # Empty queue but future not done yet — keep waiting
                    await asyncio.sleep(0.05)
                    continue
                await websocket.send_text(json.dumps({"type": "chunk", "data": token}))

            # Ensure future is awaited
            result = await future
            # Send any remaining output as chunks
            for line in result.splitlines(keepends=True):
                await websocket.send_text(json.dumps({"type": "chunk", "data": line}))
            await websocket.send_text(json.dumps({"type": "done"}))

            # Persist to chat history (t10-5)
            _append_chat_history(
                base_dir, project_path,
                [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": result},
                ],
            )
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            try:
                await websocket.send_text(json.dumps({"type": "error", "data": str(exc)}))
            except Exception:
                pass

    # ── Tool call ─────────────────────────────────────────────────────────
    @app.post("/tools/call")
    async def call_tool(req: ToolCallRequest) -> dict[str, Any]:
        tool = registry.get(req.tool)
        if tool is None:
            raise HTTPException(status_code=404, detail=f"Tool '{req.tool}' not found")
        if not permissions.is_allowed(req.tool, req.arguments):
            raise HTTPException(status_code=403, detail="Permission denied")
        result = runner.run(tool, req.arguments)
        return {"result": result}

    # ── File browser – list entries ────────────────────────────────────────
    @app.get("/files")
    async def list_files(path: Optional[str] = Query(default=None)) -> dict[str, Any]:
        if path:
            # Validate the top-level segment is an allowed root
            top = Path(path).parts[0] if Path(path).parts else ""
            if top not in _BROWSER_ROOTS:
                raise HTTPException(status_code=403, detail=f"Root '{top}' not browsable")
            target = _safe_path(base_dir, path)
        else:
            # Return the allowed root directories
            entries = []
            for root in sorted(_BROWSER_ROOTS):
                d = base_dir / root
                if d.is_dir():
                    entries.append({"name": root, "type": "dir"})
            return {"entries": entries}

        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")

        entries = []
        for item in target.iterdir():
            entries.append({"name": item.name, "type": "dir" if item.is_dir() else "file"})
        return {"entries": entries}

    # ── File browser – read file ───────────────────────────────────────────
    @app.get("/files/read")
    async def read_file(path: str = Query(...)) -> dict[str, Any]:
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BROWSER_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not readable")
        target = _safe_path(base_dir, path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return {"path": path, "content": content}

    # ── File browser – write / create file ────────────────────────────────
    @app.post("/files/write")
    async def write_file(req: FileWriteRequest) -> dict[str, str]:
        top = Path(req.path).parts[0] if Path(req.path).parts else ""
        if top not in _BROWSER_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not writable")
        target = _safe_path(base_dir, req.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(req.content, encoding="utf-8")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return {"status": "ok", "path": req.path}

    # ── Import local project into workspace ───────────────────────────────
    @app.post("/files/import")
    async def import_project(req: FileImportRequest) -> dict[str, Any]:
        """Copy a local folder into workspace/ for development."""
        from modules.import_project.src.import_tools import import_project as _import
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _import(
                source_path=req.source_path,
                destination_name=req.destination_name,
                overwrite=req.overwrite,
            ),
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    # ── Scan a local folder (preview before import) ────────────────────────
    @app.get("/files/scan")
    async def scan_folder(
        path: str = Query(..., description="Local path to scan"),
        max_depth: int = Query(default=2, ge=1, le=5),
    ) -> dict[str, Any]:
        """List contents of any local directory to preview before importing."""
        from modules.import_project.src.import_tools import scan_folder as _scan
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _scan(path, max_depth)
        )
        if result.get("error") and not result.get("exists", True):
            raise HTTPException(status_code=404, detail=result["error"])
        return result

    # ── Build system detection ─────────────────────────────────────────────
    @app.get("/build/detect")
    async def detect_build(path: str = Query(default="workspace")) -> dict[str, Any]:
        """Auto-detect the build system in a project directory."""
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not accessible for builds")
        target = _safe_path(base_dir, path)
        if not target.is_dir():
            raise HTTPException(status_code=404, detail="Directory not found")
        for marker, system, build_cmd, test_cmd in _BUILD_DETECTORS:
            if (target / marker).is_file():
                return {
                    "system": system,
                    "marker": marker,
                    "build_command": build_cmd,
                    "test_command": test_cmd,
                    "cwd": path,
                }
        return {"system": "unknown", "marker": None, "build_command": None, "test_command": None, "cwd": path}

    # ── Terminal WebSocket – real-time subprocess streaming ────────────────
    @app.websocket("/ws/terminal")
    async def ws_terminal(websocket: WebSocket) -> None:
        """Run a shell command inside workspace/projects and stream its output."""
        await websocket.accept()
        proc: Optional[asyncio.subprocess.Process] = None
        try:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            command: str = data.get("command", "").strip()
            rel_cwd: str = data.get("cwd", "workspace")

            if not command:
                await websocket.send_text(json.dumps({"type": "error", "data": "No command provided"}))
                return

            # Security: restrict working directory to build roots
            top = Path(rel_cwd).parts[0] if Path(rel_cwd).parts else ""
            if top not in _BUILD_ROOTS:
                await websocket.send_text(
                    json.dumps({"type": "error", "data": f"cwd must be inside {sorted(_BUILD_ROOTS)}"})
                )
                return

            cwd = _safe_path(base_dir, rel_cwd)
            cwd.mkdir(parents=True, exist_ok=True)

            logger.info("Terminal WS: running %r in %s", command, cwd)

            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(cwd),
            )

            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace")
                await websocket.send_text(json.dumps({"type": "stdout", "data": line}))

            await proc.wait()
            await websocket.send_text(json.dumps({"type": "exit", "code": proc.returncode}))

        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.exception("Terminal WS error: %s", exc)
            try:
                await websocket.send_text(json.dumps({"type": "error", "data": str(exc)}))
            except Exception:
                pass
        finally:
            if proc is not None and proc.returncode is None:
                proc.terminate()

    # ── PTY terminal WebSocket – full interactive shell ────────────────────
    @app.websocket("/ws/pty")
    async def ws_pty(websocket: WebSocket) -> None:
        """Provide a real interactive PTY shell session over WebSocket.

        Protocol:
          Client → Server: JSON ``{"type": "input", "data": "<chars>"}``
                        or ``{"type": "resize", "cols": N, "rows": N}``
          Server → Client: JSON ``{"type": "output", "data": "<chars>"}``
                        or ``{"type": "exit", "code": N}``
        """
        import os
        import pty
        import select
        import signal
        import fcntl
        import struct
        import termios

        await websocket.accept()

        master_fd: Optional[int] = None
        child_pid: Optional[int] = None

        try:
            # Parse optional init message for cwd / cols / rows
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            init = json.loads(raw)
            rel_cwd: str = init.get("cwd", "workspace")
            cols: int = int(init.get("cols", 120))
            rows: int = int(init.get("rows", 30))

            # Restrict cwd to allowed roots
            top = Path(rel_cwd).parts[0] if Path(rel_cwd).parts else ""
            if top not in _BUILD_ROOTS:
                await websocket.send_text(
                    json.dumps({"type": "error", "data": f"cwd must be inside {sorted(_BUILD_ROOTS)}"})
                )
                return

            cwd = _safe_path(base_dir, rel_cwd)
            cwd.mkdir(parents=True, exist_ok=True)

            # Fork a child process attached to a PTY
            child_pid, master_fd = pty.fork()

            if child_pid == 0:
                # ── Child process ──
                os.chdir(str(cwd))
                shell = os.environ.get("SHELL", "/bin/bash")
                os.execvpe(shell, [shell], {
                    **os.environ,
                    "TERM": "xterm-256color",
                    "COLUMNS": str(cols),
                    "LINES": str(rows),
                })
                os._exit(1)  # should not reach here

            # ── Parent process ──
            # Set initial terminal size
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

            loop = asyncio.get_event_loop()

            async def _read_pty() -> None:
                """Continuously read PTY output and forward to WebSocket."""
                fd = master_fd
                pid = child_pid
                while True:
                    try:
                        r, _, _ = await loop.run_in_executor(
                            None, lambda fd=fd: select.select([fd], [], [], 0.05)
                        )
                        if not r:
                            # Check if child exited
                            result = await loop.run_in_executor(
                                None, lambda pid=pid: os.waitpid(pid, os.WNOHANG)
                            )
                            if result[0] != 0:
                                code = os.waitstatus_to_exitcode(result[1])
                                await websocket.send_text(json.dumps({"type": "exit", "code": code}))
                                return
                            continue
                        data = await loop.run_in_executor(None, lambda fd=fd: os.read(fd, 4096))
                        if not data:
                            break
                        text = data.decode("utf-8", errors="replace")
                        await websocket.send_text(json.dumps({"type": "output", "data": text}))
                    except OSError:
                        break

            async def _read_ws() -> None:
                """Forward WebSocket input to PTY."""
                fd = master_fd
                while True:
                    try:
                        msg = await websocket.receive_text()
                        pkt = json.loads(msg)
                        if pkt.get("type") == "input":
                            payload = pkt.get("data", "").encode("utf-8", errors="replace")
                            await loop.run_in_executor(
                                None, lambda fd=fd, p=payload: os.write(fd, p)
                            )
                        elif pkt.get("type") == "resize":
                            c = int(pkt.get("cols", cols))
                            r = int(pkt.get("rows", rows))
                            ws_struct = struct.pack("HHHH", r, c, 0, 0)
                            fcntl.ioctl(fd, termios.TIOCSWINSZ, ws_struct)
                    except WebSocketDisconnect:
                        return
                    except Exception:
                        return

            await asyncio.gather(_read_pty(), _read_ws(), return_exceptions=True)

        except WebSocketDisconnect:
            pass
        except asyncio.TimeoutError:
            try:
                await websocket.send_text(json.dumps({"type": "error", "data": "Init timeout"}))
            except Exception:
                pass
        except Exception as exc:
            logger.exception("PTY WS error: %s", exc)
            try:
                await websocket.send_text(json.dumps({"type": "error", "data": str(exc)}))
            except Exception:
                pass
        finally:
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if master_fd is not None:
                try:
                    os.close(master_fd)
                except OSError:
                    pass

    # ── Roadmap API ─────────────────────────────────────────────────────────
    @app.get("/roadmap")
    async def get_roadmap() -> dict[str, Any]:
        """Return the full roadmap with milestones and tasks."""
        roadmap_file = base_dir / "workspace" / "roadmap.json"
        if not roadmap_file.is_file():
            raise HTTPException(status_code=404, detail="roadmap.json not found")
        try:
            data = json.loads(roadmap_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return data

    @app.patch("/roadmap/task/{task_id}")
    async def update_roadmap_task(task_id: str, req: RoadmapTaskUpdate) -> dict[str, Any]:
        """Update a task's status in the roadmap."""
        valid_statuses = {"pending", "in_progress", "done"}
        if req.status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{req.status}'. Must be one of {sorted(valid_statuses)}",
            )
        roadmap_file = base_dir / "workspace" / "roadmap.json"
        if not roadmap_file.is_file():
            raise HTTPException(status_code=404, detail="roadmap.json not found")
        try:
            data = json.loads(roadmap_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        # Find and update the task
        found = False
        for milestone in data.get("milestones", []):
            for task in milestone.get("tasks", []):
                if task.get("id") == task_id:
                    task["status"] = req.status
                    if req.notes:
                        task["notes"] = req.notes
                    found = True
                    break
            if found:
                # Recalculate milestone status
                tasks = milestone.get("tasks", [])
                statuses = {t.get("status") for t in tasks}
                if statuses == {"done"}:
                    milestone["status"] = "done"
                elif "in_progress" in statuses or ("done" in statuses and "pending" in statuses):
                    milestone["status"] = "in_progress"
                break

        if not found:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        # Atomic write: write to temp file then rename
        content = json.dumps(data, indent=2) + "\n"
        fd, tmp_path = tempfile.mkstemp(
            dir=str(roadmap_file.parent), suffix=".tmp", prefix=".roadmap_"
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(content)
            Path(tmp_path).replace(roadmap_file)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise
        return {"status": "ok", "task_id": task_id, "new_status": req.status}

    @app.get("/roadmap/next")
    async def get_next_roadmap_task() -> dict[str, Any]:
        """Return the next pending (or in_progress) task from the roadmap."""
        roadmap_file = base_dir / "workspace" / "roadmap.json"
        if not roadmap_file.is_file():
            raise HTTPException(status_code=404, detail="roadmap.json not found")
        data = json.loads(roadmap_file.read_text(encoding="utf-8"))
        for milestone in data.get("milestones", []):
            if milestone.get("status") == "done":
                continue
            for task in milestone.get("tasks", []):
                if task.get("status") in ("pending", "in_progress"):
                    return {
                        "task": task,
                        "milestone": {
                            "id": milestone["id"],
                            "title": milestone["title"],
                        },
                    }
        return {"task": None, "milestone": None}

    # ── Git clone ─────────────────────────────────────────────────────────────
    @app.post("/git/clone")
    async def git_clone(req: GitCloneRequest) -> dict[str, Any]:
        """Clone a git repository URL into workspace/ or projects/."""
        import re
        url = req.url.strip()
        if not url:
            raise HTTPException(status_code=400, detail="URL is required")

        # Determine destination name from URL if not provided
        dest_name = req.destination.strip()
        if not dest_name:
            # Extract repo name from URL (e.g. https://github.com/user/repo.git → repo)
            m = re.search(r"/([^/]+?)(?:\.git)?$", url)
            dest_name = m.group(1) if m else "cloned_repo"

        # Sanitise: only allow safe folder names
        dest_name = re.sub(r"[^A-Za-z0-9_\-.]", "_", dest_name)
        if not dest_name:
            raise HTTPException(status_code=400, detail="Could not determine destination name")

        dest = base_dir / "projects" / dest_name
        if dest.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Destination 'projects/{dest_name}' already exists",
            )

        # Run git clone in executor so it doesn't block the event loop
        import subprocess
        cmd = ["git", "clone", "--depth", "1"]
        if req.branch:
            cmd += ["--branch", req.branch]
        cmd += [url, str(dest)]
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=120),
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Clone failed: {exc}")

        if result.returncode != 0:
            raise HTTPException(
                status_code=400,
                detail=f"git clone failed: {(result.stderr or result.stdout).strip()}",
            )

        # Count cloned files
        n_files = sum(1 for _ in dest.rglob("*") if _.is_file())
        return {
            "status": "ok",
            "destination": f"projects/{dest_name}",
            "files": n_files,
            "url": url,
        }

    # ── Git panel endpoints ────────────────────────────────────────────────────

    @app.get("/git/status")
    async def git_panel_status(path: str = Query(default="workspace")) -> dict[str, Any]:
        """Return git status (branch, staged, unstaged, untracked files) for a project path."""
        import subprocess
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, path)
        if not (repo_dir / ".git").exists():
            return {"error": "not_a_git_repo", "path": path}
        try:
            # porcelain v1 output: XY filename
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "status", "--porcelain=v1", "-u"],
                    cwd=str(repo_dir), capture_output=True, text=True, timeout=15,
                ),
            )
            staged, unstaged, untracked = [], [], []
            for line in proc.stdout.splitlines():
                if len(line) < 4:
                    continue
                xy, fname = line[:2], line[3:]
                x, y = xy[0], xy[1]
                if x != " " and x != "?":
                    staged.append({"file": fname.strip(), "status": x})
                if y == "M" or y == "D":
                    unstaged.append({"file": fname.strip(), "status": y})
                if x == "?" and y == "?":
                    untracked.append(fname.strip())

            # current branch
            branch_proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=str(repo_dir), capture_output=True, text=True, timeout=5,
                ),
            )
            branch = branch_proc.stdout.strip() or "HEAD"

            # recent commits
            log_proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "log", "--oneline", "-10"],
                    cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
                ),
            )
            commits = [{"sha": l[:7], "message": l[8:].strip()} for l in log_proc.stdout.splitlines() if len(l) > 8]

            return {"branch": branch, "staged": staged, "unstaged": unstaged, "untracked": untracked, "commits": commits}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/git/diff")
    async def git_panel_diff(path: str = Query(...), file: str = Query(default="")) -> dict[str, Any]:
        """Return the git diff for the repo (or a specific file if provided)."""
        import subprocess
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, path)
        if not (repo_dir / ".git").exists():
            return {"error": "not_a_git_repo"}
        try:
            cmd = ["git", "diff"]
            if file:
                cmd.append(file)
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, cwd=str(repo_dir), capture_output=True, text=True, timeout=15),
            )
            # Also get staged diff
            staged_cmd = ["git", "diff", "--cached"]
            if file:
                staged_cmd.append(file)
            staged_proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(staged_cmd, cwd=str(repo_dir), capture_output=True, text=True, timeout=15),
            )
            return {"diff": proc.stdout, "staged_diff": staged_proc.stdout}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/git/stage")
    async def git_panel_stage(req: GitStageRequest) -> dict[str, Any]:
        """Stage or unstage files in a git repo."""
        import subprocess
        top = Path(req.path).parts[0] if Path(req.path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, req.path)
        if not (repo_dir / ".git").exists():
            raise HTTPException(status_code=400, detail="Not a git repository")
        try:
            if req.unstage:
                cmd = ["git", "restore", "--staged"] + (req.files if req.files else ["."])
            else:
                cmd = ["git", "add"] + (req.files if req.files else ["."])
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, cwd=str(repo_dir), capture_output=True, text=True, timeout=15),
            )
            if proc.returncode != 0:
                raise HTTPException(status_code=400, detail=proc.stderr.strip() or proc.stdout.strip())
            return {"status": "ok", "action": "unstaged" if req.unstage else "staged", "files": req.files}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/git/commit")
    async def git_panel_commit(req: GitCommitRequest) -> dict[str, Any]:
        """Commit staged changes with a message."""
        import subprocess
        top = Path(req.path).parts[0] if Path(req.path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, req.path)
        if not (repo_dir / ".git").exists():
            raise HTTPException(status_code=400, detail="Not a git repository")
        if not req.message.strip():
            raise HTTPException(status_code=400, detail="Commit message is required")
        try:
            # Stage specified files (or all if none given)
            if req.files:
                stage_proc = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["git", "add"] + req.files,
                        cwd=str(repo_dir), capture_output=True, text=True, timeout=15,
                    ),
                )
                if stage_proc.returncode != 0:
                    raise HTTPException(status_code=400, detail=stage_proc.stderr.strip())

            commit_proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "commit", "-m", req.message],
                    cwd=str(repo_dir), capture_output=True, text=True, timeout=30,
                ),
            )
            if commit_proc.returncode != 0:
                raise HTTPException(status_code=400, detail=commit_proc.stderr.strip() or commit_proc.stdout.strip())
            return {"status": "ok", "message": req.message, "output": commit_proc.stdout.strip()}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── Knowledge base endpoints ───────────────────────────────────────────────

    @app.get("/knowledge/list")
    async def knowledge_list_sources(project_path: str = Query(default="")) -> dict[str, Any]:
        """List all knowledge sources indexed for a project."""
        try:
            from modules.knowledge.src.knowledge_tools import knowledge_list
            return knowledge_list(project_path=project_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/knowledge/fetch")
    async def knowledge_fetch_source(req: KnowledgeFetchRequest) -> dict[str, Any]:
        """Fetch a URL and add it to the project knowledge base."""
        try:
            from modules.knowledge.src.knowledge_tools import knowledge_fetch
            return await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: knowledge_fetch(req.url, project_path=req.project_path, label=req.label),
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/knowledge/remove")
    async def knowledge_remove_source(req: KnowledgeRemoveRequest) -> dict[str, Any]:
        """Remove a knowledge source from the project knowledge base."""
        try:
            from modules.knowledge.src.knowledge_tools import knowledge_remove
            return knowledge_remove(source_id=req.source_id, project_path=req.project_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/knowledge/search")
    async def knowledge_search_endpoint(
        query: str = Query(...),
        project_path: str = Query(default=""),
        top_k: int = Query(default=5),
    ) -> dict[str, Any]:
        """Search the project knowledge base."""
        try:
            from modules.knowledge.src.knowledge_tools import knowledge_search
            return knowledge_search(query=query, project_path=project_path, top_k=top_k)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── Project profile + rules endpoints ─────────────────────────────────────

    @app.get("/profile")
    async def profile_get_endpoint(project_path: str = Query(default="")) -> dict[str, Any]:
        """Get the AI profile for a project."""
        try:
            from modules.project_profile.src.profile_tools import profile_get
            return profile_get(project_path=project_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/profile")
    async def profile_set_endpoint(req: ProfileSetRequest) -> dict[str, Any]:
        """Create or update the AI profile for a project."""
        try:
            from modules.project_profile.src.profile_tools import profile_set
            return profile_set(
                project_path=req.project_path,
                project_name=req.project_name or None,
                description=req.description or None,
                tech_stack=req.tech_stack or None,
                ai_persona=req.ai_persona or None,
                coding_standards=req.coding_standards or None,
                llm_backend=req.llm_backend or None,
                knowledge_sources=req.knowledge_sources or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/profile/detect")
    async def profile_detect_endpoint(project_path: str = Query(...)) -> dict[str, Any]:
        """Auto-detect the tech stack and suggest a profile for a project."""
        try:
            from modules.project_profile.src.profile_tools import profile_detect
            return profile_detect(project_path=project_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/rules")
    async def rules_get_endpoint(project_path: str = Query(default="")) -> dict[str, Any]:
        """Get all AI rules for a project."""
        try:
            from modules.project_profile.src.profile_tools import rules_get
            return rules_get(project_path=project_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/rules")
    async def rules_add_endpoint(req: RulesAddRequest) -> dict[str, Any]:
        """Add a rule to the project AI rule set."""
        valid_types = {"must", "must_not", "prefer"}
        if req.rule_type not in valid_types:
            raise HTTPException(status_code=400, detail=f"rule_type must be one of {sorted(valid_types)}")
        try:
            from modules.project_profile.src.profile_tools import rules_add
            return rules_add(rule=req.rule, rule_type=req.rule_type, project_path=req.project_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.delete("/rules/{rule_id}")
    async def rules_remove_endpoint(rule_id: str, project_path: str = Query(default="")) -> dict[str, Any]:
        """Remove a rule from the project AI rule set."""
        try:
            from modules.project_profile.src.profile_tools import rules_remove
            return rules_remove(rule_id=rule_id, project_path=project_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── Scaffold endpoints ─────────────────────────────────────────────────────

    @app.post("/scaffold/module")
    async def scaffold_module_endpoint(req: ScaffoldModuleRequest) -> dict[str, Any]:
        """Generate a new module skeleton from a name and description."""
        try:
            from modules.scaffold.src.scaffold_tools import scaffold_module
            return scaffold_module(name=req.name, description=req.description, tools=req.tools or None)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/scaffold/plugin")
    async def scaffold_plugin_endpoint(req: ScaffoldPluginRequest) -> dict[str, Any]:
        """Generate a new plugin skeleton from a name and description."""
        try:
            from modules.scaffold.src.scaffold_tools import scaffold_plugin
            return scaffold_plugin(name=req.name, description=req.description, tools=req.tools or None)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/scaffold/tests")
    async def scaffold_tests_endpoint(req: ScaffoldTestsRequest) -> dict[str, Any]:
        """Generate pytest stubs for an existing module."""
        try:
            from modules.scaffold.src.scaffold_tools import scaffold_tests
            return scaffold_tests(module_name=req.module_name, output_path=req.output_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── Phase 9: Plugin ecosystem endpoints ────────────────────────────────────

    @app.get("/plugins")
    async def list_plugins() -> dict[str, Any]:
        """List all installed plugins with metadata."""
        plugins = plugin_loader.loaded_plugins
        return {
            "plugins": [
                {
                    "name": meta.get("name", name),
                    "version": meta.get("version", "?"),
                    "description": meta.get("description", ""),
                    "author": meta.get("author", ""),
                }
                for name, meta in plugins.items()
            ],
            "count": len(plugins),
        }

    @app.post("/plugins/reload")
    async def reload_plugins() -> dict[str, Any]:
        """Hot-reload all plugins from the plugins/ directory."""
        try:
            plugin_loader.load_all()
            _watcher_state["mtime"] = _plugins_dir.stat().st_mtime if _plugins_dir.exists() else 0.0
            return {
                "status": "reloaded",
                "count": len(plugin_loader.loaded_plugins),
                "plugins": list(plugin_loader.loaded_plugins.keys()),
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/plugins/install")
    async def install_plugin(req: PluginInstallRequest) -> dict[str, Any]:
        """Install a plugin by cloning a GitHub/Git URL into plugins/."""
        url = req.url.strip()
        if not url:
            raise HTTPException(status_code=400, detail="URL is required")
        # Derive plugin directory name from URL
        name = url.rstrip("/").rsplit("/", 1)[-1]
        if name.endswith(".git"):
            name = name[:-4]
        if not name:
            raise HTTPException(status_code=400, detail="Could not determine plugin name from URL")
        dest = _plugins_dir / name
        if dest.exists():
            return {"status": "already_installed", "plugin": name, "path": str(dest.relative_to(base_dir))}
        try:
            result = subprocess.run(
                ["git", "clone", "--depth=1", url, str(dest)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise HTTPException(status_code=500, detail=result.stderr or "git clone failed")
            # Auto-register the newly installed plugin using the public API
            plugin_loader.load_plugin(dest)
            _watcher_state["mtime"] = _plugins_dir.stat().st_mtime if _plugins_dir.exists() else 0.0
            return {
                "status": "installed",
                "plugin": name,
                "path": str(dest.relative_to(base_dir)),
                "tools": len(plugin_loader.loaded_plugins.get(name, {}).get("tools", [])),
            }
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="git clone timed out")

    @app.delete("/plugins/{name}")
    async def remove_plugin(name: str) -> dict[str, Any]:
        """Remove an installed plugin by name."""
        # Validate name (no path traversal)
        if "/" in name or "\\" in name or name.startswith("."):
            raise HTTPException(status_code=400, detail="Invalid plugin name")
        dest = _plugins_dir / name
        if not dest.exists():
            raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
        try:
            shutil.rmtree(dest)
            plugin_loader.unload_plugin(name)
            return {"status": "removed", "plugin": name}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/plugins/generate")
    async def generate_plugin_with_ai(req: PluginGenerateRequest) -> dict[str, Any]:
        """Generate a plugin skeleton with AI-assisted tool definitions."""
        if not req.name or not req.description:
            raise HTTPException(status_code=400, detail="name and description are required")
        try:
            from modules.scaffold.src.scaffold_tools import scaffold_plugin
            # Use LLM to generate better tool definitions if a backend is configured
            tools: list[dict[str, Any]] = []
            backend = req.llm_backend or config.get("llm", {}).get("default_backend", "")
            if backend:
                try:
                    from llm.factory import create_llm
                    llm = create_llm(backend, config)
                    prompt = (
                        f"Generate a JSON array of tool definitions for a SwissAgent plugin called '{req.name}'. "
                        f"Description: {req.description}\n"
                        "Each tool must have: name, description, function (as 'plugins.<slug>.<slug>_plugin.<fn>'), "
                        "and arguments (JSON schema). Return ONLY the JSON array, no markdown."
                    )
                    raw = llm.complete(prompt)
                    # Extract JSON array from response
                    match = re.search(r"\[.*\]", raw, re.DOTALL)
                    if match:
                        tools = json.loads(match.group(0))
                except Exception:  # noqa: BLE001
                    tools = []  # Fall back to default tool generation
            return scaffold_plugin(name=req.name, description=req.description, tools=tools or None)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── Phase 11: Sandbox code execution ──────────────────────────────────────

    @app.post("/sandbox/run")
    async def sandbox_run(req: SandboxRunRequest) -> dict[str, Any]:
        """Run a command in a sandboxed environment.

        If use_docker=True and Docker is available, runs inside a container.
        Otherwise runs with subprocess with a timeout.
        """
        # Validate working directory — resolve first to prevent traversal tricks
        allowed_roots = {"workspace", "projects"}
        work_path = (base_dir / req.working_dir).resolve()
        base_resolved = base_dir.resolve()
        # Use is_relative_to for robust cross-platform path containment check (Python 3.9+)
        if not work_path.is_relative_to(base_resolved):
            raise HTTPException(status_code=403, detail="Path traversal denied")
        # Check that the resolved path is under an allowed root
        rel_parts = work_path.relative_to(base_resolved).parts
        top = rel_parts[0] if rel_parts else ""
        if top not in allowed_roots:
            raise HTTPException(status_code=403, detail=f"working_dir must be under: {allowed_roots}")
        if not work_path.exists():
            work_path.mkdir(parents=True, exist_ok=True)

        timeout = max(5, min(req.timeout, 300))

        docker_available = shutil.which("docker") is not None
        use_docker_actual = req.use_docker and docker_available
        docker_fallback = req.use_docker and not docker_available

        if use_docker_actual:
            cmd = [
                "docker", "run", "--rm",
                "--network=none",
                "--memory=256m",
                "--cpus=1",
                "-v", f"{work_path}:/workspace:ro",
                "-w", "/workspace",
                req.docker_image,
                "sh", "-c", req.command,
            ]
        else:
            cmd = ["sh", "-c", req.command]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(work_path),
            )
            response: dict[str, Any] = {
                "status": "ok",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "docker": use_docker_actual,
            }
            if docker_fallback:
                response["warning"] = (
                    "Docker is not installed on this system. "
                    "Command ran via subprocess fallback (no container isolation)."
                )
            return response
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "error": f"Command timed out after {timeout}s",
                "stdout": "",
                "stderr": "",
                "returncode": -1,
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── File rename ─────────────────────────────────────────────────────────
    @app.post("/files/rename")
    async def rename_file(req: FileRenameRequest) -> dict[str, str]:
        """Rename or move a file/directory within allowed roots."""
        for p in (req.old_path, req.new_path):
            top = Path(p).parts[0] if Path(p).parts else ""
            if top not in _BROWSER_ROOTS:
                raise HTTPException(status_code=403, detail=f"Root '{top}' not writable")
        src = _safe_path(base_dir, req.old_path)
        dst = _safe_path(base_dir, req.new_path)
        if not src.exists():
            raise HTTPException(status_code=404, detail="Source path not found")
        if dst.exists():
            raise HTTPException(status_code=409, detail="Destination already exists")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return {"status": "ok", "old_path": req.old_path, "new_path": req.new_path}

    # ── File / directory delete ─────────────────────────────────────────────
    @app.post("/files/delete")
    async def delete_file(req: FileDeleteRequest) -> dict[str, str]:
        """Delete a file or empty directory within allowed roots."""
        import shutil
        top = Path(req.path).parts[0] if Path(req.path).parts else ""
        if top not in _BROWSER_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not deletable")
        target = _safe_path(base_dir, req.path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        if target.is_dir():
            shutil.rmtree(str(target))
        else:
            target.unlink()
        return {"status": "ok", "path": req.path}

    # ── Full-text search across workspace files ────────────────────────────
    @app.get("/search")
    async def search_files(
        q: str = Query(..., min_length=1, description="Search query"),
        path: str = Query(default="workspace", description="Root directory to search"),
        max_results: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        """Search for text across all files in the given directory."""
        import re
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BROWSER_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not searchable")
        target = _safe_path(base_dir, path)
        if not target.is_dir():
            raise HTTPException(status_code=404, detail="Directory not found")

        results: list[dict[str, Any]] = []
        try:
            pattern = re.compile(re.escape(q), re.IGNORECASE)
        except re.error:
            raise HTTPException(status_code=400, detail="Invalid search pattern")

        def _walk(d: Path, rel: str) -> None:
            if len(results) >= max_results:
                return
            try:
                entries = sorted(d.iterdir(), key=lambda e: e.name)
            except PermissionError:
                return
            for item in entries:
                if len(results) >= max_results:
                    return
                if item.name.startswith(".") and item.is_dir():
                    continue
                if item.is_dir():
                    if item.name in _SEARCH_SKIP_DIRS:
                        continue
                    _walk(item, f"{rel}/{item.name}" if rel else item.name)
                elif item.is_file() and item.suffix.lower() not in _SEARCH_SKIP_EXTS:
                    try:
                        text = item.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        continue
                    for line_no, line in enumerate(text.splitlines(), 1):
                        if pattern.search(line):
                            file_rel = f"{path}/{rel}/{item.name}" if rel else f"{path}/{item.name}"
                            results.append({
                                "file": file_rel,
                                "line": line_no,
                                "text": line.strip()[:200],
                            })
                            if len(results) >= max_results:
                                return

        await asyncio.get_event_loop().run_in_executor(None, lambda: _walk(target, ""))
        return {"query": q, "count": len(results), "results": results}

    # ── Inline code completion (Copilot-style) ────────────────────────────────
    class CompleteRequest(BaseModel):
        prefix: str
        suffix: str = ""
        language: str = ""
        path: str = ""
        llm_backend: str = ""

    @app.post("/api/complete")
    async def code_complete(req: CompleteRequest) -> dict[str, Any]:
        """Return a short code completion for the given prefix/suffix.

        Called by the Monaco InlineCompletionsProvider.  The LLM backend
        defaults to whatever is configured in ``agent.default_llm_backend``.
        """
        from llm.factory import create_llm

        backend = req.llm_backend or config.get("agent.default_llm_backend", "ollama")
        llm = create_llm(backend, config)

        lang_hint = f"Language: {req.language}\n" if req.language else ""
        file_hint = f"File: {req.path}\n" if req.path else ""
        system_msg = (
            "You are a code completion assistant. "
            "Complete the code exactly at the <CURSOR> marker. "
            "Return ONLY the completion text — no explanation, no markdown fences, "
            "no repetition of the prefix."
        )
        user_msg = (
            f"{lang_hint}{file_hint}"
            f"Code before cursor:\n{req.prefix[-_AI_COMPLETE_PREFIX_CHARS:]}\n"
            f"<CURSOR>\n"
            f"Code after cursor:\n{req.suffix[:_AI_COMPLETE_SUFFIX_CHARS]}"
        )

        try:
            raw = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: llm.chat([
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ]),
            )
        except Exception as exc:
            logger.warning("Code completion error: %s", exc)
            return {"completion": ""}

        # Strip any accidental markdown fences the LLM might have included
        completion = raw.strip()
        if completion.startswith("```"):
            lines = completion.splitlines()
            inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
            completion = "\n".join(inner)

        return {"completion": completion}

    # ── AI editor endpoints (Phase 7) ─────────────────────────────────────────

    @app.post("/ai/complete")
    async def ai_complete(req: AiCompleteRequest) -> dict[str, Any]:
        """Inline code completion using file content + cursor offset (t7-1/t7-6).

        The frontend passes the full file content and the cursor byte offset;
        this endpoint derives the prefix/suffix and queries the LLM.
        """
        from llm.factory import create_llm

        backend = req.llm_backend or config.get("agent.default_llm_backend", "ollama")
        llm = create_llm(backend, config)

        prefix = req.file_content[: req.cursor_offset]
        suffix = req.file_content[req.cursor_offset :]
        lang_hint = f"Language: {req.language}\n" if req.language else ""
        file_hint = f"File: {req.path}\n" if req.path else ""
        system_msg = (
            "You are a code completion assistant. "
            "Complete the code exactly at the <CURSOR> marker. "
            "Return ONLY the completion text — no explanation, no markdown fences, "
            "no repetition of the prefix."
        )
        user_msg = (
            f"{lang_hint}{file_hint}"
            f"Code before cursor:\n{prefix[-_AI_COMPLETE_PREFIX_CHARS:]}\n"
            f"<CURSOR>\n"
            f"Code after cursor:\n{suffix[:_AI_COMPLETE_SUFFIX_CHARS]}"
        )

        try:
            raw = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: llm.chat([
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ]),
            )
        except Exception as exc:
            logger.warning("AI complete error: %s", exc)
            return {"completion": ""}

        completion = raw.strip()
        if completion.startswith("```"):
            lines = completion.splitlines()
            inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
            completion = "\n".join(inner)

        return {"completion": completion}

    @app.post("/ai/action")
    async def ai_action(req: AiActionRequest) -> dict[str, Any]:
        """Run an AI action (explain/refactor/tests/fix/docstring) on a code selection.

        Used by the floating selection toolbar (t7-2) and Monaco context menu (t7-3).
        """
        from llm.factory import create_llm

        backend = req.llm_backend or config.get("agent.default_llm_backend", "ollama")
        llm = create_llm(backend, config)

        lang_hint = f"Language: {req.language}\n" if req.language else ""
        file_hint = f"File: {req.path}\n" if req.path else ""
        prompt_intro = _AI_ACTION_PROMPTS.get(req.action, "Analyse the following code:")
        system_msg = "You are an expert software developer. Be concise and precise."
        user_msg = (
            f"{lang_hint}{file_hint}"
            f"{prompt_intro}\n\n"
            f"```\n{req.selection}\n```"
        )

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: llm.chat([
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ]),
            )
        except Exception as exc:
            logger.warning("AI action error: %s", exc)
            return {"result": f"Error: {exc}"}

        return {"result": result}

    @app.post("/ai/propose")
    async def ai_propose(req: AiProposeRequest) -> dict[str, Any]:
        """Return a proposed new version of a file based on a natural-language instruction.

        Used by the diff viewer (t7-4): the frontend shows old vs new in a Monaco
        DiffEditor so the user can accept or reject the change.
        """
        from llm.factory import create_llm

        backend = req.llm_backend or config.get("agent.default_llm_backend", "ollama")
        llm = create_llm(backend, config)

        lang_hint = f"Language: {req.language}\n" if req.language else ""
        file_hint = f"File: {req.path}\n" if req.path else ""
        system_msg = (
            "You are an expert software developer. "
            "Given a file and an instruction, return the complete modified file content. "
            "Return ONLY the file content — no explanation, no markdown fences, "
            "no preamble, no trailing commentary."
        )
        user_msg = (
            f"{lang_hint}{file_hint}"
            f"Instruction: {req.instruction}\n\n"
            f"Current file content:\n{req.file_content}"
        )

        try:
            proposed = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: llm.chat([
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ]),
            )
        except Exception as exc:
            logger.warning("AI propose error: %s", exc)
            return {"proposed_content": "", "error": str(exc)}

        proposed = proposed.strip()
        if proposed.startswith("```"):
            lines = proposed.splitlines()
            inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
            proposed = "\n".join(inner)

        return {"proposed_content": proposed}

    # ── IDE push endpoint (Open WebUI tool / external integrations) ────────────
    @app.post("/api/ide/push")
    async def ide_push(req: IdePushRequest) -> dict[str, Any]:
        """Write a file to the workspace from an external tool (e.g. Open WebUI).

        The IDE frontend polls ``GET /api/ide/pending`` to discover pushed files
        and open them automatically in the editor.
        """
        top = Path(req.path).parts[0] if Path(req.path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(
                status_code=403,
                detail=f"Path must be inside {sorted(_BUILD_ROOTS)}",
            )
        target = _safe_path(base_dir, req.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(req.content, encoding="utf-8")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        # Track the pushed file so the IDE can open it
        _ide_pending_pushes.append(req.path)
        logger.info("IDE push: wrote %s (%d bytes)", req.path, len(req.content))
        return {"status": "ok", "path": req.path, "bytes": len(req.content)}

    @app.get("/api/ide/pending")
    async def ide_pending() -> dict[str, Any]:
        """Return (and clear) the list of recently pushed file paths."""
        paths = list(_ide_pending_pushes)
        _ide_pending_pushes.clear()
        return {"paths": paths}

    @app.get("/api/ide/status")
    async def ide_status() -> dict[str, Any]:
        """Lightweight health-check used by Open WebUI tool and status badge."""
        return {
            "status": "ok",
            "version": "0.2.0",
            "tools": len(registry.list_tools()),
        }

    # ── Phase 10-5: Persistent chat history ───────────────────────────────────

    @app.get("/chat/history")
    async def chat_history_get(
        project_path: str = Query(default=""),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        """Return chat history for the given project (or global if no project_path)."""
        history = _load_chat_history(base_dir, project_path)
        return {"messages": history[-limit:], "total": len(history)}

    @app.post("/chat/history")
    async def chat_history_append(req: ChatMessageRequest) -> dict[str, str]:
        """Append a message to the chat history."""
        if req.role not in ("user", "assistant", "system"):
            raise HTTPException(status_code=400, detail="role must be user/assistant/system")
        _append_chat_history(
            base_dir, req.project_path,
            [{"role": req.role, "content": req.content, "ts": datetime.datetime.now(datetime.timezone.utc).isoformat()}],
        )
        return {"status": "ok"}

    @app.delete("/chat/history")
    async def chat_history_clear(project_path: str = Query(default="")) -> dict[str, str]:
        """Clear the chat history for the given project."""
        _save_chat_history(base_dir, project_path, [])
        return {"status": "ok"}

    # ── Phase 10-6: Agent session memory ──────────────────────────────────────

    @app.get("/memory")
    async def memory_get(project_path: str = Query(default="")) -> dict[str, Any]:
        """Return the session memory key-value store."""
        return {"memory": _load_session_memory(base_dir, project_path)}

    @app.post("/memory")
    async def memory_set(req: SessionMemoryRequest) -> dict[str, str]:
        """Store a key-value fact in session memory."""
        if not req.key.strip():
            raise HTTPException(status_code=400, detail="key must not be empty")
        mem = _load_session_memory(base_dir, req.project_path)
        mem[req.key] = req.value
        _save_session_memory(base_dir, req.project_path, mem)
        return {"status": "ok"}

    @app.delete("/memory/{key}")
    async def memory_delete(key: str, project_path: str = Query(default="")) -> dict[str, str]:
        """Delete a key from session memory."""
        mem = _load_session_memory(base_dir, project_path)
        mem.pop(key, None)
        _save_session_memory(base_dir, project_path, mem)
        return {"status": "ok"}

    # ── Phase 11-7: Model download helper ─────────────────────────────────────

    # Curated list of recommended open-source models
    _RECOMMENDED_MODELS: list[dict[str, Any]] = [
        {
            "name": "codestral",
            "label": "Codestral 22B",
            "description": "Mistral's code-specialist model — best for code generation",
            "backend": "ollama",
            "pull": "ollama pull codestral",
            "size_gb": 12.9,
        },
        {
            "name": "deepseek-r1",
            "label": "DeepSeek R1",
            "description": "DeepSeek reasoning model — strong at planning & analysis",
            "backend": "ollama",
            "pull": "ollama pull deepseek-r1",
            "size_gb": 4.7,
        },
        {
            "name": "phi4",
            "label": "Phi-4 14B",
            "description": "Microsoft Phi-4 — small but capable for code & chat",
            "backend": "ollama",
            "pull": "ollama pull phi4",
            "size_gb": 8.9,
        },
        {
            "name": "qwen2.5-coder",
            "label": "Qwen 2.5 Coder 7B",
            "description": "Alibaba Qwen 2.5 Coder — excellent code completion",
            "backend": "ollama",
            "pull": "ollama pull qwen2.5-coder",
            "size_gb": 4.7,
        },
        {
            "name": "llama3.2",
            "label": "Llama 3.2 3B",
            "description": "Meta Llama 3.2 — fast & lightweight general assistant",
            "backend": "ollama",
            "pull": "ollama pull llama3.2",
            "size_gb": 2.0,
        },
    ]

    @app.get("/models/list")
    async def models_list() -> dict[str, Any]:
        """List recommended downloadable models + locally installed models."""
        ollama_url = config.get("llm.ollama.base_url", "http://localhost:11434")
        installed: list[str] = []
        try:
            import requests as _req  # type: ignore[import]
            resp = _req.get(f"{ollama_url}/api/tags", timeout=5)
            if resp.ok:
                installed = [m.get("name", "") for m in resp.json().get("models", [])]
        except Exception:
            pass
        models = []
        for m in _RECOMMENDED_MODELS:
            entry = dict(m)
            entry["installed"] = any(m["name"] in name for name in installed)
            models.append(entry)
        return {"models": models, "installed": installed}

    @app.post("/models/download")
    async def models_download(req: ModelDownloadRequest) -> dict[str, Any]:
        """Start a background model download (ollama pull or curl for LocalAI)."""
        if not req.model_name.strip():
            raise HTTPException(status_code=400, detail="model_name must not be empty")

        job_id = f"{req.model_name}_{int(time.time())}"
        _model_download_jobs[job_id] = {"status": "running", "model": req.model_name, "log": []}

        def _do_download() -> None:
            entry = _model_download_jobs[job_id]
            try:
                if req.backend == "ollama":
                    ollama_url = config.get("llm.ollama.base_url", "http://localhost:11434")
                    proc = subprocess.Popen(
                        ["ollama", "pull", req.model_name],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    for line in (proc.stdout or []):
                        entry["log"].append(line.rstrip())
                    proc.wait()
                    entry["status"] = "done" if proc.returncode == 0 else "error"
                elif req.url:
                    # Download a .gguf file directly
                    models_dir = base_dir / "models"
                    models_dir.mkdir(exist_ok=True)
                    filename = Path(req.url).name or f"{req.model_name}.gguf"
                    dest = models_dir / filename
                    proc = subprocess.Popen(
                        ["curl", "-L", "-o", str(dest), req.url],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    for line in (proc.stdout or []):
                        entry["log"].append(line.rstrip())
                    proc.wait()
                    entry["status"] = "done" if proc.returncode == 0 else "error"
                else:
                    entry["status"] = "error"
                    entry["log"].append("No download URL provided for non-ollama backend")
            except Exception as exc:
                entry["status"] = "error"
                entry["log"].append(str(exc))

        threading.Thread(target=_do_download, daemon=True, name=f"model-dl-{job_id}").start()
        return {"status": "started", "job_id": job_id, "model": req.model_name}

    @app.get("/models/download/status")
    async def models_download_status(job_id: str = Query(...)) -> dict[str, Any]:
        """Check the status of a model download job."""
        if job_id not in _model_download_jobs:
            raise HTTPException(status_code=404, detail="job_id not found")
        return _model_download_jobs[job_id]

    # ── Phase 13: Autonomous Self-Build ───────────────────────────────────────

    @app.post("/self-build/run", dependencies=[Depends(_require_auth)])
    async def self_build_run(req: SelfBuildRequest) -> dict[str, Any]:
        """Run one self-build cycle synchronously (short tasks only)."""
        from core.self_build import SelfBuildLoop
        from llm.factory import create_llm

        backend = req.llm_backend or config.get("agent.default_llm_backend", "ollama")
        llm = create_llm(backend, config)
        loop_obj = SelfBuildLoop(base_dir, llm)
        log_lines: list[str] = []

        def _emit(line: str) -> None:
            log_lines.append(line)

        result = await loop_obj.run(_emit, task_id=req.task_id or None)
        result["log_text"] = "".join(log_lines)
        return result

    @app.websocket("/ws/self-build")
    async def ws_self_build(websocket: WebSocket) -> None:
        """Stream self-build log output token by token."""
        await websocket.accept()
        try:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            backend = data.get("llm_backend", config.get("agent.default_llm_backend", "ollama"))
            task_id_req = data.get("task_id", "") or None

            from core.self_build import SelfBuildLoop
            from llm.factory import create_llm

            llm = create_llm(backend, config)
            loop_obj = SelfBuildLoop(base_dir, llm)

            ws_queue: queue.Queue[str | None] = queue.Queue()

            def _emit(line: str) -> None:
                ws_queue.put(line)

            async def _run_build() -> None:
                await loop_obj.run(_emit, task_id=task_id_req)
                ws_queue.put(None)  # sentinel

            build_task = asyncio.ensure_future(_run_build())

            while True:
                try:
                    msg = ws_queue.get(timeout=0.1)
                except Exception:
                    if build_task.done():
                        break
                    await asyncio.sleep(0.05)
                    continue
                if msg is None:
                    break
                await websocket.send_text(json.dumps({"type": "log", "data": msg}))

            await build_task
            await websocket.send_text(json.dumps({"type": "done"}))
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            try:
                await websocket.send_text(json.dumps({"type": "error", "data": str(exc)}))
            except Exception:
                pass

    @app.get("/self-build/log")
    async def self_build_log() -> dict[str, Any]:
        """Return self-build telemetry log."""
        from core.self_build import _load_telemetry
        telem = _load_telemetry(base_dir)
        total = len(telem)
        successes = sum(1 for e in telem if e.get("success"))
        avg_attempts = (
            sum(e.get("attempts", 1) for e in telem) / total if total else 0
        )
        return {
            "entries": telem,
            "summary": {
                "total": total,
                "successes": successes,
                "failures": total - successes,
                "success_rate": round(successes / total, 3) if total else 0,
                "avg_attempts": round(avg_attempts, 2),
            },
        }

    # ── Phase 14: Code quality endpoints ─────────────────────────────────────

    @app.post("/format", dependencies=[Depends(_require_auth)])
    async def format_code(req: FormatRequest) -> dict[str, Any]:
        """Format code using black (Python) or prettier-style (JS/JSON)."""
        lang = req.language.lower()
        content = req.content

        if lang == "python":
            # Try black via subprocess
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: subprocess.run(
                        [sys.executable, "-m", "black", "-", "--quiet"],
                        input=content.encode(),
                        capture_output=True,
                        timeout=15,
                    ),
                )
                if result.returncode == 0:
                    formatted_output = result.stdout.decode()
                    return {"formatted": formatted_output, "tool": "black", "changed": formatted_output != content}
            except Exception:
                pass
            # Fallback: validate syntax only
            try:
                import ast
                ast.parse(content)
                return {"formatted": content, "tool": "none", "changed": False}
            except SyntaxError as exc:
                raise HTTPException(status_code=422, detail=f"Syntax error: {exc}")

        elif lang == "json":
            try:
                parsed = json.loads(content)
                formatted = json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"
                return {"formatted": formatted, "tool": "json", "changed": formatted != content}
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=422, detail=f"Invalid JSON: {exc}")

        else:
            # For other languages just return as-is
            return {"formatted": content, "tool": "none", "changed": False}

    @app.post("/lint", dependencies=[Depends(_require_auth)])
    async def lint_code(req: LintRequest) -> dict[str, Any]:
        """Run static analysis on code. Returns list of diagnostics."""
        lang = req.language.lower()
        if lang != "python":
            return {"diagnostics": [], "tool": "none"}

        # Write content to a temp file and run ruff or pyflakes
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", encoding="utf-8", delete=False
        ) as tmp:
            tmp.write(req.content)
            tmp_path = tmp.name

        diagnostics: list[dict[str, Any]] = []
        tool_used = "none"
        try:
            # Try ruff first
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    [sys.executable, "-m", "ruff", "check", "--output-format=json", tmp_path],
                    capture_output=True,
                    timeout=15,
                ),
            )
            if result.returncode in (0, 1):  # 0=clean, 1=findings
                try:
                    raw = json.loads(result.stdout.decode() or "[]")
                    tool_used = "ruff"
                    for item in raw:
                        diagnostics.append({
                            "line": item.get("location", {}).get("row", 1),
                            "col": item.get("location", {}).get("column", 1),
                            "code": item.get("code", ""),
                            "message": item.get("message", ""),
                            "severity": "warning",
                        })
                except Exception:
                    pass
            if tool_used == "none":
                # Fallback: ast parse
                import ast
                try:
                    ast.parse(req.content)
                except SyntaxError as exc:
                    diagnostics.append({
                        "line": exc.lineno or 1,
                        "col": exc.offset or 1,
                        "code": "E999",
                        "message": str(exc.msg),
                        "severity": "error",
                    })
                tool_used = "ast"
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

        return {"diagnostics": diagnostics, "tool": tool_used}

    @app.get("/stats", dependencies=[Depends(_require_auth)])
    async def workspace_stats(project_path: str = Query(default="")) -> dict[str, Any]:
        """Return code statistics for the workspace or a specific project."""
        target = _safe_path(base_dir / "workspace", project_path) if project_path else base_dir / "workspace"
        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        _EXT_LANG: dict[str, str] = {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".html": "HTML", ".css": "CSS", ".json": "JSON",
            ".md": "Markdown", ".toml": "TOML", ".yaml": "YAML", ".yml": "YAML",
            ".sh": "Shell", ".cpp": "C++", ".c": "C", ".h": "C/C++ Header",
            ".java": "Java", ".rs": "Rust", ".go": "Go",
        }
        _SKIP = {".git", "__pycache__", "node_modules", ".swissagent", "dist", "build"}

        lang_stats: dict[str, dict[str, int]] = {}
        total_files = 0
        total_lines = 0

        for path in target.rglob("*"):
            if path.is_dir():
                continue
            if any(part in _SKIP for part in path.parts):
                continue
            ext = path.suffix.lower()
            lang = _EXT_LANG.get(ext, "Other")
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").count("\n")
            except Exception:
                continue
            total_files += 1
            total_lines += lines
            if lang not in lang_stats:
                lang_stats[lang] = {"files": 0, "lines": 0}
            lang_stats[lang]["files"] += 1
            lang_stats[lang]["lines"] += lines

        breakdown = [
            {"language": k, "files": v["files"], "lines": v["lines"]}
            for k, v in sorted(lang_stats.items(), key=lambda x: x[1]["lines"], reverse=True)
        ]
        return {
            "total_files": total_files,
            "total_lines": total_lines,
            "breakdown": breakdown,
        }

    @app.get("/search/symbol", dependencies=[Depends(_require_auth)])
    async def search_symbol(
        query: str = Query(..., min_length=1),
        language: str = Query(default="python"),
        project_path: str = Query(default=""),
    ) -> dict[str, Any]:
        """Search for function/class/variable definitions matching query."""
        target = _safe_path(base_dir / "workspace", project_path) if project_path else base_dir / "workspace"
        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        lang = language.lower()
        if lang == "python":
            patterns = [
                re.compile(rf"^\s*(def|class|async def)\s+({re.escape(query)}\w*)\s*", re.MULTILINE),
            ]
            ext_filter = {".py"}
        elif lang in ("javascript", "typescript"):
            patterns = [
                re.compile(rf"^\s*(function|class|const|let|var)\s+({re.escape(query)}\w*)\s*", re.MULTILINE),
            ]
            ext_filter = {".js", ".ts", ".jsx", ".tsx"}
        else:
            patterns = [re.compile(rf"\b({re.escape(query)}\w*)\b")]
            ext_filter = None

        _SKIP = {".git", "__pycache__", "node_modules", ".swissagent"}
        results: list[dict[str, Any]] = []

        for path in target.rglob("*"):
            if path.is_dir():
                continue
            if any(part in _SKIP for part in path.parts):
                continue
            if ext_filter and path.suffix.lower() not in ext_filter:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for pattern in patterns:
                for m in pattern.finditer(text):
                    line_no = text[: m.start()].count("\n") + 1
                    results.append({
                        "file": str(path.relative_to(base_dir)),
                        "line": line_no,
                        "match": m.group(0).strip(),
                    })
            if len(results) >= 100:
                break

        return {"results": results[:100], "query": query}

    @app.post("/diff/apply", dependencies=[Depends(_require_auth)])
    async def diff_apply(req: DiffApplyRequest) -> dict[str, Any]:
        """Apply a unified diff patch to a file."""
        if not req.path:
            raise HTTPException(status_code=400, detail="path is required")
        target = _safe_path(base_dir / "workspace", req.path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        original = target.read_text(encoding="utf-8")

        # Use subprocess patch command if available
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".patch", delete=False
        ) as tmp_patch:
            tmp_patch.write(req.patch)
            patch_file = tmp_patch.name

        try:
            result = subprocess.run(
                ["patch", "--dry-run", str(target), patch_file],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise HTTPException(
                    status_code=422,
                    detail=f"Patch validation failed: {result.stderr.decode()[:500]}",
                )
            # Apply for real
            result = subprocess.run(
                ["patch", str(target), patch_file],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise HTTPException(
                    status_code=422,
                    detail=f"Patch apply failed: {result.stderr.decode()[:500]}",
                )
            new_content = target.read_text(encoding="utf-8")
            return {"applied": True, "path": req.path, "line_count_delta": len(new_content.splitlines()) - len(original.splitlines())}
        except HTTPException:
            raise
        except FileNotFoundError:
            raise HTTPException(status_code=501, detail="patch command not available on this system")
        finally:
            try:
                Path(patch_file).unlink(missing_ok=True)
            except Exception:
                pass

    # ── Phase 15: Project Templates & Multi-Language Toolchain ────────────────

    @app.get("/templates")
    async def list_templates() -> dict[str, Any]:
        """Return available project templates from the templates/ directory."""
        tmpl_root = base_dir / "templates"
        templates: list[dict[str, Any]] = []
        if tmpl_root.is_dir():
            for entry in sorted(tmpl_root.iterdir()):
                if not entry.is_dir():
                    continue
                meta_file = entry / "template.json"
                if meta_file.is_file():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    except Exception:
                        meta = {}
                else:
                    meta = {}
                src_dir = entry / "src"
                file_list: list[str] = []
                if src_dir.is_dir():
                    file_list = [f.name for f in sorted(src_dir.iterdir()) if f.is_file()]
                templates.append({
                    "name": entry.name,
                    "description": meta.get("description", ""),
                    "version": meta.get("version", "0.1.0"),
                    "files": file_list,
                })
        return {"templates": templates}

    @app.post("/templates/apply")
    async def apply_template(req: TemplateApplyRequest) -> dict[str, Any]:
        """Copy a template into workspace/<dest> with optional variable substitution."""
        if not req.name or not req.dest:
            raise HTTPException(status_code=400, detail="name and dest are required")
        tmpl_src = base_dir / "templates" / req.name / "src"
        if not tmpl_src.is_dir():
            raise HTTPException(status_code=404, detail=f"Template '{req.name}' not found")
        dest_path = _safe_path(base_dir / "workspace", req.dest)
        dest_path.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for src_file in tmpl_src.rglob("*"):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(tmpl_src)
            dst_file = dest_path / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                content = src_file.read_text(encoding="utf-8")
                for key, val in req.context.items():
                    content = content.replace(f"{{{{{key}}}}}", val)
                dst_file.write_text(content, encoding="utf-8")
            except UnicodeDecodeError:
                shutil.copy2(src_file, dst_file)
            copied.append(str(rel))
        return {"applied": True, "template": req.name, "dest": req.dest, "files": copied}

    @app.get("/toolchain")
    async def detect_toolchain() -> dict[str, Any]:
        """Probe PATH for installed language runtimes and compilers."""
        _PROBES: list[tuple[str, str, list[str]]] = [
            ("python",     "Python",      [sys.executable, "--version"]),
            ("node",       "Node.js",     ["node", "--version"]),
            ("npm",        "npm",         ["npm", "--version"]),
            ("gcc",        "GCC",         ["gcc", "--version"]),
            ("g++",        "G++",         ["g++", "--version"]),
            ("clang",      "Clang",       ["clang", "--version"]),
            ("java",       "Java",        ["java", "-version"]),
            ("javac",      "Java Compiler",["javac", "-version"]),
            ("dotnet",     ".NET",        ["dotnet", "--version"]),
            ("go",         "Go",          ["go", "version"]),
            ("cargo",      "Rust/Cargo",  ["cargo", "--version"]),
            ("rustc",      "Rust",        ["rustc", "--version"]),
            ("lua",        "Lua",         ["lua", "-v"]),
            ("lua5.4",     "Lua 5.4",     ["lua5.4", "-v"]),
            ("ruby",       "Ruby",        ["ruby", "--version"]),
            ("cmake",      "CMake",       ["cmake", "--version"]),
            ("make",       "Make",        ["make", "--version"]),
            ("git",        "Git",         ["git", "--version"]),
        ]
        tools: list[dict[str, Any]] = []
        loop = asyncio.get_event_loop()

        def _probe(cmd: list[str]) -> tuple[bool, str]:
            try:
                r = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=5,
                )
                out = (r.stdout or r.stderr or b"").decode(errors="replace").split("\n")[0].strip()
                return (r.returncode == 0 or bool(out)), out
            except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
                return False, ""

        for key, label, cmd in _PROBES:
            available, version_str = await loop.run_in_executor(None, _probe, cmd)
            if available:
                tools.append({"key": key, "label": label, "version": version_str, "available": True})

        return {"toolchain": tools, "count": len(tools)}

    @app.post("/snippet/run")
    async def run_snippet(req: SnippetRunRequest) -> dict[str, Any]:
        """Run a short code snippet in a chosen language and return output."""
        lang = req.language.lower()
        timeout = max(1, min(req.timeout, 30))  # clamp between 1s and 30s

        _LANG_RUNNERS: dict[str, tuple[str, str]] = {
            "python":     (sys.executable, ".py"),
            "javascript": ("node",          ".js"),
            "bash":       ("bash",          ".sh"),
            "lua":        ("lua",           ".lua"),
            "ruby":       ("ruby",          ".rb"),
        }

        if lang not in _LANG_RUNNERS:
            raise HTTPException(status_code=400, detail=f"Unsupported language '{lang}'. Supported: {list(_LANG_RUNNERS)}")

        runner_cmd, ext = _LANG_RUNNERS[lang]
        # Check runner is available
        if runner_cmd != sys.executable and not shutil.which(runner_cmd):
            raise HTTPException(status_code=501, detail=f"Runtime '{runner_cmd}' not found on this system")

        with tempfile.NamedTemporaryFile(
            suffix=ext, mode="w", encoding="utf-8", delete=False
        ) as tmp:
            tmp.write(req.code)
            tmp_path = tmp.name

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [runner_cmd, tmp_path],
                    capture_output=True,
                    timeout=timeout,
                ),
            )
            return {
                "stdout": result.stdout.decode(errors="replace"),
                "stderr": result.stderr.decode(errors="replace"),
                "returncode": result.returncode,
                "language": lang,
            }
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=408, detail=f"Snippet timed out after {timeout}s")
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    @app.post("/templates/save")
    async def save_template(req: TemplateSaveRequest) -> dict[str, Any]:
        """Snapshot a workspace sub-directory as a new named template."""
        if not req.name or not req.source:
            raise HTTPException(status_code=400, detail="name and source are required")
        # Validate template name (alphanumeric + dash/underscore)
        if not re.match(r"^[a-zA-Z0-9_-]+$", req.name):
            raise HTTPException(status_code=400, detail="Template name must be alphanumeric (dash/underscore allowed)")
        src_path = _safe_path(base_dir / "workspace", req.source)
        if not src_path.exists():
            raise HTTPException(status_code=404, detail="Source path not found in workspace")
        tmpl_dest = base_dir / "templates" / req.name
        if tmpl_dest.exists():
            raise HTTPException(status_code=409, detail=f"Template '{req.name}' already exists")
        tmpl_dest.mkdir(parents=True)
        src_dir = tmpl_dest / "src"
        if src_path.is_dir():
            shutil.copytree(src_path, src_dir)
            files = [f.name for f in sorted(src_dir.rglob("*")) if f.is_file()]
        else:
            src_dir.mkdir()
            shutil.copy2(src_path, src_dir / src_path.name)
            files = [src_path.name]
        meta = {"name": req.name, "description": req.description, "version": "0.1.0", "files": files}
        (tmpl_dest / "template.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return {"saved": True, "name": req.name, "files": files}

    # ── Phase 16: Archive (ZIP / TAR / 7z) ───────────────────────────────────

    @app.post("/archive/pack")
    async def archive_pack(req: ArchivePackRequest) -> dict[str, Any]:
        """Pack a directory or file into a ZIP, TAR, or 7z archive."""
        if not req.src or not req.dst:
            raise HTTPException(status_code=400, detail="src and dst are required")
        from modules.zip.src.zip_tools import zip_pack, tar_pack, sevenz_pack
        fmt = req.format.lower()
        loop = asyncio.get_event_loop()
        try:
            if fmt == "tar":
                result = await loop.run_in_executor(None, lambda: tar_pack(req.src, req.dst))
            elif fmt == "7z":
                result = await loop.run_in_executor(None, lambda: sevenz_pack(req.src, req.dst))
            else:
                result = await loop.run_in_executor(None, lambda: zip_pack(req.src, req.dst))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @app.post("/archive/extract")
    async def archive_extract(req: ArchiveExtractRequest) -> dict[str, Any]:
        """Extract an archive to the given destination directory."""
        if not req.src or not req.dst:
            raise HTTPException(status_code=400, detail="src and dst are required")
        from modules.zip.src.zip_tools import zip_extract, tar_extract, sevenz_extract
        src_lower = req.src.lower()
        loop = asyncio.get_event_loop()
        try:
            if src_lower.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2")):
                result = await loop.run_in_executor(None, lambda: tar_extract(req.src, req.dst))
            elif src_lower.endswith(".7z"):
                result = await loop.run_in_executor(None, lambda: sevenz_extract(req.src, req.dst))
            else:
                result = await loop.run_in_executor(None, lambda: zip_extract(req.src, req.dst))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @app.post("/archive/add")
    async def archive_add_file(req: ArchiveAddFileRequest) -> dict[str, Any]:
        """Add a single file to an existing ZIP archive."""
        from modules.zip.src.zip_tools import zip_add_file
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: zip_add_file(req.archive, req.file)
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    # ── Phase 16: Documentation generator ────────────────────────────────────

    @app.post("/doc/generate")
    async def doc_generate(req: DocGenerateRequest) -> dict[str, Any]:
        """Generate documentation for Python source files and write to output."""
        from modules.doc.src.doc import doc_generate as _gen
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _gen(req.src, req.output, format=req.format, title=req.title or None),
        )
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("error", "doc_generate failed"))
        return result

    @app.post("/doc/lint")
    @app.get("/doc/lint")
    async def doc_lint_endpoint(docs_dir: str = Query(..., description="Path to docs directory")) -> dict[str, Any]:
        """Lint Markdown documentation files for broken links and empty headings."""
        from modules.doc.src.doc import doc_lint
        result = await asyncio.get_event_loop().run_in_executor(None, lambda: doc_lint(docs_dir))
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("error", "doc_lint failed"))
        return result

    # ── Phase 16: Network / HTTP ──────────────────────────────────────────────

    @app.post("/network/download")
    async def network_download(req: NetworkDownloadRequest) -> dict[str, Any]:
        """Download a file from a URL to the local filesystem."""
        if not req.url or not req.dst:
            raise HTTPException(status_code=400, detail="url and dst are required")
        from modules.network.src.network import download_file
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: download_file(req.url, req.dst)
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @app.post("/network/request")
    async def network_http_request(req: NetworkHttpRequest) -> dict[str, Any]:
        """Make an HTTP request and return the response."""
        if not req.url:
            raise HTTPException(status_code=400, detail="url is required")
        from modules.network.src.network import http_get, http_post
        loop = asyncio.get_event_loop()
        method = req.method.upper()
        if method == "GET":
            result = await loop.run_in_executor(
                None, lambda: http_get(req.url, headers=req.headers or None)
            )
        elif method == "POST":
            result = await loop.run_in_executor(
                None, lambda: http_post(req.url, body=req.body, headers=req.headers or None)
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported method: {req.method}")
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    # ── Phase 16: Package manager ─────────────────────────────────────────────

    @app.post("/packages/install")
    async def packages_install(req: PackageInstallRequest) -> dict[str, Any]:
        """Install a package using pip, npm, gem, cargo, or go."""
        if not req.name:
            raise HTTPException(status_code=400, detail="name is required")
        from modules.package.src.package import pkg_install
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: pkg_install(
                req.name,
                version=req.version or None,
                manager=req.manager or None,
                cwd=req.cwd or None,
            ),
        )
        if result.get("returncode", 0) != 0:
            raise HTTPException(status_code=400, detail=result.get("stderr", "install failed"))
        return result

    @app.post("/packages/uninstall")
    async def packages_uninstall(req: PackageUninstallRequest) -> dict[str, Any]:
        """Uninstall a package."""
        if not req.name:
            raise HTTPException(status_code=400, detail="name is required")
        from modules.package.src.package import pkg_uninstall
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: pkg_uninstall(req.name, manager=req.manager or None, cwd=req.cwd or None),
        )
        if result.get("returncode", 0) != 0:
            raise HTTPException(status_code=400, detail=result.get("stderr", "uninstall failed"))
        return result

    @app.get("/packages/list")
    async def packages_list(
        manager: str = Query(default="pip"),
        cwd: str = Query(default=""),
    ) -> dict[str, Any]:
        """List installed packages."""
        from modules.package.src.package import pkg_list
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: pkg_list(manager=manager, cwd=cwd or None)
        )
        return result

    # ── Phase 16: Image processing ────────────────────────────────────────────

    @app.post("/image/resize")
    async def image_resize_endpoint(req: ImageResizeRequest) -> dict[str, Any]:
        """Resize an image to the given dimensions."""
        if not req.path:
            raise HTTPException(status_code=400, detail="path is required")
        from modules.image.src.image_tools import image_resize
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: image_resize(req.path, req.width, req.height, dst=req.dst or None),
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @app.post("/image/convert")
    async def image_convert_endpoint(req: ImageConvertRequest) -> dict[str, Any]:
        """Convert an image to a different format."""
        if not req.path or not req.format:
            raise HTTPException(status_code=400, detail="path and format are required")
        from modules.image.src.image_tools import image_convert
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: image_convert(req.path, req.format, dst=req.dst or None),
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @app.get("/image/info")
    async def image_info_endpoint(path: str = Query(..., description="Path to image file")) -> dict[str, Any]:
        """Return metadata about an image file."""
        from modules.image.src.image_tools import image_info
        result = await asyncio.get_event_loop().run_in_executor(None, lambda: image_info(path))
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    # ── Phase 16: Audio processing ────────────────────────────────────────────

    @app.post("/audio/convert")
    async def audio_convert_endpoint(req: AudioConvertRequest) -> dict[str, Any]:
        """Convert an audio file to a different format or codec."""
        if not req.src or not req.dst:
            raise HTTPException(status_code=400, detail="src and dst are required")
        from modules.audio.src.audio import audio_convert
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: audio_convert(req.src, req.dst, codec=req.codec)
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @app.post("/audio/trim")
    async def audio_trim_endpoint(req: AudioTrimRequest) -> dict[str, Any]:
        """Trim an audio file to the given time range (milliseconds)."""
        if not req.src or not req.dst:
            raise HTTPException(status_code=400, detail="src and dst are required")
        from modules.audio.src.audio import audio_trim
        end = req.end_ms if req.end_ms >= 0 else None
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: audio_trim(req.src, req.dst, start_ms=req.start_ms, end_ms=end)
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @app.get("/audio/info")
    async def audio_info_endpoint(path: str = Query(..., description="Path to audio file")) -> dict[str, Any]:
        """Return metadata about an audio file."""
        from modules.audio.src.audio import audio_info
        result = await asyncio.get_event_loop().run_in_executor(None, lambda: audio_info(path))
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    # ── Phase 16: Debug / process tools ──────────────────────────────────────

    @app.get("/debug/process")
    async def debug_process(pid: int = Query(..., description="Process ID to inspect")) -> dict[str, Any]:
        """Return OS-level information about a running process."""
        if pid <= 0:
            raise HTTPException(status_code=404, detail=f"Invalid process ID: {pid}")
        from modules.debug.src.debug import debug_attach
        result = await asyncio.get_event_loop().run_in_executor(None, lambda: debug_attach(pid))
        if result.get("status") == "error":
            raise HTTPException(status_code=404, detail=result.get("error", "Process not found"))
        return result

    @app.get("/debug/memory")
    async def debug_memory_endpoint(pid: int = Query(..., description="Process ID")) -> dict[str, Any]:
        """Return memory usage information for a process."""
        from modules.debug.src.debug import debug_memory
        result = await asyncio.get_event_loop().run_in_executor(None, lambda: debug_memory(pid))
        if result.get("status") == "error":
            raise HTTPException(status_code=404, detail=result.get("error", "Process not found"))
        return result

    @app.get("/debug/trace")
    async def debug_trace_endpoint(pid: int = Query(..., description="Process ID (use current PID for self-trace)")) -> dict[str, Any]:
        """Capture a stack trace snapshot of a process."""
        from modules.debug.src.debug import debug_trace
        result = await asyncio.get_event_loop().run_in_executor(None, lambda: debug_trace(pid))
        if result.get("status") == "error":
            raise HTTPException(status_code=404, detail=result.get("error", "Trace failed"))
        return result

    # ── Phase 17: Notes & Tasks ───────────────────────────────────────────────

    def _notes_file() -> Path:
        return base_dir / "workspace" / ".notes.json"

    def _tasks_file() -> Path:
        return base_dir / "workspace" / ".tasks.json"

    def _load_json_list(path: Path) -> list:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save_json_list(path: Path, data: list) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    @app.get("/notes")
    async def notes_list() -> dict[str, Any]:
        """List all notes."""
        return {"notes": _load_json_list(_notes_file())}

    @app.post("/notes")
    async def notes_create(req: NoteCreateRequest) -> dict[str, Any]:
        """Create a new note."""
        import time as _time
        if not req.title.strip():
            raise HTTPException(status_code=400, detail="title is required")
        notes = _load_json_list(_notes_file())
        note = {
            "id": str(len(notes) + 1) + "_" + str(int(_time.time())),
            "title": req.title,
            "content": req.content,
            "file_path": req.file_path,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        notes.append(note)
        _save_json_list(_notes_file(), notes)
        return {"status": "ok", "note": note}

    @app.patch("/notes/{note_id}")
    async def notes_update(note_id: str, req: NoteUpdateRequest) -> dict[str, Any]:
        """Update a note's title, content, or file_path."""
        notes = _load_json_list(_notes_file())
        for n in notes:
            if n.get("id") == note_id:
                if req.title:
                    n["title"] = req.title
                if req.content:
                    n["content"] = req.content
                if req.file_path:
                    n["file_path"] = req.file_path
                _save_json_list(_notes_file(), notes)
                return {"status": "ok", "note": n}
        raise HTTPException(status_code=404, detail=f"Note '{note_id}' not found")

    @app.delete("/notes/{note_id}")
    async def notes_delete(note_id: str) -> dict[str, Any]:
        """Delete a note by id."""
        notes = _load_json_list(_notes_file())
        new_notes = [n for n in notes if n.get("id") != note_id]
        if len(new_notes) == len(notes):
            raise HTTPException(status_code=404, detail=f"Note '{note_id}' not found")
        _save_json_list(_notes_file(), new_notes)
        return {"status": "ok", "deleted": note_id}

    @app.get("/tasks")
    async def tasks_list() -> dict[str, Any]:
        """List all task board items."""
        return {"tasks": _load_json_list(_tasks_file())}

    @app.post("/tasks")
    async def tasks_create(req: TaskCreateRequest) -> dict[str, Any]:
        """Create a new task."""
        import time as _time
        if not req.title.strip():
            raise HTTPException(status_code=400, detail="title is required")
        if req.status not in ("todo", "in_progress", "done"):
            raise HTTPException(status_code=400, detail="status must be todo, in_progress, or done")
        tasks = _load_json_list(_tasks_file())
        task = {
            "id": str(len(tasks) + 1) + "_" + str(int(_time.time())),
            "title": req.title,
            "description": req.description,
            "status": req.status,
            "priority": req.priority,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        tasks.append(task)
        _save_json_list(_tasks_file(), tasks)
        return {"status": "ok", "task": task}

    @app.patch("/tasks/{task_id}")
    async def tasks_update(task_id: str, req: TaskUpdateRequest) -> dict[str, Any]:
        """Update a task."""
        tasks = _load_json_list(_tasks_file())
        for t in tasks:
            if t.get("id") == task_id:
                if req.title:
                    t["title"] = req.title
                if req.description:
                    t["description"] = req.description
                if req.status:
                    if req.status not in ("todo", "in_progress", "done"):
                        raise HTTPException(status_code=400, detail="status must be todo, in_progress, or done")
                    t["status"] = req.status
                if req.priority:
                    t["priority"] = req.priority
                _save_json_list(_tasks_file(), tasks)
                return {"status": "ok", "task": t}
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    @app.delete("/tasks/{task_id}")
    async def tasks_delete(task_id: str) -> dict[str, Any]:
        """Delete a task by id."""
        tasks = _load_json_list(_tasks_file())
        new_tasks = [t for t in tasks if t.get("id") != task_id]
        if len(new_tasks) == len(tasks):
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        _save_json_list(_tasks_file(), new_tasks)
        return {"status": "ok", "deleted": task_id}

    # ── Phase 18: Git Advanced Features ──────────────────────────────────────

    @app.get("/git/log")
    async def git_log_endpoint(
        path: str = Query(default="workspace"),
        limit: int = Query(default=20),
    ) -> dict[str, Any]:
        """Return git commit log with sha, message, author, date, files_changed."""
        import subprocess
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, path)
        if not (repo_dir / ".git").exists():
            raise HTTPException(status_code=400, detail="Not a git repository")
        try:
            sep = "|||"
            fmt = f"%H{sep}%s{sep}%an{sep}%ai"
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "log", f"--pretty=format:{fmt}", f"-{limit}"],
                    cwd=str(repo_dir), capture_output=True, text=True, timeout=15,
                ),
            )
            if proc.returncode != 0:
                raise HTTPException(status_code=400, detail=proc.stderr.strip())
            commits = []
            for line in proc.stdout.splitlines():
                parts = line.split(sep, 3)
                if len(parts) == 4:
                    sha, msg, author, date = parts
                    # count files changed
                    stat_proc = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda s=sha: subprocess.run(
                            ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", s],
                            cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
                        ),
                    )
                    files_changed = [f for f in stat_proc.stdout.splitlines() if f]
                    commits.append({
                        "sha": sha[:7],
                        "full_sha": sha,
                        "message": msg,
                        "author": author,
                        "date": date.strip(),
                        "files_changed": files_changed,
                    })
            return {"commits": commits}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/git/branches")
    async def git_branches_list(path: str = Query(default="workspace")) -> dict[str, Any]:
        """List all branches, marking the current branch."""
        import subprocess
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, path)
        if not (repo_dir / ".git").exists():
            raise HTTPException(status_code=400, detail="Not a git repository")
        try:
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "branch", "-a"],
                    cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
                ),
            )
            if proc.returncode != 0:
                raise HTTPException(status_code=400, detail=proc.stderr.strip())
            branches = []
            for line in proc.stdout.splitlines():
                is_current = line.startswith("*")
                name = line.lstrip("* ").strip()
                if name:
                    branches.append({"name": name, "current": is_current})
            return {"branches": branches}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/git/branches")
    async def git_branch_create(req: GitBranchCreateRequest, path: str = Query(default="workspace")) -> dict[str, Any]:
        """Create a new branch, optionally from a base branch."""
        import subprocess
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, path)
        if not (repo_dir / ".git").exists():
            raise HTTPException(status_code=400, detail="Not a git repository")
        if not req.name.strip():
            raise HTTPException(status_code=400, detail="Branch name is required")
        try:
            cmd = ["git", "branch", req.name]
            if req.base:
                cmd.append(req.base)
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, cwd=str(repo_dir), capture_output=True, text=True, timeout=10),
            )
            if proc.returncode != 0:
                raise HTTPException(status_code=400, detail=proc.stderr.strip() or proc.stdout.strip())
            return {"status": "ok", "branch": req.name}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.delete("/git/branches/{name:path}")
    async def git_branch_delete(name: str, path: str = Query(default="workspace")) -> dict[str, Any]:
        """Delete a branch."""
        import subprocess
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, path)
        if not (repo_dir / ".git").exists():
            raise HTTPException(status_code=400, detail="Not a git repository")
        try:
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "branch", "-d", name],
                    cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
                ),
            )
            if proc.returncode != 0:
                raise HTTPException(status_code=400, detail=proc.stderr.strip() or proc.stdout.strip())
            return {"status": "ok", "deleted": name}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/git/checkout")
    async def git_checkout_endpoint(req: GitCheckoutRequest, path: str = Query(default="workspace")) -> dict[str, Any]:
        """Checkout a branch or restore a file."""
        import subprocess
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, path)
        if not (repo_dir / ".git").exists():
            raise HTTPException(status_code=400, detail="Not a git repository")
        if not req.target.strip():
            raise HTTPException(status_code=400, detail="target is required")
        try:
            if req.is_file:
                cmd = ["git", "checkout", "--", req.target]
            else:
                cmd = ["git", "checkout", req.target]
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, cwd=str(repo_dir), capture_output=True, text=True, timeout=15),
            )
            if proc.returncode != 0:
                raise HTTPException(status_code=400, detail=proc.stderr.strip() or proc.stdout.strip())
            return {"status": "ok", "target": req.target}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/git/stash")
    async def git_stash_list(path: str = Query(default="workspace")) -> dict[str, Any]:
        """List all stash entries."""
        import subprocess
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, path)
        if not (repo_dir / ".git").exists():
            raise HTTPException(status_code=400, detail="Not a git repository")
        try:
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "stash", "list"],
                    cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
                ),
            )
            entries = [{"index": i, "description": line.strip()} for i, line in enumerate(proc.stdout.splitlines()) if line.strip()]
            return {"stash": entries}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/git/stash")
    async def git_stash_push(req: GitStashPushRequest, path: str = Query(default="workspace")) -> dict[str, Any]:
        """Push current changes to stash."""
        import subprocess
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, path)
        if not (repo_dir / ".git").exists():
            raise HTTPException(status_code=400, detail="Not a git repository")
        try:
            cmd = ["git", "stash", "push"]
            if req.message:
                cmd += ["-m", req.message]
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, cwd=str(repo_dir), capture_output=True, text=True, timeout=15),
            )
            if proc.returncode != 0:
                raise HTTPException(status_code=400, detail=proc.stderr.strip() or proc.stdout.strip())
            return {"status": "ok", "output": proc.stdout.strip()}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/git/stash/pop")
    async def git_stash_pop(req: GitStashPopRequest, path: str = Query(default="workspace")) -> dict[str, Any]:
        """Pop a stash entry."""
        import subprocess
        top = Path(path).parts[0] if Path(path).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, path)
        if not (repo_dir / ".git").exists():
            raise HTTPException(status_code=400, detail="Not a git repository")
        try:
            cmd = ["git", "stash", "pop", f"stash@{{{req.index}}}"]
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, cwd=str(repo_dir), capture_output=True, text=True, timeout=15),
            )
            if proc.returncode != 0:
                raise HTTPException(status_code=400, detail=proc.stderr.strip() or proc.stdout.strip())
            return {"status": "ok", "output": proc.stdout.strip()}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/git/blame")
    async def git_blame_file(
        repo: str = Query(default="workspace"),
        file: str = Query(..., description="File path relative to the repo root"),
    ) -> dict[str, Any]:
        """Return per-line blame data: sha, author, date, line content."""
        import subprocess
        top = Path(repo).parts[0] if Path(repo).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        repo_dir = _safe_path(base_dir, repo)
        if not (repo_dir / ".git").exists():
            raise HTTPException(status_code=400, detail="Not a git repository")
        try:
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "blame", "--porcelain", file],
                    cwd=str(repo_dir), capture_output=True, text=True, timeout=15,
                ),
            )
            if proc.returncode != 0:
                raise HTTPException(status_code=400, detail=proc.stderr.strip() or proc.stdout.strip())
            import datetime as _blame_dt
            lines = []
            current: dict[str, Any] = {}
            line_num = 0
            for raw in proc.stdout.splitlines():
                if raw.startswith("\t"):
                    line_num += 1
                    lines.append({
                        "line_num": line_num,
                        "sha": current.get("sha", "")[:7],
                        "author": current.get("author", ""),
                        "date": current.get("date", ""),
                        "line": raw[1:],
                    })
                    current = {}
                elif " " in raw:
                    key, _, val = raw.partition(" ")
                    if len(key) == 40 and all(c in "0123456789abcdef" for c in key):
                        current["sha"] = key
                    elif key == "author":
                        current["author"] = val
                    elif key == "author-time":
                        current["date"] = _blame_dt.datetime.fromtimestamp(int(val), tz=_blame_dt.timezone.utc).isoformat()
            return {"blame": lines}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── Phase 19: Project-Wide Refactoring ───────────────────────────────────

    @app.post("/refactor/find-replace")
    async def refactor_find_replace(req: RefactorFindReplaceRequest) -> dict[str, Any]:
        """Find (and optionally replace) text across all workspace files."""
        import re as _re
        import glob as _glob
        workspace_dir = base_dir / "workspace"
        pattern = req.glob_pattern or "**/*"
        matches = []
        files_changed = 0
        try:
            all_files = [
                Path(p) for p in _glob.glob(str(workspace_dir / pattern), recursive=True)
                if Path(p).is_file()
            ]
            for fpath in all_files:
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                file_matches = []
                if req.is_regex:
                    try:
                        compiled = _re.compile(req.find)
                    except _re.error as e:
                        raise HTTPException(status_code=400, detail=f"Invalid regex: {e}")
                    for i, line in enumerate(text.splitlines(), 1):
                        if compiled.search(line):
                            after = compiled.sub(req.replace, line) if req.replace else line
                            file_matches.append({"line": i, "before": line, "after": after})
                else:
                    for i, line in enumerate(text.splitlines(), 1):
                        if req.find in line:
                            after = line.replace(req.find, req.replace) if req.replace else line
                            file_matches.append({"line": i, "before": line, "after": after})
                if file_matches:
                    rel = str(fpath.relative_to(base_dir))
                    for m in file_matches:
                        matches.append({"file": rel, "line": m["line"], "before": m["before"], "after": m["after"]})
                    if not req.dry_run and req.replace:
                        if req.is_regex:
                            new_text = compiled.sub(req.replace, text)
                        else:
                            new_text = text.replace(req.find, req.replace)
                        fpath.write_text(new_text, encoding="utf-8")
                        files_changed += 1
            return {"matches": matches, "files_changed": files_changed, "dry_run": req.dry_run}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/refactor/rename")
    async def refactor_rename(req: RefactorRenameRequest) -> dict[str, Any]:
        """Rename a symbol across all matching workspace files."""
        import glob as _glob
        if not req.old_name.strip() or not req.new_name.strip():
            raise HTTPException(status_code=400, detail="old_name and new_name are required")
        workspace_dir = base_dir / "workspace"
        pattern = req.glob_pattern or "**/*"
        changes = []
        try:
            all_files = [
                Path(p) for p in _glob.glob(str(workspace_dir / pattern), recursive=True)
                if Path(p).is_file()
            ]
            for fpath in all_files:
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                count = text.count(req.old_name)
                if count > 0:
                    new_text = text.replace(req.old_name, req.new_name)
                    fpath.write_text(new_text, encoding="utf-8")
                    changes.append({"file": str(fpath.relative_to(base_dir)), "count": count})
            return {"changes": changes}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/refactor/extract")
    async def refactor_extract(req: RefactorExtractRequest) -> dict[str, Any]:
        """Extract lines from a file into a new named function and return the diff."""
        import difflib
        if not req.file or not req.new_name.strip():
            raise HTTPException(status_code=400, detail="file and new_name are required")
        top = Path(req.file).parts[0] if Path(req.file).parts else ""
        if top not in _BUILD_ROOTS:
            raise HTTPException(status_code=403, detail=f"Root '{top}' not allowed")
        target = _safe_path(base_dir, req.file)
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"File '{req.file}' not found")
        try:
            text = target.read_text(encoding="utf-8")
            lines = text.splitlines(keepends=True)
            total = len(lines)
            s = max(0, req.start_line - 1)
            e = min(total, req.end_line)
            if s >= e:
                raise HTTPException(status_code=400, detail="start_line must be less than end_line")
            extracted = lines[s:e]
            # Detect indent of first extracted line for de-indentation
            first_indent = len(extracted[0]) - len(extracted[0].lstrip()) if extracted else 0
            body = "".join("    " + ln[first_indent:] if ln.strip() else ln for ln in extracted)
            func_def = f"\ndef {req.new_name}():\n{body}\n"
            call_line = " " * first_indent + f"{req.new_name}()\n"
            new_lines = lines[:s] + [call_line] + lines[e:]
            new_text = func_def + "".join(new_lines)
            diff = "".join(difflib.unified_diff(
                lines, new_text.splitlines(keepends=True),
                fromfile=req.file, tofile=req.file,
            ))
            target.write_text(new_text, encoding="utf-8")
            return {"file": req.file, "diff": diff}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return app


# ── Module-level helper functions for chat history + session memory ────────────

def _chat_history_path(base_dir: Path, project_path: str) -> Path:
    if project_path:
        return base_dir / project_path / ".swissagent" / "chat_history.json"
    return base_dir / ".swissagent" / "chat_history.json"


def _load_chat_history(base_dir: Path, project_path: str) -> list[dict[str, Any]]:
    p = _chat_history_path(base_dir, project_path)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_chat_history(base_dir: Path, project_path: str, history: list[dict[str, Any]]) -> None:
    p = _chat_history_path(base_dir, project_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")


def _append_chat_history(
    base_dir: Path, project_path: str, messages: list[dict[str, Any]]
) -> None:
    history = _load_chat_history(base_dir, project_path)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for msg in messages:
        if "ts" not in msg:
            msg = dict(msg, ts=now)
        history.append(msg)
    # Keep last 500 messages to prevent unbounded growth
    _save_chat_history(base_dir, project_path, history[-500:])


def _memory_path(base_dir: Path, project_path: str) -> Path:
    if project_path:
        return base_dir / project_path / ".swissagent" / "session_memory.json"
    return base_dir / ".swissagent" / "session_memory.json"


def _load_session_memory(base_dir: Path, project_path: str) -> dict[str, str]:
    p = _memory_path(base_dir, project_path)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_session_memory(base_dir: Path, project_path: str, mem: dict[str, str]) -> None:
    p = _memory_path(base_dir, project_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(mem, indent=2) + "\n", encoding="utf-8")


# In-process store for files pushed via /api/ide/push
_ide_pending_pushes: list[str] = []

# In-process store for model download jobs
_model_download_jobs: dict[str, Any] = {}
