# Open WebUI ↔ SwissAgent IDE Integration

This plugin lets **Open WebUI** (or any OpenAI-compatible chat UI) push
AI-generated code directly into the **SwissAgent IDE** — the same way GitHub
Copilot Chat applies suggestions to VS Code files.

## How it works

```
Open WebUI chat  ──push_file_to_ide()──►  SwissAgent /api/ide/push
                                                  │
                                           writes file to disk
                                                  │
                              IDE polls /api/ide/pending  ──► auto-opens file
```

---

## Quick start

### 1 — Start SwissAgent

```bash
pip install -e .
python -m swissagent          # listens on http://localhost:8000 by default
```

### 2 — Start Open WebUI

```bash
# Docker (simplest)
docker run -d -p 3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  -v open-webui:/app/backend/data \
  ghcr.io/open-webui/open-webui:main
```

Then open **http://localhost:3000**, create an account and log in.

### 3 — Install this tool in Open WebUI

1. Go to **Workspace → Tools → + New Tool**
2. Paste the contents of `plugin.py` into the editor
3. Change `SWISSAGENT_URL` at the top if SwissAgent runs on a different host/port
4. Click **Save**

### 4 — Enable the tool in a chat

1. Open a new chat
2. Click the **🔧 Tools** button (bottom of the message input)
3. Enable **SwissAgent IDE Tools**
4. Ask the model to write code — when it calls `push_file_to_ide`, the file
   appears automatically in your SwissAgent editor

---

## Available tool functions

| Function | Description |
|---|---|
| `push_file_to_ide(path, content)` | Write/update a file in the workspace |
| `read_file_from_ide(path)` | Read an existing file into the conversation |
| `list_workspace_files(path)` | Browse the workspace directory tree |
| `ide_status()` | Check SwissAgent is running |

---

## Example prompts

```
Create a Python FastAPI app with two endpoints: GET /hello and POST /echo.
Save it to workspace/src/app.py
```

```
Read workspace/src/app.py and add input validation using Pydantic models.
Save the updated version back to the same path.
```

```
List the files in workspace/ and summarise what this project does.
```

---

## Security note

`/api/ide/push` only writes to `workspace/` and `projects/` — it cannot
write to `configs/`, `core/`, or any other restricted directory.
Path-traversal attempts are blocked by the server.

---

## Without Open WebUI

SwissAgent's **built-in AI Agent chat panel** already has full Copilot-style
features with no extra software needed:

* **⬆ Apply to file** button on every code block in the chat
* **📋 Copy** button on every code block
* **Slash commands**: `/fix`, `/explain`, `/test`, `/docs` auto-inject the
  currently open file as context
* **Inline ghost-text completions** (Monaco editor, online only) powered by
  your local Ollama model

Just type in the AI Agent panel and use the buttons — no Open WebUI required.
