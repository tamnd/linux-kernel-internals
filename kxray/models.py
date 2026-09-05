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
    # The loadable module the function came from, when ftrace printed one. Built in functions have
    # no module and this stays None, which is every function in a Tier 0 trace.
    module: str | None = None
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

# What a parser did with one line. Every line of every committed artefact gets exactly one of
# these, which is the point: a line the parser quietly walked past is the one that goes wrong.
READ = "read"
SKIPPED = "skipped"
UNPARSED = "unparsed"


@dataclass
class Lines:
    """How every line of a file was accounted for.

    `read` turned into something. `skipped` was never data, so a blank line, a separator or a
    header the kernel prints above the rows. `unparsed` was meant to be data and was not
    understood.

    The reason all three are counted rather than just the last one is that the interesting drift
    moves a line between the first two. A parser that starts treating a data line as a header does
    not report a failure and does not raise, it just returns fewer rows, and the only way to see
    that from outside is to have written down how many lines were in each bucket beforehand.

    `total` has to equal the number of lines in the file. `tools/baseline` checks that, and a
    reader that cannot make the three numbers add up is a reader that is guessing.
    """

    read: int = 0
    skipped: int = 0
    unparsed: int = 0

    @property
    def total(self) -> int:
        return self.read + self.skipped + self.unparsed

    def count(self, verdict: str) -> None:
        setattr(self, verdict, getattr(self, verdict) + 1)

    def __str__(self) -> str:
        return f"{self.read} read, {self.skipped} skipped, {self.unparsed} unparsed"


@dataclass
class Tape:
    """A whole function_graph trace, as a forest of frames plus the events between them."""

    source: str = "<text>"
    tracer: str | None = None
    roots: list[Frame] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    unparsed: list[UnparsedLine] = field(default_factory=list)
    lines: Lines = field(default_factory=Lines)

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


# ---------------------------------------------------------------------------------------------
# The flat function tracer. One line per call, no nesting, and the column function_graph does not
# print: the state of the machine at the moment the call happened.


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


# ---------------------------------------------------------------------------------------------
# Trace events. Unlike the two function tracers, an event has a shape of its own, and the kernel
# publishes that shape at /sys/kernel/tracing/events/<group>/<event>/format so that nothing has
# to guess it. These models are that file, and a line read through it.


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


# ---------------------------------------------------------------------------------------------
# What the kernel knows about its own types. Parsed by kxray.btf, rendered by kxwidgets and by
# the generated sections of a blueprint.


@dataclass(frozen=True)
class Member:
    """One field of a struct or a union, as BTF records it.

    The offset is in bits and not in bytes, because a bitfield does not start on a byte boundary
    and the format refuses to pretend otherwise.
    """

    name: str
    type_id: int
    bit_offset: int
    bitfield_size: int = 0  # 0 means this field is not a bitfield

    @property
    def byte_offset(self) -> int:
        return self.bit_offset // 8

    @property
    def is_bitfield(self) -> bool:
        return self.bitfield_size > 0


@dataclass(frozen=True)
class EnumValue:
    name: str
    value: int


@dataclass(frozen=True)
class Param:
    """One parameter of a function prototype. An empty name is a parameter nobody named."""

    name: str
    type_id: int


@dataclass(frozen=True)
class SecInfo:
    """Where one variable sits inside a section, from a datasec record."""

    type_id: int
    offset: int
    size: int


@dataclass(frozen=True)
class Type:
    """One entry in the type section.

    One dataclass for all nineteen kinds rather than nineteen classes. A reader looking at a
    struct should not have to know a class hierarchy to ask what its fields are, and the fields
    that do not apply to a kind are simply empty.
    """

    id: int
    kind: str
    name: str = ""
    size: int | None = None  # bytes, for the kinds that have a size
    type_id: int | None = None  # what this refers to, for the kinds that refer to something
    vlen: int = 0
    kind_flag: bool = False
    members: tuple[Member, ...] = ()
    values: tuple[EnumValue, ...] = ()
    params: tuple[Param, ...] = ()
    variables: tuple[SecInfo, ...] = ()
    element_type: int | None = None  # array element
    index_type: int | None = None  # array index, which is always an int in practice
    nelems: int | None = None
    encoding: int = 0  # int only: signed, char and bool bits
    bits: int | None = None  # int only: how many bits are actually used
    bit_offset: int = 0  # int only, and only for the old way of writing a bitfield
    linkage: int | None = None  # func and var only
    component_idx: int | None = None  # decl_tag only

    @property
    def is_composite(self) -> bool:
        return self.kind in ("struct", "union")

    def __str__(self) -> str:
        named = f" {self.name}" if self.name else ""
        return f"[{self.id}] {self.kind}{named}"


