#pragma once
/**
 * SwissAgent Native — BackendProc
 *
 * Manages the lifecycle of the Python/uvicorn backend subprocess.
 * Responsibilities:
 *   - Locate a Python interpreter (SWISSAGENT_PYTHON env var, then PATH)
 *   - Spawn:  python -m uvicorn core.api_server:create_app --factory
 *               --host 127.0.0.1 --port <port>
 *   - Poll GET /health until the backend is ready
 *   - Provide a graceful stop method (TerminateProcess + cleanup)
 */

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <winhttp.h>
#include <string>
#include <functional>
#include <thread>
#include <atomic>
#include <sstream>
#include <filesystem>

#pragma comment(lib, "winhttp.lib")

namespace sa {

class BackendProc {
public:
    struct Config {
        int         port        = 8000;
        std::wstring python     = L"python";    // exe name or full path
        std::wstring workDir;                   // CWD for the python process
        int         healthRetries = 40;         // seconds to wait
        bool        autoRestart   = false;
    };

    using LogCallback = std::function<void(const std::string&)>;

    explicit BackendProc(Config cfg, LogCallback log = nullptr)
        : cfg_(std::move(cfg)), log_(log) {}

    ~BackendProc() { stop(); }

    // ── Launch the backend synchronously (blocks until healthy or timeout) ──
    bool start() {
        if (running_) return true;

        // Find Python
        std::wstring pyExe = resolvePython();

        // Build command line:
        // python -m uvicorn core.api_server:create_app --factory
        //        --host 127.0.0.1 --port <N> --log-level warning
        std::wostringstream cmd;
        cmd << L"\"" << pyExe << L"\""
            << L" -m uvicorn core.api_server:create_app --factory"
            << L" --host 127.0.0.1 --port " << cfg_.port
            << L" --log-level warning";

        std::wstring cmdLine = cmd.str();
        doLog("[backend] cmd: " + wideToUtf8(cmdLine));

        STARTUPINFOW si{};
        si.cb          = sizeof(si);
        si.dwFlags     = STARTF_USESTDHANDLES;
        // Pipe stdout/stderr so we can capture logs without a console window
        SECURITY_ATTRIBUTES sa_attr{};
        sa_attr.nLength              = sizeof(sa_attr);
        sa_attr.bInheritHandle       = TRUE;
        sa_attr.lpSecurityDescriptor = nullptr;

        HANDLE hStdoutRd = nullptr, hStdoutWr = nullptr;
        CreatePipe(&hStdoutRd, &hStdoutWr, &sa_attr, 0);
        SetHandleInformation(hStdoutRd, HANDLE_FLAG_INHERIT, 0);

        si.hStdOutput = hStdoutWr;
        si.hStdError  = hStdoutWr;
        si.hStdInput  = nullptr;

        PROCESS_INFORMATION pi{};
        std::wstring wd = cfg_.workDir.empty() ? L"." : cfg_.workDir;

        BOOL ok = CreateProcessW(
            nullptr,
            const_cast<LPWSTR>(cmdLine.c_str()),
            nullptr, nullptr,
            TRUE,                          // inherit handles
            CREATE_NO_WINDOW,              // no console window
            nullptr,
            wd.c_str(),
            &si, &pi
        );

        // Close write end in parent
        CloseHandle(hStdoutWr);

        if (!ok) {
            CloseHandle(hStdoutRd);
            doLog("[backend] CreateProcess failed: " + std::to_string(GetLastError()));
            return false;
        }

        procInfo_  = pi;
        running_   = true;
        stdoutRead_ = hStdoutRd;

        // Drain stdout in a background thread
        logThread_ = std::thread([this]() {
            char buf[512];
            DWORD read;
            while (ReadFile(stdoutRead_, buf, sizeof(buf) - 1, &read, nullptr) && read > 0) {
                buf[read] = '\0';
                doLog(std::string("[backend] ") + buf);
            }
        });

        doLog("[backend] process started (PID=" + std::to_string(pi.dwProcessId) + ")");
        return waitUntilHealthy();
    }

