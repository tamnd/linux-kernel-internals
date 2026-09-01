"""Where a box goes when you draw a trace.

This is arithmetic, not drawing. It turns a tree of frames into a list of rectangles expressed as
percentages, and then a widget renders those as `<div>` and an animation renders the same ones as
manim rectangles. Both get the identical answer because both call this.

That matters more than it sounds. A lesson shows a tape and then shows an animation of the same
trace thirty seconds later, and if the wide box is in a different place in the two of them the
reader concludes, correctly, that one of the pictures is lying.

The one thing to keep in mind is what the numbers mean. `function_graph` records how long a call
took and never when it started, so a width is a duration and a left edge is only the order things
were called in. When a duration is missing anywhere in a branch the whole branch falls back to
equal widths and every box in it is marked `to_scale=False`, so a renderer can say so.
"""

from __future__ import annotations

from dataclasses import dataclass

from kxray.models import Frame


@dataclass(frozen=True)
class Span:
    """One frame, placed. `left` and `width` are percentages of the whole tape.

    `to_scale` is false when this box was placed by counting rather than by timing, which happens
    whenever a parent or one of its children has no duration. An incomplete frame at the edge of
    the ring buffer is the usual cause, and it is normal input rather than a broken trace.
    """

    frame: Frame
    left: float
    width: float
    to_scale: bool

    @property
    def row(self) -> int:
        return self.frame.depth


def place(
    frame: Frame, left: float = 0.0, width: float = 100.0, *, to_scale: bool = True
) -> list[Span]:
    """Work out where every box under this frame goes.

    Children are laid out from the left in call order, each one as wide as its share of the
    parent's duration. When any of that is unknown the children split the parent's width evenly
    instead, and every box placed that way is marked, so nobody reads a width as a measurement
    when it is a guess.
    """
    spans = [Span(frame, left, width, to_scale)]
    children = frame.children
    if not children:
        return spans

    durations = [child.duration_us for child in children]
    total = frame.duration_us
    known = all(one is not None for one in durations)
    spent = sum(one or 0.0 for one in durations)
    # Durations are rounded to three decimals on their way out of the kernel, so a set of children
    # can add up to a hair more than the parent without anything being wrong. A whole percent of
    # slack absorbs that, and anything past it means the numbers do not describe this tree.
    fits = total is not None and total > 0 and spent <= total * 1.01
    scaled = to_scale and known and fits

    if scaled:
        cursor = left
        for child in children:
            share = width * ((child.duration_us or 0.0) / (total or 1.0))
            spans.extend(place(child, cursor, share, to_scale=True))
            cursor += share
        return spans

    share = width / len(children)
    for index, child in enumerate(children):
        spans.extend(place(child, left + index * share, share, to_scale=False))
    return spans
