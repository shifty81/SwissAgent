#pragma once
/**
 * SwissAgent Native — WebViewWindow
 *
 * Wraps a Win32 top-level window that hosts the Microsoft WebView2 control.
 *
 * Usage:
 *   WebViewWindow wnd;
 *   wnd.create(hInst, L"SwissAgent", 1280, 800);
 *   wnd.navigate(L"http://127.0.0.1:8001/");   // splash server
 *   // later, once backend is up:
 *   wnd.navigate(L"http://127.0.0.1:8000/");
 *
 * WebView2 is a COM-based control shipped with the "WebView2 Runtime" that
 * comes pre-installed on Windows 10 21H1+ and Windows 11.  The matching SDK
 * headers (WebView2.h + WebView2Loader.lib) are downloaded by the CMake build.
 *
 * If the WebView2 Runtime is not installed we fall back to ShellExecute so the
 * user can still reach the IDE in their default browser.
 */

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <shellapi.h>
#include <string>
#include <functional>

// WebView2 headers are included only when the SDK is present (CMake defines
// SA_WEBVIEW2_AVAILABLE when it finds the SDK).
#ifdef SA_WEBVIEW2_AVAILABLE
#  include <WebView2.h>
#  include <wrl.h>
using namespace Microsoft::WRL;
#endif

#pragma comment(lib, "shell32.lib")

namespace sa {

class WebViewWindow {
public:
    using ReadyCallback = std::function<void()>;

    WebViewWindow() = default;
    ~WebViewWindow() { destroy(); }

    // ── Create the host window ───────────────────────────────────────────────
    bool create(HINSTANCE hInst, const std::wstring& title,
                int w = 1280, int h = 820,
                ReadyCallback onReady = nullptr) {
        hInst_    = hInst;
        onReady_  = std::move(onReady);

        WNDCLASSEXW wc{};
        wc.cbSize        = sizeof(wc);
        wc.lpfnWndProc   = WndProc;
        wc.hInstance     = hInst;
        wc.hCursor       = LoadCursorW(nullptr, IDC_ARROW);
        wc.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
        wc.lpszClassName = kClassName;
        wc.hIcon = static_cast<HICON>(
            LoadImageW(hInst, MAKEINTRESOURCEW(1),
                       IMAGE_ICON, 0, 0, LR_DEFAULTCOLOR | LR_DEFAULTSIZE));
        if (!wc.hIcon) wc.hIcon = LoadIconW(nullptr, IDI_APPLICATION);
        wc.hIconSm = wc.hIcon;
        RegisterClassExW(&wc);

        hwnd_ = CreateWindowExW(0, kClassName, title.c_str(),
                                WS_OVERLAPPEDWINDOW,
                                CW_USEDEFAULT, CW_USEDEFAULT, w, h,
                                nullptr, nullptr, hInst, this);
        if (!hwnd_) return false;

        ShowWindow(hwnd_, SW_SHOWNORMAL);
        UpdateWindow(hwnd_);

#ifdef SA_WEBVIEW2_AVAILABLE
        initWebView2();
#endif
        return true;
    }

    // ── Navigate to a URL ────────────────────────────────────────────────────
    void navigate(const std::wstring& url) {
        pendingUrl_ = url;
#ifdef SA_WEBVIEW2_AVAILABLE
        if (webview_) {
            webview_->Navigate(url.c_str());
            return;
        }
#endif
        // Fallback: open in browser when WebView2 isn't available
        ShellExecuteW(nullptr, L"open", url.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
    }

    // ── Run the Win32 message loop ───────────────────────────────────────────
    static int runMessageLoop() {
        MSG msg{};
        while (GetMessageW(&msg, nullptr, 0, 0)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        return static_cast<int>(msg.wParam);
    }

    void show()  { if (hwnd_) { ShowWindow(hwnd_, SW_RESTORE); SetForegroundWindow(hwnd_); } }
    void hide()  { if (hwnd_) ShowWindow(hwnd_, SW_HIDE); }
    void close() { if (hwnd_) PostMessageW(hwnd_, WM_CLOSE, 0, 0); }

    HWND hwnd() const { return hwnd_; }

    void destroy() {
        if (hwnd_) { DestroyWindow(hwnd_); hwnd_ = nullptr; }
    }

private:
    HINSTANCE   hInst_  = nullptr;
    HWND        hwnd_   = nullptr;
    std::wstring pendingUrl_;
    ReadyCallback onReady_;

#ifdef SA_WEBVIEW2_AVAILABLE
    ComPtr<ICoreWebView2Controller>   controller_;
    ComPtr<ICoreWebView2>             webview_;

    void initWebView2() {
        HRESULT hr = CreateCoreWebView2EnvironmentWithOptions(
            nullptr, nullptr, nullptr,
            Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
                [this](HRESULT envHr, ICoreWebView2Environment* env) -> HRESULT {
                    if (FAILED(envHr) || !env) return envHr;
                    env->CreateCoreWebView2Controller(
                        hwnd_,
                        Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                            [this](HRESULT ctlHr, ICoreWebView2Controller* ctl) -> HRESULT {
                                if (FAILED(ctlHr) || !ctl) return ctlHr;
                                controller_ = ctl;
                                ctl->get_CoreWebView2(&webview_);

                                // Resize WebView2 to fill window
                                resizeWebView();

                                // Navigate to pending URL
                                if (!pendingUrl_.empty())
                                    webview_->Navigate(pendingUrl_.c_str());

                                if (onReady_) onReady_();
                                return S_OK;
                            }).Get());
                    return S_OK;
                }).Get());

        if (FAILED(hr)) {
            // WebView2 Runtime not installed — prompt user
            int btn = MessageBoxW(hwnd_,
                L"The WebView2 Runtime is not installed.\n\n"
                L"Click OK to install it (requires internet access),\n"
                L"or Cancel to open the IDE in your default browser instead.",
                L"SwissAgent — WebView2 Missing",
                MB_OKCANCEL | MB_ICONINFORMATION);
            if (btn == IDOK) {
                ShellExecuteW(nullptr, L"open",
                    L"https://go.microsoft.com/fwlink/p/?LinkId=2124703",
                    nullptr, nullptr, SW_SHOWNORMAL);
            }
            if (!pendingUrl_.empty())
                ShellExecuteW(nullptr, L"open", pendingUrl_.c_str(),
                              nullptr, nullptr, SW_SHOWNORMAL);
        }
    }

    void resizeWebView() {
        if (!controller_ || !hwnd_) return;
        RECT rc{};
        GetClientRect(hwnd_, &rc);
        controller_->put_Bounds(rc);
    }
#endif

    static constexpr wchar_t kClassName[] = L"SwissAgentWebViewWnd";

    // ── Window procedure ─────────────────────────────────────────────────────
    static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
        WebViewWindow* self = nullptr;

        if (msg == WM_NCCREATE) {
            auto* cs = reinterpret_cast<CREATESTRUCTW*>(lp);
            self = static_cast<WebViewWindow*>(cs->lpCreateParams);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
        } else {
            self = reinterpret_cast<WebViewWindow*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
        }

        if (msg == WM_SIZE && self) {
#ifdef SA_WEBVIEW2_AVAILABLE
            self->resizeWebView();
#endif
        }

        if (msg == WM_DESTROY) {
            PostQuitMessage(0);
            return 0;
        }

        return DefWindowProcW(hwnd, msg, wp, lp);
    }
};

} // namespace sa
