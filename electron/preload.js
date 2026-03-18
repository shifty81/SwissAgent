/**
 * SwissAgent Desktop — Electron preload script
 *
 * Runs in the renderer process with contextIsolation enabled.
 * Exposes a minimal safe API to the web page via contextBridge.
 */

'use strict';

const { contextBridge, ipcRenderer } = require('electron');

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
