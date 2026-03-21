/**
 * SwissAgent Native — main.cpp
 * ─────────────────────────────────────────────────────────────────────────────
 * Windows Win32 application that:
 *
 *   1. Starts a built-in C++ HTTP server (SplashServer, port 8001)
 *      which serves an animated loading page and a /status JSON endpoint.
 *
 *   2. Opens a WebView2 window that points at http://127.0.0.1:8001/
 *      (the splash page) while the backend is starting.
 *
 *   3. Spawns the SwissAgent Python / uvicorn backend as a child process
 *      and polls /health until it is ready (BackendProc).
 *
 *   4. Once the backend is healthy, notifies the SplashServer (so the
 *      JavaScript in the splash page auto-navigates to the real IDE)
 *      and also navigates the WebView2 window directly.
 *
 *   5. Adds a system-tray icon (TrayIcon) that lets the user:
 *        • Show / hide the IDE window
 *        • Open IDE in the default browser
 *        • Restart the Python backend
 *        • Quit the application
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * Build requirements (handled by CMakeLists.txt):
 *   • C++17 / MSVC or MinGW-w64
 *   • cpp-httplib  (fetched via CMake FetchContent — provides <httplib.h>)
 *   • WebView2 SDK (optional — fetched via NuGet / FetchContent;
 *                   define SA_WEBVIEW2_AVAILABLE to enable)
 *   • Windows SDK 10.0.19041.0 or later
 * ─────────────────────────────────────────────────────────────────────────────
 */

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

// Require Windows 10+
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#ifndef WINVER
#define WINVER 0x0A00
#endif

#include <windows.h>
#include <shlobj.h>          // SHGetKnownFolderPath
#include <string>
#include <thread>
#include <atomic>
#include <memory>
#include <filesystem>

// Our header-only modules
#include "backend.hpp"
#include "server.hpp"
#include "tray.hpp"
#include "webview.hpp"

#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "ole32.lib")

namespace fs = std::filesystem;

// ── Configuration ─────────────────────────────────────────────────────────────

static constexpr int BACKEND_PORT = 8000;
static constexpr int SPLASH_PORT  = 8001;

// ── Helper: locate the project root ──────────────────────────────────────────
/**
 * Strategy:
 *   1. The directory of the running executable (development layout:
 *      native/build/ → ../.. gives the project root).
 *   2. A bundled "backend" folder next to the executable (installed layout).
 *   3. Fall back to the current working directory.
 */
static fs::path findProjectRoot(const fs::path& exeDir) {
    // 1. "backend" sibling of the exe (installed / packaged)
    {
        auto candidate = exeDir / "backend";
        if (fs::exists(candidate / "core" / "api_server.py"))
            return candidate;
    }

    // 2. Walk up from exe looking for the marker file pyproject.toml
    for (auto dir = exeDir; dir != dir.root_path(); dir = dir.parent_path()) {
        if (fs::exists(dir / "pyproject.toml"))
            return dir;
    }

    // 3. CWD
    return fs::current_path();
}

// ── Helper: wide ↔ narrow conversions ─────────────────────────────────────────
static std::wstring toWide(const std::string& s) {
    if (s.empty()) return {};
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, nullptr, 0);
    std::wstring w(n - 1, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, &w[0], n);
    return w;
}

// ── AppHost — ties together all subsystems ────────────────────────────────────
class AppHost {
public:
    AppHost(HINSTANCE hInst, const fs::path& projectRoot)
        : hInst_(hInst), projectRoot_(projectRoot) {}

    int run() {
        mainThreadId_ = GetCurrentThreadId();

        // ── 1. Start the built-in splash server ──────────────────────────────
        splash_ = std::make_unique<sa::SplashServer>(SPLASH_PORT);
        splash_->start();

        // ── 2. Create the WebView2 / Win32 window ────────────────────────────
        webview_ = std::make_unique<sa::WebViewWindow>();
        if (!webview_->create(hInst_, L"SwissAgent", 1440, 900)) {
            MessageBoxW(nullptr,
                L"Failed to create the application window.",
                L"SwissAgent — Fatal Error", MB_ICONERROR);
            return 1;
        }
        std::wstring splashUrl = toWide("http://127.0.0.1:" +
                                        std::to_string(SPLASH_PORT) + "/");
        webview_->navigate(splashUrl);

        // ── 3. Create the system-tray icon ────────────────────────────────────
        tray_ = std::make_unique<sa::TrayIcon>();
        tray_->create(hInst_, buildTrayCallbacks());
        tray_->setTooltip(L"SwissAgent — starting…");

        // ── 4. Start the Python backend in a background thread ───────────────
        const DWORD mainThreadId = mainThreadId_;
        backendThread_ = std::thread([this, mainThreadId]() {
            sa::BackendProc::Config cfg;
            cfg.port         = BACKEND_PORT;
            cfg.workDir      = projectRoot_.wstring();
            cfg.healthRetries = 45;

            backend_ = std::make_unique<sa::BackendProc>(cfg, [](const std::string& msg) {
                OutputDebugStringA((msg + "\n").c_str());
            });

            bool ok = backend_->start();

            // Post result back to main thread as a thread message (hwnd=null)
            PostThreadMessageW(mainThreadId,
                               WM_APP + 1,
                               ok ? 1 : 0, 0);
        });

        // ── 5. Install a custom message handler for WM_APP+1 ─────────────────
        //   We do this via subclassing the window from the message loop.
        //   Simple approach: use a hook via SetWindowSubclass (comctl32).
        //   We'll handle it inline in the message loop instead.
        backendReadyMsg_ = WM_APP + 1;

        // ── 6. Run the Win32 message loop ─────────────────────────────────────
        MSG msg{};
        while (GetMessageW(&msg, nullptr, 0, 0)) {
            if (msg.message == WM_APP + 1 && !msg.hwnd) {
                handleBackendReady(msg.wParam == 1);
            }
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }

        // ── 7. Cleanup ────────────────────────────────────────────────────────
        if (backend_) backend_->stop();
        if (backendThread_.joinable()) backendThread_.join();
        if (splash_) splash_->stop();

        return static_cast<int>(msg.wParam);
    }

private:
    HINSTANCE  hInst_;
    fs::path   projectRoot_;
    UINT       backendReadyMsg_ = 0;
    DWORD      mainThreadId_    = 0;

