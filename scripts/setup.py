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
    for d in ("logs", "cache", "models", "workspace", "projects"):
        (root / d).mkdir(exist_ok=True)
    gitkeep = root / "cache" / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()
    print("Setup complete. Run: swissagent --help")


if __name__ == "__main__":
    main()