@dataclass(frozen=True)
class Field:
    """One field of a struct after flattening, with the answer a lesson actually wants.

    `path` is what you would type in C to reach it, so an anonymous struct in the middle
    contributes nothing to it, which is exactly how C behaves.
    """

    path: str
    type_name: str
    byte_offset: int
    bit_offset: int
    size: int | None
    bitfield_size: int = 0
    tags: tuple[str, ...] = ()  # user, rcu, percpu: who is allowed to follow this pointer

    @property
    def is_bitfield(self) -> bool:
        return self.bitfield_size > 0

    @property
    def is_annotated(self) -> bool:
        """Whether this field carries an annotation about how it may be reached.

        An annotation changes no offset and no size, so it never shows up in the arithmetic. It
        is the difference between a pointer you may dereference and one that will corrupt memory
        or crash the machine if you do.
        """
        return bool(self.tags)

    @property
    def end(self) -> int | None:
        """The first byte after this field, or None when the size is unknown."""
        return None if self.size is None else self.byte_offset + self.size


@dataclass(frozen=True)
class Hole:
    """Padding between two fields. The reason anyone runs pahole in the first place."""

    after: str
    byte_offset: int
    size: int


@dataclass
class Layout:
    """What a struct looks like in memory, for one architecture.

    The architecture matters and is not in the file. BTF records no pointer size at all, so the
    same blob describes a different memory layout on a 32-bit machine than on a 64-bit one. That
    is why `pointer_size` is recorded here and printed with the table.
    """

    name: str
    size: int | None
    pointer_size: int
    fields: list[Field] = field(default_factory=list)
    holes: list[Hole] = field(default_factory=list)

    @property
    def padding(self) -> int:
        return sum(hole.size for hole in self.holes)

    def offset_of(self, path: str) -> int:
        for one in self.fields:
            if one.path == path:
                return one.byte_offset
        raise KeyError(f"{self.name} has no field called {path!r}")

    def table(self) -> str:
        """The layout as a table, holes included, in the order the bytes are laid out."""
        rows = [("offset", "size", "field", "type")]
        for one in self.fields:
            size = "?" if one.size is None else str(one.size)
            if one.is_bitfield:
                size = f"{one.bitfield_size} bits"
            rows.append((str(one.byte_offset), size, one.path, one.type_name))
        widths = [max(len(row[i]) for row in rows) for i in range(4)]
        out = []
        for index, row in enumerate(rows):
            out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
            if index == 0:
                out.append("  ".join("-" * width for width in widths))
        for hole in self.holes:
            out.append(f"{hole.size} byte hole at offset {hole.byte_offset}, after {hole.after}")
        return "\n".join(out)


@dataclass(frozen=True)
class Slot:
    """One function pointer in an ops table.

    `filled_by` is the name of the function that is actually in the slot. It stays None until
    somebody reads a real instance out of a real kernel, because what a function pointer holds is
    a fact about a running machine and not about a type. The type only says what shape it has to
    be.
    """

    name: str
    signature: str
    byte_offset: int
    filled_by: str | None = None

    @property
    def filled(self) -> bool:
        return self.filled_by is not None


@dataclass
class OpsTable:
    """A struct of function pointers, which is how the kernel does polymorphism.

    There is no `class` in C and no vtable the compiler makes for you, so the kernel writes one by
    hand: a struct full of function pointers, one instance per implementation, and a pointer to
    the instance hanging off the object. `file_operations`, `inode_operations` and `net_device_ops`
    are all this. Learn to read one and a large part of the kernel stops being a mystery.

    `instance` is the name of the particular one being looked at, such as `ext4_file_operations`.
    It is None when what is being looked at is the interface rather than an implementation of it.
    """

    name: str
    slots: list[Slot] = field(default_factory=list)
    data_fields: list[Field] = field(default_factory=list)
    size: int | None = None
    instance: str | None = None

    @property
    def filled(self) -> list[Slot]:
        return [one for one in self.slots if one.filled]

    def slot(self, name: str) -> Slot:
        for one in self.slots:
            if one.name == name:
                return one
        raise KeyError(f"{self.name} has no slot called {name!r}")

    def with_implementations(self, filled: dict[str, str]) -> OpsTable:
        """The same table with the slots filled in, for when you know what is in the instance.

        Returns a new table rather than changing this one, so the interface and an implementation
        of it can sit side by side without one quietly overwriting the other.
        """
        unknown = sorted(set(filled) - {one.name for one in self.slots})
        if unknown:
            raise KeyError(f"{self.name} has no slot called {unknown[0]!r}")
        slots = [
            Slot(one.name, one.signature, one.byte_offset, filled.get(one.name, one.filled_by))
            for one in self.slots
        ]
        return OpsTable(self.name, slots, self.data_fields, self.size, self.instance)

    def table(self) -> str:
        rows = [("offset", "slot", "filled by")]
        for one in self.slots:
            rows.append((str(one.byte_offset), one.name, one.filled_by or "nothing yet"))
        widths = [max(len(row[i]) for row in rows) for i in range(3)]
        out = []
        for index, row in enumerate(rows):
            out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
            if index == 0:
                out.append("  ".join("-" * width for width in widths))
        out.append("")
        out.extend(one.signature for one in self.slots)
        return "\n".join(out)
