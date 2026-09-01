"""The models that everything else renders.

A parser produces these and nothing else. Rendering never reaches into a parser, which is what
lets one trace appear as a tape in a notebook, as an animation in a lesson and as a table in a
blueprint without the three of them disagreeing about what happened.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

# The slowness markers ftrace puts in the duration column, from
# Documentation/trace/ftrace.rst. The kernel prints the marker, not the threshold, so a reader
# who wants the number has to know this table. Now the parser knows it for them.
DURATION_MARKERS = {
    "+": "over 10 us",
    "!": "over 100 us",
    "#": "over 1000 us",
    "*": "over 10 ms",
    "@": "over 100 ms",
    "$": "over 1 s",
}


@dataclass
class Frame:
    """One function call in a trace.

    A frame is complete when its closing brace was seen. Traces get cut off at the top and the
    bottom all the time, because the ring buffer is a ring, so an incomplete frame is normal
    input rather than an error.
    """

    name: str
    cpu: int
    depth: int
    line: int
    duration_us: float | None = None
    marker: str | None = None
    task: str | None = None
    complete: bool = True
    children: list[Frame] = field(default_factory=list)
    parent: Frame | None = field(default=None, repr=False, compare=False)

    @property
    def self_time_us(self) -> float | None:
        """Time in this function and not in anything it called.

        None when the duration is unknown. A child with an unknown duration counts as zero,
        which makes the answer an upper bound rather than a guess.
        """
        if self.duration_us is None:
            return None
        spent = sum(c.duration_us or 0.0 for c in self.children)
        return round(self.duration_us - spent, 3)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def walk(self) -> Iterator[Frame]:
        """This frame, then everything under it, in the order the kernel called them."""
        yield self
        for child in self.children:
            yield from child.walk()

    def find(self, name: str) -> list[Frame]:
        return [f for f in self.walk() if f.name == name]

    def path(self) -> list[str]:
        """Names from the outermost frame down to this one."""
        names = []
        node: Frame | None = self
        while node is not None:
            names.append(node.name)
            node = node.parent
        return list(reversed(names))

    def tree(self, max_depth: int | None = None) -> str:
        lines = []
        for f in self.walk():
            if max_depth is not None and f.depth - self.depth > max_depth:
                continue
            indent = "  " * (f.depth - self.depth)
            dur = "" if f.duration_us is None else f"{f.duration_us:.3f} us"
            tail = "" if f.complete else "  (never closed)"
            lines.append(f"{indent}{f.name}  {dur}{tail}".rstrip())
        return "\n".join(lines)


@dataclass
class Comment:
    """A `/* ... */` line, which is where trace_printk output and event text come out."""

    cpu: int
    line: int
    text: str


@dataclass
class InterruptEntry:
    """The `==========>` marker. Everything after it ran in interrupt context."""

    cpu: int
    line: int


@dataclass
class InterruptExit:
    """The `<==========` marker."""

    cpu: int
    line: int


@dataclass
class TaskSwitch:
    """The banner ftrace prints when the CPU it is tracing changes task."""

    cpu: int
    line: int
    previous: str
    following: str


@dataclass
class UnparsedLine:
    """A line the parser did not understand.

    This exists so that a trace format change breaks one line rather than forty lessons. The
    price of that tolerance is a count: every corpus artefact records how many unparsed lines it
    should have, and CI fails when the number goes up.
    """

    line: int
    text: str
    reason: str


Event = Comment | InterruptEntry | InterruptExit | TaskSwitch


@dataclass
class Tape:
    """A whole function_graph trace, as a forest of frames plus the events between them."""

    source: str = "<text>"
    tracer: str | None = None
    roots: list[Frame] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    unparsed: list[UnparsedLine] = field(default_factory=list)

    def walk(self) -> Iterator[Frame]:
        for root in self.roots:
            yield from root.walk()

    def find(self, name: str) -> list[Frame]:
        return [f for f in self.walk() if f.name == name]

    @property
    def frame_count(self) -> int:
        return sum(1 for _ in self.walk())

    @property
    def max_depth(self) -> int:
        return max((f.depth for f in self.walk()), default=0)

    @property
    def cpus(self) -> list[int]:
        return sorted({f.cpu for f in self.walk()})

    @property
    def total_duration_us(self) -> float:
        """Wall time covered by the outermost frames, as far as the trace knows."""
        return round(sum(r.duration_us or 0.0 for r in self.roots), 3)

    @property
    def touched_interrupt_context(self) -> bool:
        """Whether an interrupt landed inside this trace.

        Lessons ask this constantly, because a frame that ran under an interrupt is playing by
        different rules and cannot sleep.
        """
        return any(isinstance(e, InterruptEntry) for e in self.events)

    def tree(self, max_depth: int | None = None) -> str:
        return "\n\n".join(root.tree(max_depth) for root in self.roots)
