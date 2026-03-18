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
    buildErrors: [],      // parsed error objects from last build
    lastBuildOutput: "",  // raw build output for "Fix with AI"
    contextTarget: null,  // path of the right-clicked tree item
  };

  // ── DOM refs ───────────────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const fileTree       = $("file-tree");
  const tabsList       = $("tabs-list");
  const outputContent  = $("output-content");
  const buildContent   = $("build-content");
  const problemsContent = $("problems-content");
  const chatMessages   = $("chat-messages");
  const chatInput      = $("chat-input");
  const statusEl       = $("status-indicator");
  const newFileDialog  = $("new-file-dialog");
  const newFilePath    = $("new-file-path");
  const llmSelect      = $("llm-backend-select");
  const contextMenu    = $("context-menu");

  // Status bar refs
  const sbFile     = $("sb-file");
  const sbCursor   = $("sb-cursor");
  const sbLanguage = $("sb-language");
  const sbAiStatus = $("sb-ai-status");

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
    // Also update status bar
    sbAiStatus.className = mode === "running" ? "sb-running" : mode === "error" ? "sb-error" : "sb-idle";
    sbAiStatus.textContent = mode === "running" ? "⟳ AI Running…" : mode === "error" ? "✕ AI Error" : "● AI Idle";
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

  function langDisplayName(lang) {
    const names = {
      python: "Python", javascript: "JavaScript", typescript: "TypeScript",
      html: "HTML", css: "CSS", json: "JSON", markdown: "Markdown",
      shell: "Shell", cpp: "C++", c: "C", csharp: "C#", java: "Java",
      rust: "Rust", go: "Go", lua: "Lua", ruby: "Ruby",
      ini: "TOML", yaml: "YAML", plaintext: "Plain Text",
    };
    return names[lang] || lang;
  }

  // ── Status bar updates ────────────────────────────────────────────────────
  function updateStatusBar() {
    if (state.activeFile) {
      sbFile.textContent = state.activeFile;
      const lang = state.openFiles[state.activeFile]?.language || "plaintext";
      sbLanguage.textContent = langDisplayName(lang);
    } else {
      sbFile.textContent = "No file open";
      sbLanguage.textContent = "Plain Text";
    }
  }

  function updateCursorPosition() {
    if (state.editor) {
      const pos = state.editor.getPosition();
      if (pos) {
        sbCursor.textContent = `Ln ${pos.lineNumber}, Col ${pos.column}`;
      }
    }
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

      // Right-click context menu
      item.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        showContextMenu(e.pageX, e.pageY, fullPath, entry.type);
      });

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

  // ── Context menu ──────────────────────────────────────────────────────────
  function showContextMenu(x, y, path, type) {
    state.contextTarget = path;
    contextMenu.style.left = x + "px";
    contextMenu.style.top = y + "px";
    contextMenu.classList.remove("hidden");
  }

  function hideContextMenu() {
    contextMenu.classList.add("hidden");
    state.contextTarget = null;
  }

  document.addEventListener("click", hideContextMenu);
  document.addEventListener("contextmenu", (e) => {
    // Only show custom menu on tree items (handled above)
    if (!e.target.closest(".tree-item")) hideContextMenu();
  });

  contextMenu.addEventListener("click", async (e) => {
    const action = e.target.closest(".ctx-item")?.dataset.action;
    if (!action || !state.contextTarget) return;
    const path = state.contextTarget;
    hideContextMenu();

    switch (action) {
      case "new-file": {
        const name = prompt("New file name:", "");
        if (name) {
          const newPath = path + "/" + name;
          await createNewFile(newPath);
        }
        break;
      }
      case "new-folder": {
        const name = prompt("New folder name:", "");
        if (name) {
          // Create a .gitkeep inside the new folder to materialize it
          const newPath = path + "/" + name + "/.gitkeep";
          await createNewFile(newPath);
        }
        break;
      }
      case "rename": {
        const parts = path.split("/");
        const oldName = parts.pop();
        const newName = prompt("Rename to:", oldName);
        if (newName && newName !== oldName) {
          const newPath = parts.concat(newName).join("/");
          try {
            const res = await fetch("/files/rename", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ old_path: path, new_path: newPath }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || "Rename failed");
            appendOutput(`✓ Renamed ${oldName} → ${newName}\n`);
            await loadFileTree();
          } catch (e) {
            appendOutput(`Error renaming: ${e.message}\n`);
          }
        }
        break;
      }
      case "copy-path": {
        try {
          await navigator.clipboard.writeText(path);
          appendOutput(`✓ Copied path: ${path}\n`);
        } catch {
          appendOutput(`Path: ${path}\n`);
        }
        break;
      }
      case "delete": {
        if (confirm(`Delete "${path}"? This cannot be undone.`)) {
          try {
            const res = await fetch("/files/delete", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ path }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || "Delete failed");
            // Close tab if open
            if (state.openFiles[path]) closeTab(path);
            appendOutput(`✓ Deleted ${path}\n`);
            await loadFileTree();
          } catch (e) {
            appendOutput(`Error deleting: ${e.message}\n`);
          }
        }
        break;
      }
    }
  });

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
    updateStatusBar();
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
        updateStatusBar();
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

      // Auto-rebuild on save
      if ($("chk-auto-rebuild").checked) {
        runBuildOrTest("build");
      }
    } catch (e) {
      appendOutput(`Error saving ${path}: ${e.message}\n`);
    }
  }

  // ── Build / Test ──────────────────────────────────────────────────────────
  async function runBuildOrTest(mode) {
    const cwdRoot = $("build-cwd-select").value;
    const subdir = $("build-subdir-select").value;
    const cwd = subdir ? `${cwdRoot}/${subdir}` : cwdRoot;

    // Switch to build tab
    switchOutputTab("build");
    buildContent.textContent = "";
    state.buildErrors = [];
    state.lastBuildOutput = "";
    $("btn-fix-ai").classList.add("hidden");

    // Detect build system
    let buildInfo;
    try {
      const res = await fetch(`/build/detect?path=${encodeURIComponent(cwd)}`);
      if (!res.ok) throw new Error(await res.text());
      buildInfo = await res.json();
    } catch (e) {
      buildContent.textContent = `⚠ Build detect failed: ${e.message}\n`;
      return;
    }

    const command = mode === "test" ? buildInfo.test_command : buildInfo.build_command;
    if (!command) {
      buildContent.textContent = `⚠ No ${mode} command detected for ${buildInfo.system || "unknown"} in ${cwd}\n`;
      return;
    }

    buildContent.textContent = `▶ ${mode === "test" ? "Testing" : "Building"} (${buildInfo.system}) in ${cwd}…\n$ ${command}\n\n`;

    // Stream via WebSocket
    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${wsProto}://${location.host}/ws/terminal`);

    ws.onopen = () => {
      ws.send(JSON.stringify({ command, cwd }));
    };

    ws.onmessage = (ev) => {
      try {
        const pkt = JSON.parse(ev.data);
        if (pkt.type === "stdout") {
          buildContent.textContent += pkt.data;
          state.lastBuildOutput += pkt.data;
          buildContent.scrollTop = buildContent.scrollHeight;
        } else if (pkt.type === "exit") {
          const ok = pkt.code === 0;
          buildContent.textContent += `\n${ok ? "✓" : "✕"} Process exited with code ${pkt.code}\n`;
          if (!ok) {
            $("btn-fix-ai").classList.remove("hidden");
            parseBuildErrors(state.lastBuildOutput);
          }
          ws.close();
        } else if (pkt.type === "error") {
          buildContent.textContent += `\n⚠ Error: ${pkt.data}\n`;
          ws.close();
        }
      } catch { /* ignore */ }
    };

    ws.onerror = () => {
      buildContent.textContent += "\n⚠ WebSocket connection error\n";
    };
  }

  // ── Error parsing ─────────────────────────────────────────────────────────
  function parseBuildErrors(output) {
    state.buildErrors = [];
    const patterns = [
      // Python: File "path", line N
      /File "([^"]+)", line (\d+)(?:.*\n\s*(.*?))?/g,
      // GCC/Clang: path:line:col: error/warning: msg
      /^([^\s:]+):(\d+):(\d+):\s*(error|warning):\s*(.*)$/gm,
      // TypeScript/ESLint: path(line,col): error TS...
      /^([^\s(]+)\((\d+),(\d+)\):\s*(error|warning)\s+(.*)$/gm,
      // Rust: error[E...]: msg\n --> path:line:col
      /^\s*-->\s+([^\s:]+):(\d+):(\d+)/gm,
      // Generic: ERROR: msg
      /^(ERROR|error|Error):\s*(.*)$/gm,
    ];

    const lines = output.split("\n");
    for (const line of lines) {
      // Python
      let m = line.match(/File "([^"]+)", line (\d+)/);
      if (m) {
        state.buildErrors.push({ file: m[1], line: parseInt(m[2]), severity: "error", message: line.trim() });
        continue;
      }
      // GCC/Clang/TS
      m = line.match(/^([^\s:]+):(\d+):(\d+):\s*(error|warning):\s*(.*)$/);
      if (m) {
        state.buildErrors.push({ file: m[1], line: parseInt(m[2]), col: parseInt(m[3]), severity: m[4], message: m[5] });
        continue;
      }
      // TypeScript parens style
      m = line.match(/^([^\s(]+)\((\d+),(\d+)\):\s*(error|warning)\s+(.*)$/);
      if (m) {
        state.buildErrors.push({ file: m[1], line: parseInt(m[2]), col: parseInt(m[3]), severity: m[4], message: m[5] });
        continue;
      }
      // Rust
      m = line.match(/^\s*-->\s+([^\s:]+):(\d+):(\d+)/);
      if (m) {
        state.buildErrors.push({ file: m[1], line: parseInt(m[2]), col: parseInt(m[3]), severity: "error", message: line.trim() });
      }
    }

    renderProblems();
  }

  function renderProblems() {
    problemsContent.innerHTML = "";
    if (state.buildErrors.length === 0) {
      problemsContent.innerHTML = '<div style="padding:12px;color:var(--text-dim)">No problems detected.</div>';
      return;
    }
    for (const err of state.buildErrors) {
      const row = document.createElement("div");
      row.className = "problem-row";

      const icon = document.createElement("span");
      icon.className = `problem-icon ${err.severity || "error"}`;
      icon.textContent = err.severity === "warning" ? "⚠" : "✕";

      const file = document.createElement("span");
      file.className = "problem-file";
      file.textContent = err.file || "unknown";

      const line = document.createElement("span");
      line.className = "problem-line";
      line.textContent = err.line ? `:${err.line}` : "";

      const msg = document.createElement("span");
      msg.className = "problem-msg";
      msg.textContent = err.message || "";

      row.appendChild(icon);
      row.appendChild(file);
      row.appendChild(line);
      row.appendChild(msg);

      // Click to jump to file+line
      row.addEventListener("click", async () => {
        // Try to map the file path to a workspace-relative path
        let filePath = err.file;
        if (filePath && !filePath.startsWith("workspace/") && !filePath.startsWith("projects/")) {
          filePath = "workspace/" + filePath;
        }
        try {
          await openFile(filePath);
          if (state.editor && err.line) {
            state.editor.revealLineInCenter(err.line);
            state.editor.setPosition({ lineNumber: err.line, column: err.col || 1 });
            state.editor.focus();
          }
        } catch { /* ignore */ }
      });

      problemsContent.appendChild(row);
    }
  }

  // ── Fix with AI ───────────────────────────────────────────────────────────
  function fixWithAI() {
    if (!state.lastBuildOutput) return;
    const errorSummary = state.buildErrors.map((e) =>
      `${e.file}:${e.line}: ${e.severity}: ${e.message}`
    ).join("\n");

    const prompt = `The build failed with the following errors. Please fix them:\n\n${errorSummary}\n\nFull build output:\n${state.lastBuildOutput.slice(-2000)}`;
    sendPrompt(prompt);
  }

  // ── Output tab switching ──────────────────────────────────────────────────
  function switchOutputTab(tabName) {
    document.querySelectorAll(".out-tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.tab === tabName)
    );
    document.querySelectorAll(".out-pane").forEach((p) => p.classList.remove("active"));
    const target = tabName === "build" ? buildContent
                 : tabName === "problems" ? problemsContent
                 : outputContent;
    target.classList.add("active");
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
      if (!path.endsWith("/.gitkeep")) {
        await openFile(path);
      }
    } catch (e) {
      appendOutput(`Error creating ${path}: ${e.message}\n`);
    }
  }

  // ── Import project dialog ─────────────────────────────────────────────────
  function showImportDialog() {
    $("import-path").value = "";
    $("import-dest").value = "";
    $("import-preview").classList.add("hidden");
    $("import-preview").textContent = "";
    $("import-dialog").classList.remove("hidden");
    $("import-path").focus();
  }

  async function scanImportFolder() {
    const path = $("import-path").value.trim();
    if (!path) return;
    const preview = $("import-preview");
    preview.textContent = "Scanning…";
    preview.classList.remove("hidden");
    try {
      const res = await fetch(`/files/scan?path=${encodeURIComponent(path)}`);
      if (!res.ok) throw new Error((await res.json()).detail || "Scan failed");
      const data = await res.json();
      let text = `📁 ${path}\n`;
      text += `Type: ${(data.detected_types || []).join(", ") || "unknown"}\n`;
      text += `Files: ${data.total_files || 0}  Dirs: ${data.total_dirs || 0}\n\n`;
      if (data.entries) {
        for (const e of data.entries.slice(0, 30)) {
          text += `  ${e.type === "dir" ? "📁" : "📄"} ${e.name}\n`;
        }
        if (data.entries.length > 30) text += `  … and ${data.entries.length - 30} more\n`;
      }
      preview.textContent = text;
    } catch (e) {
      preview.textContent = `⚠ ${e.message}`;
    }
  }

  async function doImport() {
    const sourcePath = $("import-path").value.trim();
    if (!sourcePath) return;
    const destName = $("import-dest").value.trim();
    try {
      const res = await fetch("/files/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_path: sourcePath, destination_name: destName }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Import failed");
      const data = await res.json();
      $("import-dialog").classList.add("hidden");
      appendOutput(`✓ Imported project: ${data.destination || sourcePath}\n`);
      await loadFileTree();
    } catch (e) {
      appendOutput(`Error importing: ${e.message}\n`);
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

      // Track cursor position for status bar
      state.editor.onDidChangeCursorPosition(updateCursorPosition);

      // Load file tree after editor is ready
      loadFileTree();
    });
  }

  // ── Output tab wiring ─────────────────────────────────────────────────────
  document.querySelectorAll(".out-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchOutputTab(btn.dataset.tab));
  });

  // ── Event wiring ───────────────────────────────────────────────────────────
  $("btn-save").addEventListener("click", saveActiveFile);
  $("btn-run-file").addEventListener("click", runAgentOnFile);
  $("btn-clear-output").addEventListener("click", () => {
    clearOutput();
    buildContent.textContent = "";
    problemsContent.innerHTML = "";
    state.buildErrors = [];
    state.lastBuildOutput = "";
    $("btn-fix-ai").classList.add("hidden");
  });
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

  // Build & Test buttons
  $("btn-build").addEventListener("click", () => runBuildOrTest("build"));
  $("btn-test").addEventListener("click", () => runBuildOrTest("test"));

  // Fix with AI button
  $("btn-fix-ai").addEventListener("click", fixWithAI);

  // Import project button + dialog
  $("btn-import-project").addEventListener("click", showImportDialog);
  $("btn-import-scan").addEventListener("click", scanImportFolder);
  $("btn-import-ok").addEventListener("click", doImport);
  $("btn-import-cancel").addEventListener("click", () => $("import-dialog").classList.add("hidden"));
  $("import-path").addEventListener("keydown", (e) => {
    if (e.key === "Enter") scanImportFolder();
    if (e.key === "Escape") $("import-dialog").classList.add("hidden");
  });

  // ── Boot ───────────────────────────────────────────────────────────────────
  initMonaco();
  appendOutput("SwissAgent IDE ready. Open a file or type a prompt to get started.\n");
  updateStatusBar();
})();