    std::unique_ptr<sa::SplashServer>   splash_;
    std::unique_ptr<sa::WebViewWindow>  webview_;
    std::unique_ptr<sa::TrayIcon>       tray_;
    std::unique_ptr<sa::BackendProc>    backend_;
    std::thread                         backendThread_;

    // ── Called when the backend thread reports success/failure ───────────────
    void handleBackendReady(bool ok) {
        if (ok) {
            std::string backendUrl = "http://127.0.0.1:" + std::to_string(BACKEND_PORT);
            splash_->setBackendReady(backendUrl);
            // Also navigate the WebView2 window directly so it does not wait
            // for the next meta-refresh
            webview_->navigate(toWide(backendUrl));
            tray_->setTooltip(L"SwissAgent — running");
        } else {
            tray_->setTooltip(L"SwissAgent — backend error");
            int btn = MessageBoxW(webview_->hwnd(),
                L"The SwissAgent Python backend failed to start.\n\n"
                L"Please ensure Python 3.10+ is installed and the\n"
                L"SwissAgent package is installed (pip install -e .).\n\n"
                L"Would you like to quit?",
                L"SwissAgent — Backend Error",
                MB_YESNO | MB_ICONERROR);
            if (btn == IDYES)
                PostQuitMessage(1);
        }
    }

    // ── Build tray callbacks ──────────────────────────────────────────────────
    sa::TrayIcon::Callbacks buildTrayCallbacks() {
        sa::TrayIcon::Callbacks cbs;

        cbs.onShow = [this]() {
            if (webview_) webview_->show();
        };

        cbs.onOpenIDE = [this]() {
            if (webview_) webview_->show();
        };

        cbs.onOpenBrowser = [this]() {
            std::wstring url = toWide("http://127.0.0.1:" +
                                      std::to_string(BACKEND_PORT));
            ShellExecuteW(nullptr, L"open", url.c_str(),
                          nullptr, nullptr, SW_SHOWNORMAL);
        };

        cbs.onRestart = [this]() {
            if (backend_) {
                backend_->stop();
                tray_->setTooltip(L"SwissAgent — restarting…");
                // Navigate back to splash while backend reboots
                std::wstring splashUrl = toWide("http://127.0.0.1:" +
                                                 std::to_string(SPLASH_PORT) + "/");
                webview_->navigate(splashUrl);

                // Restart in a new thread
                if (backendThread_.joinable()) backendThread_.join();
                const DWORD tid = mainThreadId_;
                backendThread_ = std::thread([this, tid]() {
                    bool ok = backend_->start();
                    PostThreadMessageW(tid, WM_APP + 1, ok ? 1 : 0, 0);
                });
            }
        };

        cbs.onQuit = [this]() {
            if (webview_) webview_->close();
        };

        return cbs;
    }
};

// ── WinMain ───────────────────────────────────────────────────────────────────
int WINAPI wWinMain(
    _In_     HINSTANCE hInst,
    _In_opt_ HINSTANCE /*hPrev*/,
    _In_     LPWSTR    /*lpCmdLine*/,
    _In_     int       /*nCmdShow*/)
{
    // Ensure we only have one running instance
    HANDLE hMutex = CreateMutexW(nullptr, TRUE, L"SwissAgentNativeSingleInstance");
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        // Bring the existing window to the front
        HWND existing = FindWindowW(L"SwissAgentWebViewWnd", nullptr);
        if (existing) { ShowWindow(existing, SW_RESTORE); SetForegroundWindow(existing); }
        return 0;
    }

    // Initialise COM (required by WebView2 and shell APIs)
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

    // Locate the project root
    wchar_t exePathBuf[MAX_PATH]{};
    GetModuleFileNameW(nullptr, exePathBuf, MAX_PATH);
    fs::path exeDir = fs::path(exePathBuf).parent_path();
    fs::path projectRoot = findProjectRoot(exeDir);

    // Run the application
    AppHost host(hInst, projectRoot);
    int result = host.run();

    CoUninitialize();
    ReleaseMutex(hMutex);
    CloseHandle(hMutex);
    return result;
}
