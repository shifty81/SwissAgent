<p align="center">
  <img src="docs/banner.svg" alt="SwissAgent — Your offline Swiss Army knife for AI-powered development" width="100%"/>
</p>

<p align="center">
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-3776ab?logo=python&logoColor=white" alt="Python 3.10+"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?logo=opensourceinitiative&logoColor=white" alt="MIT License"/></a>
  <img src="https://img.shields.io/badge/Offline-First-2ea043?logo=circle&logoColor=white" alt="Offline-First"/>
  <img src="https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Monaco-Editor-007acc?logo=visual-studio-code&logoColor=white" alt="Monaco Editor"/>
  <img src="https://img.shields.io/badge/Modules-42%2B-ff6b6b?logo=puzzle&logoColor=white" alt="42+ Modules"/>
  <img src="https://img.shields.io/badge/Phase-51%20Complete-8957e5?logo=checkmarx&logoColor=white" alt="Phase 51"/>
</p>

<p align="center">
  <strong>SwissAgent</strong> is a self-hosted, fully offline AI development platform.<br/>
  Give it a prompt and it plans, calls tools, writes code, runs builds, processes assets, and reports back —<br/>
  <em>all without sending anything to the cloud.</em>
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/683c01e0-f2c9-4e9f-9794-aa58480d9b84"
       alt="SwissAgent IDE — Monaco editor, activity-bar panels, model downloads, and context-aware AI Agent chat"
       width="100%"/>
</p>

---

> 🐳 **Docker is completely optional.** SwissAgent runs perfectly with just **Python 3.10+** and **Ollama**.  
> 📖 **New here?** Read the **[Step-by-step Setup Guide →](docs/SETUP.md)** including no-Docker, Windows, and all LLM backends.

---

## ✨ What can SwissAgent do?

| Category | Capability |
|---|---|
| 🤖 **Context-Aware AI Chat** | Fully persistent conversation — the AI remembers your entire session, knows the active project, and is aware of every SwissAgent feature |
| 🧠 **AI Persona System** | 13 built-in specialist personas (Senior Developer, Architect, DevOps, Security Auditor, and more) with full app context baked in |
| 🔄 **Agentic AI loop** | plan → tool-call → execute → reflect, up to 20 iterations per task |
| 🧩 **42+ built-in modules** | 200+ tools: filesystem, git, build, image, audio, zip, docs, packages, debug, render, docker, deploy, and more |
| 🖥️ **Monaco Web IDE** | VS Code-style editor with AI chat panel, inline ghost-text completions, and rich activity-bar panels |
| 🔌 **Plugin system** | Drop a Python file into `plugins/` — auto-loaded with no restart needed |
| 🔒 **Permission system** | Fine-grained allow/block control over tools and file paths |
| 🏗️ **Self-build loop** | Reads its own roadmap, writes code, tests in Docker sandbox, commits — fully autonomously |
| 📦 **Archive & packaging** | ZIP / TAR / 7z via `/archive/*` |
| 📄 **Doc generator** | Auto-generate Markdown / HTML / JSON docs from Python source |
| 🌐 **Network tools** | HTTP GET/POST, file download/upload |
| 📥 **Package manager** | pip, npm, cargo, gem, go |
| 🖼️ **Image processing** | Resize, convert, crop, rotate (Pillow) |
| 🔊 **Audio processing** | Convert, trim, normalise (FFmpeg / pydub) |
| 🐳 **Docker management** | Build/run containers, view logs |
| 🚀 **Remote deployment** | SSH-based deploys with history |
| 🗄️ **Database tools** | SQLite/SQL queries and schema management |
| 📡 **Event bus & webhooks** | Real-time pub/sub and webhook delivery |
| ⏱️ **Task queue & cron** | Background jobs and recurring schedules |
| 💡 **Brainstorm mode** | AI-powered ideation sessions → exportable plans |
| 🔍 **Web search** | Search the web for docs and answers |
| 🔐 **Secret vault** | Encrypted local key-value secret storage |
| 📋 **Code snippets** | Save, search, and reuse code fragments |
| 🏠 **Multi-project workspace** | Manage multiple projects from one place |
| 📡 **REST API** | Full HTTP API — use from any language or tool |

---

## 🚀 Quick Start

```bash
# Clone and install
git clone https://github.com/shifty81/SwissAgent.git && cd SwissAgent
bash scripts/install.sh          # installs deps + opens the IDE in your browser
```

**Windows (browser):**
```powershell
git clone https://github.com/shifty81/SwissAgent.git
cd SwissAgent
python -m venv .venv && .venv\Scripts\Activate.ps1
pip install -e .
python -m core.cli ui
```

Then open **http://localhost:8000** — you'll see the Monaco IDE with the context-aware AI chat panel.

