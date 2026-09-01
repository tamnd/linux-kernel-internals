# The browser half of Tier 0

The kernel runs on the page. Python runs in a worker. This is what carries a call from one to the other and an answer back.

`PROTOCOL.md` one directory up is the contract. This file is about how it is built and what state it is in.

## Which side is which, and why it is that way round

Python has to block, because a lesson cell that says `await` in front of every line is a lesson about promises rather than about the kernel. Only a worker is allowed to block, so Python is the worker and the emulator is on the page.

That is the opposite of what `PROTOCOL.md` said before any of this was written, and the correction came out of writing it. `Atomics.wait` throws on the main thread whatever headers the page was served with, so the arrangement that reads more naturally does not work at all.

A request goes to the page as a message, which is queued before the worker goes to sleep and so arrives while it is sleeping. The answer comes back through a shared buffer, because a sleeping worker cannot receive a message. An answer too long for the buffer comes back in pieces.

## The files

`channel.js` is the shared buffer and the blocking call, and it is the only file that knows there are two threads.

`guest.js` builds a line of shell and reads the answer back out of the serial stream. No emulator, no state, so all of it is testable.

`host.js` is the page side: it queues commands onto the one shell, gives each of them a deadline, and turns a request into an answer. The emulator reaches it as an object with `send` and `listen`, which is why the tests can hand it something else.

`kxbox.js` is what the worker puts on its global scope, and it is the object `kxbox/bridge.py` goes looking for.

`page.js`, `worker.js` and `index.html` are the wiring. `serve.py` serves this directory with the two headers a blocking worker needs, which `python3 -m http.server` does not send.

## The state of it

No kernel has been booted. v86 is not vendored, the kernel image is not built, and there is no rootfs, so the page has nothing to start and says so when you open it.

Everything that could be checked without an emulator is checked. `just web` runs it. Forty tests, and the useful ones are the parsing of a serial stream that contains the prompt and the echo of the command, a write arriving in pieces and ending up as one file, two commands not interleaving on the one shell, and a blocking call across two real threads with the answer deliberately late.

Node's worker threads are not a browser. What they share with one is `Atomics.wait`, `SharedArrayBuffer` and `postMessage`, which is the part of this that is ours.

## What the guest needs

A busybox shell on `ttyS0` with `base64`, `cat` and `printf`, `/sys/kernel/tracing` mounted, and a line reading `__kx:READY` printed once the shell is up. The page waits for that line rather than for a prompt, because a prompt is whatever the rootfs decided and the marker is a fact we control.
