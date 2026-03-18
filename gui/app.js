/**
 * SwissAgent IDE — frontend application
 * Uses Monaco Editor (loaded via CDN) and the SwissAgent REST + WebSocket API.
 */
(function () {
  "use strict";

  // ── Constants ───────────────────────────────────────────────────────────────
  const MAX_BUILD_OUTPUT_FOR_AI = 2000;

  // ── Code-block store — keyed by incrementing ID to avoid encoding issues ────
  const _codeStore = new Map();
  let   _codeStoreSeq = 0;

  // ── State ──────────────────────────────────────────────────────────────────
  const state = {
    openFiles: {},        // path → { content, language, modified, model }
    activeFile: null,     // currently visible path
    editor: null,         // Monaco editor instance
    editorMode: null,     // "monaco" | "fallback" | null
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

  // ── Code-block rendering (Copilot-style Apply + Copy buttons) ────────────
  /** Parse ```lang\ncode``` fences and return an HTML string with action buttons. */
  function _renderCodeBlocks(rawText) {
    // Safely escape text outside code fences
    function escHtml(s) {
      return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    const parts = rawText.split(/(```[\w]*\n[\s\S]*?```)/g);
    return parts.map((part) => {
      const m = part.match(/^```([\w]*)\n([\s\S]*?)```$/);
      if (!m) return `<span class="chat-text">${escHtml(part)}</span>`;
      const lang = m[1] || "text";
      const code = m[2].trimEnd();
      const id = ++_codeStoreSeq;
      _codeStore.set(id, code);
      return (
        `<div class="code-block">` +
        `<div class="code-block-header">` +
        `<span class="code-lang">${escHtml(lang)}</span>` +
        `<div class="code-block-actions">` +
        `<button class="code-copy-btn" data-cid="${id}" title="Copy to clipboard">📋 Copy</button>` +
        `<button class="code-apply-btn" data-cid="${id}" title="Apply to active file">⬆ Apply to file</button>` +
        `</div></div>` +
        `<pre class="code-content"><code>${escHtml(code)}</code></pre>` +
        `</div>`
      );
    }).join("");
  }

  /** Wire the Copy / Apply buttons inside a rendered chat message element. */
  function _bindCodeButtons(msgEl) {
    msgEl.querySelectorAll(".code-copy-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const code = _codeStore.get(Number(btn.dataset.cid));
        if (code === undefined) return;
        navigator.clipboard.writeText(code).catch(() => appendOutput(`Code:\n${code}\n`));
        btn.textContent = "✓ Copied";
        setTimeout(() => { btn.textContent = "📋 Copy"; }, 1500);
      });
    });
    msgEl.querySelectorAll(".code-apply-btn").forEach((btn) => {
      btn.addEventListener("click", () => _applyCodeToEditor(Number(btn.dataset.cid)));
    });
  }

  /** Replace a streaming-complete agent message's textContent with rendered HTML. */
  function _finaliseAgentMessage(msgEl) {
    const raw = msgEl.textContent;
    if (!raw.includes("```")) return; // nothing to render
    msgEl.innerHTML = _renderCodeBlocks(raw);
    _bindCodeButtons(msgEl);
  }

  /** Apply a stored code snippet to the active editor file. */
  function _applyCodeToEditor(codeId) {
    const code = _codeStore.get(codeId);
    if (code === undefined) return;
    if (!state.activeFile) {
      // Prompt for a filename
      const name = prompt("No file open. Enter a workspace path to create:", "workspace/snippet.txt");
      if (!name) return;
      createNewFile(name).then(() => {
        setTimeout(() => _applyCodeToEditor(codeId), 400);
      });
      return;
    }
    if (state.editorMode === "monaco" && state.openFiles[state.activeFile]?.model) {
      state.openFiles[state.activeFile].model.setValue(code);
    } else if (state.editorMode === "fallback") {
      $("fallback-editor").value = code;
      if (state.openFiles[state.activeFile]) state.openFiles[state.activeFile].content = code;
    }
    markModified(state.activeFile);
    appendOutput(`⬆ Applied code block to ${state.activeFile}\n`);
    switchOutputTab("output");
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
    if (state.editorMode === "monaco" && state.editor) {
      const pos = state.editor.getPosition();
      if (pos) {
        sbCursor.textContent = `Ln ${pos.lineNumber}, Col ${pos.column}`;
      }
    } else if (state.editorMode === "fallback") {
      const ta = $("fallback-editor");
      const text = ta.value.substring(0, ta.selectionStart);
      const lines = text.split("\n");
      const line = lines.length;
      const col = lines[lines.length - 1].length + 1;
      sbCursor.textContent = `Ln ${line}, Col ${col}`;
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
      case "open-split": {
        await openSplitFile(path);
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
      if (state.editorMode === "monaco") {
        const model = monaco.editor.createModel(data.content, lang);
        model.onDidChangeContent(() => markModified(path));
        state.openFiles[path] = { content: data.content, language: lang, modified: false, model };
      } else {
        state.openFiles[path] = { content: data.content, language: lang, modified: false, model: null };
      }
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
    if (state.editorMode === "monaco" && state.editor && state.openFiles[path]) {
      state.editor.setModel(state.openFiles[path].model);
    } else if (state.editorMode === "fallback" && state.openFiles[path]) {
      $("fallback-editor").value = state.openFiles[path]?.content ?? "";
      $("fallback-editor").classList.remove("hidden");
    }
    $("editor-welcome").classList.add("hidden");
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
        if (state.editorMode === "monaco" && state.editor) state.editor.setModel(null);
        if (state.editorMode === "fallback") {
          $("fallback-editor").value = "";
          $("fallback-editor").classList.add("hidden");
          $("editor-welcome").classList.remove("hidden");
        }
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
    const content = state.editorMode === "monaco"
      ? file.model.getValue()
      : $("fallback-editor").value;
    if (state.editorMode === "fallback") file.content = content;
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

    const prompt = `The build failed with the following errors. Please fix them:\n\n${errorSummary}\n\nFull build output:\n${state.lastBuildOutput.slice(-MAX_BUILD_OUTPUT_FOR_AI)}`;
    sendPrompt(prompt);
  }

  // ── Output tab switching ──────────────────────────────────────────────────
  function switchOutputTab(tabName) {
    document.querySelectorAll(".out-tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.tab === tabName)
    );
    document.querySelectorAll(".out-pane").forEach((p) => p.classList.remove("active"));
    const paneMap = {
      build: buildContent,
      problems: problemsContent,
      terminal: $("terminal-content"),
      roadmap: $("roadmap-content"),
    };
    const target = paneMap[tabName] || outputContent;
    target.classList.add("active");

    if (tabName === "terminal") _ensureTerminal();
    if (tabName === "roadmap") loadRoadmapPanel();
  }

  // ── Slash commands ─────────────────────────────────────────────────────────
  /** Expand /fix /explain /test /docs into a full context-aware prompt. */
  function _expandSlashCommand(raw) {
    const trimmed = raw.trim();
    if (!trimmed.startsWith("/")) return raw;

    const activeContent = (() => {
      if (!state.activeFile) return "";
      if (state.editorMode === "monaco" && state.openFiles[state.activeFile]?.model) {
        return state.openFiles[state.activeFile].model.getValue();
      }
      if (state.editorMode === "fallback") {
        return $("fallback-editor").value || state.openFiles[state.activeFile]?.content || "";
      }
      return state.openFiles[state.activeFile]?.content || "";
    })();

    const fileLine = state.activeFile ? `File: \`${state.activeFile}\`` : "";
    const fence = (c) => (c ? `\n\`\`\`\n${c}\n\`\`\`` : "");

    const [cmd, ...rest] = trimmed.split(/\s+([\s\S]*)/).filter(Boolean);
    const extra = rest.join(" ").trim();

    switch (cmd.toLowerCase()) {
      case "/fix":
        return `${fileLine}\nFix the bugs or issues in this code${extra ? `: ${extra}` : "."}${fence(activeContent)}`;
      case "/explain":
        return `${fileLine}\nExplain what this code does in clear, concise terms.${fence(activeContent)}`;
      case "/test":
        return `${fileLine}\nWrite unit tests for this code. Return only the test code in a code block.${fence(activeContent)}`;
      case "/docs":
        return `${fileLine}\nAdd docstrings/comments to every function and class in this code. Return the fully documented version.${fence(activeContent)}`;
      case "/refactor":
        return `${fileLine}\nRefactor this code to improve readability and maintainability${extra ? `: ${extra}` : "."}${fence(activeContent)}`;
      default:
        return raw;
    }
  }

  // ── Agent interaction ──────────────────────────────────────────────────────
  async function sendPrompt(promptText) {
    if (!promptText.trim()) return;

    const expandedPrompt = _expandSlashCommand(promptText);

    appendChat(promptText, "user");   // show original text in chat
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
      await streamViaWebSocket(wsUrl, expandedPrompt, backend, agentMsg);
    } catch {
      // WebSocket unavailable — fallback to plain fetch
      await runViaFetch(expandedPrompt, backend, agentMsg);
    }

    // Render code blocks now that the full response is available
    _finaliseAgentMessage(agentMsg);

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
    const file = state.openFiles[path];
    const content = state.editorMode === "monaco"
      ? (file?.model?.getValue() ?? "")
      : ($("fallback-editor").value || file?.content || "");
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
      text += `Type: ${(data.summary?.detected_project_types ?? []).join(", ") || "unknown"}\n`;
      text += `Files: ${data.summary?.total_files ?? 0}  Dirs: ${data.summary?.total_dirs ?? 0}\n\n`;
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
  function initFallbackEditor() {
    state.editorMode = "fallback";
    $("editor-loading").style.display = "none";
    $("fallback-editor").classList.add("hidden");
    $("editor-welcome").classList.remove("hidden");

    // Update status-bar editor-mode badge
    const badge = $("sb-editor-mode");
    badge.textContent = "Fallback Editor";
    badge.className = "mode-fallback";
    badge.title = "Monaco CDN unavailable — using plain-text fallback. Click to reload with Monaco when online.";
    badge.style.cursor = "pointer";
    badge.addEventListener("click", () => location.reload());

    // Tab key → 4-space indent
    $("fallback-editor").addEventListener("keydown", (e) => {
      if (e.key === "Tab") {
        e.preventDefault();
        const ta = $("fallback-editor");
        const start = ta.selectionStart;
        const end = ta.selectionEnd;
        ta.value = ta.value.substring(0, start) + "    " + ta.value.substring(end);
        ta.selectionStart = ta.selectionEnd = start + 4;
        if (state.activeFile) markModified(state.activeFile);
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        saveActiveFile();
      }
    });

    $("fallback-editor").addEventListener("input", () => {
      if (state.activeFile) markModified(state.activeFile);
      updateCursorPosition();
    });

    $("fallback-editor").addEventListener("keyup", updateCursorPosition);
    $("fallback-editor").addEventListener("click", updateCursorPosition);

    loadFileTree();
    appendOutput(
      "⚠ Monaco Editor CDN unavailable — using plain-text fallback editor.\n" +
      "All file and agent features (slash commands, Apply buttons) still work.\n" +
      "Connect to the internet and reload the page to get the full Monaco IDE.\n"
    );
    _startPendingPushPoller();
  }

  function initMonaco() {
    // If the CDN loader script itself failed (onerror set the flag), skip straight
    // to the fallback rather than waiting for the 8-second timeout.
    if (typeof require !== "function" || window.__monacoLoaderFailed) {
      initFallbackEditor();
      return;
    }

    let monacoLoaded = false;
    const fallbackTimer = setTimeout(() => {
      if (!monacoLoaded) initFallbackEditor();
    }, 8000);

    require(["vs/editor/editor.main"], function () {
      if (monacoLoaded) return; // guard against double-fire
      monacoLoaded = true;
      clearTimeout(fallbackTimer);

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

      state.editorMode = "monaco";
      $("editor-loading").style.display = "none";
      $("editor-welcome").classList.remove("hidden");

      // Update status-bar editor-mode badge
      const badge = $("sb-editor-mode");
      badge.textContent = "Monaco";
      badge.className = "mode-monaco";
      badge.title = "Monaco Editor (full IDE — syntax highlighting, IntelliSense, minimap)";

      // Ctrl+S to save
      state.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, saveActiveFile);

      // Track cursor position for status bar
      state.editor.onDidChangeCursorPosition(updateCursorPosition);

      // ── Copilot-style inline completions ──────────────────────────────────
      let _completionTimer = null;
      monaco.languages.registerInlineCompletionsProvider({ pattern: "**" }, {
        provideInlineCompletions(model, position) {
          return new Promise((resolve) => {
            clearTimeout(_completionTimer);
            _completionTimer = setTimeout(async () => {
              try {
                const offset   = model.getOffsetAt(position);
                const allText  = model.getValue();
                const prefix   = allText.slice(0, offset);
                const suffix   = allText.slice(offset);
                const res = await fetch("/api/complete", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    prefix,
                    suffix,
                    language: model.getLanguageId(),
                    path: state.activeFile || "",
                    llm_backend: llmSelect.value,
                  }),
                });
                if (!res.ok) { resolve({ items: [] }); return; }
                const data = await res.json();
                if (!data.completion) { resolve({ items: [] }); return; }
                resolve({
                  items: [{
                    insertText: data.completion,
                    range: new monaco.Range(
                      position.lineNumber, position.column,
                      position.lineNumber, position.column,
                    ),
                  }],
                });
              } catch { resolve({ items: [] }); }
            }, 700);
          });
        },
        freeInlineCompletions() {},
      });

      // Load file tree after editor is ready
      loadFileTree();
      _startPendingPushPoller();
    });
  }

  // ── Pending-push poller (files pushed via /api/ide/push open automatically) ─
  function _startPendingPushPoller() {
    setInterval(async () => {
      try {
        const res = await fetch("/api/ide/pending");
        if (!res.ok) return;
        const { paths } = await res.json();
        for (const p of paths) {
          await openFile(p);
          appendOutput(`📥 File pushed to IDE: ${p}\n`);
        }
        if (paths.length) await loadFileTree();
      } catch { /* server may not be ready yet */ }
    }, 3000);
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

  // Clone repo button + dialog
  $("btn-clone-repo").addEventListener("click", showCloneDialog);
  $("btn-clone-ok").addEventListener("click", doClone);
  $("btn-clone-cancel").addEventListener("click", () => $("clone-dialog").classList.add("hidden"));
  $("clone-url").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doClone();
    if (e.key === "Escape") $("clone-dialog").classList.add("hidden");
  });

  // ── Git clone ──────────────────────────────────────────────────────────────
  function showCloneDialog() {
    $("clone-url").value = "";
    $("clone-dest").value = "";
    $("clone-branch").value = "";
    const status = $("clone-status");
    status.className = "clone-status hidden";
    status.textContent = "";
    $("clone-dialog").classList.remove("hidden");
    $("clone-url").focus();
  }

  async function doClone() {
    const url = $("clone-url").value.trim();
    if (!url) return;
    const dest = $("clone-dest").value.trim();
    const branch = $("clone-branch").value.trim();
    const status = $("clone-status");
    status.className = "clone-status running";
    status.textContent = "⟳ Cloning… (this may take a moment)";
    $("btn-clone-ok").disabled = true;
    try {
      const res = await fetch("/git/clone", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, destination: dest, branch }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Clone failed");
      status.className = "clone-status success";
      status.textContent = `✓ Cloned into ${data.destination} (${data.files} files)`;
      await loadFileTree();
      await _refreshProjectSwitcher();
      appendOutput(`✓ Cloned ${url} → ${data.destination}\n`);
      setTimeout(() => $("clone-dialog").classList.add("hidden"), 1500);
    } catch (e) {
      status.className = "clone-status error";
      status.textContent = `⚠ ${e.message}`;
    } finally {
      $("btn-clone-ok").disabled = false;
    }
  }

  // ── Project switcher ───────────────────────────────────────────────────────
  async function _refreshProjectSwitcher() {
    const sel = $("project-switcher");
    try {
      // Collect subdirs from both workspace/ and projects/
      const [wsRes, prRes] = await Promise.all([
        fetch("/files?path=workspace"),
        fetch("/files?path=projects"),
      ]);
      const options = [{ value: "", label: "— open project —" }];
      if (wsRes.ok) {
        const data = await wsRes.json();
        for (const e of (data.entries || [])) {
          if (e.type === "dir") options.push({ value: `workspace/${e.name}`, label: `workspace/${e.name}` });
        }
      }
      if (prRes.ok) {
        const data = await prRes.json();
        for (const e of (data.entries || [])) {
          if (e.type === "dir") options.push({ value: `projects/${e.name}`, label: `projects/${e.name}` });
        }
      }
      sel.innerHTML = options.map((o) =>
        `<option value="${o.value}">${o.label}</option>`
      ).join("");
    } catch { /* ignore */ }
  }

  $("project-switcher").addEventListener("change", async (e) => {
    const path = e.target.value;
    if (!path) return;
    // Load the file tree rooted at this project dir
    await loadFileTree(path);
    e.target.value = "";  // reset so it can be re-selected
  });

  // ── PTY terminal ─────────────────────────────────────────────────────────
  const _ptyState = { term: null, fitAddon: null, ws: null, ready: false };

  function _ensureTerminal() {
    const container = $("terminal-content");
    if (_ptyState.ready) {
      if (_ptyState.fitAddon) _ptyState.fitAddon.fit();
      return;
    }
    if (window.__xtermLoaderFailed || typeof Terminal === "undefined") {
      container.innerHTML =
        '<div style="padding:16px;color:var(--text-dim)">' +
        "⚠ xterm.js CDN unavailable. Connect to the internet to use the terminal tab.<br>" +
        "You can still run commands via the Build/Test buttons." +
        "</div>";
      return;
    }
    _ptyState.ready = true;

    const term = new Terminal({
      theme: {
        background: "#1e1e2e",
        foreground: "#cdd6f4",
        cursor: "#f5c2e7",
        selectionBackground: "#45475a",
      },
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      cursorBlink: true,
      convertEol: true,
    });
    _ptyState.term = term;

    let fitAddon = null;
    if (typeof FitAddon !== "undefined") {
      fitAddon = new FitAddon.FitAddon();
      term.loadAddon(fitAddon);
      _ptyState.fitAddon = fitAddon;
    }

    term.open(container);
    if (fitAddon) fitAddon.fit();

    // Resize observer to keep terminal sized correctly
    const ro = new ResizeObserver(() => { if (fitAddon) fitAddon.fit(); });
    ro.observe(container);

    _connectPty(term, fitAddon);
  }

  function _connectPty(term, fitAddon) {
    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${wsProto}://${location.host}/ws/pty`);
    _ptyState.ws = ws;

    ws.onopen = () => {
      const cols = fitAddon ? term.cols : 120;
      const rows = fitAddon ? term.rows : 30;
      ws.send(JSON.stringify({ type: "init", cwd: "workspace", cols, rows }));
    };

    ws.onmessage = (ev) => {
      try {
        const pkt = JSON.parse(ev.data);
        if (pkt.type === "output") term.write(pkt.data);
        else if (pkt.type === "exit") term.write(`\r\n\x1b[33m[Process exited with code ${pkt.code}]\x1b[0m\r\n`);
        else if (pkt.type === "error") term.write(`\r\n\x1b[31m[Error: ${pkt.data}]\x1b[0m\r\n`);
      } catch { /* ignore */ }
    };

    ws.onclose = () => {
      term.write("\r\n\x1b[33m[Connection closed — click here to reconnect]\x1b[0m\r\n");
      _ptyState.ready = false;
      // Allow reconnect on click
      $("terminal-content").addEventListener("click", () => {
        if (!_ptyState.ready) {
          $("terminal-content").innerHTML = "";
          _ensureTerminal();
        }
      }, { once: true });
    };

    ws.onerror = () => ws.close();

    // Forward keyboard input to PTY
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "input", data }));
      }
    });

    // Forward resize events
    term.onResize(({ cols, rows }) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols, rows }));
      }
    });
  }

  // ── Roadmap panel ─────────────────────────────────────────────────────────
  const _roadmapCache = { data: null };

  async function loadRoadmapPanel() {
    const container = $("roadmap-content");
    try {
      const res = await fetch("/roadmap");
      if (!res.ok) throw new Error("Roadmap not found");
      const data = await res.json();
      _roadmapCache.data = data;
      renderRoadmapPanel(container, data);
    } catch (e) {
      container.innerHTML = `<div style="padding:16px;color:var(--danger)">⚠ ${e.message}</div>`;
    }
  }

  function renderRoadmapPanel(container, data) {
    const statusIcon = { done: "✅", in_progress: "🔄", pending: "⬜" };

    let html = `<div class="roadmap-header">
      <span>📋 ${data.project || "Roadmap"} — ${data.version || ""}</span>
      <button id="btn-roadmap-next-task" title="Send next pending task to the AI agent">▶ Work on Next Task</button>
    </div>`;

    for (const m of (data.milestones || [])) {
      const badge = `<span class="milestone-badge badge-${m.status}">${m.status.replace("_", " ")}</span>`;
      const tasks = (m.tasks || []).map((t) => {
        const workBtn = (t.status !== "done")
          ? `<button class="task-work-btn" data-task-id="${t.id}" data-task-title="${encodeURIComponent(t.title)}" data-task-desc="${encodeURIComponent(t.description || "")}">▶ Work</button>`
          : "";
        return `<div class="task-row">
          <span class="task-status-icon">${statusIcon[t.status] || "⬜"}</span>
          <div class="task-info">
            <div class="task-title">${escHtmlSimple(t.title)}</div>
            ${t.description ? `<div class="task-desc">${escHtmlSimple(t.description)}</div>` : ""}
          </div>
          ${workBtn}
        </div>`;
      }).join("");

      html += `<div class="milestone-block">
        <div class="milestone-title" data-milestone="${m.id}">
          <span class="milestone-arrow">▶</span>
          <span class="milestone-label">${escHtmlSimple(m.title)}</span>
          ${badge}
        </div>
        <div class="milestone-tasks ${m.status !== "done" ? "open" : ""}" id="mt-${m.id}">${tasks}</div>
      </div>`;
    }

    container.innerHTML = html;

    // Collapse/expand milestones
    container.querySelectorAll(".milestone-title").forEach((el) => {
      el.addEventListener("click", () => {
        const id = el.dataset.milestone;
        const tasks = $(`mt-${id}`);
        const arrow = el.querySelector(".milestone-arrow");
        if (tasks) {
          const open = tasks.classList.toggle("open");
          if (arrow) arrow.classList.toggle("open", open);
        }
      });
    });

    // "Work" buttons on individual tasks
    container.querySelectorAll(".task-work-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const title = decodeURIComponent(btn.dataset.taskTitle || "");
        const desc = decodeURIComponent(btn.dataset.taskDesc || "");
        const taskId = btn.dataset.taskId;
        _workOnTask(taskId, title, desc);
      });
    });

    // "Work on Next Task" button
    const nextBtn = $("btn-roadmap-next-task");
    if (nextBtn) {
      nextBtn.addEventListener("click", async () => {
        try {
          const res = await fetch("/roadmap/next");
          const data = await res.json();
          if (!data.task) {
            appendOutput("🎉 All roadmap tasks are complete!\n");
            return;
          }
          _workOnTask(data.task.id, data.task.title, data.task.description || "");
        } catch (e) {
          appendOutput(`Error fetching next task: ${e.message}\n`);
        }
      });
    }
  }

  function _workOnTask(taskId, title, description) {
    const prompt =
      `You are implementing a task from the SwissAgent roadmap.\n\n` +
      `Task: ${title}\n` +
      (description ? `Description: ${description}\n\n` : "\n") +
      `Please implement this task now. Make the required code changes, ` +
      `create any new files needed, and explain what you did.`;
    sendPrompt(prompt);
    // Mark task in_progress
    fetch(`/roadmap/task/${taskId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "in_progress" }),
    }).catch(() => {});
    switchOutputTab("output");
  }

  function escHtmlSimple(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Command palette ────────────────────────────────────────────────────────
  const _palette = {
    visible: false,
    mode: "files",    // "files" | "commands"
    items: [],
    activeIdx: 0,
    _fileCache: null,
  };

  const _commands = [
    { icon: "💾", label: "Save File", hint: "Ctrl+S", action: () => saveActiveFile() },
    { icon: "▶", label: "Run Agent on File", hint: "", action: () => runAgentOnFile() },
    { icon: "🔨", label: "Build Project", hint: "", action: () => runBuildOrTest("build") },
    { icon: "🧪", label: "Run Tests", hint: "", action: () => runBuildOrTest("test") },
    { icon: "⬇", label: "Clone Repository", hint: "", action: () => showCloneDialog() },
    { icon: "📥", label: "Import Project", hint: "", action: () => showImportDialog() },
    { icon: "↺", label: "Refresh File Tree", hint: "", action: () => loadFileTree() },
    { icon: "📋", label: "View Roadmap", hint: "", action: () => switchOutputTab("roadmap") },
    { icon: "⬛", label: "Open Terminal", hint: "", action: () => switchOutputTab("terminal") },
    { icon: "🔍", label: "Search Files", hint: "", action: () => { /* handled by searchbox */ } },
    { icon: "✕", label: "Clear Output", hint: "", action: () => {
      clearOutput();
      buildContent.textContent = "";
      problemsContent.innerHTML = "";
    }},
  ];

  async function _paletteGetFiles() {
    if (_palette._fileCache) return _palette._fileCache;
    const results = [];
    const roots = ["workspace", "projects"];
    for (const root of roots) {
      try {
        await _walkForPalette(root, results, 4);
      } catch { /* ignore */ }
    }
    _palette._fileCache = results;
    // Cache invalidates after 30s
    setTimeout(() => { _palette._fileCache = null; }, 30000);
    return results;
  }

  async function _walkForPalette(path, results, depth) {
    if (depth <= 0 || results.length > 500) return;
    const res = await fetch(`/files?path=${encodeURIComponent(path)}`);
    if (!res.ok) return;
    const data = await res.json();
    for (const e of (data.entries || [])) {
      const fullPath = `${path}/${e.name}`;
      if (e.type === "file") results.push(fullPath);
      else if (e.type === "dir" && !e.name.startsWith(".")) await _walkForPalette(fullPath, results, depth - 1);
    }
  }

  function openPalette(mode) {
    _palette.mode = mode;
    _palette.visible = true;
    _palette._fileCache = null;
    const overlay = $("cmd-palette");
    const input = $("cmd-palette-input");
    overlay.classList.remove("hidden");
    input.value = "";
    input.placeholder = mode === "commands" ? "Type a command…" : "Type a file name…";
    input.focus();
    _renderPalette("");
  }

  function closePalette() {
    _palette.visible = false;
    $("cmd-palette").classList.add("hidden");
  }

  async function _renderPalette(query) {
    const list = $("cmd-palette-list");
    list.innerHTML = '<div style="padding:10px 16px;color:var(--text-dim);font-size:12px">Loading…</div>';
    _palette.activeIdx = 0;

    if (_palette.mode === "commands") {
      const filtered = _commands.filter((c) =>
        !query || c.label.toLowerCase().includes(query.toLowerCase())
      );
      _palette.items = filtered;
      list.innerHTML = filtered.length
        ? filtered.map((c, i) => `<div class="palette-item${i === 0 ? " active" : ""}" data-idx="${i}">
            <span class="palette-item-icon">${c.icon}</span>
            <span class="palette-item-label">${c.label}</span>
            <span class="palette-item-hint">${c.hint}</span>
          </div>`).join("")
        : '<div style="padding:10px 16px;color:var(--text-dim);font-size:12px">No commands match.</div>';
    } else {
      const files = await _paletteGetFiles();
      const lq = query.toLowerCase();
      const filtered = query
        ? files.filter((f) => f.toLowerCase().includes(lq)).slice(0, 50)
        : files.slice(0, 50);
      _palette.items = filtered;
      list.innerHTML = filtered.length
        ? filtered.map((f, i) => {
            const parts = f.split("/");
            const name = parts.pop();
            const dir = parts.join("/");
            return `<div class="palette-item${i === 0 ? " active" : ""}" data-idx="${i}">
              <span class="palette-item-icon">📄</span>
              <span class="palette-item-label">${escHtmlSimple(name)}</span>
              <span class="palette-item-hint">${escHtmlSimple(dir)}</span>
            </div>`;
          }).join("")
        : '<div style="padding:10px 16px;color:var(--text-dim);font-size:12px">No files found.</div>';
    }

    // Bind click handlers
    list.querySelectorAll(".palette-item").forEach((el) => {
      el.addEventListener("click", () => _paletteActivateIdx(Number(el.dataset.idx)));
    });
  }

  function _paletteActivateIdx(idx) {
    _palette.activeIdx = idx;
    if (_palette.mode === "commands") {
      const cmd = _palette.items[idx];
      if (cmd) { closePalette(); cmd.action(); }
    } else {
      const file = _palette.items[idx];
      if (file) { closePalette(); openFile(file); }
    }
  }

  function _paletteMove(delta) {
    const list = $("cmd-palette-list");
    const items = list.querySelectorAll(".palette-item");
    if (!items.length) return;
    items[_palette.activeIdx]?.classList.remove("active");
    _palette.activeIdx = Math.max(0, Math.min(items.length - 1, _palette.activeIdx + delta));
    items[_palette.activeIdx]?.classList.add("active");
    items[_palette.activeIdx]?.scrollIntoView({ block: "nearest" });
  }

  $("cmd-palette-input").addEventListener("input", (e) => {
    _renderPalette(e.target.value);
  });

  $("cmd-palette-input").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closePalette(); e.preventDefault(); }
    else if (e.key === "ArrowDown") { _paletteMove(1); e.preventDefault(); }
    else if (e.key === "ArrowUp") { _paletteMove(-1); e.preventDefault(); }
    else if (e.key === "Enter") { _paletteActivateIdx(_palette.activeIdx); e.preventDefault(); }
  });

  $("cmd-palette").addEventListener("click", (e) => {
    if (e.target === $("cmd-palette")) closePalette();
  });

  // Global keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.shiftKey && e.key.toLowerCase() === "p") {
      e.preventDefault();
      if (_palette.visible) closePalette();
      else openPalette("commands");
    } else if (mod && !e.shiftKey && e.key.toLowerCase() === "p") {
      e.preventDefault();
      if (_palette.visible) closePalette();
      else openPalette("files");
    }
  });

  // ── Activity bar panel switching ──────────────────────────────────────────
  document.querySelectorAll(".ab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const panel = btn.dataset.panel;
      // Update active button
      document.querySelectorAll(".ab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      // Show matching panel
      document.querySelectorAll(".sb-panel").forEach((p) => p.classList.remove("active"));
      const targetPanel = document.getElementById(
        panel === "roadmap" ? "panel-roadmap-sidebar" : `panel-${panel}`
      );
      if (targetPanel) targetPanel.classList.add("active");
      // Lazy-load panel content when first shown
      if (panel === "git")       loadGitPanel();
      if (panel === "knowledge") { loadKnowledgePanel(); loadProfilePanel(); loadRulesPanel(); }
      if (panel === "roadmap")   loadRoadmapSidebar();
      // Focus search input when search panel is shown
      if (panel === "search") setTimeout(() => $("sb-search-input")?.focus(), 50);
    });
  });

  // ── Search panel in sidebar ───────────────────────────────────────────────
  async function runSidebarSearch() {
    const query = $("sb-search-input").value.trim();
    if (!query) return;
    const resultsDiv = $("sb-search-results");
    resultsDiv.innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:4px">Searching…</div>';
    try {
      const res = await fetch(`/search?q=${encodeURIComponent(query)}&path=workspace&max_results=30`);
      const data = await res.json();
      const results = data.results || [];
      if (!results.length) {
        resultsDiv.innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:4px">No results.</div>';
        return;
      }
      resultsDiv.innerHTML = results.map((r) => `
        <div class="search-result-item" data-path="${escHtmlSimple(r.path)}" data-line="${r.line || 1}" style="padding:3px 4px;cursor:pointer;border-radius:3px;margin-bottom:2px;">
          <div style="font-size:11px;font-family:var(--font-mono);color:var(--accent);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escHtmlSimple(r.path)}</div>
          <div style="font-size:10px;color:var(--text-dim);font-family:var(--font-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${r.line ? `L${r.line}: ` : ""}${escHtmlSimple(r.match || "")}</div>
        </div>
      `).join("");
      resultsDiv.querySelectorAll(".search-result-item").forEach((el) => {
        el.addEventListener("mouseenter", () => { el.style.background = "var(--surface2)"; });
        el.addEventListener("mouseleave", () => { el.style.background = ""; });
        el.addEventListener("click", () => {
          openFile(el.dataset.path);
          // Switch to explorer panel to show context
          document.querySelector('.ab-btn[data-panel="explorer"]')?.click();
        });
      });
    } catch (e) {
      resultsDiv.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  $("btn-sb-search").addEventListener("click", runSidebarSearch);
  $("sb-search-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSidebarSearch();
  });

  // ── Git panel ─────────────────────────────────────────────────────────────
  let _gitCurrentPath = "workspace";

  async function _gitPath() {
    // Use the current project switcher value or "workspace"
    const sw = $("project-switcher");
    const val = sw ? sw.value : "";
    if (val && val !== "") return val;
    const cwd = $("build-cwd-select");
    return cwd ? (cwd.value || "workspace") : "workspace";
  }

  async function loadGitPanel() {
    const path = await _gitPath();
    _gitCurrentPath = path;
    $("git-branch-info").textContent = "Loading…";
    try {
      const res = await fetch(`/git/status?path=${encodeURIComponent(path)}`);
      const data = await res.json();
      if (data.error) {
        $("git-branch-info").textContent = "⚠ Not a git repo";
        $("git-staged-list").innerHTML = "";
        $("git-unstaged-list").innerHTML = "";
        $("git-untracked-list").innerHTML = "";
        $("git-log-list").innerHTML = "";
        return;
      }
      renderGitPanel(data);
    } catch (e) {
      $("git-branch-info").textContent = `Error: ${e.message}`;
    }
  }

  function renderGitPanel(data) {
    $("git-branch-info").textContent = `⎇ ${data.branch || "HEAD"}`;

    function makeFileItem(item, isStaged, isUntracked) {
      const div = document.createElement("div");
      div.className = "git-file-item";
      const status = isUntracked ? "?" : (item.status || " ");
      const colorClass = `git-status-${status}`;
      div.innerHTML = `
        <span class="git-status-badge ${colorClass}">${status}</span>
        <span class="git-file-name" title="${escHtmlSimple(isUntracked ? item : item.file)}">${escHtmlSimple(isUntracked ? item : item.file)}</span>
        <button class="git-file-action" title="${isStaged ? "Unstage" : "Stage"}">${isStaged ? "−" : "＋"}</button>
        <button class="git-file-action" title="View diff" data-diff="1">⊿</button>
      `;
      const fileName = isUntracked ? item : item.file;
      div.querySelectorAll(".git-file-action").forEach((btn) => {
        if (btn.dataset.diff) {
          btn.addEventListener("click", () => showGitDiff(_gitCurrentPath, fileName));
        } else {
          btn.addEventListener("click", () => {
            const files = [fileName];
            fetch("/git/stage", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ path: _gitCurrentPath, files, unstage: isStaged }),
            }).then(() => loadGitPanel());
          });
        }
      });
      return div;
    }

    const staged = $("git-staged-list");
    staged.innerHTML = "";
    (data.staged || []).forEach((f) => staged.appendChild(makeFileItem(f, true, false)));
    if (!data.staged?.length) staged.innerHTML = '<div style="font-size:11px;color:var(--text-dim);padding:2px 4px">Nothing staged</div>';

    const unstaged = $("git-unstaged-list");
    unstaged.innerHTML = "";
    (data.unstaged || []).forEach((f) => unstaged.appendChild(makeFileItem(f, false, false)));
    if (!data.unstaged?.length) unstaged.innerHTML = '<div style="font-size:11px;color:var(--text-dim);padding:2px 4px">Nothing modified</div>';

    const untracked = $("git-untracked-list");
    untracked.innerHTML = "";
    (data.untracked || []).forEach((f) => untracked.appendChild(makeFileItem(f, false, true)));
    if (!data.untracked?.length) untracked.innerHTML = '<div style="font-size:11px;color:var(--text-dim);padding:2px 4px">No untracked files</div>';

    const log = $("git-log-list");
    log.innerHTML = (data.commits || []).map((c) =>
      `<div class="git-log-item"><span class="git-sha">${escHtmlSimple(c.sha)}</span>${escHtmlSimple(c.message)}</div>`
    ).join("") || '<div style="font-size:11px;color:var(--text-dim);padding:2px 4px">No commits</div>';
  }

  async function showGitDiff(path, file) {
    try {
      const res = await fetch(`/git/diff?path=${encodeURIComponent(path)}&file=${encodeURIComponent(file)}`);
      const data = await res.json();
      const diffText = (data.staged_diff || "") + (data.diff || "");
      $("git-diff-title").textContent = file || "Diff";
      $("git-diff-content").textContent = diffText || "(no diff)";
      $("git-diff-area").classList.remove("hidden");
    } catch (e) {
      appendOutput(`Git diff error: ${e.message}\n`);
    }
  }

  $("btn-git-refresh").addEventListener("click", () => loadGitPanel());

  $("btn-git-stage-all").addEventListener("click", async () => {
    const path = await _gitPath();
    try {
      await fetch("/git/stage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, files: [], unstage: false }),
      });
      loadGitPanel();
    } catch (e) {
      appendOutput(`Stage all error: ${e.message}\n`);
    }
  });

  $("btn-git-commit").addEventListener("click", async () => {
    const msg = $("git-commit-msg").value.trim();
    if (!msg) { appendOutput("⚠ Please enter a commit message.\n"); return; }
    const path = await _gitPath();
    try {
      const res = await fetch("/git/commit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, message: msg, files: [] }),
      });
      const data = await res.json();
      if (data.detail) throw new Error(data.detail);
      appendOutput(`✅ Committed: ${msg}\n`);
      $("git-commit-msg").value = "";
      loadGitPanel();
    } catch (e) {
      appendOutput(`Commit error: ${e.message}\n`);
    }
  });

  $("btn-git-diff-close").addEventListener("click", () => {
    $("git-diff-area").classList.add("hidden");
  });

  // ── Knowledge panel ────────────────────────────────────────────────────────
  function _kbProjectPath() {
    const sw = $("project-switcher");
    return (sw && sw.value) ? sw.value : "";
  }

  async function loadKnowledgePanel() {
    const path = _kbProjectPath();
    $("kb-source-list").innerHTML = '<div style="color:var(--text-dim);font-size:11px">Loading…</div>';
    try {
      const res = await fetch(`/knowledge/list?project_path=${encodeURIComponent(path)}`);
      const data = await res.json();
      renderKbSources(data.sources || []);
    } catch (e) {
      $("kb-source-list").innerHTML = `<div style="color:var(--danger);font-size:11px">Error: ${e.message}</div>`;
    }
  }

  function renderKbSources(sources) {
    const list = $("kb-source-list");
    if (!sources.length) {
      list.innerHTML = '<div style="color:var(--text-dim);font-size:11px;font-style:italic">No knowledge sources yet.</div>';
      return;
    }
    list.innerHTML = sources.map((s) => `
      <div class="kb-source-item">
        <span class="kb-label" title="${escHtmlSimple(s.url || s.source_id)}">${escHtmlSimple(s.label || s.url || s.source_id)}</span>
        <span style="color:var(--text-dim);font-size:10px;margin-left:auto;">${s.chunks || 0} chunks</span>
        <button data-source-id="${escHtmlSimple(s.source_id)}" title="Remove source">✕</button>
      </div>
    `).join("");
    list.querySelectorAll("button[data-source-id]").forEach((btn) => {
      btn.addEventListener("click", () => removeKbSource(btn.dataset.sourceId));
    });
  }

  async function removeKbSource(sourceId) {
    const path = _kbProjectPath();
    try {
      await fetch("/knowledge/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_id: sourceId, project_path: path }),
      });
      loadKnowledgePanel();
    } catch (e) {
      appendOutput(`Remove KB source error: ${e.message}\n`);
    }
  }

  $("btn-kb-add").addEventListener("click", async () => {
    const url = $("kb-add-url").value.trim();
    if (!url) return;
    const path = _kbProjectPath();
    $("btn-kb-add").textContent = "⟳";
    $("btn-kb-add").disabled = true;
    try {
      const res = await fetch("/knowledge/fetch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, project_path: path }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      $("kb-add-url").value = "";
      appendOutput(`📚 Indexed: ${data.label || url} (${data.chunks || 0} chunks)\n`);
      loadKnowledgePanel();
    } catch (e) {
      appendOutput(`KB fetch error: ${e.message}\n`);
    } finally {
      $("btn-kb-add").textContent = "＋";
      $("btn-kb-add").disabled = false;
    }
  });

  $("kb-add-url").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("btn-kb-add").click();
  });

  $("btn-kb-search").addEventListener("click", async () => {
    const query = $("kb-search-query").value.trim();
    if (!query) return;
    const path = _kbProjectPath();
    try {
      const res = await fetch(`/knowledge/search?query=${encodeURIComponent(query)}&project_path=${encodeURIComponent(path)}&top_k=3`);
      const data = await res.json();
      const results = data.results || [];
      const div = $("kb-search-results");
      if (!results.length) {
        div.innerHTML = '<div style="color:var(--text-dim);font-size:11px">No results found.</div>';
      } else {
        div.innerHTML = results.map((r) => `
          <div class="kb-chunk">
            <div class="kb-chunk-label">${escHtmlSimple(r.source_label || "")}</div>
            <div>${escHtmlSimple((r.text || "").slice(0, 200))}${(r.text || "").length > 200 ? "…" : ""}</div>
          </div>
        `).join("");
      }
    } catch (e) {
      $("kb-search-results").innerHTML = `<div style="color:var(--danger);font-size:11px">Error: ${e.message}</div>`;
    }
  });

  $("kb-search-query").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("btn-kb-search").click();
  });

  $("btn-kp-refresh-kb").addEventListener("click", () => loadKnowledgePanel());

  // ── Profile panel ──────────────────────────────────────────────────────────
  async function loadProfilePanel() {
    const path = _kbProjectPath();
    try {
      const res = await fetch(`/profile?project_path=${encodeURIComponent(path)}`);
      const data = await res.json();
      renderProfileDisplay(data);
    } catch (_) {
      // No profile yet
    }
  }

  function renderProfileDisplay(profile) {
    const div = $("profile-display");
    if (!profile || (!profile.project_name && !profile.tech_stack?.length)) {
      div.innerHTML = '<div class="profile-empty">No profile set. Click Detect or fill in fields.</div>';
      return;
    }
    const rows = [];
    if (profile.project_name) rows.push(`<div class="pf-row"><span class="pf-key">Name:</span> ${escHtmlSimple(profile.project_name)}</div>`);
    if (profile.tech_stack?.length) rows.push(`<div class="pf-row"><span class="pf-key">Stack:</span> ${escHtmlSimple(profile.tech_stack.join(", "))}</div>`);
    if (profile.llm_backend) rows.push(`<div class="pf-row"><span class="pf-key">LLM:</span> ${escHtmlSimple(profile.llm_backend)}</div>`);
    if (profile.coding_standards) rows.push(`<div class="pf-row"><span class="pf-key">Standards:</span> ${escHtmlSimple(profile.coding_standards)}</div>`);
    div.innerHTML = rows.join("");
    // Populate edit fields
    if (profile.project_name) $("profile-name").value = profile.project_name;
    if (profile.description) $("profile-desc").value = profile.description;
    if (profile.tech_stack?.length) $("profile-stack").value = profile.tech_stack.join(", ");
    if (profile.ai_persona) $("profile-persona").value = profile.ai_persona;
    if (profile.coding_standards) $("profile-standards").value = profile.coding_standards;
  }

  $("btn-profile-detect").addEventListener("click", async () => {
    const path = _kbProjectPath() || "workspace";
    $("btn-profile-detect").textContent = "⟳ Detecting…";
    try {
      const res = await fetch(`/profile/detect?project_path=${encodeURIComponent(path)}`);
      const data = await res.json();
      if (data.detected) {
        $("profile-stack").value = (data.tech_stack || []).join(", ");
        if (data.ai_persona) $("profile-persona").value = data.ai_persona;
        appendOutput(`✅ Detected: ${(data.tech_stack || []).join(", ")}\n`);
      } else {
        appendOutput("ℹ Could not auto-detect tech stack for this path.\n");
      }
    } catch (e) {
      appendOutput(`Profile detect error: ${e.message}\n`);
    } finally {
      $("btn-profile-detect").textContent = "⚙ Detect";
    }
  });

  $("btn-profile-save").addEventListener("click", async () => {
    const path = _kbProjectPath();
    const stack = $("profile-stack").value.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      const res = await fetch("/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_path: path,
          project_name: $("profile-name").value.trim(),
          description: $("profile-desc").value.trim(),
          tech_stack: stack,
          ai_persona: $("profile-persona").value.trim(),
          coding_standards: $("profile-standards").value.trim(),
        }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      appendOutput("✅ Profile saved.\n");
      loadProfilePanel();
    } catch (e) {
      appendOutput(`Profile save error: ${e.message}\n`);
    }
  });

  // ── Rules panel ────────────────────────────────────────────────────────────
  async function loadRulesPanel() {
    const path = _kbProjectPath();
    try {
      const res = await fetch(`/rules?project_path=${encodeURIComponent(path)}`);
      const data = await res.json();
      renderRulesList(data.rules || []);
    } catch (_) {
      $("rules-list").innerHTML = "";
    }
  }

  function renderRulesList(rules) {
    const list = $("rules-list");
    if (!rules.length) {
      list.innerHTML = '<div style="color:var(--text-dim);font-size:11px;font-style:italic">No rules yet.</div>';
      return;
    }
    list.innerHTML = rules.map((r) => `
      <div class="rule-item">
        <span class="rule-type rule-type-${r.rule_type}">${r.rule_type.replace("_", " ")}</span>
        <span class="rule-text">${escHtmlSimple(r.rule)}</span>
        <button data-rule-id="${escHtmlSimple(r.id)}" title="Remove rule">✕</button>
      </div>
    `).join("");
    list.querySelectorAll("button[data-rule-id]").forEach((btn) => {
      btn.addEventListener("click", () => removeRule(btn.dataset.ruleId));
    });
  }

  $("btn-rules-add").addEventListener("click", async () => {
    const text = $("rules-add-text").value.trim();
    const type = $("rules-type-select").value;
    if (!text) return;
    const path = _kbProjectPath();
    try {
      await fetch("/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rule: text, rule_type: type, project_path: path }),
      });
      $("rules-add-text").value = "";
      loadRulesPanel();
    } catch (e) {
      appendOutput(`Add rule error: ${e.message}\n`);
    }
  });

  $("rules-add-text").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("btn-rules-add").click();
  });

  async function removeRule(ruleId) {
    const path = _kbProjectPath();
    try {
      await fetch(`/rules/${encodeURIComponent(ruleId)}?project_path=${encodeURIComponent(path)}`, { method: "DELETE" });
      loadRulesPanel();
    } catch (e) {
      appendOutput(`Remove rule error: ${e.message}\n`);
    }
  }

  // ── Roadmap sidebar panel ─────────────────────────────────────────────────
  async function loadRoadmapSidebar() {
    const container = $("roadmap-sidebar-content");
    container.innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:4px">Loading…</div>';
    try {
      const res = await fetch("/roadmap");
      const data = await res.json();
      const statusIcon = { done: "✅", in_progress: "🔄", pending: "⬜", blocked: "🚫" };
      let html = "";
      for (const m of (data.milestones || [])) {
        if (m.status === "done") continue; // hide completed milestones from sidebar
        const tasks = (m.tasks || []).filter((t) => t.status !== "done");
        if (!tasks.length) continue;
        html += `<div class="rsb-milestone">
          <div class="rsb-ms-title">${escHtmlSimple(m.title)}</div>
          ${tasks.map((t) => `
            <div class="rsb-task" data-task-id="${t.id}" data-task-title="${encodeURIComponent(t.title)}" data-task-desc="${encodeURIComponent(t.description || "")}">
              <span class="rsb-status">${statusIcon[t.status] || "⬜"}</span>
              <span class="rsb-title">${escHtmlSimple(t.title)}</span>
            </div>
          `).join("")}
        </div>`;
      }
      container.innerHTML = html || '<div style="color:var(--accent2);font-size:11px;padding:4px">🎉 All tasks complete!</div>';
      container.querySelectorAll(".rsb-task").forEach((el) => {
        el.addEventListener("click", () => {
          const title = decodeURIComponent(el.dataset.taskTitle || "");
          const desc = decodeURIComponent(el.dataset.taskDesc || "");
          _workOnTask(el.dataset.taskId, title, desc);
          switchOutputTab("output");
        });
      });
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  $("btn-roadmap-refresh-sb").addEventListener("click", () => loadRoadmapSidebar());

  $("btn-roadmap-work-next-sb").addEventListener("click", async () => {
    try {
      const res = await fetch("/roadmap/next");
      const data = await res.json();
      if (!data.task) { appendOutput("🎉 All roadmap tasks are complete!\n"); return; }
      _workOnTask(data.task.id, data.task.title, data.task.description || "");
      switchOutputTab("output");
    } catch (e) {
      appendOutput(`Error fetching next task: ${e.message}\n`);
    }
  });

  // ── Split editor ───────────────────────────────────────────────────────────
  let _splitEditor = null;
  let _splitFile = null;
  const _splitFiles = {}; // path → {content, language, model}

  function toggleSplitEditor() {
    const splitEl = $("editor-container-split");
    const btn = $("btn-split-editor");
    const active = !splitEl.classList.contains("hidden");
    if (active) {
      splitEl.classList.add("hidden");
      btn.classList.remove("active");
      if (_splitEditor) { _splitEditor.dispose(); _splitEditor = null; }
    } else {
      splitEl.classList.remove("hidden");
      btn.classList.add("active");
      if (state.editorMode === "monaco" && typeof monaco !== "undefined") {
        _splitEditor = monaco.editor.create($("editor-split-inner"), {
          theme: "swissagent-dark",
          fontSize: 14,
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          lineNumbers: "on",
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          automaticLayout: true,
          readOnly: false,
        });
      }
      renderSplitTabs();
    }
  }

  function renderSplitTabs() {
    const list = $("split-tabs-list");
    list.innerHTML = Object.keys(_splitFiles).map((path) => `
      <div class="split-tab ${_splitFile === path ? "active" : ""}" data-path="${escHtmlSimple(path)}">
        <span>${escHtmlSimple(path.split("/").pop())}</span>
        <span style="font-size:10px;opacity:.5;cursor:pointer;" data-close="${escHtmlSimple(path)}">✕</span>
      </div>
    `).join("");
    list.querySelectorAll(".split-tab").forEach((tab) => {
      tab.addEventListener("click", (e) => {
        if (e.target.dataset.close) {
          const p = e.target.dataset.close;
          delete _splitFiles[p];
          if (_splitFile === p) { _splitFile = Object.keys(_splitFiles)[0] || null; }
          renderSplitTabs();
          if (_splitFile) openSplitFile(_splitFile);
          return;
        }
        openSplitFile(tab.dataset.path);
      });
    });
  }

  async function openSplitFile(path) {
    const splitEl = $("editor-container-split");
    if (splitEl.classList.contains("hidden")) toggleSplitEditor();
    if (!_splitFiles[path]) {
      try {
        const res = await fetch(`/files/read?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        _splitFiles[path] = { content: data.content || "", language: data.language || "plaintext" };
      } catch (e) {
        appendOutput(`Split editor error: ${e.message}\n`);
        return;
      }
    }
    _splitFile = path;
    if (_splitEditor) {
      const lang = _splitFiles[path].language;
      _splitEditor.setValue(_splitFiles[path].content || "");
      if (typeof monaco !== "undefined") {
        monaco.editor.setModelLanguage(_splitEditor.getModel(), lang);
      }
    }
    renderSplitTabs();
  }

  $("btn-split-editor").addEventListener("click", () => toggleSplitEditor());

  // ── Boot ───────────────────────────────────────────────────────────────────
  initMonaco();
  _refreshProjectSwitcher();
  appendOutput("SwissAgent IDE ready. Open a file or type a prompt to get started.\n");
  appendOutput("Tip: Ctrl+P = file picker  |  Ctrl+Shift+P = command palette  |  Terminal tab = interactive shell\n");
  updateStatusBar();
})();
