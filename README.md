# SwissAgent

> Offline AI-powered development platform — your Swiss Army knife for software development.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

- 🤖 **Agentic AI loop** — plan, tool-call, execute, repeat
- 🔌 **34 built-in modules** — filesystem, git, build, image, audio, render, and more
- 🧩 **Plugin system** — extend with custom tools
- 🔒 **Permission system** — fine-grained tool and path access control
- 🖥️ **CLI + REST API** — command-line and HTTP interfaces
- 📦 **Offline-first** — works with Ollama local LLMs
- 🗂️ **Multi-project workspace** — manage multiple projects from one place

## Installation

```bash
git clone https://github.com/yourorg/SwissAgent.git
cd SwissAgent
python scripts/setup.py
```

## Quick Start

```bash
swissagent run "list all Python files in workspace/"
swissagent list-tools
swissagent list-modules
swissagent serve --host 0.0.0.0 --port 8000
```

## Modules

| Module | Description |
|--------|-------------|
| filesystem | File read/write/copy/move/delete |
| git | Git init/clone/commit/push/pull/diff/log |
| build | CMake/Make/Ninja build system integration |
| image | Resize/convert/crop/rotate images |
| zip | ZIP/TAR/7z archive creation and extraction |
| network | HTTP GET/POST/PUT/DELETE, file download/upload |
| script | Python/shell/Lua/Node.js script execution |
| cache | Disk-based key-value caching |
| memory | Persistent agent memory |
| security | Secret scanning, file hashing |
| index | Project code indexing and search |
| ... | 23 more modules |

## Configuration

```toml
# configs/config.toml
[llm.ollama]
base_url = "http://localhost:11434"
model = "llama3"
```

## API

```bash
curl http://localhost:8000/health
curl http://localhost:8000/tools
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": "list files in workspace/", "llm_backend": "local"}'
```

## Testing

```bash
pytest tests/ -v
```

## License

MIT — see [LICENSE](LICENSE)
