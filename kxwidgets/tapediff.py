"""TapeDiff: two traces one above the other, with what changed marked on both.

One trace is data. Two traces are a transformation, and the transformation is usually the thing the
lesson is about. What did turning the option on change? What is different when the file is already
in the page cache? A reader can answer that from two tapes drawn separately, by looking back and
forth, and they will miss things, because a function that appears in one and not the other is one
box in about sixty.

    from kxray.trace import function_graph
    from kxwidgets import TapeDiff

    TapeDiff(cold, warm, labels=("cold cache", "warm cache"))

The verdict comes from `kxdiff` and is not worked out again here. `kxdiff` already answers the two
questions that make a comparison repeatable, which are what is being compared and how strictly, so
this widget takes a policy and a level and shows the answer rather than having opinions of its own.
The default pair is the one worth asking most often: did the same operation take the same path,
with the machine's own noise left out.

Three things about reading one, and the first is the one people get wrong.

The two tapes are on separate scales by default. Each is a hundred percent of its own total, so a
box that looks the same width on both sides is the same fraction of its own trace and not the same
number of microseconds. That is the right default because it is the comparison that survives a
change of machine, and it is the wrong one when the question is whether something got faster. Pass
`shared_scale=True` for that, and both tapes are drawn against the longer of the two, so the
shorter one ends part way across and the difference is the empty space.

The marking is about names and not about times. A box gets a ring and a dot in front of its name
when that function appears on its side and not on the other, which is a fact about the trace.
Whether a box got wider is a fact about a clock, and on Tier 0 the clock is v86, so this widget
marks nothing for being slower. The ring is a channel of its own rather than a change of fill,
because the fill already means the duration marker and the border already means whether the width
is a measurement, and a colour with two jobs is a colour a reader cannot trust.

Frames the policy dropped are drawn faintly rather than left out. A comparison that quietly removes
a third of a trace and reports a pass has told the truth and shown something else, and the faint
boxes are the difference between those two.
"""

from __future__ import annotations

from kxdiff import SAME_OPERATION, SEQUENCE, Level, Policy, diff
from kxray.layout import Span, place
from kxray.models import Frame, Tape
from kxshapes import TraceCell
from kxwidgets.html import BAND, MONO, MUTED, Widget, card, style, tag, text
from kxwidgets.shapes import ROW_GAP, ROW_HEIGHT, trace_cell

# Tinted when a function is on this side and not the other. Two colours rather than one, because
# something that appeared and something that went away are different news.
ONLY_LEFT = "#c0504d"
ONLY_RIGHT = "#3f8f3f"


