# The bridge protocol

What the page has to give Python so that a lesson cell can drive the kernel running in it.

Four calls. Everything a lesson does is a shell line, a file read, a file write or a module load, because those four are what the kernel already exposes to a shell, and because a protocol small enough to hold in your head is a protocol somebody else can reimplement.

## The object

The page puts one object on the JavaScript global, called `kxbox`. Python finds it through Pyodide's `js` module, and when it is not there the session falls back to a recording and says so in its banner.

```js
globalThis.kxbox = {
  sh(line) { ... },            // returns { status, stdout, stderr }
  read(path) { ... },          // returns a string
  write(path, text) { ... },   // returns nothing, throws on failure
  insmod(path) { ... },        // returns { status, stdout, stderr }
}
```

`sh` runs one line in the guest's shell and waits for it to finish. `read` and `write` are file operations inside the guest, which is how everything under `/proc` and `/sys/kernel/tracing` is reached. `insmod` loads a module and is separate from `sh` only because the failure modes are worth reporting differently.

## The calls are synchronous

This is the part that constrains where the book can be hosted, so it is written down here rather than found out later.

A lesson cell that says `await` in front of every line is a lesson about promises. Reading a trace is hard enough without that, so `box.sh(...)` returns a result rather than a promise.

v86 runs in a Web Worker and the Python side blocks on `Atomics.wait` against a `SharedArrayBuffer` until the worker replies. That is the same technique JupyterLite uses to make `input()` work, and it needs the page to be cross origin isolated, which means two response headers:

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

GitHub Pages cannot set headers, so the interactive Tier 0 page needs somewhere that can, or a service worker that adds them to its own responses. That decision is not made yet. It does not block the lessons, because every lesson also runs from the recording, which is the path this repository tests.

## Errors

A call that fails throws on the JavaScript side, and the Python side turns that into an exception with the guest's message in it. A shell line that exits non zero is not a failure: it comes back as a `Command` with a non zero `status`, because a lesson about error paths needs to see the error rather than catch an exception about it.

## What a tape is made of

There is no `trace` call in the protocol, on purpose. Tracing is four writes, a read and a parse, and the sequence lives in Python where it can be read and changed. `kxbox/bridge.py` does it in the same order `kxray.tracefs` does on a real machine, including putting the tracer back afterwards, because a lesson that left `function_graph` on would slow every later cell down and the reader would blame the wrong thing.

## The state of it

None of this has been run. The kernel is not built, the JavaScript half is not written, and the emulator has never been booted for this project. What exists is this document, the Python half in `kxbox/bridge.py`, and a stand in object in the tests that implements the four calls so the Python half is exercised.

That is on purpose. Writing the protocol down first is what makes it possible to argue about it before there is code depending on it.
