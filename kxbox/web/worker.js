// The worker: Pyodide, the project's own package, and the bridge object Python looks for.
//
// This is the side that is allowed to block, which is the reason Python is here and the emulator
// is not. The bridge itself is in `kxbox.js`, so this file is the part that would change if the
// page ever loaded Python some other way.
//
// Three messages go each way and no more. The page sends the shared buffer once to start, then a
// numbered cell of code whenever it wants something run. The worker sends back news about itself,
// numbered answers, and protocol requests, and the page tells them apart by looking for a `call`.

import { install } from "./kxbox.js";

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.28.0/full/";

// The project as a wheel, built by `just web-wheel` and served from the same origin as this file.
// A wheel rather than a copy of the source tree, because `micropip` already knows how to unpack
// one into the right place, and because a wheel carries the version that produced it.
const WHEEL = "build/linux_kernel_internals-0.0.0-py3-none-any.whl";

let python = null;

async function boot(channel) {
  install(channel, (request) => self.postMessage(request), self);

  const { loadPyodide } = await import(`${PYODIDE}pyodide.mjs`);
  python = await loadPyodide({ indexURL: PYODIDE });

  await python.loadPackage("micropip");
  const micropip = python.pyimport("micropip");
  await micropip.install(new URL(WHEEL, self.location.href).href);

  return python.runPythonAsync("import sys, kxray; sys.version.split()[0]");
}

self.addEventListener("message", async (event) => {
  const message = event.data || {};

  if (message.channel) {
    try {
      const version = await boot(message.channel);
      self.postMessage({ ready: true, version: String(version) });
    } catch (error) {
      // Almost always one of two things: no network for the Pyodide CDN, or the wheel not built.
      // Both are worth saying out loud, because from the page they look identical.
      self.postMessage({ ready: false, error: String(error && error.message ? error.message : error) });
    }
    return;
  }

  if (message.code) {
    if (!python) {
      self.postMessage({ cell: message.cell, error: "Python is not up yet" });
      return;
    }
    try {
      const value = await python.runPythonAsync(message.code);
      self.postMessage({ cell: message.cell, value: String(value ?? "") });
    } catch (error) {
      self.postMessage({ cell: message.cell, error: String(error) });
    }
  }
});
