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

`checks.js` is the list of things a lesson stops working without, and it is one list rather than two because a check that passes under node and is never run in a tab is a check for the wrong machine.

`harness.js` is what the page does: boot, time it, run the checks, wait for Python, run every recipe both ways, take one trace for the picture, and leave everything it learned on `window.kxResults`.

`both-ways.py` is the comparison. It runs each recipe in the corpus against the live kernel and against its recording and says whether the two agree, which is the one M0 criterion that cannot be checked anywhere but here. Off a page there is no emulator to find, so both halves come back as the recording and every recipe matches itself, which reads as a pass and is not one. `kxbox/bothways.py` is the part of it that is not about the page, and it is where the decision about what counts as agreement lives. That decision took seven attempts and every one of them was a real defect found by running this, so the reasons are written next to the lists rather than summarised here.

`first-tape.py` is the picture: one trace, real Python that a lesson could contain rather than a demo written for this page. It runs after the comparison, so it has to trace a recipe that gives the same answer on a guest that has already been used. Which ones do is written down as `repeatable` in the recipe list.

`measure.js` runs the whole of that in Chrome and prints the numbers. It drives the browser over the DevTools protocol directly rather than through a driver library, which is one fewer thing to pin for about eighty lines of code. `just web-measure` is the short way to run it.

`headless.js` boots the same kernel under node instead of on a page. There is no worker and no shared buffer in it, because nothing is blocking on that side and it is allowed to await. Everything below that, which is the part that talks to the kernel, is the same code the page runs.

`vendor.toml` pins v86 by commit and by sha256 of every file taken from it. `python3 -m tools.vendor` fetches them and `--check` says whether what is on disk is what the pin asked for. The vendored files are not committed.

## The state of it

It boots. `node kxbox/web/headless.js smoke` starts the pinned kernel, waits for the ready marker, and runs nine checks, each one named after something a lesson stops working without.

Running it found two bugs that the tests had been passing over. A write to any tracefs file did nothing and reported success, and every read came back with one extra newline. Both bugs were in code with tests, and in both cases the test double was the thing that was wrong: it had been written to match the protocol as designed rather than what a busybox shell on a serial line actually does. The doubles now match the real guest, and there are tests that fail if they drift apart again.

Everything that can be checked without an emulator still is, because that is what runs in CI. `just web` runs it. Forty one tests, and the useful ones are the parsing of a serial stream that contains the prompt and the echo of the command, a write arriving in pieces and ending up as one file, two commands not interleaving on the one shell, and a blocking call across two real threads with the answer deliberately late.

It also runs in a browser now, which is what M0 was actually asking. `just web-measure` boots the pinned kernel in Chrome on a throwaway profile, runs the same ten checks, brings Pyodide up in the worker, runs every recipe against its recording, and takes one filtered trace all the way through the bridge and back. A shell in about two and a half seconds on an idle laptop, ten checks passing, three of three recipes agreeing in about seventeen seconds, and forty one frames of a real tape drawn by the same widget a notebook would use. The numbers and the surprises are in `../kernel/RESULTS.md`.

Two surprises are worth repeating here. A visible window is about three times slower than a headless one, and almost all of that is sensitivity to what else the machine is doing rather than a fixed cost. Headless boots in 2.2 seconds whether the laptop is idle or has several compiler jobs on it. Visible goes from 2.6 seconds to between 6.4 and 9.1. Every node number this project quoted before is therefore optimistic about what a reader waits for, and none of them was wrong about whether it works.

The second one is that the page itself was most of the cost. The comparison took 196 seconds the first time it passed, and 14 seconds after `harness.js` stopped appending to the console element once per byte and reading `scrollHeight` once per byte. Both of those are cheap on their own and neither is cheap a hundred thousand times against an element holding hundreds of kilobytes, and the emulator shares a thread with all of it. It looked like the guest getting slower until commands went past their deadline, which is the misleading part: the twenty second deadline in `host.js` was doing its job on a guest that was fine. It also cost this project a wrong conclusion for a while, because the visible window number it produced got written down as the compositor slowing the emulator, and it was not.

## What the guest needs

A busybox shell on `ttyS0` with `base64`, `cat` and `printf`, `/sys/kernel/tracing` mounted, and a line reading `__kx:READY` printed once the shell is up. The page waits for that line rather than for a prompt, because a prompt is whatever the rootfs decided and the marker is a fact we control.
