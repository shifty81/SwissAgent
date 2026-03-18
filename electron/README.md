# SwissAgent Desktop (Electron Wrapper)

This directory contains the Electron wrapper that packages SwissAgent as a
native desktop application with a system-tray icon.

## Prerequisites

* **Node.js ≥ 18** and **npm**
* **Python 3.10+** with SwissAgent installed (`pip install -e .` from the repo root)
* **Electron** (installed via npm below)

## Quick start (development)

```bash
cd electron
npm install
npm start
```

Electron will launch the SwissAgent FastAPI backend automatically, wait for it
to become healthy, and then open the IDE in a native window.

## Building a distributable

```bash
# macOS (.dmg)
npm run package-mac

# Windows (.exe installer)
npm run package-win

# Linux (.AppImage / .deb)
npm run package-linux
```

Built artefacts appear in `electron/dist/`.

## Configuration

| Environment variable   | Default      | Description                                   |
|------------------------|--------------|-----------------------------------------------|
| `SWISSAGENT_PYTHON`    | `python3`    | Python executable used to start the backend   |

## How it works

1. `main.js` spawns `python3 -m uvicorn core.api_server:create_app --factory`
   in the repo root directory.
2. It polls `http://localhost:8000/health` until the server responds (up to 30 s).
3. A `BrowserWindow` is opened pointing at `http://localhost:8000`.
4. A system-tray icon is created; closing the window minimises to tray.
5. On quit, the backend subprocess is terminated gracefully.
