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
    print("\n[1/3] Installing Python dependencies…")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", str(root)],
        check=True,
    )
    print("      ✓ Python dependencies installed.")


def _create_dirs(root: Path) -> None:
    print("\n[2/3] Creating required directories…")
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
    print("\n[3/3] Checking Ollama (local LLM backend)…")
    if shutil.which("ollama"):
        print("      ✓ Ollama found.")
    else:
        print(
            textwrap.dedent("""\
            ⚠  Ollama not found on PATH.
               SwissAgent uses Ollama as the default LLM backend (100% offline).
               Install it from https://ollama.com/download, then run:
                   ollama pull llama3
               You can also use:
                 • An OpenAI-compatible API:  set llm_backend = "api" in configs/config.toml
                 • Open WebUI (chat UI):      set llm_backend = "openwebui" (see below)
            """)
        )


def _print_summary(root: Path, launch: bool) -> None:
    print("\n[3/3] Setup complete! 🎉")
    print()
    print("      Logs will be written to: logs/swissagent.log")
    print()
    if launch:
        print("      Launching SwissAgent IDE in your browser…")
    else:
        print(
            textwrap.dedent("""\
            Quick-start commands:
              # Open the web IDE (auto-opens browser):
              swissagent ui

              # Or start the API server only:
              swissagent serve

              # Run the agent from the CLI:
              swissagent run "list all Python files in workspace/"

              # List available tools:
              swissagent list-tools

            IDE features:
              • Slash commands in chat: /fix  /explain  /test  /docs  /refactor
              • Code blocks have ⬆ Apply to file + 📋 Copy buttons
              • Inline completions (Monaco editor, requires internet for CDN)
              • Files pushed via POST /api/ide/push open automatically

            LLM backends:  ollama (default) | api | openwebui | local
            See configs/config.toml to configure.

            Docker (optional — manual only):
              bash scripts/docker-build.sh   # build image manually first
              docker compose up -d           # then start the full stack
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


