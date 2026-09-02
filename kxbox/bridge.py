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
Chrome, and `kxbox/web/first-tape.py` takes one filtered trace through every layer of the
arrangement above: Python in the worker, a blocking call over the shared buffer, JavaScript on the
page, a busybox shell on a serial line, the tracer inside the guest, and a parsed tape coming back.
The numbers are in `kxbox/kernel/RESULTS.md`.

The shape of what is below did not change when the emulator arrived, which is the nicest thing that
can be said about a protocol. The contents of `tape` changed a great deal, and not because of the
emulator. It changed when `kxbox/bothways.py` first ran this against the recordings it is supposed
to agree with, which is a different question from whether it runs at all, and got four answers
wrong at once. They are all marked below. The lesson worth keeping is that a backend tested against
a stand in is tested against what somebody thought the kernel did.
"""

from __future__ import annotations

import sys

# Where the tracer's controls live inside the guest. The same names `kxray.tracefs` uses on a real
# machine, because it is the same interface and there is no reason for two spellings of it.
TRACING = "/sys/kernel/tracing"
CURRENT_TRACER = f"{TRACING}/current_tracer"
ON = f"{TRACING}/tracing_on"
TRACE = f"{TRACING}/trace"
OPTIONS = f"{TRACING}/trace_options"

# `set_graph_function` and not `set_ftrace_filter`, which is what this used to write to, and the
# difference is the whole shape of the answer. The filter traces the functions you name and
# nothing else, so asking it for `vfs_write` gets a flat list of `vfs_write` calls with no tree
# under any of them. `set_graph_function` traces the ones you name and everything they call, which
# is what a lesson about what a write does actually wants. `kxray.tracefs` has always used the
# second one on a real machine, so for as long as this said `set_ftrace_filter` the same lesson
# showed a tree on Tier 1 and a flat list on Tier 0. Nothing caught it because nothing had ever
# run both sides against each other, which is now what `kxbox/bothways.py` is for.
GRAPH = f"{TRACING}/set_graph_function"
MAX_DEPTH = f"{TRACING}/max_graph_depth"

# The two trace options every capture is taken with, and what each one is for.
#
# `funcgraph-proc` adds the column saying which task a line belongs to. Every committed capture has
# it, and without it a trace with two processes in it is a trace nobody can untangle.
#
# `nofuncgraph-irqs` keeps functions called from interrupt context out of the trace. That is a
# choice about what a lesson is about rather than a tidiness measure. A timer tick landing inside
# the window is not something the person tracing did, it is not part of what they are looking at,
# and with the option left at its default it arrives or does not arrive depending on nothing they
# control. The first run of `kxbox/bothways.py` after this file was fixed had `write-1byte` diverge
# thirty calls in, into `handle_level_irq` and `mask_and_ack_8259A`, for exactly that reason. So
# the concession `bothways` documents, that interrupts are allowed to differ, is made by the tracer
# here rather than hoped for. Every committed capture reproduces exactly with this set.
WANTED = ("funcgraph-proc", "nofuncgraph-irqs")
RESTORED = ("nofuncgraph-proc", "funcgraph-irqs")

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

    def tape(
        self,
        recipe: str,
        do=None,
        functions: tuple[str, ...] = (),
        *,
        owns_window: bool = False,
        max_depth: int = 0,
    ):
        """Turn the tracer on, run the thing, turn it off, and parse what came out.

        The sequence is the same one `kxray.tracefs` runs on a real machine, in the same order,
        including putting the tracer back afterwards. A lesson that left `function_graph` on
        would slow every later cell down and the reader would blame the wrong thing.

        `owns_window` is for the programs in the rootfs that turn the tracer on and off around one
        system call from the inside. `writebyte`, `twowrites` and `touchpage` all do that, which is
        the only reason a beginner's first trace has three frames in it rather than seventeen. If
        this turned tracing on before running them, every write the shell did on the way to
        starting them would be in the capture too, and the one the reader came for would be
        somewhere in the middle with nothing marking it.

        `max_depth` is the same knob `kxray.tracefs` has and 0 means no limit, which is what every
        committed capture used. It is worth reaching for when the thing being traced is not a
        program that owns its window, because `set_graph_function` records everything underneath
        what you named and a busy window fills the ring buffer faster than a serial line can drain
        it. That failure looks like the guest hanging rather than like too much output.
        """
        from kxray import trace

        before = self.read(CURRENT_TRACER).strip()
        # Off before anything is configured. Changing the tracer while it is running gives a
        # buffer with two tracers' records in it, and the parser is right to be confused by that.
        self.write(ON, "0")
        self.write(CURRENT_TRACER, "function_graph")
        for option in WANTED:
            self.write(OPTIONS, option)
        self.write(GRAPH, "\n".join(functions) if functions else "")
        self.write(MAX_DEPTH, str(max_depth))
        # Empty the ring buffer before starting. Writing to it truncates it, which is the whole
        # effect wanted here. Without this a second tape in the same session carries the first
        # one's records as well, and the reader gets a trace of something they did a minute ago.
        self.write(TRACE, "")
        try:
            if not owns_window:
                self.write(ON, "1")
            if do is not None:
                do()
            self.write(ON, "0")
            text = self.read(TRACE)
        finally:
            # Put the machine back whatever happened, including when the thing being traced threw.
            # Leaving `function_graph` selected with a graph function set is not a tidy failure: the
            # buffer keeps filling from whatever the guest does next, and the next command that
            # reads it waits for megabytes over a serial line and times out looking like a hang.
            # That is how a single error here used to take the rest of the session with it.
            #
            # The tracer goes back last, and that order is not a preference. The funcgraph options
            # only exist while `function_graph` is the tracer, so putting the tracer back to `nop`
            # first has the rest of this refused with `Invalid argument`.
            self.write(ON, "0")
            for option in RESTORED:
                self.write(OPTIONS, option)
            self.write(GRAPH, "")
            self.write(MAX_DEPTH, "0")
            self.write(CURRENT_TRACER, before or "nop")
        return trace.parse(text, source=f"v86:{recipe}")
