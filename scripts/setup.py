#!/usr/bin/env python3
"""SwissAgent environment setup script.

Usage:
    python scripts/setup.py            # Install deps + create dirs
    python scripts/setup.py --launch   # Also launch the web IDE in browser
"""
from __future__ import annotations
import argparse
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

MIN_PYTHON = (3, 10)


def _check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        sys.exit(
            f"ERROR: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required "
            f"(found {sys.version.split()[0]})."
        )


def _install_deps(root: Path) -> None:
    print("\n[1/4] Installing Python dependencies…")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", str(root)],
        check=True,
    )
    print("      ✓ Python dependencies installed.")


def _create_dirs(root: Path) -> None:
    print("\n[2/4] Creating required directories…")
    dirs = [
        "logs",
        "cache",
        "models",
        "workspace",
        "projects",
        "plugins",
        "logs/dev_mode_backups",
        "logs/dev_mode_staging",
        "workspace/sample_project/assets/2D",
        "workspace/sample_project/assets/3D",
        "workspace/sample_project/assets/audio",
        "workspace/sample_project/assets/video",
        "workspace/sample_project/build",
    ]
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)
    gitkeep = root / "cache" / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()
    print("      ✓ Directories ready.")


def _check_ollama() -> None:
    print("\n[3/4] Checking Ollama (local LLM backend)…")
    if shutil.which("ollama"):
        print("      ✓ Ollama found.")
    else:
        print(
            textwrap.dedent("""\
            ⚠  Ollama not found on PATH.
               SwissAgent uses Ollama as the default LLM backend (100% offline).
               Install it from https://ollama.com/download, then run:
                   ollama pull llama3
               You can also use an OpenAI-compatible API by setting
               llm_backend = "api" in configs/config.toml.
            """)
        )


def _print_summary(root: Path, launch: bool) -> None:
    print("\n[4/4] Setup complete! 🎉")
    print()
    print("      Logs will be written to: logs/swissagent.log")
    print()
    if launch:
        print("      Launching SwissAgent IDE in your browser…")
    else:
        print(
            textwrap.dedent(f"""\
            Quick-start commands:
              # Open the web IDE (auto-opens browser):
              swissagent ui

              # Or start the API server only:
              swissagent serve

              # Run the agent from the CLI:
              swissagent run "list all Python files in workspace/"

              # List available tools:
              swissagent list-tools
            """)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap SwissAgent environment.")
    parser.add_argument(
        "--launch", action="store_true",
        help="Start the web IDE and open it in the default browser after setup.",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Host for the IDE server (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port", default=8000, type=int,
        help="Port for the IDE server (default: 8000).",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent

    _check_python()
    _install_deps(root)
    _create_dirs(root)
    _check_ollama()
    _print_summary(root, args.launch)

    if args.launch:
        subprocess.run(
            [
                sys.executable, "-m", "core.cli",
                "ui",
                "--host", args.host,
                "--port", str(args.port),
            ],
            cwd=str(root),
        )


if __name__ == "__main__":
    main()