    // ── Terminate the backend gracefully ────────────────────────────────────
    void stop() {
        if (!running_) return;
        doLog("[backend] stopping…");
        TerminateProcess(procInfo_.hProcess, 0);
        WaitForSingleObject(procInfo_.hProcess, 3000);
        CloseHandle(procInfo_.hProcess);
        CloseHandle(procInfo_.hThread);
        if (stdoutRead_) { CloseHandle(stdoutRead_); stdoutRead_ = nullptr; }
        if (logThread_.joinable()) logThread_.join();
        running_ = false;
    }

    bool isRunning() const {
        if (!running_) return false;
        DWORD ec = STILL_ACTIVE;
        GetExitCodeProcess(procInfo_.hProcess, &ec);
        return ec == STILL_ACTIVE;
    }

    std::string backendUrl() const {
        return "http://127.0.0.1:" + std::to_string(cfg_.port);
    }

private:
    Config           cfg_;
    LogCallback      log_;
    PROCESS_INFORMATION procInfo_{};
    HANDLE           stdoutRead_ = nullptr;
    std::thread      logThread_;
    bool             running_ = false;

    void doLog(const std::string& msg) {
        if (log_) log_(msg);
        OutputDebugStringA((msg + "\n").c_str());
    }

    // ── Resolve Python executable ────────────────────────────────────────────
    std::wstring resolvePython() {
        // 1. SWISSAGENT_PYTHON env var
        wchar_t envBuf[512]{};
        if (GetEnvironmentVariableW(L"SWISSAGENT_PYTHON", envBuf, 512) > 0)
            return envBuf;

        // 2. Explicit config
        if (!cfg_.python.empty()) return cfg_.python;

        return L"python";
    }

    // ── Poll GET /health ─────────────────────────────────────────────────────
    bool waitUntilHealthy() {
        doLog("[backend] waiting for /health…");
        for (int i = 0; i < cfg_.healthRetries; ++i) {
            if (!isRunning()) {
                doLog("[backend] process exited prematurely");
                return false;
            }
            if (httpGet200(L"127.0.0.1", cfg_.port, L"/health")) {
                doLog("[backend] healthy ✓");
                return true;
            }
            Sleep(1000);
        }
        doLog("[backend] timed out waiting for health");
        return false;
    }

    // ── Synchronous HTTP GET — returns true if status == 200 ────────────────
    static bool httpGet200(const std::wstring& host, int port, const std::wstring& path) {
        HINTERNET hSession = WinHttpOpen(
            L"SwissAgent-Native/0.2",
            WINHTTP_ACCESS_TYPE_NO_PROXY,
            WINHTTP_NO_PROXY_NAME,
            WINHTTP_NO_PROXY_BYPASS, 0);
        if (!hSession) return false;

        HINTERNET hConnect = WinHttpConnect(hSession, host.c_str(),
            static_cast<INTERNET_PORT>(port), 0);
        if (!hConnect) { WinHttpCloseHandle(hSession); return false; }

        HINTERNET hRequest = WinHttpOpenRequest(
            hConnect, L"GET", path.c_str(),
            nullptr, WINHTTP_NO_REFERER,
            WINHTTP_DEFAULT_ACCEPT_TYPES, 0);

        bool ok = false;
        if (hRequest) {
            DWORD timeout = 2000;
            WinHttpSetOption(hRequest, WINHTTP_OPTION_RECEIVE_TIMEOUT,  &timeout, sizeof(timeout));
            WinHttpSetOption(hRequest, WINHTTP_OPTION_CONNECT_TIMEOUT,  &timeout, sizeof(timeout));
            if (WinHttpSendRequest(hRequest, WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                                   WINHTTP_NO_REQUEST_DATA, 0, 0, 0)) {
                if (WinHttpReceiveResponse(hRequest, nullptr)) {
                    DWORD status = 0, sz = sizeof(status);
                    WinHttpQueryHeaders(hRequest,
                        WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                        WINHTTP_HEADER_NAME_BY_INDEX, &status, &sz, nullptr);
                    ok = (status == 200);
                }
            }
            WinHttpCloseHandle(hRequest);
        }
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return ok;
    }

    // ── Wide → UTF-8 helper ──────────────────────────────────────────────────
    static std::string wideToUtf8(const std::wstring& w) {
        if (w.empty()) return {};
        int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), -1, nullptr, 0, nullptr, nullptr);
        std::string s(n - 1, '\0');
        WideCharToMultiByte(CP_UTF8, 0, w.c_str(), -1, &s[0], n, nullptr, nullptr);
        return s;
    }
};

} // namespace sa
