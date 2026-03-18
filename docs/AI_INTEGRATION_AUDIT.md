# SwissAgent — AI Integration Audit & NovaForge Engine Comparison

> **Purpose:** Full audit of every AI integration point in SwissAgent today, a detailed
> breakdown of the reusable (non-game) components in
> [NovaForge / Atlas Engine](https://github.com/shifty81/NovaForge), a head-to-head
> comparison of the two, and a frank recommendation on which codebase should carry the
> AI integration work going forward.

---

## Table of Contents

1. [SwissAgent — Current AI Integration Inventory](#1-swissagent--current-ai-integration-inventory)
2. [NovaForge — Reusable Engine & Editor Inventory (game stripped)](#2-novaforge--reusable-engine--editor-inventory-game-stripped)
3. [Side-by-Side Comparison](#3-side-by-side-comparison)
4. [Recommendation](#4-recommendation)
5. [AI Integration Roadmap](#5-ai-integration-roadmap)

---

## 1. SwissAgent — Current AI Integration Inventory

### 1.1 LLM Backends (`llm/`)

| File | Backend | Status | Notes |
|------|---------|--------|-------|
| `llm/base.py` | Abstract interface | ✅ Implemented | `chat()`, `generate()`, `tool_call()` |
| `llm/ollama.py` | Ollama (local HTTP) | ✅ Implemented | Default; no key required; streaming via REST |
| `llm/api.py` | OpenAI-compatible API | ✅ Implemented | GPT-4o, Anthropic, any OpenAI-compatible endpoint |
| `llm/local.py` | llama-cpp-python | ⚠️ Stub only | GGUF path wired in config, but `generate()` not implemented |
| `llm/factory.py` | Backend factory | ✅ Implemented | Reads `llm.backend` from `configs/config.toml` |

**Gaps identified:**
- No streaming output to CLI/API — full response buffered before returning.
- `llm/local.py` has the path plumbing but the actual inference call is missing.
- No retry/fallback logic if Ollama is unavailable.
- No token-counting or context-window management.
- No embedding support (`text-embedding-*`, `nomic-embed-text`, etc.).

---

### 1.2 Agent Loop (`core/agent.py`)

```
run(prompt)
 ├─ _plan()               LLM produces a list of step descriptions
 ├─ _select_tool_calls()  LLM maps each step → tool + arguments (JSON)
 ├─ _execute_tool()       Permission check → TaskRunner → result appended to history
 └─ _finalize()           LLM summarises all results into a human answer
```

**Current state:**
- Single-threaded inner loop; `TaskRunner` uses a 4-worker thread pool only for actual tool I/O.
- Maximum 20 iterations; no adaptive early-stopping.
- No streaming of intermediate results — CLI blocks until fully done.
- Planning step is a single LLM call; no tree-of-thought or self-critique.
- No multi-agent / parallel-agent capability.
- History is held in RAM only — no persistent conversation across `run()` calls by default.

---

### 1.3 Tool & Module System (`core/tool_registry.py`, `modules/`, `plugins/`)

| Capability | Implementation | Status |
|------------|----------------|--------|
| Tool registration via JSON | `modules/*/tools.json` | ✅ |
| Plugin discovery | `plugins/` directory scan | ✅ |
| 36 built-in modules | See full table in README | ✅ / ⚠️ (many are stubs) |
| Permission guard on tool calls | `core/permission.py` | ✅ |
| Hot reload of modules | Not implemented | ❌ |

**Fully implemented modules:** `filesystem`, `git`, `build`, `image`, `script`, `network`, `cache`, `memory`, `ui`, `editor`, `audio`, `index`, `zip`.

**Stubs (scaffolding only):** `render`, `shader`, `blender`, `animation`, `tile`, `security`, `doc`, `debug`, `asset`, `resource`, `profile`, `package`, `installer`, `api`, `server`, `database`, `job`, `pipeline`, `test`, `ci`, `template`, `binary`.

---

### 1.4 Memory System (`modules/memory/`)

| Function | Description | Status |
|----------|-------------|--------|
| `memory_store(key, value)` | Persist arbitrary text to disk | ✅ |
| `memory_recall(key)` | Retrieve exact key | ✅ |
| `memory_search(query)` | Substring/regex search across stored memories | ✅ |
| `memory_delete(key)` | Remove a memory | ✅ |
| `memory_list()` | Enumerate all keys | ✅ |

**Gap:** Search is substring/regex only — no semantic (vector) search.  No embeddings, no FAISS/Chroma, no RAG pipeline.

---

### 1.5 Audio Pipeline (`audio_pipeline/tts_sfx.py`)

| Capability | Library | Status |
|------------|---------|--------|
| Text-to-speech | `pyttsx3` (offline) | ✅ |
| Sound-effect generation | `SoX` CLI | ✅ |
| Speech-to-text (STT / Whisper) | Not implemented | ❌ |
| Streaming audio output | Not implemented | ❌ |

---

### 1.6 Image Generation (`stable_diffusion/stable_diffusion_interface.py`)

| Capability | Status |
|------------|--------|
| AUTOMATIC1111 web-UI API integration | ✅ stub/interface |
| Local diffusion model loading | ❌ not implemented |
| Prompt-to-image in agent loop | ❌ no tool definition wired |
| ControlNet / img2img | ❌ |

---

### 1.7 Media Pipeline (`tools/media_pipeline.py`)

Offline asset generation called by the agent to produce project assets:

| Generator | Backing technology | Status |
|-----------|--------------------|--------|
| 2D image | Pillow placeholder / SD interface | ⚠️ placeholder fallback |
| Texture / icon | Pillow | ✅ basic |
| 3D model | Blender CLI | ⚠️ requires Blender installed |
| Audio clip | pyttsx3 TTS | ✅ |
| SFX | SoX | ✅ |
| Video | Blender render | ⚠️ requires Blender |
| Asset manifest | JSON index | ✅ |

---

### 1.8 Stage Manager (`stage_manager/`)

Tracks project build progression through 5 default milestones (Seed → Core → Alpha → Beta → Release). Not directly AI integration, but the agent reads the current stage goal to guide its planning step.

---

### 1.9 Dev Mode — Self-Upgrade (`dev_mode/self_upgrade.py`)

Agent can regenerate its own internal tool stubs, apply patches to `modules/`, and roll back via timestamped backups. This is a unique self-improvement capability that no other system in this comparison provides.

---

### 1.10 UI Code Generation (`modules/ui/src/ui.py`)

Generates boilerplate UI code for three frameworks: ImGui (C++), HTML/CSS, Win32 API. This is AI-assisted code synthesis, not a runtime UI framework.

---

### 1.11 Code Intelligence (`modules/editor/`, `modules/index/`)

- **editor module:** Calls external formatters (black, prettier, clang-format, gofmt, rustfmt) and linters (flake8, eslint, cppcheck, cargo clippy).
- **index module:** Full-text regex indexing of a project tree; `index_search(query)` for substring/regex code search.

**Gap:** No AST-level analysis, no LSP integration, no semantic code search.

---

### 1.12 Build Feedback Parser (`tools/feedback_parser.py`)

40+ error patterns matched across Python, C/C++, C#, Java, Rust, Go, Kotlin, TypeScript.  Parsed errors are fed back into the agent loop so the agent can attempt self-repair.

---

### 1.13 REST API (`core/api_server.py`)

FastAPI server exposing:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Liveness check |
| `/tools` | GET | List all registered tools |
| `/run` | POST | Run agent with prompt |
| `/tools/call` | POST | Invoke a single tool directly |

**Gap:** No WebSocket for streaming, no auth/rate-limiting, no session/conversation state.

---

### 1.14 Configuration (`configs/config.toml`)

```toml
[llm.ollama]
base_url = "http://localhost:11434"
model    = "llama3"

[llm.api]
base_url = "https://api.openai.com"
key      = ""
model    = "gpt-4o"

[llm.local]
model_path = "models/model.gguf"

[permissions]
allowed_dirs = ["workspace", "projects", "cache", "logs"]
blocked_dirs = ["configs", "core", "llm"]
```

---

## 2. NovaForge — Reusable Engine & Editor Inventory (game stripped)

This section covers **only** what remains after removing all game-specific content
(`cpp_server/` game systems, `data/` JSON, `cpp_client/` game rendering). The reusable
layer consists of:

```
engine/   ← Atlas Engine (generic, game-agnostic)
editor/   ← Atlas Editor (standalone PCG/content authoring tool)
cpp_client/include/editor/  ← 32 header-only editor tools + EditorToolLayer
tools/    ← Python modding utilities (validate_json, create_ship, Blender addon)
```

---

### 2.1 Atlas Engine (`engine/`)

**Language:** C++17  
**Build:** CMake 3.20+  
**License:** (see NovaForge repo)

| Subsystem | Directory | Purpose |
|-----------|-----------|---------|
| **ECS** | `engine/ecs/` | Type-safe entity/component/system framework + `DeltaEditStore` for editor property overrides |
| **GraphVM** | `engine/graphvm/` | Deterministic bytecode virtual machine + compiler for gameplay/workflow logic |
| **Assets** | `engine/assets/` | Asset registry, `.atlasb` binary format, hot-reload, serialization |
| **Networking** | `engine/net/` | Client-Server + P2P, lockstep/rollback, delta compression, lag compensation, jitter buffer |
| **Simulation** | `engine/sim/` | Fixed-rate tick scheduler, deterministic execution |
| **World** | `engine/world/` | Cube-sphere (planetary), voxel grid, LOD |
| **Animation** | `engine/animation/` | Skeletal, blend weights |
| **Audio** | `engine/audio/` | OpenAL-based audio subsystem |
| **Camera** | `engine/camera/` | Free-fly, orbit, ortho |
| **Input** | `engine/input/` | Keyboard, mouse, controller |
| **Physics** | `engine/physics/` | Collision, movement |
| **Plugin** | `engine/plugin/` | C++ plugin architecture |
| **Core/Logging** | `engine/core/` | Bootstrap, logging, configuration |

**Key engine properties relevant to AI integration:**
- **Deterministic simulation** — identical output given the same seed; critical for reproducible AI inference pipelines.
- **GraphVM** — a compiled bytecode VM that could represent AI reasoning graphs / workflow DAGs with zero-overhead native execution.
- **Hot-reload assets** — update AI model weights or prompt templates without restarting.
- **Plugin architecture** — each AI backend can be a loaded plugin.
- **ECS for state** — agent state, conversation history, tool results can all be ECS components; the tick scheduler drives the agent loop.

---

### 2.2 Atlas Editor (`editor/`)

**Language:** C++17  
**UI framework:** ImGui (docking) + Atlas UI  
**Build:** CMake; standalone binary or F12 overlay inside game client

#### 2.2.1 Core Editor Infrastructure

| Component | Purpose |
|-----------|---------|
| `editor/ui/` | Docking layout, keybind manager, undo stack |
| `EditorCommandBus` | FIFO fire-and-forget command execution |
| `UndoableCommandBus` | Full undo/redo stack |
| `EditorEventBus` | Publish-subscribe event system |
| `DeltaEditStore` | Records and persists property deltas across PCG regeneration |
| `SceneBookmarkManager` | Save/restore editor state checkpoints |

#### 2.2.2 Editor Panels

| Panel | Purpose |
|-------|---------|
| `ECSInspectorPanel` | Real-time entity/component state inspector |
| `NetInspectorPanel` | Network state debugger |
| `ConsolePanel` | Debug console with log levels |

#### 2.2.3 Editor Tools (27 active tools)

Animation Editor, Asset Stats Panel, Batch Operations, Camera View, Delta Edits Merge, Edit Propagation, Environment Control, Event Timeline, Function Assignment, Hotkey Manager, IK Rig Tool, Layer/Tag System, Lighting Control, Live Edit Mode, Map Editor, Material/Shader Tool, Multi-Selection Manager, NPC Spawner, PCG Snapshot Manager, Prefab Library, Resource Balancer, Scene Bookmark Manager, Script Console, Ship Module Editor, Simulation Step Controller, Snap/Align Tool, Visual Diff Tool.

#### 2.2.4 AI Integration in Editor (`editor/ai/`)

| Component | Size | Purpose |
|-----------|------|---------|
| `AIAggregator` | ~850 lines | Central orchestrator — manages backend selection, coordinates prompt generation and response parsing |
| `LocalLLMBackend` | ~12,000 lines | Ollama / LLaMA local integration; prompt engineering for PCG assets; response validation; fallback routing |
| `TemplateAIBackend` | ~5,600 lines | Deterministic template-based generation; fallback when LLM unavailable; seed-controlled |

**What the AI layer generates:** procedural ship designs, space stations, mission narratives, NPC personalities, quest text.

---

### 2.3 Atlas UI Framework (`cpp_client/include/ui/atlas/`)

Custom immediate-mode, GPU-accelerated UI toolkit:
- Single draw-call batching — all UI in one GPU pass
- Sci-fi widget set: panels, status arcs, capacitor rings, module racks, overview tables
- Drag-to-move panels, click, tab switching, scrolling
- Themeable (teal, amber, colorblind-safe)
- **Zero external dependencies** beyond OpenGL 3.3

---

### 2.4 EditorToolLayer (F12 Overlay, `cpp_client/include/editor/`)

32 header-only editor tools compiled into the game client. Toggle with F12. Compile out completely (`NOVAFORGE_EDITOR_TOOLS=OFF`) for zero-overhead release builds. Shared infrastructure: `EditorCommandBus`, `UndoableCommandBus`, `EditorEventBus`.

---

### 2.5 Python Tooling (`tools/`)

| Tool | Purpose |
|------|---------|
| `validate_json.py` | JSON schema + range validation |
| `create_ship.py` | Interactive CLI wizard for creating ship definitions |
| `BlenderSpaceshipGenerator/` | Blender 3.0+ addon: 18 ship classes, 4 faction styles, modular PCG, JSON import/export |

---

### 2.6 Build & Test Infrastructure

- CMake 3.20+ with presets; `make build-all` / `make test`
- Engine test suite: **374+ assertions**
- Server test suite: **832+ assertions** across 170+ functions
- Docker: `docker build -f Dockerfile -t nova-forge-server .`
- Cross-platform: Windows, Linux, macOS

---

## 3. Side-by-Side Comparison

| Dimension | SwissAgent | NovaForge (engine + editor only) |
|-----------|-----------|----------------------------------|
| **Language** | Python 3.10+ | C++17 |
| **LLM backends** | Ollama ✅, OpenAI-compat API ✅, local stub ⚠️ | LocalLLMBackend (Ollama/LLaMA) ✅, TemplateAIBackend ✅ |
| **Agent / orchestration loop** | Plan → select tools → execute → finalize (Python, iterative) | No general-purpose agent loop; AI is invoked from editor panels for PCG tasks |
| **Tool / plugin system** | 36 JSON-defined modules + plugin loader | C++ plugin architecture; 27 editor tools; all game-specific |
| **Memory / state** | Key-value disk store; no vector search | ECS components + DeltaEditStore (property deltas); no general-purpose memory |
| **UI** | Generates HTML / ImGui / Win32 *code* (not a runtime UI) | Full GPU-accelerated immediate-mode UI (Atlas UI); docking editor shell (ImGui) |
| **Editor** | `editor` module calls external formatters/linters | Full 27-tool docking editor with undo/redo, event buses, F12 overlay |
| **Audio** | pyttsx3 TTS + SoX SFX ✅; Whisper STT ❌ | OpenAL playback; no TTS/STT |
| **Image / asset generation** | Stable Diffusion stub + Pillow textures | Blender PCG addon; AIAggregator for PCG JSON; no raster diffusion |
| **Code execution** | 10+ languages via subprocess | None (game engine, not a code runner) |
| **Build runner** | Multi-language compiler/hot-reload (Python) | CMake/Make C++ build for engine itself |
| **Self-improvement** | Dev mode: agent rewrites its own tools | Not present |
| **Stage / project progression** | Stage manager (5 milestones) | 15-phase roadmap (doc only, not runtime) |
| **REST API** | FastAPI `/run`, `/tools`, `/health` | None (client-server game protocol, not a general API) |
| **Networking** | HTTP REST only | Full lockstep/rollback, delta compression, lag compensation (game networking) |
| **Determinism** | Not guaranteed | Deterministic simulation + GraphVM (strong guarantee) |
| **Performance** | Python — adequate for I/O-bound tool dispatch | C++ — orders of magnitude faster for CPU-bound workloads |
| **Ecosystem** | Python LLM ecosystem (LangChain, HuggingFace, etc.) | C++ — rich game-dev ecosystem; thinner LLM tooling |
| **Iteration speed** | Fast — edit a `.py` file, reload | Slower — recompile C++ |
| **Test coverage** | Partial (tests/ directory exists, coverage unknown) | 374 engine + 832 server assertions |
| **Documentation** | `docs/README.md` (minimal) | 30+ markdown files covering every subsystem |
| **Maturity of AI integration** | LLM wired in, agent loop functional | AI used in one narrow domain (PCG); much larger codebase for that one use case |
| **Self-contained offline operation** | Yes — Ollama default | Yes — LocalLLMBackend + TemplateAIBackend fallback |
| **Ease of adding new AI tools** | Very easy — add a `tools.json` entry | Hard — requires C++ code + CMake rebuild |

---

## 4. Recommendation

### Short answer

**Keep SwissAgent as the primary AI integration platform. Borrow specific architectural patterns from NovaForge rather than replacing the platform.**

### Rationale

#### Where NovaForge's non-game components would genuinely help

| NovaForge asset | What to borrow | How to apply in SwissAgent |
|-----------------|----------------|---------------------------|
| **Atlas Editor patterns** | Docking panel system, `EditorCommandBus`, `UndoableCommandBus`, `EditorEventBus` | Implement a proper Python web dashboard (FastAPI + htmx or React) with an undo/redo action log, event bus, and panel layout — a "SwissAgent Studio" |
| **`DeltaEditStore`** | Property-delta tracking across regeneration | Apply in the memory module: track which agent-generated artefacts have been manually overridden so reruns don't clobber human edits |
| **`AIAggregator` pattern** | Central orchestrator that routes to multiple AI backends with fallback | Refactor `llm/factory.py` into a full `AIAggregator` that: (a) tries each backend in priority order, (b) caches results, (c) falls back to template generation |
| **`TemplateAIBackend`** | Seed-controlled deterministic fallback when LLM unavailable | Add a template backend to `llm/` so SwissAgent stays usable when no model server is running |
| **GraphVM concept** | Deterministic compiled workflow execution | Model the agent loop as a directed graph (nodes = plan steps, edges = tool dependencies) so steps can run in topological order, not just sequentially; allows parallelism and replay |
| **`LocalLLMBackend`** | Production-grade Ollama/LLaMA integration | Complete `llm/local.py` using the patterns in NovaForge's 12,000-line implementation; add proper prompt templates, response validation, and retry logic |
| **Plugin architecture** | Formal versioned plugin contracts | Strengthen SwissAgent's `PluginLoader` with version constraints, capability declarations, and sandboxed execution |
| **Test suite structure** | 800+ assertion server test suite | Adopt the same assertion-density approach for SwissAgent modules — especially the tool registry and agent loop |

#### Why a full migration to NovaForge engine would *not* be better suited

1. **Wrong abstraction level.** Atlas Engine is a real-time deterministic game simulation engine. SwissAgent's workload is I/O-bound, LLM-latency-bound, and asynchronous by nature — not fixed-rate tick-driven.

2. **No agent loop.** NovaForge has no general-purpose autonomous agent (plan → tool → execute → reflect). The AI integration is a narrow PCG module that generates game content JSON on demand. Building an agent loop on top of Atlas Engine would require writing the entire orchestration layer from scratch in C++.

3. **Python LLM ecosystem is irreplaceable at this stage.** Virtually every open-source LLM tool (LangChain, LlamaIndex, HuggingFace Transformers, vLLM, llama-cpp-python, Whisper, etc.) is Python-first. Replicating this in C++ would multiply development effort by 5-10×.

4. **Iteration speed.** The edit-test cycle for AI prompts, tool definitions, and module logic in Python takes seconds. Recompiling C++ takes minutes to hours.

5. **REST API is already production-grade.** SwissAgent's FastAPI server is a better integration surface for AI tools than anything in NovaForge, which has no general HTTP API.

6. **Game-engine features are irrelevant to the use-case.** Delta compression, lag compensation, cube-sphere world generation, skeletal animation, OpenGL rendering — none of these contribute to an AI development assistant.

---

## 5. AI Integration Roadmap

> This roadmap is ordered by value-to-effort ratio. Items marked **[NovaForge-inspired]**
> directly incorporate patterns or code from the NovaForge audit.

---

### Phase 1 — Foundation Hardening (Weeks 1–4)

- [ ] **Complete `llm/local.py`** — Implement `generate()` and `tool_call()` using `llama-cpp-python`; load GGUF from `configs/config.toml`; add context-window truncation. *[NovaForge-inspired: port prompt templates from `LocalLLMBackend`]*
- [ ] **Add `TemplateBackend`** — Deterministic fallback that returns structured tool-call JSON from templates when no LLM is available. *[NovaForge-inspired: `TemplateAIBackend`]*
- [ ] **LLM retry / fallback chain** — `AIAggregator` wrapper over `factory.py`: try primary backend → secondary → template, with exponential back-off. *[NovaForge-inspired: `AIAggregator` pattern]*
- [ ] **Streaming responses** — Add `stream=True` to Ollama and API backends; pipe tokens to CLI and WebSocket endpoint.
- [ ] **Token budget management** — Track input + output tokens per call; truncate history to fit context window; log usage.
- [ ] **Expand test coverage** — Achieve 80%+ coverage on `core/`, `llm/`, and all fully-implemented modules. *[NovaForge-inspired: 800+ assertion density]*

---

### Phase 2 — Semantic Memory & RAG (Weeks 5–8)

- [ ] **Embedding backend** — Add `llm/embedder.py` supporting `nomic-embed-text` via Ollama or `text-embedding-ada-002` via API.
- [ ] **Vector store** — Integrate FAISS or ChromaDB for local vector search; add `memory_embed(key, text)` and `memory_semantic_search(query, top_k)` tools.
- [ ] **RAG pipeline** — Before each LLM call, retrieve top-k relevant memories and prepend as context.
- [ ] **Persistent conversation history** — Serialize conversation state to `workspace/{project}/history.json`; reload on next `run()`.
- [ ] **`DeltaEditStore` equivalent** — Track which agent-generated files have been manually edited; skip regeneration of those files. *[NovaForge-inspired: `DeltaEditStore`]*

---

### Phase 3 — Agent Loop Upgrade (Weeks 9–12)

- [ ] **Graph-based planning** — Replace the flat plan list with a DAG: steps that don't depend on each other can run in parallel via `TaskRunner`. *[NovaForge-inspired: GraphVM concept]*
- [ ] **ReAct pattern** — After each tool call, LLM reflects on the result and decides next action (Reason → Act → Observe loop).
- [ ] **Self-critique / verification step** — After `_finalize()`, a second LLM call checks the answer against the original prompt and flags gaps.
- [ ] **Multi-agent support** — `AgentPool` manages N concurrent agents; a coordinator agent delegates sub-tasks; results are merged.
- [ ] **Adaptive iteration limit** — Stop early if all plan steps succeeded; extend limit if still making progress.

---

### Phase 4 — Developer Experience & UI (Weeks 13–18)

- [ ] **SwissAgent Studio (Web UI)** — FastAPI + htmx or React dashboard with: live tool-call log, agent state panel, memory browser, config editor. *[NovaForge-inspired: docking panel system, ConsolePanel, ECSInspectorPanel]*
- [ ] **WebSocket endpoint** — `/ws/run` streams tokens, tool results, and status updates in real time.
- [ ] **Undo/redo action log** — All file writes and tool calls tracked in an audit log; `undo_last_action()` tool rolls back the most recent destructive operation. *[NovaForge-inspired: `UndoableCommandBus`]*
- [ ] **Event bus** — `core/event_bus.py`: publish agent events (tool_called, plan_updated, error) that UI and plugins can subscribe to. *[NovaForge-inspired: `EditorEventBus`]*
- [ ] **Session auth** — API key or JWT for the REST server; rate-limiting per client.

---

### Phase 5 — Audio & Vision (Weeks 19–24)

- [ ] **Whisper STT** — Add `audio_pipeline/stt_whisper.py` using `openai-whisper` (offline); expose `transcribe_audio(path)` tool.
- [ ] **Streaming TTS** — Replace pyttsx3 with Coqui TTS or Kokoro for higher quality; support voice cloning from a sample.
- [ ] **Complete Stable Diffusion integration** — Wire `stable_diffusion_interface.py` into a proper `generate_image(prompt, model, steps)` tool; add ControlNet support; expose in media pipeline.
- [ ] **Vision / multimodal LLM** — Add `llava`, `bakllava`, or GPT-4V support in the API backend; enable `analyze_image(path)` tool.
- [ ] **3D asset generation** — Complete the Blender module stub; provide `generate_3d_model(prompt)` tool that calls Blender CLI with a generated Python script. *[NovaForge-inspired: BlenderSpaceshipGenerator patterns]*

---

### Phase 6 — Code Intelligence (Weeks 25–30)

- [ ] **LSP integration** — `modules/lsp/` wraps `pylsp`, `clangd`, `rust-analyzer` via subprocess; exposes `get_completions`, `get_diagnostics`, `go_to_definition` tools.
- [ ] **AST-level code analysis** — Use `tree-sitter` (Python bindings) for language-agnostic AST parsing; expose `find_function(name)`, `list_classes()`, `extract_dependencies()` tools.
- [ ] **Semantic code search** — Embed all indexed source files; `index_semantic_search(query)` returns relevant code chunks ranked by embedding similarity.
- [ ] **Auto-fix pipeline** — After `feedback_parser` detects errors, agent automatically applies suggested fixes (pip install, import correction, type annotation) without human prompting.
- [ ] **Test generation** — `generate_tests(file)` tool: LLM reads source → generates pytest / unittest file → runs it → iterates on failures.

---

### Phase 7 — Plugin Ecosystem & Self-Improvement (Weeks 31–36)

- [ ] **Versioned plugin contracts** — `plugins/*/plugin.json` gains `api_version`, `capabilities[]`, and `dependencies[]`; loader enforces compatibility. *[NovaForge-inspired: versioned plugin architecture]*
- [ ] **Plugin marketplace / registry** — `plugins/registry.json` lists community plugins with install URL; `swissagent plugin install <name>` downloads and activates.
- [ ] **Dev mode — agent-generated modules** — Expand `dev_mode/self_upgrade.py`: agent can write a new module from a spec, run its tests, and self-register it.
- [ ] **Prompt library** — `configs/prompts/` directory of versioned, tagged prompt templates; agent selects best template for each task type.
- [ ] **Fine-tuning pipeline** — Export agent conversation logs → JSONL training format → `tools/finetune.py` calls Ollama or HuggingFace to fine-tune a small model on domain-specific interactions.
- [ ] **Benchmark suite** — Automated evaluation of agent performance on a fixed set of tasks; tracks regression across LLM backend upgrades.

---

### Summary Table

| Phase | Focus | Key Deliverables | Timeline |
|-------|-------|-----------------|----------|
| 1 | Foundation | Local LLM, template fallback, AIAggregator, streaming, tests | Weeks 1–4 |
| 2 | Semantic Memory | Embeddings, vector store, RAG, persistent history | Weeks 5–8 |
| 3 | Agent Loop | DAG planning, ReAct, self-critique, multi-agent | Weeks 9–12 |
| 4 | Developer UX | Web UI studio, WebSocket, undo/redo, event bus, auth | Weeks 13–18 |
| 5 | Audio & Vision | Whisper STT, Coqui TTS, Stable Diffusion, vision LLM | Weeks 19–24 |
| 6 | Code Intelligence | LSP, tree-sitter AST, semantic code search, test generation | Weeks 25–30 |
| 7 | Plugins & Self-Improvement | Versioned plugins, marketplace, fine-tuning, benchmarks | Weeks 31–36 |

---

*Audit prepared: 2026-03-18*  
*Repositories audited: [shifty81/SwissAgent](https://github.com/shifty81/SwissAgent), [shifty81/NovaForge](https://github.com/shifty81/NovaForge)*
