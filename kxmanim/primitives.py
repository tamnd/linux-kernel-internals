"""The nine shapes every animation is built out of, as data rather than as drawing.

There are nine and there will keep being nine. A reader who has watched three animations should
already know what every shape on screen means, and that only works if the set is closed and small.
Adding a tenth shape because one scene wanted something is how a visual language turns into a pile
of pictures.

    Frame card      one function, coloured by subsystem, badged by context
    Layer band      one of the eight horizontal layers, always in the same order
    Object box      one struct, with its fields as rows and its annotations as glyphs
    Pointer thread  one field pointing at another object, drawn by what it promises
    Ops plug        one function pointer table, with what is plugged into each socket
    Trace cell      one call from a trace, as wide as it took
    CPU lane        one CPU's row of trace cells
    Context badge   which of the six contexts this is running in
    Memory slot     a chunk of memory, drawn at a size you can compare

Nothing in this file imports manim. Everything here is a dataclass with numbers in it, so the
whole visual system can be tested on a laptop with no video encoder, and so the same primitives
could be rendered to something other than video later without any of this changing.

Every primitive has an `alt()` that says what it is in words. That is not a courtesy. An animation
that cannot be described in words is an animation that half the readers get nothing from, and
writing the description is usually how you find out the scene is trying to say two things at once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import log2

from kxray.layout import Span, place
from kxray.models import Frame, Layout, OpsTable, Tape
from kxray.vocabulary import (
    LOCK_GLYPH,
    Context,
    Layer,
    Reference,
    Subsystem,
    context,
    layer_depth,
    reference,
    subsystem_for,
    tags_for,
)

# The closed set, by the name a storyboard uses to say which shapes a scene is allowed to use.
PRIMITIVES: tuple[str, ...] = (
    "frame-card",
    "layer-band",
    "object-box",
    "pointer-thread",
    "ops-plug",
    "trace-cell",
    "cpu-lane",
    "context-badge",
    "memory-slot",
)


# -- 1. frame card ------------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameCard:
    """One function, drawn as a card in its subsystem's colour with its context badge on it.

    Both of those have to be passed in. A `function_graph` trace prints `ext4_file_write_iter`
    and nothing else, so the trace does not know which file that came from and does not know
    which context it ran in. Guessing either one from the name is wrong often enough to matter,
    so this asks, and a scene that has not looked it up gets a dull grey card that looks
    unfinished, because it is.
    """

    primitive = "frame-card"

    name: str
    subsystem: Subsystem
    context: Context
    note: str = ""

    @classmethod
    def of(cls, name: str, *, path: str | None = None, ran_in: str = "process", note: str = ""):
        return cls(name, subsystem_for(path), context(ran_in), note)

    def alt(self) -> str:
        parts = [f"{self.name}, in {self.subsystem.name}, {self.context.name}"]
        if self.note:
            parts.append(self.note)
        return ". ".join(parts)


# -- 2. layer band ------------------------------------------------------------------------------


@dataclass(frozen=True)
class LayerBand:
    """One of the eight bands, at the depth it always sits at."""

    primitive = "layer-band"

    layer: Layer
    label: str = ""
    lit: bool = False

    @property
    def depth(self) -> int:
        return layer_depth(self.layer.key)

    def alt(self) -> str:
        if self.label:
            return f"{self.layer.name}, where {self.label} runs. {self.layer.blurb}."
        return f"{self.layer.name}: {self.layer.blurb}."


@dataclass(frozen=True)
class LayerDescent:
    """The eight bands with some of them lit up, which is what a syscall descending looks like.

    Bands come out top to bottom whatever order they went in, because a reader who has learnt
    that the page cache sits above the block layer should never have to check which way up a
    particular picture is.
    """

    bands: tuple[LayerBand, ...]

    @classmethod
    def of(cls, lit: dict[str, str]):
        bands = [LayerBand(one, lit.get(one.key, ""), one.key in lit) for one in _all_layers()]
        return cls(tuple(sorted(bands, key=lambda b: b.depth)))

    @property
    def path(self) -> tuple[LayerBand, ...]:
        """Only the lit bands, top to bottom, which is the route the call actually took."""
        return tuple(one for one in self.bands if one.lit)

    def alt(self) -> str:
        steps = " then ".join(f"{one.layer.name} ({one.label})" for one in self.path)
        return f"Down through {steps}." if steps else "Nothing is lit up."


def _all_layers() -> list[Layer]:
    from kxray.vocabulary import LAYERS

    return list(LAYERS)


# -- 3. object box ------------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldRow:
    """One row of an object box: what it is called, what it is, and what is true about it."""

    name: str
    type_name: str
    byte_offset: int
    glyphs: tuple[str, ...] = ()
    lock: str = ""

    def alt(self) -> str:
        parts = [f"{self.name} at offset {self.byte_offset}, {self.type_name}"]
        if self.lock:
            parts.append(f"protected by {self.lock}")
        return ", ".join(parts)


@dataclass(frozen=True)
class ObjectBox:
    """One struct as a box of rows, with the annotations shown as glyphs down the side.

    The rows come out of BTF, so the field names and the offsets are whatever the kernel that
    was built actually has rather than whatever the book said last year. The glyphs come from
    type tags, which BTF keeps, so `__user` and `__rcu` survive into the picture.

    Locks do not come out of BTF. `struct_member` annotations are not in the format, so which
    lock covers which field is something a human writes down and something a human can get
    wrong. That is why it is a separate argument and not something this works out.
    """

    primitive = "object-box"

    name: str
    rows: tuple[FieldRow, ...]
    size: int | None = None
    hidden: int = 0

    @classmethod
    def of(
        cls,
        layout: Layout,
        *,
        show: list[str] | None = None,
        locks: dict[str, str] | None = None,
    ):
        locks = locks or {}
        wanted = [one for one in layout.fields if show is None or one.path in show]
        rows = tuple(
            FieldRow(
                name=one.path,
                type_name=one.type_name,
                byte_offset=one.byte_offset,
                glyphs=tuple(tag.glyph for tag in tags_for(one.type_name)),
                lock=locks.get(one.path, ""),
            )
            for one in wanted
        )
        return cls(layout.name, rows, layout.size, len(layout.fields) - len(wanted))

    def alt(self) -> str:
        head = f"{self.name}, {self.size} bytes" if self.size else self.name
        body = ". ".join(one.alt() for one in self.rows)
        tail = f". {self.hidden} more fields not shown" if self.hidden else ""
        return f"{head}. {body}{tail}"

    def legend(self) -> list[str]:
        """What each glyph on this box means, so the picture explains itself."""
        from kxray.vocabulary import TYPE_TAGS

        shown = {glyph for row in self.rows for glyph in row.glyphs}
        out = [one.describe() for one in TYPE_TAGS if one.glyph in shown]
        if any(row.lock for row in self.rows):
            out.append(f"{LOCK_GLYPH} the lock you must hold to touch this field")
        return out


# -- 4. pointer thread --------------------------------------------------------------------------


@dataclass(frozen=True)
class PointerThread:
    """One object pointing at another, drawn by what the pointer promises rather than by taste.

    Solid means a reference is held. Dashed means one is not. Dotted means RCU, and the answer
    goes stale the moment you leave the read side. Getting this wrong in a picture is how people
    end up writing a use after free, so the line style is the point of the shape.
    """

    primitive = "pointer-thread"

    from_object: str
    from_field: str
    to_object: str
    reference: Reference

    @classmethod
    def of(cls, from_object: str, from_field: str, to_object: str, *, kind: str = "owning"):
        return cls(from_object, from_field, to_object, reference(kind))

    def alt(self) -> str:
        return (
            f"{self.from_object}.{self.from_field} points at {self.to_object}, "
            f"{self.reference.describe()}"
        )


# -- 5. ops plug --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Socket:
    name: str
    signature: str
    byte_offset: int
    filled_by: str = ""

    def alt(self) -> str:
        who = self.filled_by or "empty in this drawing"
        return f"{self.name} at offset {self.byte_offset}: {who}"


@dataclass(frozen=True)
class OpsPlug:
    """A table of function pointers as a row of sockets, with what is plugged into each.

    An empty socket here does not mean the kernel leaves it null. It means nobody told this
    drawing what is in it, and what sits in a function pointer is a fact about a running kernel
    rather than a fact about a type. BTF can tell you the socket exists and what shape a plug
    has to be. Only a live machine can tell you what is in it.
    """

    primitive = "ops-plug"

    name: str
    instance: str
    sockets: tuple[Socket, ...]

    @classmethod
    def of(cls, table: OpsTable):
        sockets = tuple(
            Socket(one.name, one.signature, one.byte_offset, one.filled_by or "")
            for one in table.slots
        )
        return cls(table.name, table.instance or "", sockets)

    @property
    def filled(self) -> tuple[Socket, ...]:
        return tuple(one for one in self.sockets if one.filled_by)

    def alt(self) -> str:
        head = f"{self.name}"
        if self.instance:
            head += f", the {self.instance} instance"
        body = ". ".join(one.alt() for one in self.sockets)
        return f"{head}, {len(self.sockets)} sockets. {body}"


# -- 6. trace cell and 7. CPU lane ----------------------------------------------------------------


@dataclass(frozen=True)
class TraceCell:
    """One call from a trace, as wide as it took and at the depth it was called from.

    `left` and `width` are percentages, and they come from `kxray.layout` rather than from
    anything here, so an animated tape and a drawn tape of the same trace agree box for box.
    """

    primitive = "trace-cell"

    name: str
    row: int
    left: float
    width: float
    duration_us: float | None
    to_scale: bool
    marker: str = ""

    @classmethod
    def of(cls, span: Span, base_depth: int = 0):
        f = span.frame
        return cls(
            name=f.name,
            row=f.depth - base_depth,
            left=span.left,
            width=span.width,
            duration_us=f.duration_us,
            to_scale=span.to_scale,
            marker=f.marker or "",
        )

    def alt(self) -> str:
        if self.duration_us is None:
            took = "duration unknown"
        else:
            took = f"{self.duration_us:.3f} microseconds"
        note = "" if self.to_scale else ", placed by call order and not by time"
        return f"{self.name} at depth {self.row}, {took}{note}"


@dataclass(frozen=True)
class CpuLane:
    """One CPU's worth of trace cells.

    There is one of these per CPU and not one per trace file. The trace file interleaves every
    CPU into one stream, so a reader who follows the indentation down the page is following two
    call stacks at once and does not know it. Splitting them into lanes is most of the point.
    """

    primitive = "cpu-lane"

    cpu: int
    cells: tuple[TraceCell, ...] = field(default_factory=tuple)

    @property
    def rows(self) -> int:
        return max((one.row for one in self.cells), default=-1) + 1

    def alt(self) -> str:
        names = ", ".join(one.name for one in self.cells[:6])
        more = f" and {len(self.cells) - 6} more" if len(self.cells) > 6 else ""
        return f"CPU {self.cpu}, {len(self.cells)} calls: {names}{more}"


def lanes(tape: Tape, *, max_depth: int | None = None) -> list[CpuLane]:
    """Split a tape into one lane per CPU, in CPU order."""
    per_cpu: dict[int, list[TraceCell]] = {}
    for root in tape.roots:
        placed = place(root)
        if max_depth is not None:
            placed = [s for s in placed if s.frame.depth - root.depth <= max_depth]
        for span in placed:
            per_cpu.setdefault(span.frame.cpu, []).append(TraceCell.of(span, root.depth))
    return [CpuLane(cpu, tuple(per_cpu[cpu])) for cpu in sorted(per_cpu)]


# -- 8. context badge ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextBadge:
    """Which of the six contexts this is, and what that context will not let you do.

    This exists as its own shape because it goes on other shapes. A frame card carries one, a
    trace cell carries one, and a scene about locking is mostly this shape changing.
    """

    primitive = "context-badge"

    context: Context

    @classmethod
    def of(cls, key: str):
        return cls(context(key))

    @property
    def glyph(self) -> str:
        return self.context.badge

    def alt(self) -> str:
        return self.context.describe()


# -- 9. memory slot -----------------------------------------------------------------------------


@dataclass(frozen=True)
class MemorySlot:
    """A chunk of memory, drawn at a width you can actually compare against another one.

    The width is logarithmic and it has to be. A page is 4096 bytes and a `struct file` is about
    230, and drawn to scale next to a 2 megabyte huge page the file is a hairline and the page is
    a hairline and the reader learns nothing. On a log scale the ordering survives and the shapes
    stay visible, which is the trade every one of these pictures makes.

    The caption always prints the real size in bytes, because a log scale that does not say it is
    a log scale is just a wrong picture.
    """

    primitive = "memory-slot"

    label: str
    size_bytes: int
    note: str = ""

    def __post_init__(self) -> None:
        if self.size_bytes < 1:
            raise ValueError(f"{self.label} has size {self.size_bytes}, and zero has no width")

    def width(self, largest: int) -> float:
        """A fraction between 0 and 1, against the biggest slot in the same picture."""
        if largest < 1:
            raise ValueError("the largest slot in a picture cannot be smaller than one byte")
        return (log2(self.size_bytes) + 1) / (log2(largest) + 1)

    def alt(self) -> str:
        parts = [f"{self.label}, {self.size_bytes} bytes"]
        if self.note:
            parts.append(self.note)
        return ", ".join(parts)


def scale(slots: list[MemorySlot]) -> list[tuple[MemorySlot, float]]:
    """Every slot with its width, measured against the biggest one in the set."""
    if not slots:
        return []
    largest = max(one.size_bytes for one in slots)
    return [(one, one.width(largest)) for one in slots]


def cards_from(frames: list[Frame], *, paths: dict[str, str], ran_in: str) -> list[FrameCard]:
    """Frame cards for a list of frames, given a table of which file each one lives in.

    The table has to be written by hand. That is the honest cost of colouring a trace by
    subsystem, and it is why most scenes colour four or five frames rather than forty.
    """
    return [FrameCard.of(one.name, path=paths.get(one.name), ran_in=ran_in) for one in frames]