class TapeDiff(Widget):
    """Two traces, drawn as tapes, with the frames that are only on one side marked.

    `level` and `policy` come from `kxdiff` and decide the verdict in the subtitle. They do not
    decide the marking, which is always about which names appear where, so a comparison that
    passes at `set` can still have every box unmarked while the verdict above them says they
    differ, because `set` does not care what order things happened in and `sequence` does.
    """

    def __init__(
        self,
        one: Tape | Frame,
        other: Tape | Frame,
        *,
        labels: tuple[str, str] = ("before", "after"),
        level: Level = SEQUENCE,
        policy: Policy = SAME_OPERATION,
        max_depth: int | None = None,
        shared_scale: bool = False,
        title: str = "",
    ) -> None:
        self.tapes = (_as_tape(one), _as_tape(other))
        self.labels = labels
        self.level = level
        self.policy = policy
        self.max_depth = max_depth
        self.shared_scale = shared_scale
        self.title = title or f"{labels[0]} against {labels[1]}"
        self.answer = diff(*self.tapes, level=level, policy=policy, labels=labels)

    # -- what gets drawn --------------------------------------------------------------------

    def kept(self) -> tuple[set[str], set[str]]:
        """The function names each side has, after the policy has taken its frames out."""
        return tuple({frame.name for frame in self.policy.keep(tape)} for tape in self.tapes)

    def only_on_one_side(self) -> tuple[set[str], set[str]]:
        left, right = self.kept()
        return left - right, right - left

    def widths(self) -> tuple[float, float]:
        """How much of the drawing each tape gets, which is the whole width unless sharing.

        Sharing needs both totals, and a tape with an incomplete frame at the edge of the ring
        buffer may not have one. When either is missing the request is refused rather than
        half honoured, because a shared scale that silently is not one is the worst outcome here.
        """
        if not self.shared_scale:
            return (100.0, 100.0)
        totals = [_total(tape) for tape in self.tapes]
        if not all(totals) or not max(totals):
            return (100.0, 100.0)
        longest = max(totals)
        return tuple(100.0 * (total / longest) for total in totals)

    def sharing(self) -> bool:
        """Whether the shared scale was asked for and could be honoured."""
        return self.shared_scale and self.widths() != (100.0, 100.0)

    def cells(self) -> tuple[list[TraceCell], list[TraceCell]]:
        """The boxes on each side, so an animation of the same comparison gets the same ones."""
        return tuple(
            [
                TraceCell.of(span, root.depth)
                for root, placed in self._placed(tape, width)
                for span in placed
            ]
            for tape, width in zip(self.tapes, self.widths(), strict=True)
        )

    def _placed(self, tape: Tape, width: float) -> list[tuple[Frame, list[Span]]]:
        out = []
        for root in tape.roots:
            placed = place(root, 0.0, width)
            if self.max_depth is not None:
                placed = [s for s in placed if s.frame.depth - root.depth <= self.max_depth]
            out.append((root, placed))
        return out

    # -- drawing ----------------------------------------------------------------------------

    def _in_the_comparison(self, tape: Tape) -> set[int]:
        """The frames the policy kept, by identity rather than by name.

        By name would be close and would be wrong in the case that matters. `same-operation` drops
        frames belonging to another task, and the function another task was in is very often a
        function the traced program calls too, so a name based answer would fade boxes that were
        compared and kept ones that were not.
        """
        return {id(frame) for frame in self.policy.keep(tape)}

    def html(self) -> str:
        left, right = self.only_on_one_side()
        body = "".join(
            self._one_side(tape, label, width, only, tint)
            for tape, label, width, only, tint in zip(
                self.tapes,
                self.labels,
                self.widths(),
                (left, right),
                (ONLY_LEFT, ONLY_RIGHT),
                strict=True,
            )
        )
        return card(self.title, self.answer.summary(), body, self._footnote(), fallback=self.text())

    def _one_side(
        self,
        tape: Tape,
        label: str,
        width: float,
        only: set[str],
        tint: str,
    ) -> str:
        compared = self._in_the_comparison(tape)
        head = tag(
            "div",
            text(f"{label}  {tape.source or 'no source'}"),
            style_=style(font_family=MONO, font_size="11px", color=MUTED, margin_bottom="2px"),
        )
        blocks = "".join(
            self._one_tape(root, placed, only, tint, compared)
            for root, placed in self._placed(tape, width)
        )
        return tag("div", head + (blocks or self._nothing()), style_=style(margin_bottom="14px"))

    def _one_tape(
        self,
        root: Frame,
        placed: list[Span],
        only: set[str],
        tint: str,
        compared: set[int],
    ) -> str:
        rows = max(span.frame.depth - root.depth for span in placed) + 1
        boxes = "".join(
            trace_cell(
                TraceCell.of(span, root.depth),
                hover=self._hover(span, only, compared),
                marked=tint if span.frame.name in only else "",
                faded=id(span.frame) not in compared,
            )
            for span in placed
        )
        return tag(
            "div",
            boxes,
            style_=style(
                position="relative",
                height=f"{rows * (ROW_HEIGHT + ROW_GAP)}px",
                margin_bottom="4px",
                background=BAND,
                border_radius="3px",
            ),
        )

    def _hover(self, span: Span, only: set[str], compared: set[int]) -> str:
        frame = span.frame
        parts = [f"{frame.name}()", f"depth {frame.depth}"]
        if frame.duration_us is not None:
            parts.append(f"{frame.duration_us:.3f} us")
        if id(frame) not in compared:
            parts.append(f"left out of the comparison by the {self.policy.name} policy")
        elif frame.name in only:
            parts.append("only on this side")
        return "\n".join(parts)

    def _nothing(self) -> str:
        return tag(
            "div",
            text("nothing on this side"),
            style_=style(font_size="12px", color=MUTED, padding="6px 0"),
        )

    def _footnote(self) -> str:
        left, right = self.only_on_one_side()
        note = (
            f"A ringed box with a dot in front of the name is a function that is only on its own "
            f"side, {len(left)} of them in {self.labels[0]} and {len(right)} in {self.labels[1]}. "
            "The ring is about which functions appear where, which is a fact about the trace. "
            "Whether a box got wider is a fact about a clock, so nothing here is marked for being "
            "slower."
        )
        note += " " + self._about_the_scale()
        if any(self.answer.dropped):
            note += (
                f" The faint boxes were left out of the comparison by the {self.policy.name} "
                f"policy, {self.answer.dropped[0]} of them on the left and "
                f"{self.answer.dropped[1]} on the right. They are drawn rather than removed, "
                "because a pass over most of a trace and a pass over all of it are different "
                "results."
            )
        if not self.answer.same:
            note += " " + "; ".join(self.answer.differences[:3])
        return note

    def _about_the_scale(self) -> str:
        if self.sharing():
            longest = self.labels[0] if self.widths()[0] >= self.widths()[1] else self.labels[1]
            return (
                f"Both tapes are drawn against {longest}, which is the longer of the two, so the "
                "empty space at the right of the shorter one is the difference between them."
            )
        if self.shared_scale:
            return (
                "A shared scale was asked for and could not be given, because one of these tapes "
                "has no total duration. Each is drawn as a hundred percent of its own again."
            )
        return (
            "Each tape is a hundred percent of its own total, so a box the same width on both "
            "sides is the same share of its own trace and not the same number of microseconds. "
            "Pass shared_scale=True when the question is whether something got faster."
        )

    def text(self) -> str:
        left, right = self.only_on_one_side()
        lines = [self.answer.summary()]
        for label, names in zip(self.labels, (left, right), strict=True):
            lines.append(f"only in {label}: {', '.join(sorted(names)) or 'nothing'}")
        return "\n".join(lines)


def _as_tape(tape: Tape | Frame) -> Tape:
    return tape if isinstance(tape, Tape) else Tape(roots=[tape])


def _total(tape: Tape) -> float | None:
    """How long the whole tape took, or nothing when any outermost call has no duration."""
    if not tape.roots:
        return None
    if any(root.duration_us is None for root in tape.roots):
        return None
    return sum(root.duration_us or 0.0 for root in tape.roots)
