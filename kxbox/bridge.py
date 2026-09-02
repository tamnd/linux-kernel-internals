"""The backend that talks to a real kernel running under v86.

v86 is an x86 emulator compiled to WebAssembly, so the kernel is running in the page and the only
way into it is through JavaScript. This module is the Python half of that conversation. The
JavaScript half is `kxbox/web/`.

`PROTOCOL.md` beside this file is the whole contract, and it is deliberately four calls wide.
Everything a lesson does is a shell line, a file read, a file write or a module load, because
those four are what the kernel already exposes to a shell and because a protocol you can hold in
your head is a protocol somebody can reimplement.

The calls are synchronous, which they have to be, because a lesson cell that says `await` in front
of every line is a lesson about promises. Blocking is the only way to get that and only a worker
may block, so Python is the worker and v86 is on the page, and the answer comes back through a
`SharedArrayBuffer`, which needs the two cross origin isolation headers listed in `PROTOCOL.md`.
That is a real constraint on where the book can be hosted and it is written down rather than
discovered later.

This has now run in a browser against a real kernel. `just web-measure` opens the harness page in
Chrome, and `kxbox/web/first-tape.py` takes one filtered trace of a write through every layer of
the arrangement above: Python in the worker, a blocking call over the shared buffer, JavaScript on
the page, a busybox shell on a serial line, the tracer inside the guest, and a parsed tape coming
back. The numbers are in `kxbox/kernel/RESULTS.md`. Everything below was written against a test
double before that and none of it changed when the emulator arrived, which is the nicest thing
that can be said about a protocol.
"""

from __future__ import annotations

import sys

# Where the tracer's controls live inside the guest. The same names `kxray.tracefs` uses on a real
# machine, because it is the same interface and there is no reason for two spellings of it.
TRACING = "/sys/kernel/tracing"
CURRENT_TRACER = f"{TRACING}/current_tracer"
FILTER = f"{TRACING}/set_ftrace_filter"
ON = f"{TRACING}/tracing_on"
TRACE = f"{TRACING}/trace"

# What the page has to expose. One object, on the JavaScript global, with the four calls.
GLOBAL = "kxbox"
CALLS = ("sh", "read", "write", "insmod")


class Unavailable(RuntimeError):
    """Raised when there is no emulator to talk to, saying which part is missing."""


def find_bridge():
    """The bridge object the page exposes, or None when this is not a page.

    Under Pyodide there is a `js` module standing for the JavaScript global scope. Everywhere
    else, importing it fails, which is the answer.
    """
    js = sys.modules.get("js")
    if js is None:
        try:
            import js  # noqa: PLC0415
        except ImportError:
            return None
    found = getattr(js, GLOBAL, None)
    if found is None:
        return None
    return found


def explain() -> str:
    """Why the live backend is not available, in the words somebody can act on."""
    if sys.modules.get("js") is None and "pyodide" not in sys.modules:
        return "not running in a browser, so there is no emulator in the page to talk to"
    return f"running in a browser, but the page has not exposed a `{GLOBAL}` object"


class V86:
    """A kernel running under v86, driven through the page's bridge object."""

    name = "v86"
    live = True
    evidence = True

    def __init__(self, bridge, profile: str = "teaching") -> None:
        missing = [one for one in CALLS if not hasattr(bridge, one)]
        if missing:
            raise Unavailable(f"the bridge object is missing {', '.join(missing)}")
        self.bridge = bridge
        self.profile = profile

    @classmethod
    def find(cls, profile: str = "teaching") -> V86 | None:
        found = find_bridge()
        return None if found is None else cls(found, profile)

    def describe(self) -> str:
        return f"v86, profile {self.profile}, uniprocessor, 32 bit, emulated timing"

    def sh(self, line: str, *, recipe: str = ""):
        from kxbox.session import Command

        reply = self.bridge.sh(line)
        return Command(
            line,
            int(getattr(reply, "status", 0)),
            str(getattr(reply, "stdout", "")),
            str(getattr(reply, "stderr", "")),
            backend=self.name,
        )

    def read(self, path: str, *, recipe: str = "") -> str:
        return str(self.bridge.read(path))

    def write(self, path: str, text: str) -> None:
        self.bridge.write(path, text)

    def insmod(self, path: str):
        from kxbox.session import Command

        reply = self.bridge.insmod(path)
        return Command(
            f"insmod {path}",
            int(getattr(reply, "status", 0)),
            str(getattr(reply, "stdout", "")),
            str(getattr(reply, "stderr", "")),
            backend=self.name,
        )

    def tape(self, recipe: str, do=None, functions: tuple[str, ...] = ()):
        """Turn the tracer on, run the thing, turn it off, and parse what came out.

        The sequence is the same one `kxray.tracefs` runs on a real machine, in the same order,
        including putting the tracer back afterwards. A lesson that left `function_graph` on
        would slow every later cell down and the reader would blame the wrong thing.
        """
        from kxray import trace

        before = self.read(CURRENT_TRACER).strip()
        self.write(FILTER, "\n".join(functions) if functions else "")
        self.write(CURRENT_TRACER, "function_graph")
        # Empty the ring buffer before starting. Writing to it truncates it, which is the whole
        # effect wanted here. Without this a second tape in the same session carries the first
        # one's records as well, and the reader gets a trace of something they did a minute ago.
        self.write(TRACE, "")
        self.write(ON, "1")
        try:
            if do is not None:
                do()
        finally:
            self.write(ON, "0")
        text = self.read(TRACE)
        self.write(CURRENT_TRACER, before or "nop")
        self.write(FILTER, "")
        return trace.parse(text, source=f"v86:{recipe}")
