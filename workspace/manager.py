"""Workspace manager — manages multi-project workspaces."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from core.logger import get_logger

logger = get_logger(__name__)


class WorkspaceManager:
    def __init__(self, workspace_root: str | Path = "workspace") -> None:
        self.root = Path(workspace_root)
        self._meta: dict[str, Any] = {}
        self._projects: dict[str, dict[str, Any]] = {}

    def load(self) -> None:
        ws_file = self.root / "workspace.json"
        if ws_file.exists():
            with ws_file.open() as f:
                self._meta = json.load(f)
        for proj_dir in self.root.iterdir():
            if proj_dir.is_dir():
                self._load_project(proj_dir)

    def _load_project(self, proj_dir: Path) -> None:
        meta_file = proj_dir / "project.json"
        if not meta_file.exists():
            return
        with meta_file.open() as f:
            meta = json.load(f)
        name = meta.get("name", proj_dir.name)
        self._projects[name] = {**meta, "_path": str(proj_dir)}
        logger.debug("Loaded project: %s", name)

    def create_project(self, name: str, template: str = "default") -> Path:
        proj_dir = self.root / name
        proj_dir.mkdir(parents=True, exist_ok=True)
        for sub in ("src", "assets", "build", "bin"):
            (proj_dir / sub).mkdir(exist_ok=True)
        meta = {"name": name, "template": template, "version": "0.1.0", "description": ""}
        with (proj_dir / "project.json").open("w") as f:
            json.dump(meta, f, indent=2)
        self._projects[name] = {**meta, "_path": str(proj_dir)}
        logger.info("Created project: %s", name)
        return proj_dir

    @property
    def projects(self) -> dict[str, dict[str, Any]]:
        return dict(self._projects)
