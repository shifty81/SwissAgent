# SwissAgent

> Your offline Swiss Army knife for vibe coding — an AI-powered development platform that reads, writes, builds, and automates your projects using natural language prompts.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

SwissAgent is a self-hosted, fully offline coding assistant. Give it a prompt and it plans, calls tools, writes code, runs builds, processes assets, and reports back — all without sending anything to the cloud. It supports **C++, C#, Java, Lua, Python, and Blender** workflows out of the box.

## Features

- 🤖 **Agentic AI loop** — plan → tool-call → execute → reflect, up to 20 iterations per task
- 🔌 **35 built-in modules** — 175+ tools covering filesystem, git, build, image, audio, render, and more
- 🧩 **Plugin system** — drop a folder into `plugins/` to add custom tools at runtime
- 🔒 **Permission system** — fine-grained allow/block control over tools and file paths
- 🖥️ **CLI + REST API** — `swissagent run "…"` from the terminal, or POST to `/run`
- 📦 **Offline-first** — default backend is [Ollama](https://ollama.com); no API key required
- 🌐 **OpenAI-compatible API backend** — connect any OpenAI-compatible endpoint (GPT-4o, Anthropic, etc.)
- 🎨 **Asset pipeline** — 2D/3D/audio/video asset generation wired into the agent loop
- 🎙️ **Audio pipeline** — offline TTS via `pyttsx3` and SFX generation via SoX
- 🖼️ **Stable Diffusion interface** — image generation via AUTOMATIC1111 web-UI API
- 🏗️ **Stage manager** — milestone-driven project progression (Seed → Core → Alpha → Beta → Release)
- 🔧 **Self-upgrade / dev mode** — agent can patch its own module stubs and roll back via timestamped backups
- 🏠 **Multi-project workspace** — manage multiple projects from one place

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Python 3.10+** | [python.org](https://www.python.org/downloads/) |
| **Ollama** *(recommended)* | [ollama.com](https://ollama.com) — run `ollama pull llama3` after install |
| **Git** | Required for the `git` module |
| **CMake / Make / Ninja** | Optional — required for the `build` module |
| **Blender** | Optional — required for the `blender` and `render` modules |
| **SoX** | Optional — required for SFX generation in the audio pipeline |

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/shifty81/SwissAgent.git
cd SwissAgent

# 2. Install Python dependencies and create required directories
python scripts/setup.py
```

`setup.py` runs `pip install -e .` and creates the `workspace/`, `projects/`, `cache/`, `models/`, `plugins/`, and `logs/` directories.

### Virtual environment (recommended)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python scripts/setup.py
```

### Install from PyPI (alternative)

```bash
pip install swissagent
```

## Quick Start

```bash
# Run the agent with a natural language prompt (uses Ollama by default)
swissagent run "list all Python files in workspace/"

# Use a different LLM backend
swissagent run "refactor workspace/main.py" --llm-backend api
swissagent run "summarise recent git commits" --llm-backend local

# Discover available tools and modules
swissagent list-tools
swissagent list-modules

# Start the HTTP API server
swissagent serve
swissagent serve --host 0.0.0.0 --port 8000

# Enable debug logging
swissagent --debug run "build the project with cmake"
```

## LLM Backends

| Backend | Flag | Description |
|---------|------|-------------|
| `ollama` *(default)* | `--llm-backend ollama` | Local Ollama server (`http://localhost:11434`). No API key needed. Recommended models: `llama3`, `deepseek-coder`, `codellama`, `qwen2.5-coder` |
| `api` | `--llm-backend api` | Any OpenAI-compatible endpoint (OpenAI, Anthropic, Groq, etc.). Set `key` in `configs/config.toml`. |
| `local` | `--llm-backend local` | GGUF model via `llama-cpp-python` (stub — provide `model_path` in config). |

### Recommended Ollama models

```bash
ollama pull llama3             # general purpose
ollama pull deepseek-coder     # coding tasks
ollama pull qwen2.5-coder      # coding + reasoning
ollama pull codellama          # code generation
```

## Modules

All 35 built-in modules are auto-discovered from the `modules/` directory at startup.

| Module | Tools | Description |
|--------|-------|-------------|
| `filesystem` | 6 | File read/write/copy/move/delete/list |
| `git` | 8 | init, clone, commit, push, pull, diff, log, status |
| `build` | 4 | CMake/Make/Ninja build system integration |
| `script` | 12 | Python, shell, Lua, Node.js, Java, C# script execution |
| `network` | 6 | HTTP GET/POST/PUT/DELETE, file download/upload |
| `image` | 8 | Resize, convert, crop, rotate, thumbnail, metadata |
| `zip` | 8 | ZIP/TAR/7z archive creation and extraction |
| `audio` | 5 | Audio processing, conversion, TTS, SFX |
| `cache` | 5 | Disk-based key-value build artifact caching |
| `memory` | 5 | Persistent agent memory (store, recall, search, delete, list) |
| `security` | 6 | Secret scanning, file hashing, vulnerability checks |
| `index` | 4 | Full-text code indexing and regex search |
| `editor` | 4 | Code formatting (black, prettier, clang-format) and linting |
| `database` | 6 | SQLite/SQL query and management |
| `ui` | 4 | UI boilerplate generation (ImGui, HTML/CSS, Win32) |
| `template` | 4 | Project scaffolding from templates |
| `test` | 4 | Test runner integration (pytest, unittest, etc.) |
| `ci` | 4 | CI/CD pipeline integration |
| `doc` | 3 | Documentation generation |
| `debug` | 4 | Debugging utilities and diagnostics |
| `package` | 5 | Package manager integration (pip, npm, cargo, etc.) |
| `installer` | 3 | Application and dependency installer |
| `server` | 5 | Local development server management |
| `render` | 3 | Rendering and image output |
| `shader` | 6 | Shader compilation and management |
| `blender` | 5 | Blender integration for 3D content creation |
| `animation` | 5 | Animation data processing |
| `tile` | 4 | Tilemap and tileset tooling |
| `asset` | 5 | Asset management and tracking |
| `resource` | 5 | Game/app resource management |
| `binary` | 5 | Binary file analysis and manipulation |
| `pipeline` | 4 | Asset and data processing pipelines |
| `profile` | 3 | Performance profiling tools |
| `job` | 5 | Background job scheduling and management |
| `api` | 4 | REST/GraphQL API client utilities |

## Configuration

Edit `configs/config.toml` to customise behaviour:

```toml
[agent]
max_iterations = 20
default_llm_backend = "ollama"

[llm.ollama]
base_url = "http://localhost:11434"
model = "llama3"          # any model pulled via `ollama pull <name>`

[llm.api]
base_url = "https://api.openai.com"
key = ""                  # your OpenAI / Anthropic / Groq API key
model = "gpt-4o"

[llm.local]
model_path = "models/model.gguf"  # path to a GGUF model file

[permissions]
allowed_dirs = ["workspace", "projects", "cache", "logs"]
blocked_dirs  = ["configs", "core", "llm"]

[server]
host = "127.0.0.1"
port = 8000

[build]
default_system = "cmake"

[cache]
max_size_mb = 512
```

## REST API

Start the server with `swissagent serve`, then:

```bash
# Health check
curl http://localhost:8000/health

# List all registered tools
curl http://localhost:8000/tools

# Run the agent
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": "list Python files in workspace/", "llm_backend": "ollama"}'

# Call a single tool directly
curl -X POST http://localhost:8000/tools/call \
  -H "Content-Type: application/json" \
  -d '{"tool": "read_file", "arguments": {"path": "workspace/main.py"}}'
```

## Plugin System

Drop a Python file into the `plugins/` directory. It will be auto-loaded at startup if it exposes a `register(registry)` function:

```python
# plugins/my_tool.py
def register(registry):
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    registry.register(
        {"name": "greet", "description": "Greet a person by name",
         "module": "my_tool"},
        greet,
    )
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run only core tests
pytest tests/test_core.py -v

# Run only module tests
pytest tests/test_modules.py -v
```

## Project Structure

```
SwissAgent/
├── core/           # Agent loop, CLI, REST API, config, permissions, tool registry
├── llm/            # LLM backends: Ollama, OpenAI-compatible API, local GGUF stub
├── modules/        # 35 capability modules (tools.json + src/)
├── plugins/        # Drop-in custom tool plugins
├── configs/        # config.toml — all runtime settings
├── workspace/      # Default project workspace
├── projects/       # Additional managed projects
├── models/         # Local GGUF model files
├── audio_pipeline/ # Offline TTS and SFX generation
├── stable_diffusion/ # AUTOMATIC1111 image generation interface
├── stage_manager/  # Project milestone tracker
├── dev_mode/       # Agent self-upgrade and module patching
├── tools/          # Build runner, feedback parser, media pipeline
├── templates/      # Project scaffolding templates
├── scripts/        # setup.py environment bootstrap
├── tests/          # Pytest test suite
└── docs/           # Extended documentation
```

## License

MIT — see [LICENSE](LICENSE)