**Windows (native C++ app — recommended):**
```powershell
# Install build deps (cmake, WebView2 Runtime, Python package)
.\native\scripts\install-deps.ps1

# Build the native app
cd native\scripts
.\build.bat Release
```

The **`native/`** directory contains a self-contained Win32/WebView2 C++ application that:
- Embeds a lightweight C++ HTTP server (`cpp-httplib`) for the animated startup splash
- Launches the Python backend as a managed child process
- Renders the full IDE in a **WebView2** window (native Edge engine — no Electron/Node required)
- Adds a system-tray icon with restart, show, and quit actions

See **[native/README.md](native/README.md)** for the full build guide.

> 💡 See **[docs/SETUP.md](docs/SETUP.md)** for the full walkthrough including virtual environments, all LLM backends, and Docker Compose.

---

## 🧠 Context-Aware AI Chat

The AI Agent panel (right side of the IDE) maintains **full conversation history** across your entire session:

- Every message you send is remembered — the AI can refer back to earlier parts of the conversation
- The AI knows which project you have open and can use that context in its replies
- The system prompt is pre-loaded with the complete SwissAgent feature catalog so the AI always knows what it can do
- Conversation history is persisted to `.swissagent/chat_history.json` per project — context survives restarts

> **AI Personas:** Switch to a specialist persona (Senior Developer, Security Auditor, DevOps Engineer, etc.) via the AI panel. Each persona inherits full app context so it stays application-aware while taking on its specialist role.

---

## 🤖 AI Persona System (Phase 42)

SwissAgent ships 13 built-in offline specialist personas:

| Persona | Role |
|---|---|
| `senior_developer` | Battle-hardened generalist developer |
| `software_architect` | System design and architecture |
| `frontend_developer` | UI/UX and browser technology |
| `backend_developer` | Server-side logic and APIs |
| `database_engineer` | Database design and optimization |
| `mobile_developer` | iOS/Android/cross-platform |
| `devops_engineer` | CI/CD, containers, infrastructure |
| `security_auditor` | Security review and hardening |
| `test_engineer` | Testing strategy and automation |
| `code_reviewer` | Code review and quality |
| `performance_engineer` | Profiling and optimization |
| `documentation_writer` | Technical writing |
| `ai_ml_engineer` | ML/AI integration |

Use `GET /ai/personas` to list all personas and `POST /ai/persona/{name}/activate` to switch the active one.

---

## 🧠 LLM Backends

| Backend | Flag | Notes |
|---|---|---|
| **Ollama** *(default)* | `--llm-backend ollama` | Local server at `localhost:11434`. No key needed. Best for offline use. |
| **LocalAI** | `--llm-backend localai` | Docker-based OpenAI-compatible server. Great for GGUF/GPTQ models. |
| **Open WebUI** | `--llm-backend openwebui` | Chat UI at `localhost:3000` that can push code into the IDE. |
| **API** | `--llm-backend api` | Any OpenAI-compatible endpoint (OpenAI, Anthropic, Groq, etc.). |
| **Local GGUF** | `--llm-backend local` | Run a `.gguf` model directly via `llama-cpp-python`. |

```bash
# Recommended models via Ollama (one-click from the Model Downloads panel)
ollama pull codestral          # Mistral code specialist — best for code generation
ollama pull deepseek-r1        # DeepSeek reasoning — strong for planning & analysis
ollama pull qwen2.5-coder      # Alibaba Qwen — excellent code completion
ollama pull phi4               # Microsoft Phi-4 — small but capable
ollama pull llama3.2           # Meta Llama 3.2 — fast & lightweight
```

---

## 📋 Prerequisites

