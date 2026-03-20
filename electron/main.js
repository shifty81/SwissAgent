/**
 * SwissAgent Desktop — Electron main process
 *
 * Startup flow:
 *   1. Launches the SwissAgent FastAPI backend
 *   2. Shows a small loading splash while the backend boots
 *   3. Once the backend is healthy, shows the Launcher window
 *   4. From the Launcher the user picks New Project / Open / Brainstorm / IDE
 *   5. The main IDE BrowserWindow opens on user action
 *   6. System-tray icon keeps the app alive when windows are closed
 *   7. On quit, terminates the backend process
 */

'use strict';

const { app, BrowserWindow, Tray, Menu, nativeImage, shell, dialog, ipcMain } = require('electron');
const path  = require('path');
const http  = require('http');
const { spawn } = require('child_process');

// ── Config ──────────────────────────────────────────────────────────────────
const BACKEND_PORT   = 8000;
const BACKEND_URL    = `http://localhost:${BACKEND_PORT}`;
const HEALTH_URL     = `${BACKEND_URL}/health`;
const HEALTH_RETRIES = 30;
const LAUNCHER_W     = 720;
const LAUNCHER_H     = 480;
const WINDOW_W       = 1440;
const WINDOW_H       = 920;

// ── State ────────────────────────────────────────────────────────────────────
let mainWindow     = null;
let launcherWindow = null;
let tray           = null;
let backendProc    = null;

// ── Helpers ──────────────────────────────────────────────────────────────────
function projectRoot() {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'backend')
    : path.join(__dirname, '..');
}

function pythonExe() {
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
    if (res.statusCode === 200) { console.log('[electron] backend ready'); resolve(); }
    else { setTimeout(() => waitForBackend(attempt + 1, resolve, reject), 1000); }
  }).on('error', () => {
    setTimeout(() => waitForBackend(attempt + 1, resolve, reject), 1000);
  });
}

// ── Launcher window ───────────────────────────────────────────────────────────
function createLauncher() {
  launcherWindow = new BrowserWindow({
    width: LAUNCHER_W,
    height: LAUNCHER_H,
    title: 'SwissAgent',
    backgroundColor: '#1e1e2e',
    resizable: false,
    frame: false,
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
      sandbox:          false,   // needed so preload can use __dirname
    },
  });

  launcherWindow.loadFile(path.join(__dirname, 'launcher.html'));

  launcherWindow.on('closed', () => { launcherWindow = null; });
}

// ── Main IDE window ───────────────────────────────────────────────────────────
function createIDEWindow(url) {
  // Close launcher if still open
  if (launcherWindow) { launcherWindow.close(); launcherWindow = null; }

  if (mainWindow) { mainWindow.show(); mainWindow.focus(); mainWindow.loadURL(url); return; }

  mainWindow = new BrowserWindow({
    width: WINDOW_W,
    height: WINDOW_H,
    title: 'SwissAgent',
    backgroundColor: '#1e1e2e',
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
      sandbox:          false,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url: u }) => {
    shell.openExternal(u);
    return { action: 'deny' };
  });

  mainWindow.on('close', (ev) => {
    if (tray) { ev.preventDefault(); mainWindow.hide(); }
  });

  mainWindow.on('closed', () => { mainWindow = null; });

  mainWindow.loadURL(url);
}

// ── Tray ──────────────────────────────────────────────────────────────────────
function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'icon.png');
  const icon = nativeImage.createFromPath(iconPath).isEmpty()
    ? nativeImage.createEmpty()
    : nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });

  tray = new Tray(icon);
  tray.setToolTip('SwissAgent');
  tray.setContextMenu(Menu.buildFromTemplate([
    {
      label: 'Show Launcher',
      click: () => {
        if (launcherWindow) { launcherWindow.show(); launcherWindow.focus(); }
        else createLauncher();
      },
    },
    {
      label: 'Open IDE',
      click: () => {
        if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
        else createIDEWindow(BACKEND_URL);
      },
    },
    { label: 'Open in Browser', click: () => shell.openExternal(BACKEND_URL) },
    { type: 'separator' },
    { label: 'Quit', click: () => { tray = null; app.quit(); } },
  ]));
  tray.on('double-click', () => {
    const w = mainWindow || launcherWindow;
    if (w) { w.show(); w.focus(); }
  });
}

// ── IPC handlers (called from preload/renderer) ───────────────────────────────
ipcMain.handle('launcher:openIDE', (_event, url) => {
  createIDEWindow(url || BACKEND_URL);
});

ipcMain.handle('launcher:close', () => {
  if (launcherWindow) launcherWindow.close();
});

ipcMain.handle('launcher:pickFolder', async () => {
  const result = await dialog.showOpenDialog({
    title: 'Open Project Folder',
    properties: ['openDirectory'],
  });
  if (result.canceled || !result.filePaths.length) return null;
  const p = result.filePaths[0];
  return { path: p, name: path.basename(p) };
});

ipcMain.on('app:quit',     () => { tray = null; app.quit(); });
ipcMain.on('app:minimize', (e) => { BrowserWindow.fromWebContents(e.sender)?.minimize(); });
ipcMain.on('app:maximize', (e) => {
  const w = BrowserWindow.fromWebContents(e.sender);
  if (w) { w.isMaximized() ? w.unmaximize() : w.maximize(); }
});

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  startBackend();

  // Splash while backend boots
  const splash = new BrowserWindow({
    width: 360, height: 240,
    title: 'SwissAgent — Starting…',
    backgroundColor: '#1e1e2e',
    resizable: false,
    frame: false,
    webPreferences: { contextIsolation: true },
  });
  splash.loadURL(`data:text/html,
    <html><body style="background:#1e1e2e;color:#cdd6f4;font-family:sans-serif;
      display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
      <div style="text-align:center">
        <div style="font-size:44px;margin-bottom:12px">🛠️</div>
        <div style="font-size:18px;font-weight:700;color:#7c6af7">SwissAgent</div>
        <div style="margin-top:8px;font-size:12px;color:#7f849c">Starting backend…</div>
      </div>
    </body></html>`);

  try {
    await new Promise((resolve, reject) => waitForBackend(0, resolve, reject));
  } catch (err) {
    dialog.showErrorBox('SwissAgent — Startup Error',
      `Could not start the backend server.\n\n${err.message}`);
    app.quit();
    return;
  }

  splash.close();
  createLauncher();
  createTray();

  app.on('activate', () => {
    if (!launcherWindow && !mainWindow) createLauncher();
    else {
      const w = launcherWindow || mainWindow;
      if (w) { w.show(); w.focus(); }
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin' && !tray) app.quit();
});

app.on('before-quit', stopBackend);

