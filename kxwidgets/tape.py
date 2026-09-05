"""SyscallTape: a function_graph trace as a picture instead of as four hundred lines.

A trace is a wall of text, and a beginner reading one has to hold the indentation, the closing
braces and the durations in their head at the same time. The same trace as a tape is one glance:
the outermost call is the bar across the top, everything it called is the row underneath, and the
slow thing is the wide box.

    from kxray.trace import function_graph
    from kxwidgets import SyscallTape

    SyscallTape(function_graph.parse(text))

One thing this cannot do, and says so under every tape it draws. `function_graph` records how long
each call took and not when it started, so a box's width is a duration and a box's horizontal
position is only the order it was called in. Children are drawn back to back from the left, and
the gap left at the right hand end of a parent is the time the parent spent in itself. That gap is
real, and where it sits is a drawing convention.

This widget works nothing out for itself. It asks `kxshapes.scene` for the arrangement and draws
what comes back, boxes and hover text both. That is a longer route than this used to take and it is
the whole point: the animation of the same trace and the table in the blueprint are handed the same
scene, so the wide box is in the same place in all three and none of them worked it out alone.

`by_cpu=True` draws one lane per CPU instead of one block per outermost call. The trace file
interleaves every CPU into a single stream, so a reader following the indentation down the page is
following two call stacks at once with nothing to warn them.
"""

from __future__ import annotations

from kxray.models import Frame, Tape
from kxshapes.scene import Lane, Scene, scene_of
from kxwidgets.html import MUTED, Widget, card, style, tag
from kxwidgets.shapes import scene_lane


class SyscallTape(Widget):
    """A whole tape, or one frame out of it, drawn as rows of boxes.

    `max_depth` counts from the outermost frame, so `max_depth=3` gives you the first three levels
    and hides everything under them. On a real write that takes the drawing from a hundred boxes
    to about a dozen, which is the difference between a picture and a smear.
    """

    def __init__(
        self,
        tape: Tape | Frame,
        *,
        max_depth: int | None = None,
        title: str = "",
        by_cpu: bool = False,
    ) -> None:
        self.roots = [tape] if isinstance(tape, Frame) else list(tape.roots)
        self.tape = tape if isinstance(tape, Tape) else None
        self.max_depth = max_depth
        self.by_cpu = by_cpu
        self.title = title or "Function graph tape"

    # -- what gets drawn --------------------------------------------------------------------

    def scene(self) -> Scene:
        """The arrangement, which this widget asks for and does not work out.

        Built fresh on each call rather than in `__init__`, because `by_cpu` and `max_depth` are
        what change it and a reader in a notebook flips those by making a second widget.
        """
        return scene_of(
            self.tape if self.tape is not None else self.roots[0],
            max_depth=self.max_depth,
            by_cpu=self.by_cpu,
            subject=self.title,
        )

    def lanes(self) -> list[Lane]:
        """The bands of the scene, which are calls or CPUs depending on `by_cpu`."""
        return list(self.scene().lanes)

    @property
    def subtitle(self) -> str:
        if self.tape is None:
            root = self.roots[0]
            return f"{root.name} on cpu {root.cpu}"
        parts = [
            f"{self.tape.frame_count} calls",
            f"cpu {', '.join(str(c) for c in self.tape.cpus) or 'unknown'}",
            f"from {self.tape.source}",
        ]
        if self.tape.unparsed:
            parts.append(f"{len(self.tape.unparsed)} unparsed lines")
        return "  ".join(parts)

    # -- drawing ----------------------------------------------------------------------------

    def html(self) -> str:
        if not self.roots:
            body = tag(
                "div",
                "There is nothing in this tape. Nothing was captured, or every line was filtered "
                "out before it got here.",
                style_=style(font_size="13px", color=MUTED),
            )
            return card(self.title, self.subtitle, body, fallback=self.text())

        scene = self.scene()
        body = "".join(scene_lane(one, labelled=self.by_cpu) for one in scene.lanes)
        return card(
            self.title,
            self.subtitle,
            body,
            self._footnote(not scene.to_scale),
            fallback=self.text(),
        )

    def _footnote(self, guessed: bool) -> str:
        note = (
            "Width is duration. Position from left is call order and not a clock, because "
            "function_graph records how long a call took and not when it started. The gap at the "
            "right hand end of a call is the time it spent in itself rather than in anything it "
            "called."
        )
        if guessed:
            note += (
                " The boxes with a red outline were placed by counting rather than by timing, "
                "because something in that branch has no duration."
            )
        if self.by_cpu:
            note += (
                " One strip per CPU. The trace file interleaves them into a single stream, so the "
                "indentation in the raw text can be two call stacks at once."
            )
        return note

    def text(self) -> str:
        if not self.roots:
            return "no frames"
        if self.by_cpu:
            return "\n".join(one.alt() for one in self.lanes())
        return "\n\n".join(root.tree(self.max_depth) for root in self.roots)
