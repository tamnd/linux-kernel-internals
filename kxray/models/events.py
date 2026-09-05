"""Trace events, and the `format` file the kernel publishes for each one.

Unlike the two function tracers an event has a shape of its own, and the kernel writes that shape
down at `/sys/kernel/tracing/events/<group>/<event>/format` so that nothing has to guess it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kxray.models.flat import Flags, TraceLog, _tally


@dataclass(frozen=True)
class EventField:
    """One `field:` line out of an event's `format` file.

    The offset and the size are the reason to read this file at all. They are per kernel and per
    architecture and they are not guessable: `long prev_state` is four bytes on the 32 bit box
    this project pins and eight on the machine you are probably reading this on, and an event
    whose layout was written down once by hand is an event that misreads one of the two.
    """

    name: str
    type: str
    offset: int
    size: int
    signed: bool
    count: int | None = None
    data_loc: bool = False

    @property
    def is_common(self) -> bool:
        """Whether this is one of the four fields every event carries, rather than its own."""
        return self.name.startswith("common_")

    @property
    def end(self) -> int:
        return self.offset + self.size

    @property
    def is_array(self) -> bool:
        return self.count is not None

    @property
    def is_text(self) -> bool:
        """Whether the value prints as text rather than as a number."""
        return self.data_loc or (self.type.startswith("char") and self.is_array)

    @property
    def declared(self) -> str:
        """The field the way the format file writes it, which is how a person looks it up."""
        written = f"{self.type} {self.name}"
        if self.is_array:
            written = f"{self.type} {self.name}[{self.count}]"
        return f"__data_loc {written}" if self.data_loc else written

    def __str__(self) -> str:
        return f"{self.declared} at {self.offset}, {self.size} byte(s)"


@dataclass(frozen=True)
class EventFormat:
    """A whole `format` file: what one event puts in the ring buffer, and how it prints it.

    The two halves are worth keeping apart in your head. The field list is the record, and it is
    the truth about what was stored. `print_fmt` is a formatting instruction, and by the time you
    read a line of `/sys/kernel/tracing/trace` it has already run, so a number in the record can
    reach you as a symbol. `sched_switch` stores `prev_state` as an integer and prints it as `S`
    or `R+`, and the two are both correct and are not the same thing.
    """

    name: str
    id: int
    fields: tuple[EventField, ...] = ()
    print_fmt: str = ""

    @property
    def common(self) -> tuple[EventField, ...]:
        return tuple(one for one in self.fields if one.is_common)

    @property
    def own(self) -> tuple[EventField, ...]:
        """The fields this event declares, which is everything but the four shared ones."""
        return tuple(one for one in self.fields if not one.is_common)

    @property
    def size(self) -> int:
        """How many bytes one of these takes in the ring buffer."""
        return max((one.end for one in self.fields), default=0)

    def field(self, name: str) -> EventField | None:
        return next((one for one in self.fields if one.name == name), None)

    def holes(self) -> list[tuple[str, int]]:
        """Padding between fields, as (the field it follows, how many bytes).

        The same question the BTF reader asks about a struct, asked about a record. An event that
        the compiler had to pad is an event whose fields are further apart than their sizes
        suggest, and somebody adding up sizes by hand will land in the wrong place.
        """
        found = []
        ordered = sorted(self.fields, key=lambda one: one.offset)
        for before, after in zip(ordered, ordered[1:], strict=False):
            gap = after.offset - before.end
            if gap > 0:
                found.append((before.name, gap))
        return found

    def table(self) -> str:
        rows = [("offset", "size", "field", "type")]
        for one in self.fields:
            rows.append((str(one.offset), str(one.size), one.name, one.declared))
        widths = [max(len(row[i]) for row in rows) for i in range(4)]
        out = []
        for index, row in enumerate(rows):
            out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
            if index == 0:
                out.append("  ".join("-" * width for width in widths))
        return "\n".join(out)


@dataclass(frozen=True)
class TraceEvent:
    """One event line, read through its format where there is one and read plainly where not.

    Named `TraceEvent` rather than `Event` because `Event` above already means a non frame line
    inside a function_graph tape, and the two have nothing to do with each other. `TraceEvent` is
    also what the kernel calls these, so the longer name is the more correct one.

    `values` is what the line said, converted to numbers wherever the format declared a number
    and the printed text was one. `symbolic` names the fields where it was not, which is not an
    error and is the normal outcome for anything `print fmt` puts through `__print_flags` or
    `__print_symbolic`. `unknown` and `missing` are the two ways a line and a format can disagree,
    and they are the whole reason for reading one through the other.
    """

    name: str
    values: dict[str, object]
    task: str
    pid: int
    cpu: int
    flags: Flags
    timestamp: float
    line: int
    layout: EventFormat | None = None
    unknown: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    symbolic: tuple[str, ...] = ()

    @property
    def context(self) -> str:
        return self.flags.context

    @property
    def bound(self) -> bool:
        """Whether a format was found for this event, so the values mean what they say."""
        return self.layout is not None

    @property
    def agrees(self) -> bool:
        """Whether the line printed exactly the fields its format declares. Usually it does not.

        A `print fmt` is free to leave a field out and free to print one twice, so disagreement
        is information rather than a fault. What it is not is something to find out by accident.
        """
        return not self.unknown and not self.missing

    def __getitem__(self, name: str) -> object:
        return self.values[name]

    def get(self, name: str, fallback: object = None) -> object:
        return self.values.get(name, fallback)

    def __str__(self) -> str:
        said = " ".join(f"{key}={value}" for key, value in self.values.items())
        return f"{self.timestamp:.6f} [{self.cpu}] {self.task}-{self.pid} {self.name}: {said}"


@dataclass
class EventLog(TraceLog):
    """A whole trace of events, and the formats they were read through."""

    events: list[TraceEvent] = field(default_factory=list)
    formats: dict[str, EventFormat] = field(default_factory=dict)

    @property
    def entries(self) -> list[TraceEvent]:
        return self.events

    def find(self, name: str) -> list[TraceEvent]:
        return [one for one in self.events if one.name == name]

    def names(self) -> dict[str, int]:
        """How many of each event are in here, most first."""
        return _tally(one.name for one in self.events)

    def unbound(self) -> list[str]:
        """Event names in the trace that no format was loaded for, so their values are strings."""
        return sorted({one.name for one in self.events if not one.bound})

    def disagreements(self) -> list[TraceEvent]:
        """Lines whose fields are not the ones their format declares. Empty is the usual answer."""
        return [one for one in self.events if one.bound and not one.agrees]

    def table(self, *fields: str) -> str:
        columns = fields or ("fields",)
        rows = [("time", "cpu", "task", "context", "event", *columns)]
        for one in self.events:
            if fields:
                said = tuple(str(one.get(name, "")) for name in fields)
            else:
                said = (" ".join(f"{k}={v}" for k, v in one.values.items()),)
            rows.append(
                (
                    f"{one.timestamp:.6f}",
                    str(one.cpu),
                    f"{one.task}-{one.pid}",
                    one.context,
                    one.name,
                    *said,
                )
            )
        widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
        out = []
        for index, row in enumerate(rows):
            out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
            if index == 0:
                out.append("  ".join("-" * width for width in widths))
        if self.overran:
            out.append(f"{self.lost} event(s) dropped, so this trace has holes in it")
        return "\n".join(out)
