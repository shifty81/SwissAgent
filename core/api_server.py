"""SwissAgent HTTP API server (FastAPI)."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from core.config_loader import ConfigLoader
from core.logger import get_logger, setup_logging
from core.module_loader import ModuleLoader
from core.permission import PermissionSystem
from core.plugin_loader import PluginLoader
from core.task_runner import TaskRunner
from core.tool_registry import ToolRegistry

logger = get_logger(__name__)


class RunRequest(BaseModel):
    prompt: str
    llm_backend: str = "ollama"


class RunResponse(BaseModel):
    result: str


class ToolCallRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = {}


def create_app(config_dir: str = "configs") -> FastAPI:
    setup_logging(log_file="logs/swissagent.log")
    app = FastAPI(
        title="SwissAgent API",
        description="Offline AI-powered development platform API",
        version="0.1.0",
    )
    base_dir = Path(__file__).resolve().parent.parent
    config = ConfigLoader(config_dir)
    config.load()
    registry = ToolRegistry()
    ModuleLoader(base_dir / "modules", registry).load_all()
    PluginLoader(base_dir / "plugins", registry).load_all()
    permissions = PermissionSystem()
    runner = TaskRunner()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "SwissAgent"}

    @app.get("/tools")
    async def list_tools() -> dict[str, Any]:
        return {"tools": registry.list_tools()}

    @app.post("/run", response_model=RunResponse)
    async def run_agent(req: RunRequest) -> RunResponse:
        from core.agent import Agent
        from llm.factory import create_llm
        llm = create_llm(req.llm_backend, config)
        agent = Agent(llm, registry, permissions, runner, config)
        result = agent.run(req.prompt)
        return RunResponse(result=result)

    @app.post("/tools/call")
    async def call_tool(req: ToolCallRequest) -> dict[str, Any]:
        tool = registry.get(req.tool)
        if tool is None:
            raise HTTPException(status_code=404, detail=f"Tool '{req.tool}' not found")
        if not permissions.is_allowed(req.tool, req.arguments):
            raise HTTPException(status_code=403, detail="Permission denied")
        result = runner.run(tool, req.arguments)
        return {"result": result}

    return app
