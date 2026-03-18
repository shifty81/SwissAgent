#!/usr/bin/env python3
"""SwissAgent environment setup script."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    print("Installing SwissAgent dependencies...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(root)], check=True)
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
    print("Setup complete. Run: swissagent --help")


if __name__ == "__main__":
    main()

