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

The arithmetic that turns frames into rectangles lives in `kxray.layout`, because the animation of
a trace has to put the wide box in the same place this does.
"""

from __future__ import annotations

from kxray.layout import Span, place
from kxray.models import DURATION_MARKERS, Frame, Tape
from kxwidgets.html import BAND, INK, MARKERS, MONO, MUTED, Widget, card, style, tag, text

ROW_HEIGHT = 22
ROW_GAP = 2


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
    ) -> None:
        self.roots = [tape] if isinstance(tape, Frame) else list(tape.roots)
        self.tape = tape if isinstance(tape, Tape) else None
        self.max_depth = max_depth
        self.title = title or "Function graph tape"

    # -- what gets drawn --------------------------------------------------------------------

    def spans(self) -> list[list[Span]]:
        """One list of spans per outermost call, already filtered by `max_depth`."""
        out = []
        for root in self.roots:
            placed = place(root)
            if self.max_depth is not None:
                placed = [s for s in placed if s.frame.depth - root.depth <= self.max_depth]
            out.append(placed)
        return out

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

        blocks = []
        guessed = False
        for placed in self.spans():
            guessed = guessed or any(not span.to_scale for span in placed)
            blocks.append(self._one_tape(placed))
        return card(
            self.title,
            self.subtitle,
            "".join(blocks),
            self._footnote(guessed),
            fallback=self.text(),
        )

    def _one_tape(self, placed: list[Span]) -> str:
        root = placed[0].frame
        rows = max(span.frame.depth - root.depth for span in placed) + 1
        height = rows * (ROW_HEIGHT + ROW_GAP)
        boxes = "".join(self._box(span, root.depth) for span in placed)
        return tag(
            "div",
            boxes,
            style_=style(
                position="relative",
                height=f"{height}px",
                margin_bottom="14px",
                background=BAND,
                border_radius="3px",
            ),
        )

    def _box(self, span: Span, base_depth: int) -> str:
        frame = span.frame
        row = frame.depth - base_depth
        colour = MARKERS.get(frame.marker or "", MARKERS[""])
        border = "#ffffff" if span.to_scale else "#b04040"
        label = tag(
            "span",
            text(_shorten(frame.name)),
            style_=style(
                font_family=MONO,
                font_size="11px",
                line_height=f"{ROW_HEIGHT}px",
                padding_left="4px",
            ),
        )
        return tag(
            "div",
            label,
            title=self._title(span),
            style_=style(
                position="absolute",
                left=f"{span.left:.4f}%",
                width=f"{span.width:.4f}%",
                top=f"{row * (ROW_HEIGHT + ROW_GAP)}px",
                height=f"{ROW_HEIGHT}px",
                min_width="2px",
                box_sizing="border-box",
                background=colour,
                border=f"1px solid {border}",
                border_radius="2px",
                overflow="hidden",
                white_space="nowrap",
                color=INK,
            ),
        )

    def _title(self, span: Span) -> str:
        """The hover text, which is where every number that did not fit in the box goes."""
        frame = span.frame
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
        return note

    def text(self) -> str:
        if not self.roots:
            return "no frames"
        return "\n\n".join(root.tree(self.max_depth) for root in self.roots)


def _shorten(name: str, limit: int = 34) -> str:
    """Kernel function names get long, and a box is only so wide."""
    return name if len(name) <= limit else name[: limit - 3] + "..."
