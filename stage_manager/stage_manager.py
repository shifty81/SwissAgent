"""Stage manager — tracks staged auto-build goals and progression.

Stages represent major milestones in a project's lifecycle.  The agent
loop reads the current stage goal, generates work, and calls
``stage_complete()`` to advance.
"""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
from core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_STAGES: dict[int, dict[str, Any]] = {
    0: {
        "name": "Seed",
        "goal": "Initial project scaffold — create folder structure, entry points, and config files.",
    },
    1: {
        "name": "Core",
        "goal": "Implement core modules: main loop, config, logging, tool registry.",
    },
    2: {
        "name": "Asset Pipeline",
        "goal": "Generate placeholder assets: 2D textures, 3D models, audio, and video.",
    },
    3: {
        "name": "Systems Integration",
        "goal": "Integrate major systems: input, physics, UI, inventory, networking stubs.",
    },
    4: {
        "name": "Stage 1 Release",
        "goal": "Full build, tests, packaging, installer, and deployable release artifact.",
    },
}


@dataclass
class StageState:
    current: int = 0
    completed: list[int] = field(default_factory=list)
    notes: dict[int, str] = field(default_factory=dict)


class StageManager:
    """Manages project build stage progression."""

    def __init__(
        self,
        stages: dict[int, dict[str, Any]] | None = None,
        state_file: str | Path | None = None,
    ) -> None:
        self._stages = stages or dict(_DEFAULT_STAGES)
        self._state_file = Path(state_file) if state_file else None
        self._state = StageState()
        if self._state_file and self._state_file.exists():
            self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_stage(self) -> int:
        return self._state.current

    @property
    def stage_count(self) -> int:
        return len(self._stages)

    def get_stage_goal(self) -> str:
        stage = self._stages.get(self._state.current)
        if stage is None:
            return "All stages complete."
        return f"[Stage {self._state.current} — {stage['name']}] {stage['goal']}"

    def get_stage_name(self) -> str:
        stage = self._stages.get(self._state.current)
        return stage["name"] if stage else "done"

    def is_complete(self) -> bool:
        return self._state.current not in self._stages

    def mark_stage_complete(self, notes: str = "") -> bool:
        """Mark the current stage as done and advance.  Returns False when all done."""
        idx = self._state.current
        if idx not in self._stages:
            logger.info("All stages already complete.")
            return False
        logger.info("Stage %d (%s) complete.", idx, self._stages[idx]["name"])
        self._state.completed.append(idx)
        if notes:
            self._state.notes[idx] = notes
        self._state.current += 1
        self._save()
        return self._state.current in self._stages

    def reset(self) -> None:
        """Reset all stages to the beginning."""
        self._state = StageState()
        self._save()

    def status(self) -> dict[str, Any]:
        return {
            "current_stage": self._state.current,
            "stage_name": self.get_stage_name(),
            "completed": self._state.completed,
            "total_stages": self.stage_count,
            "is_complete": self.is_complete(),
            "goal": self.get_stage_goal(),
        }

    def add_stage(self, index: int, name: str, goal: str) -> None:
        """Add or replace a stage definition."""
        self._stages[index] = {"name": name, "goal": goal}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        if self._state_file is None:
            return
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "current": self._state.current,
            "completed": self._state.completed,
            "notes": {str(k): v for k, v in self._state.notes.items()},
        }
        self._state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> None:
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            self._state.current = data.get("current", 0)
            self._state.completed = data.get("completed", [])
            self._state.notes = {int(k): v for k, v in data.get("notes", {}).items()}
        except Exception as exc:
            logger.warning("Could not load stage state: %s", exc)
