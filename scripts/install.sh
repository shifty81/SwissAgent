#!/usr/bin/env bash
# SwissAgent — one-liner bootstrap
# Usage:  bash scripts/install.sh [--no-launch] [--host HOST] [--port PORT]
#
# What it does:
#   1. Creates logs/ directory and starts capturing all output to logs/install.log
#   2. Verifies Python 3.10+
#   3. Installs SwissAgent and all Python dependencies (pip install -e .)
#   4. Creates all required project directories
#   5. Checks whether Ollama is installed (and prints install instructions if not)
#   6. Starts the web IDE and opens it in the default browser (default behaviour)
#
# Examples:
#   bash scripts/install.sh                          # install + open web IDE
#   bash scripts/install.sh --no-launch              # install only, no browser
#   bash scripts/install.sh --host 0.0.0.0 --port 9000

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

LAUNCH=1
PORT=8000
HOST="127.0.0.1"

# ── Parse flags ────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-launch)   LAUNCH=0 ;;
    --launch)      LAUNCH=1 ;;
    --port)        PORT="$2"; shift ;;
    --host)        HOST="$2"; shift ;;
    -h|--help)
      echo "Usage: bash scripts/install.sh [--no-launch] [--host HOST] [--port PORT]"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

# ── Create logs dir early so we can start logging immediately ──────────────
mkdir -p "$ROOT_DIR/logs"
LOG_FILE="$ROOT_DIR/logs/install.log"

# Redirect all stdout + stderr to both the terminal and the log file.
exec > >(tee -a "$LOG_FILE") 2>&1

echo "============================================================"
echo "  SwissAgent Installer — $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Log file: $LOG_FILE"
echo "============================================================"
echo ""

# ── Error trap ─────────────────────────────────────────────────────────────
# On any unexpected exit, print a clear message and the log path.
_on_error() {
  local exit_code=$?
  local line_no=$1
  echo ""
  echo "============================================================"
  echo "  [ERR ] Installation failed at line $line_no (exit code $exit_code)."
  echo "  Full log saved to: $LOG_FILE"
  echo "============================================================"
}
trap '_on_error $LINENO' ERR
set -euo pipefail

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

# ── Upgrade pip ─────────────────────────────────────────────────────────────
info "Upgrading pip…"
"$PYTHON_CMD" -m pip install --upgrade pip
ok "pip is up to date."

# ── Install deps ────────────────────────────────────────────────────────────
info "Installing SwissAgent and Python dependencies…"
info "(this may take a minute — all output is captured to $LOG_FILE)"
cd "$ROOT_DIR"
"$PYTHON_CMD" -m pip install -e . --no-warn-script-location
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

  # Read the configured model name from config.toml (default: llama3).
  OLLAMA_MODEL="llama3"
  if [[ -f "$ROOT_DIR/configs/config.toml" ]]; then
    _parsed=$("$PYTHON_CMD" -c "
import sys, re
try:
    import toml
    data = toml.load('$ROOT_DIR/configs/config.toml')
    print(data.get('llm', {}).get('ollama', {}).get('model', 'llama3'))
except Exception:
    print('llama3')
" 2>/dev/null)
    [[ -n "$_parsed" ]] && OLLAMA_MODEL="$_parsed"
  fi

  # Check whether the required model is already pulled.
  info "Checking for Ollama model '$OLLAMA_MODEL'…"
  if ollama list 2>/dev/null | grep -qi "^${OLLAMA_MODEL}[[:space:]:]"; then
    ok "Ollama model '$OLLAMA_MODEL' is available."
  else
    warn "Ollama model '$OLLAMA_MODEL' was not found in 'ollama list'."
    warn "Pulling it now (this may take several minutes on the first run)…"
    if ollama pull "$OLLAMA_MODEL"; then
      ok "Model '$OLLAMA_MODEL' downloaded successfully."
    else
      warn "Could not pull '$OLLAMA_MODEL' automatically."
      warn "Run this manually when ready:  ollama pull $OLLAMA_MODEL"
      warn "Alternatively, set llm_backend = \"api\" in configs/config.toml."
    fi
  fi
else
  warn "Ollama not found on PATH."
  warn "Install it from https://ollama.com/download, then run:"
  warn "   ollama pull llama3"
  warn "Alternatively, set llm_backend = \"api\" in configs/config.toml."
fi

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
ok "Setup complete! 🎉"
echo ""
echo "  Full install log: $LOG_FILE"
echo ""

if [[ "$LAUNCH" -eq 1 ]]; then
  info "Starting SwissAgent IDE at http://$HOST:$PORT …"
  info "Press Ctrl+C to stop the server."
  echo ""
  # Run the server directly (not via exec) so that any startup error is
  # captured by the tee pipe and shown on screen before this script exits.
  "$PYTHON_CMD" -m core.cli ui --host "$HOST" --port "$PORT"
else
  echo "  Quick-start commands:"
  echo "    python -m core.cli ui            # Open web IDE in browser"
  echo "    python -m core.cli serve         # Start API server only"
  echo "    python -m core.cli run \"prompt\" # Run agent from CLI"
  echo "    python -m core.cli list-tools    # List all tools"
  echo ""
  echo "  Run setup + launch together:"
  echo "    bash scripts/install.sh"
  echo "    (or: bash scripts/install.sh --no-launch  to skip browser launch)"
  echo ""
fi
