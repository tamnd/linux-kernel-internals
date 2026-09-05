"""One arrangement of shapes, worked out once, for all three things that draw a trace.

    from kxray.trace import parse_file
    from kxshapes.scene import scene_of

    scene = scene_of(parse_file("corpora/traces/tier0/write-1k.txt"), subject="a 1 KB write")
    print(scene.table())
    print(scene.uses())

The problem this fixes was three conversions, not three renderers. Three renderers is the design.
Three conversions is the bug, and there were three: `kxwidgets/tape.py` walked the frames and built
its own `TraceCell` for each one, `tools/bpcgen.py` printed the indented text tree and drew no
shapes at all, and a `kxmanim` storyboard listed the primitives it used in a hand written TOML
field with no trace behind it. So the notebook, the blueprint and the animation of one capture were
three separate readings of it that happened to agree, and nothing would have said so on the day
they stopped.

Now there is one reading. A `Scene` is a tape turned into lanes of `Step`s, each step holding one
of the nine shapes and the words that go with it, in call order. What each renderer does with that
is the part that is allowed to differ:

    kxwidgets   draws every step at once, positioned by lane, row, left and width
    bpc         prints the steps in order as a table, which is what a blueprint can carry
    kxmanim     reveals the steps in order, and checks its `shows` field against `uses()`

The words are here rather than in a renderer for the same reason the numbers are. `Step.detail` is
the hover text on a box in a notebook, the note column in a blueprint table and the spoken alt text
under an animation, and those three saying different things about the same call is the failure the
whole exercise is trying to make impossible.

What this does not do is decide anything a capture cannot answer. Position from the left is call
order and never a clock, because `function_graph` records how long a call took and not when it
started, and `Scene.to_scale` is False the moment any branch in it lost a duration. A renderer that
wants to draw a warning about that reads the flag rather than working it out again.
"""

from __future__ import annotations

from dataclasses import dataclass

from kxray.layout import Span, place
from kxray.models import DURATION_MARKERS, Frame, Tape, grid
from kxshapes import PRIMITIVES, CpuLane, TraceCell


@dataclass(frozen=True)
class Step:
    """One shape in a scene, the words that belong to it, and where it comes in the order.

    `order` is call order across the whole scene and it is what an animation reveals along. A
    widget ignores it and draws everything at once, which is the point of keeping it as a number
    on the step rather than as the shape of the data.
    """

    order: int
    lane: int
    shape: TraceCell
    detail: str

    @property
    def primitive(self) -> str:
        return self.shape.primitive

    @property
    def row(self) -> int:
        return self.shape.row

    def alt(self) -> str:
        return self.shape.alt()


@dataclass(frozen=True)
class Lane:
    """One horizontal band of the scene, which is either an outermost call or one CPU.

    Both arrangements are lanes because both are drawn the same way and only the label differs.
    Splitting a trace by CPU is a different question from splitting it by call, and a reader who
    has learned to read one band has learned to read the other.
    """

    index: int
    label: str
    steps: tuple[Step, ...]

    @property
    def rows(self) -> int:
        """How many levels deep this lane goes, counting from its own outermost frame."""
        return max((one.row for one in self.steps), default=-1) + 1

    def alt(self) -> str:
        names = ", ".join(one.shape.name for one in self.steps[:6])
        more = f" and {len(self.steps) - 6} more" if len(self.steps) > 6 else ""
        return f"{self.label}, {len(self.steps)} calls: {names}{more}"


