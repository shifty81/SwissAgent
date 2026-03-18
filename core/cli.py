"""SwissAgent CLI entry point."""
from __future__ import annotations
import sys
from pathlib import Path
import click
from core.logger import setup_logging


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging.")
@click.option("--config-dir", default="configs", show_default=True, help="Config directory.")
@click.pass_context
def main(ctx: click.Context, debug: bool, config_dir: str) -> None:
    """SwissAgent — Offline AI-powered development platform."""
    import logging
    setup_logging(level=logging.DEBUG if debug else logging.INFO, log_file="logs/swissagent.log")
    ctx.ensure_object(dict)
    ctx.obj["config_dir"] = config_dir
    ctx.obj["debug"] = debug


@main.command()
@click.argument("prompt")
@click.option("--llm-backend", default="ollama", show_default=True,
              type=click.Choice(["ollama", "local", "api", "openwebui", "localai"]),
              help="LLM backend to use.")
@click.pass_context
def run(ctx: click.Context, prompt: str, llm_backend: str) -> None:
    """Run the agent with a natural language PROMPT."""
    from core.agent import Agent
    from core.config_loader import ConfigLoader
    from core.module_loader import ModuleLoader
    from core.permission import PermissionSystem
    from core.plugin_loader import PluginLoader
    from core.task_runner import TaskRunner
    from core.tool_registry import ToolRegistry
    from llm.factory import create_llm

    config = ConfigLoader(ctx.obj["config_dir"])
    config.load()
    registry = ToolRegistry()
    base_dir = Path(__file__).resolve().parent.parent
    ModuleLoader(base_dir / "modules", registry).load_all()
    PluginLoader(base_dir / "plugins", registry).load_all()
    llm = create_llm(llm_backend, config)
    permissions = PermissionSystem()
    runner = TaskRunner()
    agent = Agent(llm, registry, permissions, runner, config)
    click.echo(agent.run(prompt))


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
@click.option("--open-browser/--no-open-browser", default=False, show_default=True,
              help="Open the GUI in the default browser after starting.")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int, open_browser: bool) -> None:
    """Start the SwissAgent HTTP API server."""
    import uvicorn
    from core.api_server import create_app
    click.echo(f"Starting SwissAgent API server at http://{host}:{port}")
    click.echo("Logs: logs/swissagent.log")
    app = create_app(ctx.obj["config_dir"])
    if open_browser:
        _schedule_browser_open(host, port)
    uvicorn.run(app, host=host, port=port)


@main.command("ui")
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Host to bind the server to.")
@click.option("--port", default=8000, show_default=True, type=int,
              help="Port to listen on.")
@click.pass_context
def ui(ctx: click.Context, host: str, port: int) -> None:
    """Launch the SwissAgent web IDE and open it in the browser."""
    import uvicorn
    from core.api_server import create_app

    url = f"http://{host}:{port}"
    click.echo(f"Starting SwissAgent IDE at {url} …")
    click.echo("Logs: logs/swissagent.log")
    app = create_app(ctx.obj["config_dir"])
    _schedule_browser_open(host, port)
    uvicorn.run(app, host=host, port=port)


def _schedule_browser_open(host: str, port: int) -> None:
    """Open the browser 1.5 s after the server starts (non-blocking)."""
    import threading
    import time
    import webbrowser

    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{display_host}:{port}"

    def _open() -> None:
        time.sleep(1.5)
        webbrowser.open(url)

    t = threading.Thread(target=_open, daemon=True)
    t.start()


@main.command("list-tools")
@click.pass_context
def list_tools(ctx: click.Context) -> None:
    """List all registered tools."""
    from core.module_loader import ModuleLoader
    from core.plugin_loader import PluginLoader
    from core.tool_registry import ToolRegistry
    from rich.console import Console
    from rich.table import Table

    registry = ToolRegistry()
    base_dir = Path(__file__).resolve().parent.parent
    ModuleLoader(base_dir / "modules", registry).load_all()
    PluginLoader(base_dir / "plugins", registry).load_all()
    console = Console()
    table = Table(title="SwissAgent Tools", show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("Module", style="green")
    table.add_column("Description")
    for tool in sorted(registry.list_tools(), key=lambda t: t["name"]):
        table.add_row(tool["name"], tool.get("module", ""), tool.get("description", ""))
    console.print(table)


@main.command("list-modules")
@click.pass_context
def list_modules(ctx: click.Context) -> None:
    """List all loaded modules."""
    from core.module_loader import ModuleLoader
    from core.tool_registry import ToolRegistry
    from rich.console import Console
    from rich.table import Table

    registry = ToolRegistry()
    base_dir = Path(__file__).resolve().parent.parent
    loader = ModuleLoader(base_dir / "modules", registry)
    loader.load_all()
    console = Console()
    table = Table(title="SwissAgent Modules", show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("Version", style="green")
    table.add_column("Description")
    for meta in loader.loaded_modules.values():
        table.add_row(meta.get("name", ""), meta.get("version", ""), meta.get("description", ""))
    console.print(table)


if __name__ == "__main__":
    main()

