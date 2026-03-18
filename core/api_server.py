"""SwissAgent HTTP API server (FastAPI)."""
from __future__ import annotations
import asyncio
import json
import os
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

    return app
