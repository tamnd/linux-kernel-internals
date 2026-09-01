// What the worker puts on its global scope, so that Python can find it.
//
// `kxbox/bridge.py` looks for exactly this object, under exactly this name, through Pyodide's `js`
// module. The four methods return plain objects, which Pyodide hands to Python as something whose
// attributes are the properties, which is why the Python side reads `reply.status` rather than
// `reply["status"]`.
//
// Every method here blocks. That is the point of the whole arrangement, and it is legal because
// this runs in a worker.

import { Caller, MORE } from "./channel.js";

export const GLOBAL = "kxbox";

export function bridge(channel, send) {
  const caller = new Caller(channel, send);
  return {
    sh: (line) => caller.call("sh", [line]),
    read: (path) => caller.call("read", [path]),
    write: (path, text) => {
      caller.call("write", [path, text]);
    },
    insmod: (path) => caller.call("insmod", [path]),
  };
}

export function install(channel, send, target = globalThis) {
  target[GLOBAL] = bridge(channel, send);
  return target[GLOBAL];
}

// The worker's own entry point. The page sends it the shared buffer once, at the start, and after
// that every message going the other way is a request. Kept out of `install` so the tests can
// drive `install` with a function instead of a port.
export function listen(scope = globalThis) {
  scope.addEventListener("message", (event) => {
    const { channel } = event.data || {};
    if (channel) install(channel, (request) => scope.postMessage(request), scope);
  });
}

export { MORE };