| Requirement | Status | Notes |
|---|---|---|
| **Python 3.10+** | ✅ Required | [python.org](https://www.python.org/) |
| **Ollama** | ✅ Recommended | [ollama.com](https://ollama.com) — free, offline |
| **Git** | ✅ Required | For the `git` module |
| **Docker** | ⚙️ Optional | Only for Compose stack or container sandbox |
| **CMake / Make** | ⚙️ Optional | For the `build` module |
| **Blender** | ⚙️ Optional | For the `blender` / `render` modules |
| **FFmpeg** | ⚙️ Optional | For audio conversion in the `audio` module |
| **Pillow** | ⚙️ Optional | For image processing in the `image` module |
| **SoX** | ⚙️ Optional | For SFX generation in the audio pipeline |

---

## 🗂️ Modules (42+ built-in)

<details>
<summary><strong>Click to expand the full module list</strong></summary>

| Module | Description |
|---|---|
| `filesystem` | File read/write/copy/move/delete/list |
| `git` | init, clone, commit, push, pull, diff, log, status |
| `build` | CMake/Make/Ninja build system integration |
| `script` | Python, shell, Lua, Node.js, Java, C# execution |
| `network` | HTTP GET/POST, file download/upload |
| `image` | Resize, convert, crop, rotate, thumbnail |
| `zip` | ZIP/TAR/7z archive creation and extraction |
| `audio` | Audio conversion, trim, normalise, merge |
| `doc` | Documentation generation (Markdown/HTML/JSON) |
| `debug` | Process inspection, stack trace, memory info |
| `package` | pip/npm/cargo/gem/go package management |
| `cache` | Disk-based key-value build artifact caching |
| `memory` | Persistent agent memory (store/recall/search) |
| `security` | Secret scanning, file hashing, checks |
| `index` | Full-text code indexing and regex search |
| `editor` | Code formatting (black, prettier, clang-format) |
| `database` | SQLite/SQL query and management |
| `ui` | UI boilerplate (ImGui, HTML/CSS, Win32) |
| `template` | Project scaffolding from templates |
| `test` | Test runner (pytest, unittest) |
| `ci` | CI/CD pipeline integration |
| `installer` | Application and dependency installer |
| `server` | Local development server management |
| `render` | Rendering and image output |
| `shader` | Shader compilation and management |
| `blender` | Blender integration for 3D content |
| `animation` | Animation data processing |
| `tile` | Tilemap and tileset tooling |
| `asset` | Asset management and tracking |
| `resource` | Game/app resource management |
| `binary` | Binary file analysis and manipulation |
| `pipeline` | Asset and data processing pipelines |
| `profile` | Performance profiling tools |
| `job` | Background job scheduling |
| `api` | REST/GraphQL API client utilities |
| `docker` | Container build, run, logs |
| `deploy` | Remote SSH deployment |
| `knowledge` | RAG-based project documentation search |
| `ai_persona` | AI specialist persona management |
| `brainstorm` | AI ideation and planning sessions |
| `vault` | Encrypted secret key-value store |
| `snippet` | Code snippet library |

</details>

---

## 🌐 REST API Highlights

Start the server: `swissagent serve`, then explore all endpoints at **http://localhost:8000/docs**.

```bash
# Health check
curl http://localhost:8000/health

# Run the context-aware AI agent
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What files are in the workspace?", "project_path": "workspace/myproject"}'

# Manage AI personas
curl http://localhost:8000/ai/personas
curl -X POST http://localhost:8000/ai/persona/senior_developer/activate

# Pack a ZIP archive
curl -X POST http://localhost:8000/archive/pack \
  -H "Content-Type: application/json" \
  -d '{"src": "workspace/myproject", "dst": "workspace/myproject.zip", "format": "zip"}'

# Install a package
curl -X POST http://localhost:8000/packages/install \
  -H "Content-Type: application/json" \
  -d '{"name": "requests", "manager": "pip"}'

# Start a brainstorm session
curl -X POST http://localhost:8000/brainstorm/session \
  -H "Content-Type: application/json" \
  -d '{"title": "New feature ideas"}'
```

---

## 🏗️ Autonomous Self-Build

SwissAgent can build *itself* — reading its own roadmap, writing code, running tests in a Docker sandbox, and committing:

```
roadmap_next_task()
  → LLM generates code
  → apply_patch() writes files
  → Docker sandbox: pytest tests/
  → pass  → git commit + roadmap_complete_task() → next task
  → fail  → retry (max 3) → rollback on final fail
```

**Guardrails:** sandboxed execution · permission system · blocked files · opt-in only.  
See [`docs/self_iteration.md`](docs/self_iteration.md) for the full loop diagram.

---

## 🧩 Plugin System

Drop a Python file into `plugins/` — auto-loaded at startup:

```python
# plugins/my_tool.py
def register(registry):
    def greet(name: str) -> str:
        return f"Hello, {name}!"
    registry.register(
        {"name": "greet", "description": "Greet a person", "module": "my_tool"},
        greet,
    )
```

---

## 🖥️ IDE Panels

| Panel | Icon | Description |
|---|---|---|
| **Explorer** | 📁 | File tree with read/write/create/delete |
| **AI** | 🤖 | Model downloads, persona selection |
| **Search** | 🔍 | Full-text search across all workspace files |
| **Git** | 🔀 | Status, diff viewer, stage/commit |
| **Code** | ✅ | Format, lint, workspace stats, symbol search |
| **Project** | 🏠 | Project management, templates, scaffolding |
| **DevOps** | 🐳 | Docker, CI/CD, remote deploy |
| **Ops** | ⚙️ | Cron, task queue, monitoring, audit log |

---

## ⚙️ Configuration

Edit `configs/config.toml`:

```toml
[agent]
max_iterations = 20
default_llm_backend = "ollama"

[llm.ollama]
base_url = "http://localhost:11434"
model = "llama3"

[permissions]
allowed_dirs = ["workspace", "projects", "cache", "logs"]
blocked_dirs  = ["configs", "core", "llm"]

[server]
host = "127.0.0.1"
port = 8000
```

---

## 📁 Project Structure

```
SwissAgent/
├── core/           # Agent loop, CLI, REST API, config, permissions, tool registry
├── llm/            # LLM backends: Ollama, LocalAI, OpenAI-compatible, local GGUF
├── modules/        # 42+ capability modules (tools.json + src/)
├── plugins/        # Drop-in custom tool plugins
│   └── open_webui_tool/  # Open WebUI → IDE push plugin
├── configs/        # config.toml — all runtime settings
├── gui/            # Web IDE (Monaco editor, AI chat panel, 8 activity-bar panels)
├── workspace/      # Default project workspace + roadmap.json
├── projects/       # Additional managed projects
├── models/         # Local GGUF model files
├── audio_pipeline/ # Offline TTS and SFX generation
├── stable_diffusion/ # AUTOMATIC1111 image generation interface
├── stage_manager/  # Project milestone tracker
├── dev_mode/       # Agent self-upgrade and module patching
├── tools/          # Build runner, feedback parser, media pipeline
├── templates/      # Project scaffolding templates
├── scripts/        # install.sh, setup.py, run_tests.py
├── tests/          # Pytest test suite (429+ tests)
└── docs/           # Extended documentation + banner
```

---

## 🧪 Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v --tb=short
```

---

## 🐳 Docker (Optional Full Stack)

```bash
# Build the SwissAgent image
bash scripts/docker-build.sh   # or: docker build -t swissagent:latest .

# Start the full AI stack (SwissAgent + LocalAI + Open WebUI)
docker compose up -d

# Open the IDE:     http://localhost:8000
# Open the chat UI: http://localhost:3000
```

See [`docs/SETUP.md`](docs/SETUP.md) for the complete Docker guide.

---

## 🗺️ Roadmap

SwissAgent is developed against a living roadmap stored in `workspace/roadmap.json`:

| Phases | Title | Status |
|---|---|---|
| 1–5 | Foundation, Web IDE, Build, Project Mgmt, Roadmap | ✅ Done |
| 6–10 | VS Code IDE, AI Editor, Plugin Ecosystem, Sandbox, Auth | ✅ Done |
| 11–13 | Open-Source AI Stack, Self-Scaffolding, Autonomous Self-Build | ✅ Done |
| 14–16 | Code Quality, Project Templates, General-Purpose Utility APIs | ✅ Done |
| 17–25 | Docker, Deploy, Monitoring, Database, Vault, Webhooks | ✅ Done |
| 26–33 | Event Bus, Cron, Audit Log, Rate Limiting, Feature Flags | ✅ Done |
| 34–37 | Config Profiles, Notification Center, Task Queue | ✅ Done |
| 38–41 | Brainstorm Mode, Web Search, Code Snippets, Diff & Patch | ✅ Done |
| 42–49 | AI Personas, Env Manager, API Client, Suggestions, Health, DocGen, Deps | ✅ Done |
| **50** | **Code Metrics & Complexity Analyzer** | ✅ **Done** |
| **51** | **Git Statistics Dashboard** | ✅ **Done** |
| **52** | **Test Runner & Coverage Dashboard** | ✅ **Done** |
| **53** | **Terminal Manager** | ✅ **Done** |
| **54** | **File Watcher** | ✅ **Done** |
| **55** | **Process Manager** | ✅ **Done** |
| **56** | **Knowledge Base / Notes Manager** | ✅ **Done** |
| **57** | **HTTP Mock Server** | ✅ **Done** |
| **58** | **Bookmark Manager** | ✅ **Done** |
| **59** | **Schema Registry** | ✅ **Done** |
| **60** | **Code Template Engine** | ✅ **Done** |
| **61** | **Changelog Generator** | ✅ **Done** |
| **62** | **Regex Playground** | ✅ **Done** |
| **63** | **Color Palette Manager** | ✅ **Done** |
| **64** | **UUID / Token Generator** | ✅ **Done** |
| **65** | **Text Statistics / Readability Analyzer** | ✅ **Done** |
| **66** | **JSON/YAML Converter & Formatter** | ✅ **Done** |
| **67** | **Hash & Checksum Tool** | ✅ **Done** |

---

## 📄 License

MIT — see [LICENSE](LICENSE)

---

<p align="center">
  Built with ❤️ as a fully offline, self-improving AI development platform.<br/>
  <em>No cloud required. No data leaves your machine.</em>
</p>
