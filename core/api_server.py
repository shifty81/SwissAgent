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
        version="0.1.0",
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

    return app
