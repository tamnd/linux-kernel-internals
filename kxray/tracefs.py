"""Talk to the kernel's tracing interface, when there is one.

    from kxray import tracefs

    tracefs.report()                 what this machine can and cannot do
    text = tracefs.capture_write()   turn on function_graph, write one byte, hand back the trace

Everything the tracer does is driven by reading and writing files under `/sys/kernel/tracing`, so
this module is a hundred lines of open and write with the sequence written down once, in order,
including putting the machine back how it was found.

Three things have to be true before it works: the kernel was built with `function_graph`, the
tracing filesystem is mounted, and you are root. On a laptop running Linux that is one `sudo`. In
a container it depends on what the container was given, and in a sandboxed runtime the directory
is usually missing entirely. `available()` answers before you try, and every failure says which
of the three is missing rather than raising a bare permission error.
"""

from __future__ import annotations

import os
import platform
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kxray.models import READ, SKIPPED, UNPARSED, Lines

# Where the tracing filesystem is mounted, newest location first.
LOCATIONS = (Path("/sys/kernel/tracing"), Path("/sys/kernel/debug/tracing"))

CONTROLS = ("current_tracer", "tracing_on", "trace")

# `oldest event ts:     2.109723`, a clock reading rather than a count of anything.
TIMESTAMP = re.compile(r"^\s*[a-z ]+ts:\s+\d+\.\d+\s*$")


class Unavailable(RuntimeError):
    """Raised when this machine cannot trace, with which part is missing."""


@dataclass(frozen=True)
class Tracefs:
    root: Path

    def path(self, name: str) -> Path:
        return self.root / name

    def read(self, name: str) -> str:
        return self.path(name).read_text(errors="replace")

    def write(self, name: str, value: str) -> None:
        target = self.path(name)
        if not target.exists():
            return
        target.write_text(value)

    def writable(self) -> bool:
        return os.access(self.path("current_tracer"), os.W_OK)

    def tracers(self) -> list[str]:
        available = self.path("available_tracers")
        return available.read_text().split() if available.exists() else []

    def capture(
        self,
        action: Callable[[], None],
        *,
        tracer: str = "function_graph",
        function: str | None = None,
        max_depth: int = 0,
    ) -> str:
        """Trace one thing and put the machine back the way it was.

        The order matters. Tracing goes off before anything is configured, the buffer is emptied
        so the trace holds this run and nothing else, and tracing goes off again before the file
        is read, because reading a live buffer gives you a trace with the reader in it.
        """
        if not self.writable():
            raise Unavailable(f"{self.root} is not writable, so this needs root")
        if tracer not in self.tracers():
            raise Unavailable(f"this kernel has no {tracer} tracer, it has {self.tracers()}")

        previous = self.read("current_tracer").strip()
        try:
            self.write("tracing_on", "0")
            self.write("current_tracer", tracer)
            self.write("set_graph_function", function or "")
            self.write("max_graph_depth", str(max_depth))
            self.write("trace", "")

            self.write("tracing_on", "1")
            action()
            self.write("tracing_on", "0")

            return self.read("trace")
        finally:
            self.write("tracing_on", "0")
            self.write("current_tracer", previous or "nop")
            self.write("set_graph_function", "")
            self.write("max_graph_depth", "0")

    def stats(self, cpu: int = 0) -> dict[str, int]:
        """The per CPU counters, where `overrun` says how many events the ring buffer dropped."""
        path = self.path(f"per_cpu/cpu{cpu}/stats")
        return parse_stats(path.read_text()) if path.exists() else {}


def _read_stat(line: str) -> tuple[str, int] | None:
    """One `name: count` line of a per CPU stats file, or None when it is not one."""
    name, sep, value = line.partition(":")
    if not sep:
        return None
    try:
        return name.strip(), int(value.strip())
    except ValueError:
        return None


def parse_stats(text: str) -> dict[str, int]:
    """The counters in a per CPU stats file, by name."""
    found = (_read_stat(line) for line in text.splitlines())
    return dict(one for one in found if one is not None)


def account_stats(text: str) -> Lines:
    """How every line of a per CPU stats file was treated, for `tools/baseline`.

    Two of the lines in that file are timestamps rather than counters, `oldest event ts` and
    `now ts`, and this reader collects counters. Those are skipped on purpose and not failures,
    which is a distinction the old code could not make because it treated a line it does not
    collect and a line it could not read the same way.
    """
    lines = Lines()
    for line in text.splitlines():
        if not line.strip():
            lines.count(SKIPPED)
        elif _read_stat(line) is not None:
            lines.count(READ)
        elif TIMESTAMP.match(line):
            lines.count(SKIPPED)
        else:
            lines.count(UNPARSED)
    return lines


def find(locations: tuple[Path, ...] = LOCATIONS) -> Tracefs | None:
    """The mounted tracing filesystem, or None."""
    for location in locations:
        if all((location / name).exists() for name in CONTROLS):
            return Tracefs(location)
    return None


def available() -> bool:
    found = find()
    return bool(found and found.writable())


def write_one_byte(path: str | None = None) -> Callable[[], None]:
    """The thing Z02 traces. One byte, one file, no library between you and the system call."""

    def action() -> None:
        target = path or (Path(tempfile.gettempdir()) / "kxray-one-byte")
        handle = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(handle, b"x")
        finally:
            os.close(handle)

    return action


def capture_write(**kwargs) -> str:
    """A function_graph trace of writing one byte to a file. Raises Unavailable if it cannot."""
    found = find()
    if found is None:
        raise Unavailable(explain())
    return found.capture(write_one_byte(), **kwargs)


def explain() -> str:
    """Why this machine cannot trace, in the order the reader should check."""
    if platform.system() != "Linux":
        return f"this is {platform.system()}, and ftrace is a Linux kernel feature"
    found = find()
    if found is None:
        return (
            "no tracing filesystem. Try `mount -t tracefs nodev /sys/kernel/tracing`. "
            "If the directory is not there at all, this runtime is sandboxed away from it"
        )
    if not found.writable():
        return f"{found.root} exists and is not writable, so this needs root"
    return "tracing looks available"


def report() -> str:
    """One paragraph on what this runtime can do, printed at the top of a lesson."""
    found = find()
    lines = [
        f"system:  {platform.system()} {platform.release()}",
        f"machine: {platform.machine()}",
        f"tracefs: {found.root if found else 'not found'}",
        f"tracers: {' '.join(found.tracers()) if found else 'none'}",
        f"status:  {explain()}",
    ]
    text = "\n".join(lines)
    print(text)
    return text
