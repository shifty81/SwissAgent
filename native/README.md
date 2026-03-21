# SwissAgent — Native Windows Application

A **C++ Win32 application** that houses the entire SwissAgent platform in a
single native Windows executable.  It embeds a lightweight HTTP server
(`cpp-httplib`), launches the Python/uvicorn backend as a managed child
process, and renders the IDE in a native **WebView2** window — all without
requiring Electron or Node.js.

---

## Architecture

```
SwissAgent.exe  (C++17, Win32)
│
├── SplashServer  (cpp-httplib, port 8001)
│   ├── GET /          → animated HTML loading page
│   ├── GET /status    → {"ready": bool, "backend_url": "…"}
│   └── GET /alive     → "ok"
│
├── BackendProc
│   ├── Locates Python (SWISSAGENT_PYTHON env var → PATH)
│   ├── Spawns: python -m uvicorn core.api_server:create_app
│   │          --factory --host 127.0.0.1 --port 8000
│   └── Polls GET /health until backend is ready (~40 s timeout)
│
├── WebViewWindow  (Microsoft WebView2)
│   ├── On start → http://127.0.0.1:8001/   (C++ splash page)
│   └── On ready → http://127.0.0.1:8000/   (Python IDE)
│
└── TrayIcon  (Win32 Shell_NotifyIcon)
    ├── Show window
    ├── Open in browser
    ├── Restart backend
    └── Quit
```

The built-in C++ HTTP server (`SplashServer`) serves the animated loading
page *while Python boots*.  The splash page JavaScript polls `/status` every
1.2 s; once the Python backend is healthy, the server sets `ready=true` and
the page auto-navigates to `http://localhost:8000`.  The `WebViewWindow` also
navigates directly when the main thread receives the backend-ready signal.

---

## Prerequisites

| Requirement | Min version | Notes |
|---|---|---|
| Windows | 10 (1903+) | WebView2 Runtime pre-installed on 21H1+ |
| CMake | 3.20 | `cmake --version` |
| C++ compiler | MSVC 2019+ **or** MinGW-w64 12+ | via Visual Studio or MSYS2 |
| Python | 3.10+ | For the backend subprocess |
| WebView2 Runtime | any | Auto-prompted if missing |

---

## Quick Start

### 1 — Install build dependencies

```powershell
# From an elevated PowerShell prompt in the project root:
.\native\scripts\install-deps.ps1
```

This script:
- Verifies CMake, a C++ compiler, and Python 3.10+ are on your `PATH`
- Checks / installs the WebView2 Runtime
- Installs the SwissAgent Python package (`pip install -e .`)

### 2 — Build

```bat
cd native\scripts
build.bat Release
```

Or manually with CMake:

```bat
cd native
cmake -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
```

With MinGW-w64:

```bat
cd native
cmake -B build -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
cmake --build build
```

### 3 — Run

```bat
native\build\Release\SwissAgent.exe
```

The application will:
1. Open a loading window (`SplashServer` — port 8001)
2. Start the Python backend in the background (port 8000)
3. Navigate the window to the IDE once the backend is ready
4. Add a system-tray icon

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SWISSAGENT_PYTHON` | `python` | Full path to the Python interpreter to use |
| `SWISSAGENT_PORT` | `8000` | Port for the Python backend *(future)* |

---

## WebView2 Notes

WebView2 is the modern browser engine from Microsoft (same as Edge) and is
**pre-installed on Windows 10 21H1+ and Windows 11**.

If it is not installed, the application will:
1. Show a dialog with a link to the WebView2 Runtime installer
2. Fall back to opening the IDE in your default browser via `ShellExecute`

The WebView2 **SDK** (headers + import library) is downloaded automatically
by CMake during the configure step via `FetchContent` from NuGet.

---

## Packaging / Distribution

Use CMake + CPack to create a ZIP or NSIS installer:

```bat
cd native\build
cmake --build . --config Release
cpack -G ZIP -C Release
cpack -G NSIS -C Release
```

The CPack install step bundles `SwissAgent.exe` **plus** the entire Python
backend into a `backend/` sub-folder, so end users only need Python installed
— the `.exe` will find and launch it automatically.

---

## Build Options

| CMake Option | Default | Description |
|---|---|---|
| `SA_USE_WEBVIEW2` | `ON` | Download and link the WebView2 SDK. Set `OFF` to build without it (browser fallback only). |

Example (build without WebView2):

```bat
cmake -B build -G "Visual Studio 17 2022" -A x64 -DSA_USE_WEBVIEW2=OFF
```

---

## Comparison with the Electron Launcher

| | Electron (`electron/`) | Native C++ (`native/`) |
|---|---|---|
| Runtime | Node.js + Chromium (~200 MB) | WebView2 (pre-installed on Win 10/11) |
| Startup | ~3–5 s | ~0.5 s |
| Memory | ~150–300 MB | ~15–30 MB |
| Distribution size | ~100 MB | ~1 MB exe + Python |
| Platform | Cross-platform | Windows only |
| Customisation | JavaScript | C++ |

Both launchers manage the same Python backend — they are interchangeable.

---

## Source Layout

```
native/
├── CMakeLists.txt          CMake build definition
├── README.md               This file
├── assets/
│   ├── icon.ico            Application icon
│   └── app.manifest        Windows application manifest
├── scripts/
│   ├── build.bat           One-click build
│   └── install-deps.ps1    Dependency installer
└── src/
    ├── main.cpp            WinMain + AppHost — ties everything together
    ├── backend.hpp         BackendProc — Python subprocess manager
    ├── server.hpp          SplashServer — embedded cpp-httplib HTTP server
    ├── webview.hpp         WebViewWindow — WebView2 window wrapper
    ├── tray.hpp            TrayIcon — system-tray icon
    ├── resource.h          Windows resource IDs
    └── SwissAgent.rc       Windows resources (icon, manifest)
```
