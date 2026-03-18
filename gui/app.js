/**
 * SwissAgent IDE — frontend application
 * Uses Monaco Editor (loaded via CDN) and the SwissAgent REST + WebSocket API.
 */
(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────────────────────────
  const state = {
    openFiles: {},        // path → { content, language, modified, model }
    activeFile: null,     // currently visible path
    editor: null,         // Monaco editor instance
    ws: null,             // active WebSocket for /ws/run
    currentWsAbort: null, // AbortController for fetch-based fallback
  };

  // ── DOM refs ───────────────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const fileTree       = $("file-tree");
  const tabsList       = $("tabs-list");
  const outputContent  = $("output-content");
  const chatMessages   = $("chat-messages");
  const chatInput      = $("chat-input");
  const statusEl       = $("status-indicator");
  const newFileDialog  = $("new-file-dialog");
  const newFilePath    = $("new-file-path");
  const llmSelect      = $("llm-backend-select");

  // ── Utilities ──────────────────────────────────────────────────────────────
  function appendOutput(text) {
    outputContent.textContent += text;
    outputContent.scrollTop = outputContent.scrollHeight;
  }

  function clearOutput() {
    outputContent.textContent = "";
  }

  function setStatus(mode) {
    statusEl.className = `status-${mode}`;
    const labels = { idle: "● Idle", running: "⟳ Running…", error: "✕ Error" };
    statusEl.textContent = labels[mode] || "● Idle";
  }

  function appendChat(text, role) {
    const msg = document.createElement("div");
    msg.className = `chat-msg ${role}`;
    msg.textContent = text;
    chatMessages.appendChild(msg);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return msg;
  }

  function extToLang(path) {
    const ext = path.split(".").pop().toLowerCase();
    const map = {
      py: "python", js: "javascript", ts: "typescript",
      html: "html", css: "css", json: "json",
      md: "markdown", sh: "shell", bash: "shell",
      cpp: "cpp", c: "c", cs: "csharp", java: "java",
      rs: "rust", go: "go", lua: "lua", rb: "ruby",
      toml: "ini", yaml: "yaml", yml: "yaml",
      txt: "plaintext",
    };
    return map[ext] || "plaintext";
  }

  // ── File tree ──────────────────────────────────────────────────────────────
  async function loadFileTree(node = null, parentEl = null) {
    const url = node ? `/files?path=${encodeURIComponent(node)}` : "/files";
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      renderTree(data.entries, parentEl || fileTree, node || "");
    } catch (e) {
      fileTree.textContent = "⚠ " + e.message;
    }
  }

  function renderTree(entries, container, parentPath) {
    container.innerHTML = "";
    entries.sort((a, b) => {
      if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    for (const entry of entries) {
      const fullPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;
      const item = document.createElement("div");
      item.className = `tree-item ${entry.type === "dir" ? "dir" : "file"}`;
      item.dataset.path = fullPath;
      item.dataset.type = entry.type;

      const icon = document.createElement("span");
      icon.className = "icon";
      icon.textContent = entry.type === "dir" ? "📁" : fileIcon(entry.name);

      const label = document.createElement("span");
      label.textContent = entry.name;

      item.appendChild(icon);
      item.appendChild(label);
      container.appendChild(item);

      if (entry.type === "dir") {
        const children = document.createElement("div");
        children.className = "tree-children";
        children.style.display = "none";
        container.appendChild(children);

        item.addEventListener("click", async () => {
          const open = children.style.display !== "none";
          children.style.display = open ? "none" : "block";
          icon.textContent = open ? "📁" : "📂";
          if (!open && children.innerHTML === "") {
            await loadFileTree(fullPath, children);
          }
        });
      } else {
        item.addEventListener("click", () => openFile(fullPath));
      }
    }
  }

  function fileIcon(name) {
    const ext = name.split(".").pop().toLowerCase();
    const m = {
      py: "🐍", js: "📜", ts: "📘", html: "🌐", css: "🎨",
      json: "📋", md: "📝", sh: "⚙", cpp: "⚙", c: "⚙",
      cs: "⚙", java: "☕", rs: "🦀", go: "🐹", lua: "🌙",
      toml: "⚙", yaml: "⚙", yml: "⚙",
    };
    return m[ext] || "📄";
  }

  // ── File open / tabs ───────────────────────────────────────────────────────
  async function openFile(path) {
    if (state.openFiles[path]) {
      activateTab(path);
      return;
    }
    try {
      const res = await fetch(`/files/read?path=${encodeURIComponent(path)}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const lang = extToLang(path);
      const model = monaco.editor.createModel(data.content, lang);
      model.onDidChangeContent(() => markModified(path));
      state.openFiles[path] = { content: data.content, language: lang, modified: false, model };
      addTab(path);
      activateTab(path);
    } catch (e) {
      appendOutput(`Error opening ${path}: ${e.message}\n`);
    }
  }

  function addTab(path) {
    const tab = document.createElement("div");
    tab.className = "tab";
    tab.dataset.path = path;

    const name = document.createElement("span");
    name.className = "tab-name";
    name.textContent = path.split("/").pop();

    const close = document.createElement("span");
    close.className = "tab-close";
    close.textContent = "✕";
    close.addEventListener("click", (e) => { e.stopPropagation(); closeTab(path); });

    tab.appendChild(name);
    tab.appendChild(close);
    tab.addEventListener("click", () => activateTab(path));
    tabsList.appendChild(tab);
  }

  function activateTab(path) {
    state.activeFile = path;
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.path === path));
    document.querySelectorAll(".tree-item.file").forEach((t) => t.classList.toggle("active", t.dataset.path === path));
    if (state.editor && state.openFiles[path]) {
      state.editor.setModel(state.openFiles[path].model);
    }
  }

  function closeTab(path) {
    const file = state.openFiles[path];
    if (file && file.modified) {
      if (!confirm(`${path} has unsaved changes. Close anyway?`)) return;
    }
    if (file && file.model) file.model.dispose();
    delete state.openFiles[path];
    const tab = tabsList.querySelector(`[data-path="${path}"]`);
    if (tab) tab.remove();
    if (state.activeFile === path) {
      const remaining = Object.keys(state.openFiles);
      if (remaining.length > 0) activateTab(remaining[remaining.length - 1]);
      else {
        state.activeFile = null;
        if (state.editor) state.editor.setModel(null);
      }
    }
  }

  function markModified(path) {
    if (state.openFiles[path]) {
      state.openFiles[path].modified = true;
      const tab = tabsList.querySelector(`[data-path="${path}"]`);
      if (tab) tab.classList.add("modified");
    }
  }

  // ── Save file ──────────────────────────────────────────────────────────────
  async function saveActiveFile() {
    const path = state.activeFile;
    if (!path) return;
    const file = state.openFiles[path];
    if (!file) return;
    const content = file.model.getValue();
    try {
      const res = await fetch("/files/write", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, content }),
      });
      if (!res.ok) throw new Error(await res.text());
      file.modified = false;
      file.content = content;
      const tab = tabsList.querySelector(`[data-path="${path}"]`);
      if (tab) tab.classList.remove("modified");
      appendOutput(`✓ Saved ${path}\n`);
    } catch (e) {
      appendOutput(`Error saving ${path}: ${e.message}\n`);
    }
  }

  // ── Agent interaction ──────────────────────────────────────────────────────
  async function sendPrompt(promptText) {
    if (!promptText.trim()) return;

    appendChat(promptText, "user");
    chatInput.value = "";
    setStatus("running");
    $("btn-send-prompt").disabled = true;
    $("btn-run-file").disabled = true;

    const agentMsg = appendChat("", "agent");
    clearOutput();

    const backend = llmSelect.value;

    // Try WebSocket streaming first; fall back to fetch
    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${wsProto}://${location.host}/ws/run`;

    try {
      await streamViaWebSocket(wsUrl, promptText, backend, agentMsg);
    } catch {
      // WebSocket unavailable — fallback to plain fetch
      await runViaFetch(promptText, backend, agentMsg);
    }

    setStatus("idle");
    $("btn-send-prompt").disabled = false;
    $("btn-run-file").disabled = false;
  }

  function streamViaWebSocket(wsUrl, prompt, backend, agentMsg) {
    return new Promise((resolve, reject) => {
      let ws;
      try { ws = new WebSocket(wsUrl); }
      catch { reject(new Error("WebSocket unavailable")); return; }

      ws.onopen = () => ws.send(JSON.stringify({ prompt, llm_backend: backend }));

      ws.onmessage = (ev) => {
        try {
          const pkt = JSON.parse(ev.data);
          if (pkt.type === "chunk") {
            agentMsg.textContent += pkt.data;
            appendOutput(pkt.data);
            chatMessages.scrollTop = chatMessages.scrollHeight;
          } else if (pkt.type === "done") {
            ws.close();
            resolve();
          } else if (pkt.type === "error") {
            agentMsg.className = "chat-msg error";
            agentMsg.textContent = "⚠ " + pkt.data;
            appendOutput("Error: " + pkt.data + "\n");
            ws.close();
            setStatus("error");
            resolve();
          }
        } catch { /* ignore non-JSON */ }
      };

      ws.onerror = () => { ws.close(); reject(new Error("ws error")); };
    });
  }

  async function runViaFetch(prompt, backend, agentMsg) {
    try {
      const res = await fetch("/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, llm_backend: backend }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      agentMsg.textContent = data.result;
      appendOutput(data.result + "\n");
    } catch (e) {
      agentMsg.className = "chat-msg error";
      agentMsg.textContent = "⚠ " + e.message;
      appendOutput("Error: " + e.message + "\n");
      setStatus("error");
    }
  }

  // ── "Run agent on file" ────────────────────────────────────────────────────
  function runAgentOnFile() {
    const path = state.activeFile;
    if (!path) {
      appendOutput("No file open.\n");
      return;
    }
    const content = state.openFiles[path]?.model?.getValue() || "";
    const prompt = `Review and improve the file '${path}':\n\n${content}`;
    sendPrompt(prompt);
  }

  // ── New file dialog ────────────────────────────────────────────────────────
  async function createNewFile(path) {
    try {
      const res = await fetch("/files/write", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, content: "" }),
      });
      if (!res.ok) throw new Error(await res.text());
      await loadFileTree();
      await openFile(path);
    } catch (e) {
      appendOutput(`Error creating ${path}: ${e.message}\n`);
    }
  }

  // ── Monaco init ────────────────────────────────────────────────────────────
  function initMonaco() {
    require(["vs/editor/editor.main"], function () {
      monaco.editor.defineTheme("swissagent-dark", {
        base: "vs-dark",
        inherit: true,
        rules: [],
        colors: {
          "editor.background": "#1e1e2e",
          "editor.foreground": "#cdd6f4",
          "editorLineNumber.foreground": "#45475a",
          "editorCursor.foreground": "#f5c2e7",
          "editor.selectionBackground": "#45475a",
          "editor.lineHighlightBackground": "#2a2a3d",
          "editorIndentGuide.background": "#313244",
        },
      });

      state.editor = monaco.editor.create($("editor-container"), {
        theme: "swissagent-dark",
        fontSize: 14,
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        fontLigatures: true,
        lineNumbers: "on",
        minimap: { enabled: true },
        scrollBeyondLastLine: false,
        wordWrap: "off",
        automaticLayout: true,
        tabSize: 4,
        insertSpaces: true,
        renderWhitespace: "selection",
        model: null,
      });

      // Ctrl+S to save
      state.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, saveActiveFile);

      // Load file tree after editor is ready
      loadFileTree();
    });
  }

  // ── Event wiring ───────────────────────────────────────────────────────────
  $("btn-save").addEventListener("click", saveActiveFile);
  $("btn-run-file").addEventListener("click", runAgentOnFile);
  $("btn-clear-output").addEventListener("click", clearOutput);
  $("btn-clear-chat").addEventListener("click", () => { chatMessages.innerHTML = ""; });
  $("btn-refresh-tree").addEventListener("click", () => loadFileTree());

  $("btn-send-prompt").addEventListener("click", () => sendPrompt(chatInput.value));
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendPrompt(chatInput.value); }
  });

  $("btn-new-file").addEventListener("click", () => {
    newFilePath.value = "workspace/";
    newFileDialog.classList.remove("hidden");
    newFilePath.focus();
  });
  $("btn-new-file-ok").addEventListener("click", () => {
    const p = newFilePath.value.trim();
    if (p) { createNewFile(p); newFileDialog.classList.add("hidden"); }
  });
  $("btn-new-file-cancel").addEventListener("click", () => newFileDialog.classList.add("hidden"));
  newFilePath.addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("btn-new-file-ok").click();
    if (e.key === "Escape") newFileDialog.classList.add("hidden");
  });

  // ── Boot ───────────────────────────────────────────────────────────────────
  initMonaco();
  appendOutput("SwissAgent IDE ready. Open a file or type a prompt to get started.\n");
})();
