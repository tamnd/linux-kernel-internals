# The bridge protocol

What the page has to give Python so that a lesson cell can drive the kernel running in it.

Four calls. Everything a lesson does is a shell line, a file read, a file write or a module load, because those four are what the kernel already exposes to a shell, and because a protocol small enough to hold in your head is a protocol somebody else can reimplement.

## The object

The worker Python runs in puts one object on its global scope, called `kxbox`. Python finds it through Pyodide's `js` module, and when it is not there the session falls back to a recording and says so in its banner.

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

Blocking is the only way to get that, and only a worker is allowed to block, so Python runs in a worker and v86 runs on the page. That is the opposite of the arrangement this document described before the JavaScript was written, and the correction is what writing it turned up: `Atomics.wait` throws on a page's main thread no matter how the page is served, so putting the emulator in the worker and Python on the page cannot work at all. It is the same shape JupyterLite uses to make `input()` work.

The request goes to the page as an ordinary message, which is queued before the worker goes to sleep and so arrives while it is sleeping. The answer comes back through a `SharedArrayBuffer`, because a sleeping worker cannot receive a message. A useful `SharedArrayBuffer` needs the page to be cross origin isolated, which means two response headers:

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

GitHub Pages cannot set headers, so the interactive Tier 0 page needs somewhere that can, or a service worker that adds them to its own responses. That decision is not made yet. It does not block the lessons, because every lesson also runs from the recording, which is the path this repository tests. `kxbox/web/serve.py` sets both headers, so the page can be run locally while the question is open.

The buffer is a fixed size and a trace is not, so an answer that does not fit comes back in pieces, with the worker asking for the rest until there is none. The alternative was a buffer big enough for the largest trace anybody ever takes, chosen by guessing, and a silent truncation the day the guess is wrong.

## How the four calls reach the kernel

There is no system call interface from JavaScript into v86. There is a byte stream in, a byte stream out, and a shell at the far end. So every call becomes a line of shell, and the real work is knowing when the line finished and what it printed.

Each command is wrapped in three markers carrying the id of the call. Everything before the first marker is the prompt and the echo of what we typed, and gets dropped. Between the first and the second is what the command printed. Between the second and the third is its standard error, which was parked in a file while it ran, because both streams share one serial line and interleaving them would be a lie about which came out of which. The last marker carries the exit status, and its arrival is what says the command is over.

There is one shell, so there is one command at a time and requests queue. Every command has a deadline, because a guest that has wedged looks exactly like a guest that is being slow, and a cell that never returns tells the reader nothing about which of the two happened.

A file is written by staging base64, decoding it into a scratch file, and copying that into the target with `cat`. Base64 because the text is sometimes a list of function names with newlines in it and shell quoting is the wrong thing to debug from inside a browser. The target is written by one command because writing to `current_tracer` twice is two writes, and the kernel reads each one separately.

The scratch file in the middle looks like one step too many and it is not. Decoding straight into a tracer file silently does nothing. Busybox base64 writes its output with `writev`, the tracer's write handler answers `EINVAL` to that, and base64 exits 0 anyway, so the tracer keeps its old value and every check says the write worked. That was traced inside the box with the syscall events on, which is why it is written down here as a fact rather than a suspicion. `cat` writes with an ordinary `write`, and one call is what the file wants.

## Errors

A call that fails throws on the JavaScript side, and the Python side turns that into an exception with the guest's message in it. A shell line that exits non zero is not a failure: it comes back as a `Command` with a non zero `status`, because a lesson about error paths needs to see the error rather than catch an exception about it.

## What a tape is made of

There is no `trace` call in the protocol, on purpose. Tracing is four writes, a read and a parse, and the sequence lives in Python where it can be read and changed. `kxbox/bridge.py` does it in the same order `kxray.tracefs` does on a real machine, including putting the tracer back afterwards, because a lesson that left `function_graph` on would slow every later cell down and the reader would blame the wrong thing.

## The state of it

All four calls have been run against a real kernel. v86 is vendored, the pinned 7.2.2 image is built, the rootfs is built, and `node kxbox/web/headless.js smoke` boots the box and exercises `sh`, `read`, `write` and the tracing path end to end. `RESULTS.md` in `kernel/` has the numbers.

Running it is what found the `writev` bug above, and a second one where every read came back with an extra newline on the end. Both were in code that had passing tests. In both cases the thing that was wrong was the test double, which had been written to match what the protocol was supposed to do rather than what a shell actually does. The doubles now match the real guest and the tests fail if they drift again.

Both halves are still tested without an emulator, because that is what runs in CI on every push. The Python half is driven through a stand in that implements the four calls. The JavaScript half is driven through a guest that answers like a shell, and the blocking call is driven across two real threads.

What is still open is the browser. A headless boot under node settles whether the kernel boots at all. It does not settle how long a reader waits in a tab, which is what the kill criterion asks about.
