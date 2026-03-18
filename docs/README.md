# SwissAgent Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Installation & Build](#installation--build)
4. [Configuration Reference](#configuration-reference)
5. [LLM Backends](#llm-backends)
6. [Agent Loop](#agent-loop)
7. [Module Reference](#module-reference)
8. [Plugin Development](#plugin-development)
9. [REST API Reference](#rest-api-reference)
10. [Special Subsystems](#special-subsystems)
11. [Testing](#testing)
12. [Troubleshooting](#troubleshooting)

---

## Overview

SwissAgent is a self-hosted, offline-first AI coding assistant that wraps a local or remote LLM in an agentic loop with 175+ callable tools. You give it a natural-language prompt; it plans steps, selects tools, executes them, observes results, and iterates until the task is done — all without sending source code to the cloud.

**Designed for:**
- Vibe-coding and rapid prototyping across C++, C#, Java, Lua, and Python
- Multi-language project automation (build, test, lint, package)
- Game-adjacent workflows (Blender, shaders, tilemaps, asset pipelines)
- Fully offline operation on a developer workstation

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    User Interface                    │
│            CLI (click)    REST API (FastAPI)         │
└─────────────────┬───────────────────────────────────┘
                  │ prompt
┌─────────────────▼───────────────────────────────────┐
│                   core/agent.py                      │
│  run(prompt)                                         │
│   ├─ _plan()            LLM → step descriptions      │
│   ├─ _select_tool_calls() LLM → tool + arguments    │
│   ├─ _execute_tool()    permission → TaskRunner      │
│   └─ _finalize()        LLM → human-readable answer  │
└────────┬─────────────────┬────────────────────────────┘
         │                 │
┌────────▼──────┐ ┌────────▼──────────────────────────┐
│  llm/         │ │  core/tool_registry.py              │
│  ├─ ollama.py │ │  modules/*/tools.json  (175 tools) │
│  ├─ api.py    │ │  plugins/              (custom)    │
│  └─ local.py  │ └───────────────────────────────────┘
└───────────────┘
```

### Key components

| Component | Path | Purpose |
|-----------|------|---------|
| Agent | `core/agent.py` | Drives the plan→tool→execute loop |
| CLI | `core/cli.py` | `swissagent` command-line entry point |
| API server | `core/api_server.py` | FastAPI HTTP server |
| Config loader | `core/config_loader.py` | TOML config with dot-notation access |
| Tool registry | `core/tool_registry.py` | Registers and looks up all tools |
| Module loader | `core/module_loader.py` | Auto-discovers modules from `modules/` |
| Plugin loader | `core/plugin_loader.py` | Auto-discovers plugins from `plugins/` |
| Permission system | `core/permission.py` | Tool and path allow/block guards |
| Task runner | `core/task_runner.py` | Executes tool callables (thread pool) |
| Logger | `core/logger.py` | Structured logging to file + console |

---

## Installation & Build

### Prerequisites

| Tool | Required | Purpose |
|------|----------|---------|
| Python 3.10+ | ✅ Always | Runtime |
| pip | ✅ Always | Package installer |
| Ollama | Recommended | Default LLM backend |
| Git | For `git` module | Version control tools |
| CMake / Make / Ninja | For `build` module | C/C++ build automation |
| Blender | For `blender`/`render` | 3D/render tools |
| SoX | For audio SFX | Sound effect generation |

### Step-by-step install

```bash
# Clone
git clone https://github.com/shifty81/SwissAgent.git
cd SwissAgent

# (Optional) create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

# Install dependencies and scaffold runtime directories
python scripts/setup.py
```

`scripts/setup.py` does two things:
1. Runs `pip install -e .` (editable install from `pyproject.toml`)
2. Creates runtime directories: `logs/`, `cache/`, `models/`, `workspace/`, `projects/`, `plugins/`

### Manual install (no setup script)

```bash
pip install -e .
mkdir -p logs cache models workspace projects plugins
```

### Running from source without install

```bash
PYTHONPATH=. python -m core.cli run "hello world"
```

### Ollama setup

```bash
# Install Ollama: https://ollama.com
ollama serve                    # start server (runs on port 11434)
ollama pull llama3              # general-purpose model
ollama pull deepseek-coder      # recommended for coding tasks
ollama pull qwen2.5-coder       # strong reasoning + coding
```

---

## Configuration Reference

All settings live in `configs/config.toml`.

```toml
[agent]
max_iterations = 20                # maximum tool-call iterations per run()
default_llm_backend = "ollama"     # "ollama" | "api" | "local"

[llm.ollama]
base_url = "http://localhost:11434" # Ollama server URL
model    = "llama3"                 # any model pulled with `ollama pull`

[llm.api]
base_url = "https://api.openai.com" # any OpenAI-compatible endpoint
key      = ""                        # API key
model    = "gpt-4o"                  # model name

[llm.local]
model_path = "models/model.gguf"    # path to a GGUF model file

[permissions]
allowed_dirs = ["workspace", "projects", "cache", "logs"]
blocked_dirs  = ["configs", "core", "llm"]   # agent cannot write here

[server]
host = "127.0.0.1"
port = 8000

[build]
default_system = "cmake"   # "cmake" | "make" | "ninja"

[cache]
max_size_mb = 512
```

---

## LLM Backends

### Ollama (default, recommended)

Requires a running `ollama serve` instance. No API key needed.

```toml
[llm.ollama]
base_url = "http://localhost:11434"
model    = "deepseek-coder"
```

The Ollama backend calls `/api/chat` for conversation and `/api/generate` for completions. Tool calls are handled by injecting a JSON-instruction prompt.

### OpenAI-compatible API

Works with OpenAI, Anthropic (via proxy), Groq, Together, and any endpoint that follows the `/v1/chat/completions` format.

```toml
[llm.api]
base_url = "https://api.openai.com"
key      = "sk-..."
model    = "gpt-4o"
```

Native `tool_calls` (function-calling) are used when available.

### Local GGUF (stub)

The `local` backend is scaffolded to load a GGUF model via `llama-cpp-python`. The inference call is not yet implemented — it returns stub responses. Provide a model path and implement the `generate()` body in `llm/local.py` to activate it.

```toml
[llm.local]
model_path = "models/mistral-7b-instruct-v0.2.Q4_K_M.gguf"
```

---

## Agent Loop

```
run(prompt)
  while not done and iterations < max_iterations:
    _plan()             → LLM produces a list of step descriptions
    _select_tool_calls() → LLM maps steps to tools + JSON arguments
    for each tool_call:
      permission_check()
      TaskRunner.run(tool, args) → result appended to history
  _finalize()           → LLM summarises all results
  return summary
```

- History is kept in RAM for the duration of a single `run()` call.
- The `memory` module provides persistent cross-run storage.
- Iterations are capped at `agent.max_iterations` (default 20).
- The permission system can block specific tools or file paths.

---

## Module Reference

Modules live in `modules/<name>/`. Each module contains:
- `module.json` — metadata (name, version, description)
- `tools.json` — tool definitions (name, description, function path, argument schema)
- `src/` — Python implementation
- `scripts/` — optional shell/Python helper scripts

### Module status

| Module | Tools | Status | Languages / Notes |
|--------|-------|--------|-------------------|
| `filesystem` | 6 | ✅ Full | read, write, copy, move, delete, list |
| `git` | 8 | ✅ Full | init, clone, commit, push, pull, diff, log, status |
| `build` | 4 | ✅ Full | cmake, make, ninja, msbuild |
| `script` | 12 | ✅ Full | Python, shell, Lua, Node.js, Java, C#, Ruby, Go |
| `network` | 6 | ✅ Full | GET/POST/PUT/DELETE, download, upload |
| `image` | 8 | ✅ Full | resize, convert, crop, rotate, thumbnail |
| `zip` | 8 | ✅ Full | ZIP/TAR/7z create and extract |
| `audio` | 5 | ✅ Full | convert, TTS, SFX, metadata |
| `cache` | 5 | ✅ Full | get, set, delete, list, clear |
| `memory` | 5 | ✅ Full | store, recall, search, delete, list |
| `security` | 6 | ✅ Full | secret scan, hash, permissions check |
| `index` | 4 | ✅ Full | build index, search, update, clear |
| `editor` | 4 | ✅ Full | format (black/prettier/clang-format), lint |
| `database` | 6 | ✅ Full | query, insert, update, delete, schema |
| `ui` | 4 | ✅ Full | ImGui, HTML/CSS, Win32 boilerplate generation |
| `render` | 3 | ⚠️ Stub | Blender render integration |
| `shader` | 6 | ⚠️ Stub | GLSL/HLSL compile and manage |
| `blender` | 5 | ⚠️ Stub | Requires Blender installed |
| `animation` | 5 | ⚠️ Stub | Animation data processing |
| `tile` | 4 | ⚠️ Stub | Tilemap/tileset tooling |
| `asset` | 5 | ⚠️ Stub | Asset tracking and management |
| `resource` | 5 | ⚠️ Stub | Game/app resource management |
| `binary` | 5 | ⚠️ Stub | Binary analysis and manipulation |
| `pipeline` | 4 | ⚠️ Stub | Asset processing pipelines |
| `profile` | 3 | ⚠️ Stub | Performance profiling |
| `package` | 5 | ⚠️ Stub | pip, npm, cargo, etc. |
| `installer` | 3 | ⚠️ Stub | App and dependency installer |
| `server` | 5 | ⚠️ Stub | Local dev server management |
| `template` | 4 | ⚠️ Stub | Project scaffolding |
| `test` | 4 | ⚠️ Stub | pytest, unittest integration |
| `ci` | 4 | ⚠️ Stub | CI/CD pipeline integration |
| `doc` | 3 | ⚠️ Stub | Documentation generation |
| `debug` | 4 | ⚠️ Stub | Debugging utilities |
| `job` | 5 | ⚠️ Stub | Background job scheduling |
| `api` | 4 | ⚠️ Stub | REST/GraphQL client utilities |

---

## Plugin Development

Create a Python file in `plugins/` and expose a `register(registry)` function:

```python
# plugins/my_tool.py
def register(registry):
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    registry.register(
        {
            "name": "greet",
            "description": "Greet a person by name",
            "module": "my_tool",
            "arguments": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
        greet,
    )
```

Plugins are auto-discovered on every startup. No restart required when using `swissagent run` — each invocation rescans.

---

## REST API Reference

Start the server:

```bash
swissagent serve                          # binds 127.0.0.1:8000
swissagent serve --host 0.0.0.0 --port 9000
```

### Endpoints

#### `GET /health`
```json
{"status": "ok", "service": "SwissAgent"}
```

#### `GET /tools`
Returns the full list of registered tool definitions.

#### `POST /run`
Run the agent with a prompt.

**Request:**
```json
{
  "prompt": "write a Python script that prints fibonacci numbers",
  "llm_backend": "ollama"
}
```

**Response:**
```json
{"result": "Done. The script has been written to workspace/fibonacci.py."}
```

#### `POST /tools/call`
Call a single tool directly, bypassing the agent loop.

**Request:**
```json
{
  "tool": "read_file",
  "arguments": {"path": "workspace/main.py"}
}
```

**Response:**
```json
{"result": "...file contents..."}
```

---

## Special Subsystems

### Audio Pipeline (`audio_pipeline/tts_sfx.py`)

Offline audio generation:
- **TTS** — `pyttsx3` synthesises speech from text with no network calls
- **SFX** — SoX CLI generates sound effects

Install dependencies:
```bash
pip install pyttsx3
# Install SoX: https://sox.sourceforge.net  (or `brew install sox` / `apt install sox`)
```

### Stable Diffusion Interface (`stable_diffusion/stable_diffusion_interface.py`)

Connects to an AUTOMATIC1111 WebUI instance for local image generation. Start AUTOMATIC1111 with `--api` flag, then the agent can call image generation tools.

### Stage Manager (`stage_manager/stage_manager.py`)

Tracks project progression through milestones: **Seed → Core → Alpha → Beta → Release**. The agent reads the current stage goal during planning to focus its actions on the right deliverables.

### Dev Mode — Self-Upgrade (`dev_mode/self_upgrade.py`)

The agent can patch its own module stubs and apply code updates. All changes are backed up with timestamps to `logs/dev_mode_backups/` before applying, enabling rollback.

### Build Feedback Parser (`tools/feedback_parser.py`)

Matches 40+ compiler/interpreter error patterns across Python, C/C++, C#, Java, Rust, Go, Kotlin, and TypeScript. Parsed errors are fed back into the agent loop so the agent can self-repair build failures.

### Media Pipeline (`tools/media_pipeline.py`)

Orchestrates offline generation of project assets:
- **2D images** — Pillow placeholder / Stable Diffusion interface
- **Textures & icons** — Pillow
- **3D models** — Blender CLI
- **Audio clips** — pyttsx3 TTS
- **SFX** — SoX
- **Video** — Blender render
- **Asset manifest** — JSON index

---

## Testing

```bash
# All tests
pytest tests/ -v

# Core subsystems only
pytest tests/test_core.py -v

# Module tests only
pytest tests/test_modules.py -v

# With coverage
pip install pytest-cov
pytest tests/ --cov=core --cov=llm --cov=modules -v
```

---

## Troubleshooting

**`swissagent: command not found`**
Run `python scripts/setup.py` first (or `pip install -e .`), then ensure your Python `bin/` directory is on `PATH`.

**`[ERROR] ConnectionRefusedError` with Ollama**
Start the Ollama server: `ollama serve`. Pull a model first: `ollama pull llama3`.

**Agent produces no tool calls**
The LLM may not be following the tool-call prompt. Try a larger or coding-focused model (`deepseek-coder`, `qwen2.5-coder`). Check `logs/swissagent.log` for raw LLM responses.

**`Permission denied for tool '...'`**
The tool or target path is blocked. Review `[permissions]` in `configs/config.toml` and add the path to `allowed_dirs`.

**Module not loading**
Check `logs/swissagent.log` for import errors. Ensure the module's `src/` directory has an `__init__.py` if needed, and that any Python dependencies listed in `module.json` are installed.

