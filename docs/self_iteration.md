# SwissAgent — Self-Iterating, Self-Scaffolding Architecture

> **Goal:** once the AI and Editor are fully operational (Phases 1–10), SwissAgent
> will use itself to write, test, and evolve its own codebase — with no human in
> the loop beyond review.

---

## Vision

SwissAgent's roadmap is structured so that the platform bootstraps its own
advanced capabilities:

1. **Phase 1–2 (Foundation + IDE)** — build the runtime and editor.
2. **Phase 3–10 (Features)** — ship all IDE, AI, and knowledge features.
3. **Phase 11 (Open-Source AI Stack)** — swap in fully open-source runtimes
   (LocalAI, Open WebUI) and wire up the Docker sandbox.
4. **Phase 12 (Self-Scaffolding Engine)** — agent can generate new modules,
   plugins, and roadmap tasks from a description prompt.
5. **Phase 13 (Autonomous Self-Build)** — the agent reads the roadmap, picks the
   next task, implements it, tests it inside a Docker sandbox, commits the result,
   and marks the task done — then moves to the next one.

---

## Open-Source Tech Stack

| Layer | Component | Why |
|---|---|---|
| Editor | **Monaco Editor** (CDN / `@monaco-editor/react`) | Same engine as VS Code, MIT licensed |
| Local LLM runtime | **LocalAI** or **Ollama** | OpenAI-compatible API, runs 100% offline |
| Recommended models | **Codestral 25.01**, **DeepSeek R1**, **Phi-4** | Top-tier open-weight coding models |
| Agentic framework | **SwissAgent core loop** (plan→tool_call→execute→reflect) | Already built; extensible |
| Chat UI | **Open WebUI** | Copilot Chat-style; can push code into IDE |
| Sandbox execution | **Docker** | Isolates AI-generated code from the host |
| Self-edit tool | **dev_mode** module | Agent patches its own source and rolls back |

---

## Self-Iteration Loop (Phase 13)

```
┌─────────────────────────────────────────────────────────┐
│                   SwissAgent Self-Build Loop            │
│                                                         │
│  roadmap_next_task()                                    │
│       │                                                 │
│       ▼                                                 │
│  Agent reads task description + relevant source files   │
│       │                                                 │
│       ▼                                                 │
│  LLM (LocalAI / Ollama) generates implementation       │
│       │                                                 │
│       ▼                                                 │
│  dev_mode.apply_patch() writes files                   │
│       │                                                 │
│       ▼                                                 │
│  Docker sandbox: pytest tests/                          │
│       │                                                 │
│   pass? ──yes──► git commit + roadmap_complete_task()  │
│       │                                                 │
│    no  ──► feed errors back to LLM (up to 3 retries)  │
│           on final fail: dev_mode.rollback()           │
└─────────────────────────────────────────────────────────┘
```

### Key agent tools involved

| Tool | Module | Purpose |
|---|---|---|
| `roadmap_next_task` | `roadmap` | Pick the next pending task |
| `roadmap_start_task` | `roadmap` | Mark task as in-progress |
| `roadmap_complete_task` | `roadmap` | Mark task done + auto-advance |
| `apply_patch` | `dev_mode` | Write generated code to disk |
| `rollback_patch` | `dev_mode` | Undo on test failure |
| `run_tests` | `test` | Execute pytest inside sandbox |
| `git_commit` | `git` | Commit successful change |

---

## Docker Sandbox Setup

```bash
# 1. Start the full stack
docker compose up -d

# Services:
#   http://localhost:8000  ← SwissAgent IDE
#   http://localhost:8080  ← LocalAI (OpenAI-compatible API)
#   http://localhost:3000  ← Open WebUI (chat)

# 2. Download a coding model into LocalAI
docker compose exec localai \
  curl -L -o /models/codestral.gguf \
  https://huggingface.co/bartowski/Codestral-22B-v0.1-GGUF/resolve/main/Codestral-22B-v0.1-Q4_K_M.gguf

# 3. Set LocalAI as the default backend
# configs/config.toml:
#   default_llm_backend = "localai"
#   [llm.localai]
#   base_url = "http://localhost:8080"
#   model = "codestral"
```

---

## Recommended Models

| Model | Size | Strengths | Ollama pull / LocalAI id |
|---|---|---|---|
| **Codestral 25.01** | 22B | Best-in-class code gen, tool use | `codestral` |
| **DeepSeek R1** | 7B–70B | Reasoning + coding, MIT license | `deepseek-r1` |
| **Phi-4** | 14B | Fast, great for scaffolding | `phi4` |
| **Qwen 2.5 Coder** | 7B–32B | Strong code, low VRAM | `qwen2.5-coder` |
| **Llama 3.1** | 8B–70B | General purpose | `llama3.1` |

---

## Security Considerations

- All AI-generated code runs **inside the Docker container** — not on the host.
- The `permissions` system in `configs/config.toml` blocks writes outside
  `workspace/` and `projects/` even within the container.
- `dev_mode.rollback_patch()` reverts any failed self-modification attempt.
- The self-build loop is **opt-in** — it only starts when you click
  "Autonomous Self-Build" in the Roadmap panel (Phase 12+).

---

## See Also

- [`workspace/roadmap.json`](../workspace/roadmap.json) — the living task list
- [`plugins/open_webui_tool/README.md`](../plugins/open_webui_tool/README.md) — Open WebUI IDE push plugin
- [`docker-compose.yml`](../docker-compose.yml) — full stack compose file
- [`llm/localai.py`](../llm/localai.py) — LocalAI backend implementation
