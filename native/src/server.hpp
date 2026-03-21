#pragma once
/**
 * SwissAgent Native — SplashServer
 *
 * A lightweight embedded HTTP server (built on cpp-httplib) that runs on
 * a configurable port and serves:
 *
 *   GET /          → animated HTML splash page (shown while Python boots)
 *   GET /status    → JSON {"ready": bool, "backend_url": "http://…"}
 *   GET /alive     → plain-text "ok"  (used by build-scripts / tests)
 *
 * The server is intended to be replaced by the Python backend once it is
 * healthy: the WebView2 window navigates away from this server to the real
 * Python URL.
 *
 * Dependencies: cpp-httplib (fetched by CMake FetchContent)
 */

#ifndef UNICODE
#define UNICODE
#endif

#include <httplib.h>
#include <string>
#include <atomic>
#include <thread>
#include <functional>

namespace sa {

class SplashServer {
public:
    explicit SplashServer(int port = 8001) : port_(port) {}

    ~SplashServer() { stop(); }

    // ── Start listening in a background thread ───────────────────────────────
    void start() {
        if (running_) return;
        running_ = true;

        svr_.Get("/", [this](const httplib::Request&, httplib::Response& res) {
            res.set_content(splashHtml(), "text/html; charset=utf-8");
        });

        svr_.Get("/status", [this](const httplib::Request&, httplib::Response& res) {
            bool r = backendReady_.load();
            std::string body =
                std::string("{\"ready\":") + (r ? "true" : "false") +
                ",\"backend_url\":\"" + backendUrl_ + "\"}";
            res.set_content(body, "application/json");
        });

        svr_.Get("/alive", [](const httplib::Request&, httplib::Response& res) {
            res.set_content("ok", "text/plain");
        });

        thread_ = std::thread([this]() {
            svr_.listen("127.0.0.1", port_);
        });
    }

    void stop() {
        if (!running_) return;
        running_ = false;
        svr_.stop();
        if (thread_.joinable()) thread_.join();
    }

    // ── Called by AppHost once the backend is confirmed healthy ──────────────
    void setBackendReady(const std::string& url) {
        backendUrl_    = url;
        backendReady_  = true;
    }

    std::string url() const {
        return "http://127.0.0.1:" + std::to_string(port_);
    }

private:
    int                 port_;
    httplib::Server     svr_;
    std::thread         thread_;
    std::atomic<bool>   running_  {false};
    std::atomic<bool>   backendReady_ {false};
    std::string         backendUrl_;

    // ── Animated HTML splash page ─────────────────────────────────────────────
    static std::string splashHtml() {
        return R"html(<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>SwissAgent — Starting…</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{
      background:#1e1e2e;color:#cdd6f4;
      font-family:"Segoe UI",system-ui,sans-serif;
      display:flex;align-items:center;justify-content:center;
      height:100vh;overflow:hidden
    }
    .card{text-align:center}
    .icon{font-size:56px;margin-bottom:18px;
          animation:pulse 1.6s ease-in-out infinite}
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
    h1{font-size:26px;font-weight:700;color:#7c6af7;margin-bottom:8px}
    p{font-size:13px;color:#7f849c;margin-bottom:24px}
    .bar{width:280px;height:4px;background:#2a2a3d;
         border-radius:9999px;overflow:hidden;margin:0 auto}
    .fill{height:100%;background:#7c6af7;border-radius:9999px;
          animation:slide 1.4s ease-in-out infinite}
    @keyframes slide{0%{width:0%;margin-left:0}
                     50%{width:60%;margin-left:20%}
                     100%{width:0%;margin-left:100%}}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">🛠️</div>
    <h1>SwissAgent</h1>
    <p>Starting backend server…</p>
    <div class="bar"><div class="fill"></div></div>
  </div>
  <script>
    // Once backend is ready, the /status endpoint will tell us to navigate
    (function poll(){
      fetch('/status').then(r=>r.json()).then(d=>{
        if(d.ready && d.backend_url)
          window.location.href = d.backend_url;
        else
          setTimeout(poll, 1200);
      }).catch(()=>setTimeout(poll,1200));
    })();
  </script>
</body>
</html>)html";
    }
};

} // namespace sa
