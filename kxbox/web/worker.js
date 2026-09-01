// The worker: Pyodide, and the bridge object Python looks for.
//
// This is the side that is allowed to block, which is the reason Python is here and the emulator
// is not. Everything it does is in `kxbox.js`, so this file is the part that would change if the
// page ever loaded Python some other way.
//
// Not run yet, for the same reason as page.js.

import { install } from "./kxbox.js";

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.28.0/full/";

let python = null;

self.addEventListener("message", async (event) => {
  const message = event.data || {};

  if (message.channel) {
    install(message.channel, (request) => self.postMessage(request), self);
    const { loadPyodide } = await import(`${PYODIDE}pyodide.mjs`);
    python = await loadPyodide({ indexURL: PYODIDE });
    self.postMessage({ ready: true });
    return;
  }

  if (message.code && python) {
    try {
      const value = await python.runPythonAsync(message.code);
      self.postMessage({ cell: message.cell, value: String(value ?? "") });
    } catch (error) {
      self.postMessage({ cell: message.cell, error: String(error) });
    }
  }
});