@dataclass(frozen=True)
class Scene:
    """A capture arranged into shapes, once, for every renderer that wants to show it.

    `to_scale` is the honest flag and it is False if any single box in the scene was placed by
    counting rather than by timing. It is not per box because a reader does not read a picture box
    by box: one guessed width shifts everything to the right of it, so the caption under the whole
    picture is where that belongs. The individual boxes carry it too, for the ones that want to
    outline the guessed ones, which the tape widget does.
    """

    id: str
    subject: str
    lanes: tuple[Lane, ...]
    to_scale: bool
    source: str = ""
    by_cpu: bool = False

    @property
    def steps(self) -> tuple[Step, ...]:
        """Every step in the scene in call order, which is the order an animation reveals."""
        out = [one for lane in self.lanes for one in lane.steps]
        return tuple(sorted(out, key=lambda one: one.order))

    @property
    def empty(self) -> bool:
        return not any(lane.steps for lane in self.lanes)

    def lane(self, index: int) -> Lane:
        return self.lanes[index]

    def cells(self, index: int) -> tuple[TraceCell, ...]:
        """The shapes of one lane and nothing else, for a renderer that wants only boxes."""
        return tuple(one.shape for one in self.lanes[index].steps)

    def uses(self) -> list[str]:
        """Which of the nine primitives are actually in here, in the order the nine are listed.

        This is what a storyboard's `shows` field gets checked against. A beat that claims to show
        a CPU lane over a capture from a uniprocessor box is claiming something the trace cannot
        support, and before this existed nothing anywhere would have noticed.
        """
        seen = {one.primitive for lane in self.lanes for one in lane.steps}
        if len(self.lanes) > 1 and self.by_cpu:
            seen.add(CpuLane.primitive)
        return [one for one in PRIMITIVES if one in seen]

    def table(self) -> str:
        """The scene as text, which is what a blueprint and a screen reader both get.

        Ordered rather than nested. The indented tree is a better picture of the shape of a call
        and a worse one of what the drawing is doing, and a blueprint that prints the tree next to
        a notebook that draws boxes is two pictures a reader has to reconcile by hand.
        """
        rows: list[tuple[str, ...]] = [("#", "lane", "depth", "call", "took", "width", "note")]
        for one in self.steps:
            took = "unknown" if one.shape.duration_us is None else f"{one.shape.duration_us:.3f}"
            rows.append(
                (
                    str(one.order),
                    self.lanes[one.lane].label,
                    str(one.row),
                    one.shape.name,
                    took,
                    f"{one.shape.width:.1f}%",
                    "" if one.shape.to_scale else "placed by call order",
                )
            )
        return grid(rows)

    def alt(self) -> str:
        """What the whole picture says, in one paragraph, for a reader who gets no picture."""
        if self.empty:
            return f"{self.subject}: nothing was captured, so there is nothing to draw"
        count = sum(len(lane.steps) for lane in self.lanes)
        band = "CPU" if self.by_cpu else "call"
        scale = (
            "every box is as wide as the call took"
            if self.to_scale
            else "some boxes were placed by call order because a duration is missing"
        )
        return (
            f"{self.subject}: {count} calls in {len(self.lanes)} {band} lanes, "
            f"{max(lane.rows for lane in self.lanes)} levels deep at the deepest, and {scale}."
        )


def detail_of(frame: Frame, span: Span) -> str:
    """Every number about one call that did not fit inside its box.

    One function, used three times. This is the hover text in a notebook, the note under a still
    and what a screen reader reads, and the reason it is not three strings written in three places
    is that two of them would drift and nobody would find out from looking at either.
    """
    parts = [f"{frame.name}()", f"cpu {frame.cpu}", f"depth {frame.depth}"]
    if frame.duration_us is None:
        parts.append("duration unknown")
    else:
        parts.append(f"{frame.duration_us:.3f} us")
        if frame.self_time_us is not None and frame.children:
            parts.append(f"{frame.self_time_us:.3f} us in itself")
    if frame.marker:
        parts.append(f"marker {frame.marker}, {DURATION_MARKERS[frame.marker]}")
    if not frame.complete:
        parts.append("never closed, so the trace was cut off here")
    if not span.to_scale:
        parts.append("width is call order, not time")
    return "\n".join(parts)


def spans_of(root: Frame, max_depth: int | None = None) -> list[Span]:
    """One outermost call laid out, cut off below `max_depth` if there is one.

    `max_depth` counts from that root and not from the top of the trace, so asking for three
    levels of a frame that was already six deep gives three, which is what the reader asked for.
    """
    placed = place(root)
    if max_depth is None:
        return placed
    return [one for one in placed if one.frame.depth - root.depth <= max_depth]


