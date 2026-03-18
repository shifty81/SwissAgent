"""SwissAgent HTTP API server (FastAPI)."""
from __future__ import annotations
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
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
    PluginLoader(base_dir / "plugins", registry).load_all()
    permissions = PermissionSystem()
    runner = TaskRunner()

    logger.info("SwissAgent API server initialized. %d tools loaded.", len(registry.list_tools()))

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

            from core.agent import Agent
            from llm.factory import create_llm

            llm = create_llm(backend, config)
            agent = Agent(llm, registry, permissions, runner, config)

            # Run the agent in a thread; stream output line-by-line
            loop = asyncio.get_event_loop()

            def _run() -> str:
                return agent.run(prompt)

            future = loop.run_in_executor(None, _run)

            # Poll for result; in future versions agent can push chunks via a queue
            result = await future
            for line in result.splitlines(keepends=True):
                await websocket.send_text(json.dumps({"type": "chunk", "data": line}))
            await websocket.send_text(json.dumps({"type": "done"}))
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
            f"Code before cursor:\n{req.prefix[-800:]}\n"
            f"<CURSOR>\n"
            f"Code after cursor:\n{req.suffix[:300]}"
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

    return app


# In-process store for files pushed via /api/ide/push
_ide_pending_pushes: list[str] = []
