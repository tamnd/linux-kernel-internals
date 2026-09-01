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

    @property
    def is_bitfield(self) -> bool:
        return self.bitfield_size > 0

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
