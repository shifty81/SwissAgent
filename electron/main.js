/**
 * SwissAgent Desktop — Electron main process (t10-3)
 *
 * Wraps the SwissAgent web IDE as a native desktop application.
 * On startup it:
 *   1. Launches the SwissAgent FastAPI backend (python -m uvicorn …)
 *   2. Waits until the server is ready (health-check loop)
 *   3. Opens a BrowserWindow pointing at http://localhost:8000
 *   4. Shows a system-tray icon so the app can be minimised to tray
 *   5. On quit, terminates the backend process
 */

'use strict';

const { app, BrowserWindow, Tray, Menu, nativeImage, shell, dialog } = require('electron');
const path  = require('path');
const http  = require('http');
const { spawn } = require('child_process');

// ── Config ──────────────────────────────────────────────────────────────────
const BACKEND_PORT   = 8000;
const BACKEND_URL    = `http://localhost:${BACKEND_PORT}`;
const HEALTH_URL     = `${BACKEND_URL}/health`;
const HEALTH_RETRIES = 30;   // max attempts × 1 s interval = 30 s timeout
const WINDOW_W       = 1400;
const WINDOW_H       = 900;

// ── State ────────────────────────────────────────────────────────────────────
let mainWindow   = null;
let tray         = null;
let backendProc  = null;
let serverReady  = false;

// ── Helpers ──────────────────────────────────────────────────────────────────
function projectRoot() {
  // When packaged the backend lives next to the app; in dev it's two levels up.
  return app.isPackaged
    ? path.join(process.resourcesPath, 'backend')
    : path.join(__dirname, '..');
}

function pythonExe() {
  // Respect SWISSAGENT_PYTHON env var; fall back to common names.
  return process.env.SWISSAGENT_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
}

// ── Backend lifecycle ─────────────────────────────────────────────────────────
function startBackend() {
  const cwd = projectRoot();
  const py  = pythonExe();
  console.log(`[electron] starting backend: ${py} in ${cwd}`);

  backendProc = spawn(
    py,
    ['-m', 'uvicorn', 'core.api_server:create_app', '--factory',
     '--host', '127.0.0.1', '--port', String(BACKEND_PORT)],
    { cwd, env: { ...process.env }, stdio: ['ignore', 'pipe', 'pipe'] }
  );

  backendProc.stdout.on('data', d => process.stdout.write(`[backend] ${d}`));
  backendProc.stderr.on('data', d => process.stderr.write(`[backend] ${d}`));
  backendProc.on('error', (err) => {
    console.error(`[electron] failed to start backend: ${err.message}`);
    dialog.showErrorBox('SwissAgent — Startup Error',
      `Could not launch the Python backend.\n\n${err.message}\n\n` +
      `Make sure Python 3.10+ is installed and accessible as "${pythonExe()}".`);
    app.quit();
  });
  backendProc.on('exit', (code) => {
    console.log(`[electron] backend exited with code ${code}`);
    backendProc = null;
  });
}

function stopBackend() {
  if (backendProc) {
    console.log('[electron] stopping backend…');
    backendProc.kill();
    backendProc = null;
  }
}

function waitForBackend(attempt, resolve, reject) {
  if (attempt >= HEALTH_RETRIES) {
    return reject(new Error(`Backend did not start after ${HEALTH_RETRIES} s`));
  }
  http.get(HEALTH_URL, (res) => {
    if (res.statusCode === 200) {
      console.log('[electron] backend ready');
      resolve();
    } else {
      setTimeout(() => waitForBackend(attempt + 1, resolve, reject), 1000);
    }
  }).on('error', () => {
    setTimeout(() => waitForBackend(attempt + 1, resolve, reject), 1000);
  });
}

// ── Window ────────────────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width:           WINDOW_W,
    height:          WINDOW_H,
    title:           'SwissAgent',
    backgroundColor: '#1e1e1e',
    webPreferences:  {
      preload:            path.join(__dirname, 'preload.js'),
      contextIsolation:   true,
      nodeIntegration:    false,
      sandbox:            true,
    },
  });

  // Open external links in the system browser instead of Electron.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('close', (ev) => {
    if (tray) {
      ev.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.loadURL(BACKEND_URL);
}

// ── Tray ──────────────────────────────────────────────────────────────────────
function createTray() {
  // Use a blank 16×16 icon if the real icon is not present.
  const iconPath = path.join(__dirname, 'assets', 'icon.png');
  const icon = nativeImage.createFromPath(iconPath).isEmpty()
    ? nativeImage.createEmpty()
    : nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });

  tray = new Tray(icon);
  tray.setToolTip('SwissAgent');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show SwissAgent', click: () => { mainWindow.show(); mainWindow.focus(); } },
    { label: 'Open in Browser', click: () => shell.openExternal(BACKEND_URL) },
    { type: 'separator' },
    { label: 'Quit', click: () => { tray = null; app.quit(); } },
  ]));
  tray.on('double-click', () => { mainWindow.show(); mainWindow.focus(); });
}

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  startBackend();

  // Show a loading window while we wait for the backend.
  mainWindow = new BrowserWindow({
    width: 480, height: 300,
    title: 'SwissAgent — Starting…',
    backgroundColor: '#1e1e1e',
    resizable: false,
    frame: false,
    webPreferences: { contextIsolation: true },
  });
  mainWindow.loadURL(`data:text/html,
    <html><body style="background:#1e1e1e;color:#ccc;font-family:sans-serif;
      display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
      <div style="text-align:center">
        <div style="font-size:48px;margin-bottom:16px">🛠️</div>
        <div style="font-size:20px;font-weight:bold;color:#4fc3f7">SwissAgent</div>
        <div style="margin-top:8px;color:#888">Starting backend…</div>
      </div>
    </body></html>`);

  try {
    await new Promise((resolve, reject) => waitForBackend(0, resolve, reject));
  } catch (err) {
    dialog.showErrorBox('SwissAgent — Startup Error',
      `Could not start the backend server.\n\n${err.message}\n\n` +
      `Make sure Python 3.10+ and uvicorn are installed, then try again.`);
    app.quit();
    return;
  }

  mainWindow.close();
  mainWindow = null;
  createWindow();
  createTray();

  app.on('activate', () => {
    if (mainWindow === null) createWindow();
    else { mainWindow.show(); mainWindow.focus(); }
  });
});

app.on('window-all-closed', () => {
  // On macOS keep app running in tray; on other platforms quit.
  if (process.platform !== 'darwin' && !tray) app.quit();
});

app.on('before-quit', stopBackend);
