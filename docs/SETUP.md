# SwissAgent — Complete Setup & Configuration Guide

> **TL;DR — Docker is completely optional.** SwissAgent runs fine without Docker.
> Docker is only needed if you want the full three-service Compose stack (LocalAI + Open WebUI)
> or container-isolated code execution in the sandbox. Everything else works with just Python + Ollama.

---

## Table of Contents

1. [Which path is right for me?](#1-which-path-is-right-for-me)
2. [Path A — Without Docker (Recommended for most users)](#2-path-a--without-docker-recommended-for-most-users)
3. [Path B — With Docker Compose (Full AI stack)](#3-path-b--with-docker-compose-full-ai-stack)
4. [Configuration Reference](#4-configuration-reference)
5. [Choosing an LLM Backend](#5-choosing-an-llm-backend)
6. [Sandbox Execution (Docker vs Subprocess)](#6-sandbox-execution-docker-vs-subprocess)
7. [Common Problems & Fixes](#7-common-problems--fixes)
8. [Windows-Specific Notes](#8-windows-specific-notes)

---

## 1. Which path is right for me?

| Situation | Recommended path |
|-----------|-----------------|
| No Docker installed, or don't want it | ✅ **Path A** — Python + Ollama only |
| Already have Docker and want the full AI stack | **Path B** — Docker Compose |
| Want a cloud LLM (OpenAI / Groq / Anthropic) | **Path A** with `llm_backend = "api"` |
| Trying SwissAgent for the first time | ✅ **Path A** |

---

## 2. Path A — Without Docker (Recommended for most users)

**Requirements:** Python 3.10+ · Git · (Ollama *or* an OpenAI-compatible API key)

### Step 1 — Install Python 3.10+

| OS | How |
|----|-----|
| Windows | Download installer from [python.org/downloads](https://www.python.org/downloads/). Tick **"Add Python to PATH"** during install. |
| macOS | `brew install python@3.11` (requires [Homebrew](https://brew.sh)) or download from python.org. |
| Linux (Debian/Ubuntu) | `sudo apt update && sudo apt install python3.11 python3.11-venv python3-pip` |

Verify:
```bash
python --version   # should print Python 3.10, 3.11, or 3.12
```

### Step 2 — Clone the repository

```bash
git clone https://github.com/shifty81/SwissAgent.git
cd SwissAgent
```

### Step 3 — Create a virtual environment (strongly recommended)

```bash
# Create
python -m venv .venv

# Activate — Linux / macOS
source .venv/bin/activate

# Activate — Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Activate — Windows (Command Prompt)
.venv\Scripts\activate.bat
```

You will need to activate the virtual environment every time you open a new terminal.
Look for `(.venv)` at the start of your prompt — that confirms it is active.

### Step 4 — Install SwissAgent

```bash
bash scripts/install.sh --no-launch
```

This will:
- Install all Python dependencies (`pip install -e .`)
- Create all required directories (`workspace/`, `projects/`, `logs/`, `cache/`, `models/`, `plugins/`)
- Check whether Ollama is installed and print instructions if it is not found

**Windows users** (PowerShell / CMD — no `bash`):
```powershell
pip install -e .
mkdir workspace, projects, logs, cache, models, plugins
```

### Step 5 — Install an LLM backend

You need at least one of the following.

#### Option A — Ollama (recommended, 100% offline)

1. Download and install from [ollama.com/download](https://ollama.com/download)
2. Start the server:
   ```bash
   ollama serve
   ```
3. Pull a model (first time only — downloads a few GB):
   ```bash
   ollama pull llama3            # general purpose
   ollama pull deepseek-coder    # coding focused
   ollama pull qwen2.5-coder     # strong reasoning + code
   ```
4. No further configuration required — `ollama` is the default backend.

#### Option B — OpenAI / Groq / Anthropic API

If you have an API key from any OpenAI-compatible service, edit
`configs/config.toml`:
```toml
[agent]
default_llm_backend = "api"

[llm.api]
base_url = "https://api.openai.com"   # or https://api.groq.com/openai, etc.
key      = "sk-..."                    # your API key
model    = "gpt-4o"                    # or "llama3-70b-8192" for Groq, etc.
```

### Step 6 — Start the IDE

```bash
python -m core.cli ui
```

This opens `http://localhost:8000` in your browser automatically.
Or use the install script to do the same:

```bash
bash scripts/install.sh
```

### Step 7 — Verify everything is working

1. Open `http://localhost:8000` in your browser
2. You should see the SwissAgent Monaco IDE
3. Type a prompt in the chat panel, for example:
   ```
   list all Python files in workspace/
   ```
4. If you see a tool-call response, the agent loop is working ✅

---

## 3. Path B — With Docker Compose (Full AI stack)

This path gives you **SwissAgent IDE + LocalAI (local LLM) + Open WebUI (chat UI)**,
all running as Docker containers.

**Requirements:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) or Docker Engine + Docker Compose (Linux)

### Step 1 — Install Docker

| OS | How |
|----|-----|
| Windows | [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/). Requires WSL 2 (Windows 10/11). |
| macOS | [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/). |
| Linux | [Docker Engine install guide](https://docs.docker.com/engine/install/). Then add your user to the docker group: `sudo usermod -aG docker $USER` |

Verify Docker is running:
```bash
docker --version
docker compose version
```

### Step 2 — Clone the repository

```bash
git clone https://github.com/shifty81/SwissAgent.git
cd SwissAgent
```

### Step 3 — Build the SwissAgent image manually (one-time)

> ⚠ **The SwissAgent image is NOT built automatically by `docker compose up`.** You must build it once before starting the stack.

```bash
bash scripts/docker-build.sh
# or manually:
docker build -t swissagent:latest .
```

### Step 4 — Start the full stack

```bash
docker compose up -d
```

This starts three services:
| Service | URL | Description |
|---------|-----|-------------|
| `swissagent` | http://localhost:8000 | Monaco IDE + REST API |
| `localai` | http://localhost:8080 | Local LLM runtime (OpenAI-compatible) |
| `open-webui` | http://localhost:3000 | Copilot Chat-style brainstorming UI |

### Step 5 — Download a model into LocalAI (first time only)

```bash
docker compose exec localai \
  curl -L -o /models/deepseek-coder.gguf \
  https://huggingface.co/TheBloke/deepseek-coder-6.7B-instruct-GGUF/resolve/main/deepseek-coder-6.7b-instruct.Q4_K_M.gguf
```

> **Note:** Models are stored in the `./models/` directory on your host machine
> and survive container restarts.

### Step 6 — Point SwissAgent at LocalAI

Edit `configs/config.toml`:
```toml
[agent]
default_llm_backend = "localai"
```

### Step 7 — Open the IDE

- SwissAgent IDE → http://localhost:8000
- Open WebUI chat → http://localhost:3000

### Stopping and restarting

```bash
docker compose down          # stop all services
docker compose up -d         # start again
docker compose logs -f       # stream logs from all services
```

---

## 4. Configuration Reference

All settings live in `configs/config.toml`. The file is created automatically
during install. Here is a fully annotated version:

```toml
# ── Agent settings ──────────────────────────────────────────────────────────
[agent]
max_iterations       = 20           # max tool-call loops per prompt
default_llm_backend  = "ollama"     # "ollama" | "api" | "localai" | "openwebui" | "local"

# ── Ollama backend (default, 100% offline) ──────────────────────────────────
[llm.ollama]
base_url = "http://localhost:11434"  # where Ollama is listening
model    = "llama3"                  # any model you have pulled

# ── OpenAI-compatible API backend ───────────────────────────────────────────
[llm.api]
base_url = "https://api.openai.com"  # or Groq / Anthropic proxy / etc.
key      = ""                         # set your API key here
model    = "gpt-4o"

# ── LocalAI backend (Docker Compose path) ───────────────────────────────────
[llm.localai]
base_url = "http://localhost:8080"
key      = ""
model    = "deepseek-coder"          # model file name loaded in LocalAI

# ── Open WebUI backend ──────────────────────────────────────────────────────
[llm.openwebui]
base_url = "http://localhost:3000"
key      = ""                         # from Open WebUI → Settings → API Keys
model    = ""                         # leave blank to auto-select

# ── Local GGUF backend (llama-cpp-python) ───────────────────────────────────
[llm.local]
model_path = "models/model.gguf"     # path to a local GGUF file

# ── Permission system ───────────────────────────────────────────────────────
[permissions]
allowed_dirs = ["workspace", "projects", "cache", "logs"]
blocked_dirs  = ["configs", "core", "llm"]  # agent cannot write here

# ── REST API server ─────────────────────────────────────────────────────────
[server]
host = "127.0.0.1"   # use 0.0.0.0 to expose on the network
port = 8000

# ── Build system ────────────────────────────────────────────────────────────
[build]
default_system = "cmake"   # "cmake" | "make" | "ninja"

# ── Build artifact cache ─────────────────────────────────────────────────────
[cache]
max_size_mb = 512
```

---

## 5. Choosing an LLM Backend

| Backend | Internet required | API key | Best for |
|---------|------------------|---------|----------|
| `ollama` | ❌ No | ❌ No | Default. Most users. |
| `api` | ✅ Yes | ✅ Yes | GPT-4o, Claude, Groq — highest quality |
| `localai` | ❌ No | ❌ No | Docker Compose stack |
| `openwebui` | ❌ No | Optional | Open WebUI + IDE push integration |
| `local` | ❌ No | ❌ No | Direct GGUF file (advanced) |

Change backend at any time via the IDE dropdown, the CLI `--llm-backend` flag,
or by editing `default_llm_backend` in `configs/config.toml`.

---

## 6. Sandbox Execution (Docker vs Subprocess)

The `/sandbox/run` API endpoint lets the agent run commands in isolation.
**Docker is NOT required** for this feature.

| `use_docker` value | Docker installed? | What happens |
|--------------------|------------------|--------------|
| `false` (default) | n/a | Runs via subprocess with a timeout |
| `true` | ✅ Yes | Runs in an isolated Docker container (`--network=none`, `--memory=256m`) |
| `true` | ❌ No | **Automatically falls back to subprocess** with a `warning` field in the response |

When Docker is not available, the endpoint still works — the response will include:
```json
{
  "status": "ok",
  "docker": false,
  "warning": "Docker is not installed on this system. Command ran via subprocess fallback (no container isolation).",
  "stdout": "...",
  ...
}
```

For the **Autonomous Self-Build** loop (Roadmap Phase 13), container isolation is
strongly recommended in production. For local development and experimentation,
the subprocess fallback is perfectly usable.

---

## 7. Common Problems & Fixes

### `swissagent: command not found`

The `swissagent` entry-point script is installed by `pip install -e .`. If it is
not found on PATH:

```bash
# Option 1: run as a module instead
python -m core.cli run "my prompt"
python -m core.cli ui

# Option 2: ensure pip's script directory is on PATH
python -m pip show swissagent   # shows "Location: ..."
# Add <Location>/../bin (Linux/macOS) or <Location>\..\..\Scripts (Windows) to PATH
```

### `ConnectionRefusedError` when using Ollama

Ollama is not running. Start it:
```bash
ollama serve
```
Or on Windows/macOS, open the Ollama desktop app from the system tray.

### Agent produces no tool calls

The model is probably too small or not code-focused enough. Try:
```bash
ollama pull deepseek-coder
ollama pull qwen2.5-coder
```
Then update `configs/config.toml`:
```toml
[llm.ollama]
model = "deepseek-coder"
```

### `Permission denied for tool '...'`

Add the path to `allowed_dirs` in `configs/config.toml`:
```toml
[permissions]
allowed_dirs = ["workspace", "projects", "cache", "logs", "my_new_dir"]
```

### IDE shows blank page / Monaco editor does not load

The Monaco editor loads from jsDelivr CDN. An internet connection is required
the first time. After the first load, the browser caches it. If you are fully
offline, a locally hosted fallback textarea editor is shown automatically.

### Open WebUI says it cannot connect to SwissAgent

1. Make sure SwissAgent is running: `python -m core.cli serve`
2. The SwissAgent plugin needs the `SWISSAGENT_BASE_URL` variable pointing at
   your SwissAgent instance. See `plugins/open_webui_tool/README.md`.

### `docker compose up` fails with port conflict

A port is already in use. Change the exposed port in `docker-compose.yml`:
```yaml
ports:
  - "8001:8000"   # map to a different host port
```

---

## 8. Windows-Specific Notes

- Use **PowerShell** or **Git Bash** (not Command Prompt) for the best experience.
- Replace `bash scripts/install.sh` with:
  ```powershell
  pip install -e .
  New-Item -ItemType Directory -Force workspace, projects, logs, cache, models, plugins
  ```
- The `sandbox/run` endpoint uses `sh -c <cmd>`. On Windows this requires Git Bash
  or WSL to be on PATH, or change the shell to `cmd /c`. For cross-platform safety,
  keep your commands POSIX-compatible or test on Linux/WSL.
- Docker Desktop on Windows requires **WSL 2** (Windows Subsystem for Linux, v2).
  Enable it in PowerShell as Administrator:
  ```powershell
  wsl --install
  ```
  Then install Docker Desktop and ensure the WSL 2 integration is enabled in
  Docker Desktop → Settings → Resources → WSL Integration.
