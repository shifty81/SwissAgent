# SwissAgent Documentation

## Overview
SwissAgent is an offline AI-powered development platform.

## Architecture
- **core/** — Agent loop, tool registry, config, permissions, CLI, API server
- **llm/** — LLM backends (Ollama, API, Local/stub)
- **modules/** — 34 capability modules
- **plugins/** — Third-party plugin extensions
- **workspace/** — Multi-project workspace management
- **templates/** — Project scaffolding templates
- **tests/** — Test suite

## Quick Start
```bash
python scripts/setup.py
swissagent list-modules
swissagent list-tools
swissagent run "list files in workspace/"
swissagent serve
```
