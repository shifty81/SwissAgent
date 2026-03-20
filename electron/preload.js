/**
 * SwissAgent Desktop — Electron preload script
 *
 * Runs in the renderer process with contextIsolation enabled.
 * Exposes a minimal safe API to the web page via contextBridge.
 */

'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// ── IDE window bridge (used in the main IDE web app) ─────────────────────────
contextBridge.exposeInMainWorld('swissagentDesktop', {
  /** True when running inside the Electron wrapper. */
  isDesktop: true,

  /** Emit an event to the main process. */
  send: (channel, data) => {
    const allowed = ['app:quit', 'app:minimize', 'app:maximize'];
    if (allowed.includes(channel)) ipcRenderer.send(channel, data);
  },

  /** Listen for events from the main process. */
  on: (channel, callback) => {
    const allowed = ['app:update-available'];
    if (allowed.includes(channel)) {
      ipcRenderer.on(channel, (_event, ...args) => callback(...args));
    }
  },
});

// ── Launcher window bridge ────────────────────────────────────────────────────
contextBridge.exposeInMainWorld('swissagentLauncher', {
  /**
   * Ask the main process to open the IDE window at the given URL.
   * @param {string} url
   */
  openIDE: (url) => ipcRenderer.invoke('launcher:openIDE', url),

  /** Close the launcher window. */
  close: () => ipcRenderer.invoke('launcher:close'),

  /**
   * Show a native folder-picker dialog.
   * @returns {Promise<{path: string, name: string} | null>}
   */
  pickFolder: () => ipcRenderer.invoke('launcher:pickFolder'),
});
