#pragma once
/**
 * SwissAgent Native — TrayIcon
 *
 * Creates a Windows system-tray icon with a context menu that lets the user:
 *   - Show / raise the main window
 *   - Open the IDE in the default browser
 *   - Restart the backend
 *   - Quit the application
 *
 * The tray icon is owned by a hidden message-pump window so it does not
 * depend on the main window being present.
 */

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <shellapi.h>
#include "resource.h"
#include <functional>
#include <string>

#pragma comment(lib, "shell32.lib")

namespace sa {

class TrayIcon {
public:
    struct Callbacks {
        std::function<void()> onShow;        // "Show window"
        std::function<void()> onOpenIDE;     // "Open IDE"
        std::function<void()> onOpenBrowser; // "Open in Browser"
        std::function<void()> onRestart;     // "Restart Backend"
        std::function<void()> onQuit;        // "Quit"
    };

    TrayIcon() = default;
    ~TrayIcon() { destroy(); }

    // ── Create the hidden message window + tray icon ─────────────────────────
    bool create(HINSTANCE hInst, Callbacks cbs) {
        hInst_ = hInst;
        cbs_   = std::move(cbs);

        // Register hidden window class
        WNDCLASSEXW wc{};
        wc.cbSize        = sizeof(wc);
        wc.lpfnWndProc   = WndProc;
        wc.hInstance     = hInst;
        wc.lpszClassName = kClassName;
        RegisterClassExW(&wc);

        // Create the hidden window (receives WM_TRAYICON messages)
        hwnd_ = CreateWindowExW(0, kClassName, L"SwissAgentTray",
                                WS_OVERLAPPEDWINDOW,
                                CW_USEDEFAULT, CW_USEDEFAULT, 0, 0,
                                nullptr, nullptr, hInst, this);
        if (!hwnd_) return false;

        // Load icon — fall back to a generic application icon if ours is missing
        HICON hIcon = static_cast<HICON>(
            LoadImageW(hInst, MAKEINTRESOURCEW(IDI_TRAY_ICON),
                       IMAGE_ICON, GetSystemMetrics(SM_CXSMICON),
                       GetSystemMetrics(SM_CYSMICON), LR_DEFAULTCOLOR));
        if (!hIcon)
            hIcon = LoadIconW(nullptr, IDI_APPLICATION);

        // Add the tray icon
        NOTIFYICONDATAW nid{};
        nid.cbSize           = sizeof(nid);
        nid.hWnd             = hwnd_;
        nid.uID              = kIconID;
        nid.uFlags           = NIF_ICON | NIF_MESSAGE | NIF_TIP;
        nid.hIcon            = hIcon;
        nid.uCallbackMessage = WM_TRAYICON;
        wcscpy_s(nid.szTip, L"SwissAgent");
        Shell_NotifyIconW(NIM_ADD, &nid);
        nid_ = nid;
        return true;
    }

    // ── Remove the tray icon and the message window ──────────────────────────
    void destroy() {
        if (!hwnd_) return;
        NOTIFYICONDATAW nid{};
        nid.cbSize = sizeof(nid);
        nid.hWnd   = hwnd_;
        nid.uID    = kIconID;
        Shell_NotifyIconW(NIM_DELETE, &nid);
        DestroyWindow(hwnd_);
        hwnd_ = nullptr;
    }

    // ── Update tooltip text (e.g. "SwissAgent — running") ───────────────────
    void setTooltip(const std::wstring& tip) {
        if (!hwnd_) return;
        NOTIFYICONDATAW nid{};
        nid.cbSize = sizeof(nid);
        nid.hWnd   = hwnd_;
        nid.uID    = kIconID;
        nid.uFlags = NIF_TIP;
        wcsncpy_s(nid.szTip, tip.c_str(), 128);
        Shell_NotifyIconW(NIM_MODIFY, &nid);
    }

private:
    HINSTANCE           hInst_ = nullptr;
    HWND                hwnd_  = nullptr;
    NOTIFYICONDATAW     nid_{};
    Callbacks           cbs_;

    static constexpr UINT kIconID    = 1;
    static constexpr wchar_t kClassName[] = L"SwissAgentTrayWnd";

    // ── Window procedure for the hidden message pump window ──────────────────
    static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
        TrayIcon* self = nullptr;

        if (msg == WM_NCCREATE) {
            auto* cs = reinterpret_cast<CREATESTRUCTW*>(lp);
            self = static_cast<TrayIcon*>(cs->lpCreateParams);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
        } else {
            self = reinterpret_cast<TrayIcon*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
        }

        if (!self) return DefWindowProcW(hwnd, msg, wp, lp);

        if (msg == WM_TRAYICON) {
            UINT ev = LOWORD(lp);
            if (ev == WM_RBUTTONUP || ev == WM_CONTEXTMENU) {
                self->showContextMenu();
            } else if (ev == WM_LBUTTONDBLCLK) {
                if (self->cbs_.onShow) self->cbs_.onShow();
            }
            return 0;
        }

        if (msg == WM_COMMAND) {
            switch (LOWORD(wp)) {
            case IDM_TRAY_SHOW:    if (self->cbs_.onShow)        self->cbs_.onShow();        break;
            case IDM_TRAY_OPEN_IDE:if (self->cbs_.onOpenIDE)     self->cbs_.onOpenIDE();     break;
            case IDM_TRAY_BROWSER: if (self->cbs_.onOpenBrowser) self->cbs_.onOpenBrowser(); break;
            case IDM_TRAY_RESTART: if (self->cbs_.onRestart)     self->cbs_.onRestart();     break;
            case IDM_TRAY_QUIT:    if (self->cbs_.onQuit)        self->cbs_.onQuit();        break;
            }
            return 0;
        }

        return DefWindowProcW(hwnd, msg, wp, lp);
    }

    // ── Build and show a right-click context menu ────────────────────────────
    void showContextMenu() {
        HMENU hMenu = CreatePopupMenu();
        AppendMenuW(hMenu, MF_STRING, IDM_TRAY_SHOW,    L"Show Window");
        AppendMenuW(hMenu, MF_STRING, IDM_TRAY_OPEN_IDE,L"Open IDE");
        AppendMenuW(hMenu, MF_STRING, IDM_TRAY_BROWSER, L"Open in Browser");
        AppendMenuW(hMenu, MF_SEPARATOR, 0, nullptr);
        AppendMenuW(hMenu, MF_STRING, IDM_TRAY_RESTART, L"Restart Backend");
        AppendMenuW(hMenu, MF_SEPARATOR, 0, nullptr);
        AppendMenuW(hMenu, MF_STRING, IDM_TRAY_QUIT,    L"Quit SwissAgent");

        // GetCursorPos + TrackPopupMenu idiom for tray menus
        POINT pt{};
        GetCursorPos(&pt);
        SetForegroundWindow(hwnd_);
        TrackPopupMenu(hMenu, TPM_BOTTOMALIGN | TPM_LEFTALIGN,
                       pt.x, pt.y, 0, hwnd_, nullptr);
        PostMessageW(hwnd_, WM_NULL, 0, 0);
        DestroyMenu(hMenu);
    }
};

} // namespace sa