def cells(source: Tape | Frame, *, max_depth: int | None = None) -> list[list[TraceCell]]:
    """The boxes, one list per outermost call, for anything that wants no words with them.

    A convenience over `scene_of` rather than a second route to the same answer: it calls the same
    layout on the same frames, so a caller that uses this and a caller that uses the scene get
    boxes in identical places.
    """
    scene = scene_of(source, max_depth=max_depth)
    return [list(scene.cells(index)) for index in range(len(scene.lanes))]


def scene_of(
    source: Tape | Frame,
    *,
    max_depth: int | None = None,
    by_cpu: bool = False,
    id: str = "",
    subject: str = "",
) -> Scene:
    """A tape or one frame out of it, arranged into lanes of steps.

    `by_cpu` splits by CPU instead of by outermost call, which is a different question about the
    same file. The trace interleaves every CPU into one stream, so a reader following the
    indentation down the page can be following two call stacks at once and have nothing to tell
    them so.
    """
    roots = [source] if isinstance(source, Frame) else list(source.roots)
    tape = source if isinstance(source, Tape) else Tape(roots=roots)
    subject = subject or _subject(source, roots)
    origin = tape.source if isinstance(source, Tape) else ""

    built = _by_cpu(roots, max_depth) if by_cpu else _by_call(roots, max_depth)

    to_scale = all(one.shape.to_scale for lane in built for one in lane.steps)
    return Scene(
        id=id or (origin or subject).replace(" ", "-"),
        subject=subject,
        lanes=tuple(built),
        to_scale=to_scale,
        source=origin,
        by_cpu=by_cpu,
    )


def _by_call(roots: list[Frame], max_depth: int | None) -> list[Lane]:
    """One lane per outermost call, which is what a tape of a single syscall looks like."""
    out: list[Lane] = []
    order = 0
    for index, root in enumerate(roots):
        steps: list[Step] = []
        for span in spans_of(root, max_depth):
            steps.append(
                Step(
                    order=order,
                    lane=index,
                    shape=TraceCell.of(span, root.depth),
                    detail=detail_of(span.frame, span),
                )
            )
            order += 1
        out.append(Lane(index=index, label=f"{root.name} on cpu {root.cpu}", steps=tuple(steps)))
    return out


def _by_cpu(roots: list[Frame], max_depth: int | None) -> list[Lane]:
    """One lane per CPU, in CPU order, walking the same spans as everything else here.

    This does the same walk `kxshapes.lanes` does rather than calling it, and the reason is the
    words. A `CpuLane` hands back cells, a cell does not carry the frame it came from, and lining
    the two lists up by position would be correct today and quietly wrong the first time either
    walk changed what it filters. `test_a_cpu_scene_holds_the_same_cells_as_the_lane_function`
    asserts the two agree cell for cell, which is the check that keeps them honest.
    """
    per_cpu: dict[int, list[tuple[TraceCell, str]]] = {}
    for root in roots:
        for span in spans_of(root, max_depth):
            per_cpu.setdefault(span.frame.cpu, []).append(
                (TraceCell.of(span, root.depth), detail_of(span.frame, span))
            )

    out: list[Lane] = []
    order = 0
    for index, cpu in enumerate(sorted(per_cpu)):
        steps: list[Step] = []
        for cell, detail in per_cpu[cpu]:
            steps.append(Step(order=order, lane=index, shape=cell, detail=detail))
            order += 1
        out.append(Lane(index=index, label=f"cpu {cpu}", steps=tuple(steps)))
    return out


def _subject(source: Tape | Frame, roots: list[Frame]) -> str:
    """What the scene is of, in words, when the caller did not say."""
    if not roots:
        return "an empty trace"
    if isinstance(source, Frame):
        return f"{source.name} on cpu {source.cpu}"
    if len(roots) == 1:
        return f"{roots[0].name} on cpu {roots[0].cpu}"
    return f"{len(roots)} calls from {source.source or 'a trace'}"
