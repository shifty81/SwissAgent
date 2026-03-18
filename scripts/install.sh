#!/usr/bin/env bash
# SwissAgent — one-liner bootstrap
# Usage:  bash scripts/install.sh [--launch] [--port PORT]
#
# What it does:
#   1. Verifies Python 3.10+
#   2. Installs SwissAgent and all Python dependencies (pip install -e .)
#   3. Creates all required project directories
#   4. Checks whether Ollama is installed (and prints install instructions if not)
#   5. Optionally starts the web IDE and opens it in the default browser
#
# Examples:
#   bash scripts/install.sh              # setup only
#   bash scripts/install.sh --launch     # setup + open browser IDE

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

LAUNCH=0
PORT=8000
HOST="127.0.0.1"

# ── Parse flags ────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --launch)      LAUNCH=1 ;;
    --port)        PORT="$2"; shift ;;
    --host)        HOST="$2"; shift ;;
    -h|--help)
      echo "Usage: bash scripts/install.sh [--launch] [--host HOST] [--port PORT]"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

# ── Helpers ────────────────────────────────────────────────────────────────
info()  { printf "\033[0;34m[INFO]\033[0m  %s\n" "$*"; }
ok()    { printf "\033[0;32m[ OK ]\033[0m  %s\n" "$*"; }
warn()  { printf "\033[0;33m[WARN]\033[0m  %s\n" "$*"; }
error() { printf "\033[0;31m[ERR ]\033[0m  %s\n" "$*" >&2; }

# ── Python check ────────────────────────────────────────────────────────────
info "Checking Python version…"
PYTHON_CMD=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    VER=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    MAJOR=${VER%%.*}
    MINOR=${VER##*.}
    if [[ "$MAJOR" -ge 3 && "$MINOR" -ge 10 ]]; then
      PYTHON_CMD="$cmd"
      ok "Found Python $VER ($cmd)"
      break
    fi
  fi
done

if [[ -z "$PYTHON_CMD" ]]; then
  error "Python 3.10+ is required but was not found."
  error "Download it from https://www.python.org/downloads/"
  exit 1
fi

# ── Install deps ────────────────────────────────────────────────────────────
info "Installing SwissAgent and Python dependencies…"
cd "$ROOT_DIR"
"$PYTHON_CMD" -m pip install -e .
ok "Python dependencies installed."

# ── Create directories ──────────────────────────────────────────────────────
info "Creating required directories…"
DIRS=(
  logs cache models workspace projects plugins
  logs/dev_mode_backups logs/dev_mode_staging
  workspace/sample_project/assets/2D
  workspace/sample_project/assets/3D
  workspace/sample_project/assets/audio
  workspace/sample_project/assets/video
  workspace/sample_project/build
)
for d in "${DIRS[@]}"; do
  mkdir -p "$ROOT_DIR/$d"
done
touch "$ROOT_DIR/cache/.gitkeep" 2>/dev/null || true
ok "Directories ready."

# ── Ollama check ────────────────────────────────────────────────────────────
info "Checking Ollama (local LLM backend)…"
if command -v ollama &>/dev/null; then
  ok "Ollama found at $(command -v ollama)."
else
  warn "Ollama not found on PATH."
  warn "Install it from https://ollama.com/download, then run:"
  warn "   ollama pull llama3"
  warn "Alternatively, set llm_backend = \"api\" in configs/config.toml."
fi

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
ok "Setup complete! 🎉"

if [[ "$LAUNCH" -eq 1 ]]; then
  info "Starting SwissAgent IDE at http://$HOST:$PORT …"
  exec "$PYTHON_CMD" -m core.cli ui --host "$HOST" --port "$PORT"
else
  echo ""
  echo "  Quick-start commands:"
  echo "    swissagent ui                    # Open web IDE in browser"
  echo "    swissagent serve                 # Start API server only"
  echo "    swissagent run \"your prompt\"     # Run agent from CLI"
  echo "    swissagent list-tools            # List all tools"
  echo ""
  echo "  Or run setup + launch together:"
  echo "    bash scripts/install.sh --launch"
  echo ""
fi
