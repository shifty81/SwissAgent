"""Multi-language build runner with hot-reload support.

Standalone tool for running builds across all supported languages and
optionally hot-reloading Python/Lua modules without a full restart.
"""
from __future__ import annotations
import importlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from core.logger import get_logger

logger = get_logger(__name__)


class BuildRunner:
    """Compile and hot-reload code across multiple languages."""

    LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
        "python": [".py"],
        "lua": [".lua"],
        "cpp": [".cpp", ".cc", ".cxx"],
        "csharp": [".cs"],
        "java": [".java"],
        "rust": [".rs"],
        "go": [".go"],
        "javascript": [".js"],
        "typescript": [".ts"],
        "kotlin": [".kt"],
    }

    def __init__(self) -> None:
        self._hot_modules: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, workspace_path: str) -> str:
        """Build all source files found under workspace_path/src/."""
        src_root = Path(workspace_path) / "src"
        if not src_root.exists():
            return f"[BuildRunner] No src/ directory found in {workspace_path}"
        output_parts: list[str] = []
        for lang_dir in sorted(src_root.iterdir()):
            if not lang_dir.is_dir():
                continue
            for file_path in sorted(lang_dir.rglob("*")):
                if file_path.is_file():
                    result = self._build_file(file_path)
                    if result:
                        output_parts.append(result)
        return "\n".join(output_parts) if output_parts else "[BuildRunner] No buildable files found."

    def hot_reload(self, module_name: str) -> dict:
        """Hot-reload a Python module by dotted name."""
        try:
            mod = sys.modules.get(module_name)
            if mod is not None:
                importlib.reload(mod)
                self._hot_modules[module_name] = mod
                return {"reloaded": module_name, "success": True}
            mod = importlib.import_module(module_name)
            self._hot_modules[module_name] = mod
            return {"imported": module_name, "success": True}
        except Exception as exc:
            logger.error("Hot reload failed for %s: %s", module_name, exc)
            return {"error": str(exc), "success": False}

    def compile_file(self, file_path: str) -> dict:
        """Compile a single file and return the result."""
        result = self._build_file(Path(file_path))
        return {"output": result or "no output", "file": file_path}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_file(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".py":
            return self._run_python(path)
        if suffix == ".lua":
            return self._run_lua(path)
        if suffix in {".cpp", ".cc", ".cxx"}:
            return self._compile_cpp(path)
        if suffix == ".cs":
            return self._build_csharp(path)
        if suffix in {".js", ".mjs"}:
            return self._run_node(path)
        if suffix == ".ts":
            return self._run_typescript(path)
        return ""

    def _run_python(self, path: Path) -> str:
        result = subprocess.run(
            [sys.executable, str(path)], capture_output=True, text=True, timeout=30
        )
        return self._fmt(path.name, result)

    def _run_lua(self, path: Path) -> str:
        result = subprocess.run(
            ["lua", str(path)], capture_output=True, text=True, timeout=30
        )
        return self._fmt(path.name, result)

    def _compile_cpp(self, path: Path) -> str:
        out = path.with_suffix("")
        result = subprocess.run(
            ["g++", str(path), "-o", str(out)], capture_output=True, text=True, timeout=60
        )
        return self._fmt(path.name, result)

    def _build_csharp(self, path: Path) -> str:
        result = subprocess.run(
            ["dotnet", "run", "--project", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        return self._fmt(path.name, result)

    def _run_node(self, path: Path) -> str:
        result = subprocess.run(
            ["node", str(path)], capture_output=True, text=True, timeout=30
        )
        return self._fmt(path.name, result)

    def _run_typescript(self, path: Path) -> str:
        tsc = subprocess.run(
            ["tsc", "--noEmit", str(path)], capture_output=True, text=True, timeout=30
        )
        return self._fmt(path.name, tsc)

    @staticmethod
    def _fmt(name: str, result: subprocess.CompletedProcess) -> str:
        parts = [f"== {name} (rc={result.returncode}) =="]
        if result.stdout.strip():
            parts.append(result.stdout.strip())
        if result.stderr.strip():
            parts.append(result.stderr.strip())
        return "\n".join(parts)
