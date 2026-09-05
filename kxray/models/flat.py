"""The flat function tracer, which is `function` rather than `function_graph`.

One line per call, no nesting, no duration, and one column function_graph does not print at all:
the state of the machine at the moment of the call. So the two answer different questions and this
project keeps both.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from kxray.models.lines import Lines
from kxray.models.tape import UnparsedLine


@dataclass(frozen=True)
class Flags:
    """The five character column ftrace prints between the CPU and the timestamp.

    Reading left to right: interrupts off, a reschedule pending, which interrupt context this is,
    how deep the preemption count is, and whether migration is disabled. A dot in any position
    means no. The column is four characters wide on kernels before migrate-disable existed, and
    both widths are read here, because a trace somebody took in 2021 is still a trace.

    This is the column that decides whether a line is a bug. The same function is fine in one
    context and forbidden in another, so a tape that leaves this out is a tape that cannot answer
    the question a concurrency lesson is about.
    """

    raw: str
    irqs_off: str
    resched: str
    interrupt: str
    preempt_depth: int
    migrate_disable: str | None = None

    @property
    def context(self) -> str:
        """Which of the six contexts in `kxray.vocabulary` this is, as far as the column can say.

        It never answers `atomic`, and that is the honest limit rather than an omission. A held
        spinlock raises the preemption count and so does a bare `preempt_disable()`, the column
        carries only the count, and nothing in it can tell the two apart. So a line with a
        preemption count and no interrupt flag comes back as `nopreempt`, which is true of both.
        """
        if self.interrupt in ("z", "Z"):
            return "nmi"
        if self.interrupt in ("h", "H"):
            return "hardirq"
        if self.interrupt == "s":
            return "softirq"
        return "nopreempt" if self.preempt_depth > 0 else "process"

    @property
    def interrupts_are_off(self) -> bool:
        return self.irqs_off in ("d", "D")

    @property
    def wants_resched(self) -> bool:
        """Something has asked for a reschedule and it has not happened yet."""
        return self.resched != "."

    def describe(self) -> str:
        parts = [f"{self.context} context"]
        if self.interrupts_are_off:
            parts.append("interrupts off")
        if self.wants_resched:
            parts.append("reschedule pending")
        if self.preempt_depth:
            parts.append(f"preemption count {self.preempt_depth}")
        return ", ".join(parts)

    def __str__(self) -> str:
        return self.raw


@dataclass(frozen=True)
class Call:
    """One line of the flat function tracer: a function ran, and who called it.

    There is no duration here and there never will be. The flat tracer records entry and nothing
    else, so the cost of a call is a question this format cannot answer, and the trace that can
    is function_graph.
    """

    name: str
    caller: str | None
    task: str
    pid: int
    cpu: int
    flags: Flags
    timestamp: float
    line: int

    @property
    def context(self) -> str:
        return self.flags.context

    def __str__(self) -> str:
        called_by = f" <- {self.caller}" if self.caller else ""
        return f"{self.timestamp:.6f} [{self.cpu}] {self.task}-{self.pid} {self.name}{called_by}"


@dataclass
class TraceLog:
    """What every line based trace has in common, whatever the tracer was.

    The banner at the top is the part worth pulling out rather than skipping. `written` counts the
    events the kernel produced and `in_buffer` counts the ones that survived, so a trace where
    they differ has holes in it that nothing in the body of the file admits to. Reading that trace
    as though it were complete is how somebody concludes a function was never called.
    """

    source: str = "<text>"
    tracer: str | None = None
    unparsed: list[UnparsedLine] = field(default_factory=list)
    lines: Lines = field(default_factory=Lines)
    in_buffer: int | None = None
    written: int | None = None
    cpu_count: int | None = None

    @property
    def entries(self) -> list:
        """Whatever this tracer put on its lines. Calls for one, events for the other."""
        raise NotImplementedError

    @property
    def lost(self) -> int | None:
        """How many events the ring buffer dropped, or None when the banner did not say."""
        if self.in_buffer is None or self.written is None:
            return None
        return max(0, self.written - self.in_buffer)

    @property
    def overran(self) -> bool:
        return bool(self.lost)

    @property
    def cpus(self) -> list[int]:
        return sorted({one.cpu for one in self.entries})

    @property
    def tasks(self) -> list[str]:
        return sorted({f"{one.task}-{one.pid}" for one in self.entries})

    def contexts(self) -> dict[str, int]:
        """How many lines happened in each context. The first thing to look at in a flat trace."""
        return _tally(one.context for one in self.entries)


@dataclass
class FunctionLog(TraceLog):
    """A whole flat function trace: the calls, and the banner that says whether it is complete."""

    calls: list[Call] = field(default_factory=list)

    @property
    def entries(self) -> list[Call]:
        return self.calls

    def find(self, name: str) -> list[Call]:
        return [one for one in self.calls if one.name == name]

    def counts(self) -> dict[str, int]:
        """How many times each function ran, most first. What the flat tracer is mostly used for."""
        return _tally(one.name for one in self.calls)

    def callers(self, name: str) -> dict[str, int]:
        """Who called this function, and how often each did."""
        return _tally(one.caller for one in self.find(name) if one.caller)

    def callees(self, name: str) -> dict[str, int]:
        """What this function was seen calling, as far as the filter let the trace see."""
        return _tally(one.name for one in self.calls if one.caller == name)

    def table(self) -> str:
        rows = [("time", "cpu", "task", "context", "function", "called by")]
        for one in self.calls:
            rows.append(
                (
                    f"{one.timestamp:.6f}",
                    str(one.cpu),
                    f"{one.task}-{one.pid}",
                    one.context,
                    one.name,
                    one.caller or "",
                )
            )
        widths = [max(len(row[i]) for row in rows) for i in range(6)]
        out = []
        for index, row in enumerate(rows):
            out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
            if index == 0:
                out.append("  ".join("-" * width for width in widths))
        if self.overran:
            out.append(f"{self.lost} event(s) dropped, so this trace has holes in it")
        return "\n".join(out)


def _tally(names: Iterator[str] | list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))
