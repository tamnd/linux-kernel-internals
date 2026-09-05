"""LockTimeline: who held what, for how long, and whether anybody had to wait for it.

This is the fourth of the signature artifacts and it is the one that needs the most care, because
the thing it is drawing is the thing a trace is worst at recording.

    from kxray.trace import function_graph
    from kxwidgets import LockTimeline

    LockTimeline(function_graph.parse(text), timings_are_real=True, title="four writers, one file")

Each row is one lock, taken and dropped inside one function. The sliver on the left is the wait,
which is how long the taking call took. The band after it is the hold, which is as wide as
everything that happened before the dropping call. A row where the sliver is invisible and the band
is long is an uncontended lock. A row where the sliver is most of the width is a lock somebody
queued for, and that is the picture worth having.

`timings_are_real` has to be said and there is no sensible default, which is the one thing about
this widget worth reading before using it. The number a wait is judged on means different things on
the two tiers. Tier 0 is v86, which has one CPU and an emulated clock, so a `down_write` there takes
microseconds because the emulator is slow and there is nothing to queue behind. Tier 1 is a real
machine, where the same number means somebody was holding the lock. Told nothing, the widget draws
every wait and refuses to call any of them contention, which is the right answer rather than a
cautious one.

Four limits, all of which the widget says out loud rather than drawing around.

`function_graph` does not record which lock. It records that `down_write` was called and not what
it was called on, so six writers on six different inodes and six writers on one look the same here.
Telling them apart needs a tracepoint that carries the address, or lockdep, and that is a different
capture. The evidence that the widget is reading the right thing anyway is two captures in
`corpora/traces/tier1/`, taken the same way on the same machine, differing in whether the writers
share a file. Six files and nobody waits, one file and two of them wait about ten milliseconds.

A lock taken in one function and dropped in another is not found at all. The two calls sit in
different subtrees and nothing in the trace says they are the same lock, so guessing would be
inventing.

Position from the left is call order and not a clock, the same as every other tape in this project,
because `function_graph` records durations and never start times. Two bands on two CPUs that look
like they overlap may or may not have overlapped. Width is a measurement. Left edge is not.
"""

from __future__ import annotations

from dataclasses import replace

from kxray.models import Frame, Tape
from kxshapes import LOCK_PAIRS, CpuLane, Hold, holds
from kxwidgets.html import LINE, MONO, MUTED, Widget, card, style, tag, text
from kxwidgets.shapes import cpu_lane

# A band that nobody waited for, and a band somebody queued behind. Contention is the whole
# question, so it is the one thing in this drawing that gets its own colour. The third colour is
# for a row nobody can answer, which happens more often than the other two and should look like an
# absence of an answer rather than like a quiet lock.
QUIET = "#cfe3f5"
CONTENDED = "#f6d3a3"
UNKNOWN = "#e8eef3"


class LockTimeline(Widget):
    """Every lock a trace took and dropped, one row each, grouped by CPU.

    `timings_are_real` says whether the clock behind the capture was a real one, and comes from the
    `timings_are_real` line in the `.meta.toml` next to the trace. Leaving it out is allowed and
    costs the verdict column, which is the intended trade rather than a nuisance.

    `pairs` overrides the table of which call takes a lock and which one drops it, for a lesson
    tracing a lock the default table has never heard of.
    """

    def __init__(
        self,
        tape: Tape | Frame,
        *,
        timings_are_real: bool | None = None,
        pairs: dict[str, str] | None = None,
        title: str = "",
    ) -> None:
        self.tape = tape if isinstance(tape, Tape) else Tape(roots=[tape])
        self.pairs = pairs
        self.timings_are_real = timings_are_real
        self.holds = holds(self.tape, pairs=pairs)
        self.title = title or "Locks taken, and who waited"

    # -- what gets drawn --------------------------------------------------------------------

    @property
    def contended(self) -> list[Hold]:
        """The holds somebody waited for, which is empty when the clock cannot be trusted."""
        return [one for one in self.holds if self.verdict(one) is True]

    def verdict(self, one: Hold) -> bool | None:
        return one.contended(timings_are_real=self.timings_are_real)

    def lanes(self) -> list[CpuLane]:
        """One lane per CPU, one row per hold on that CPU.

        The rows are stacked in the order the locks were taken and they are not a shared clock.
        Each band was placed inside its own outermost call, so two rows in a lane are two separate
        timelines drawn one above the other, and the footnote says so.
        """
        return [
            CpuLane(
                cpu,
                tuple(
                    cell
                    for row, one in enumerate(found)
                    for cell in (replace(one.wait_cell, row=row), replace(one.cell, row=row))
                ),
            )
            for cpu, found in sorted(self._per_cpu().items())
        ]

    def _per_cpu(self) -> dict[int, list[Hold]]:
        found: dict[int, list[Hold]] = {}
        for one in self.holds:
            found.setdefault(one.cpu, []).append(one)
        return found

    # -- drawing ----------------------------------------------------------------------------

    def html(self) -> str:
        if not self.holds:
            return card(self.title, self._subtitle(), self._nothing(), fallback=self.text())
        body = "".join(self._one_cpu(lane) for lane in self.lanes())
        return card(self.title, self._subtitle(), body, self._footnote(), fallback=self.text())

    def _nothing(self) -> str:
        pairs = self.pairs or LOCK_PAIRS
        names = ", ".join(f"{takes} with {drops}" for takes, drops in sorted(pairs.items()))
        return tag(
            "div",
            text(
                "No lock in this trace was both taken and dropped inside the same function, so "
                f"there is nothing to draw. The pairs looked for were {names}. A lock taken in "
                "one function and released in another is invisible here on purpose, because "
                "nothing in the trace says the two calls are about the same lock."
            ),
            style_=style(font_size="13px", color=MUTED, line_height="1.5"),
        )

    def _one_cpu(self, lane: CpuLane) -> str:
        found = self._per_cpu()[lane.cpu]
        tasks = ", ".join(dict.fromkeys(one.task for one in found))
        head = tag(
            "div",
            text(f"cpu {lane.cpu}  {tasks}"),
            style_=style(font_family=MONO, font_size="11px", color=MUTED, margin_bottom="2px"),
        )
        rows = "".join(self._row(one) for one in found)
        return tag(
            "div",
            head + cpu_lane(lane, labelled=False) + rows,
            style_=style(margin_bottom="12px"),
        )

    def _row(self, one: Hold) -> str:
        waited = "unknown" if one.waited_us is None else f"{one.waited_us:.3f} us"
        held = "unknown" if one.held_us is None else f"{one.held_us:.3f} us"
        answer = self.verdict(one)
        verdict = {True: "somebody waited", False: "nobody waited"}.get(answer, "cannot say")
        colour = {True: CONTENDED, False: QUIET}.get(answer, UNKNOWN)
        chip = tag(
            "span",
            text(verdict),
            style_=style(
                background=colour,
                border=f"1px solid {LINE}",
                border_radius="10px",
                padding="1px 8px",
                font_size="11px",
                margin_right="8px",
            ),
        )
        return tag(
            "div",
            chip
            + tag(
                "span",
                text(f"{one.taken_by} inside {one.inside}: waited {waited}, held {held}"),
                style_=style(font_family=MONO, font_size="11px"),
            ),
            style_=style(padding="3px 0"),
        )

    def _subtitle(self) -> str:
        cpus = sorted({one.cpu for one in self.holds})
        parts = [f"{len(self.holds)} lock{'' if len(self.holds) == 1 else 's'} taken"]
        if cpus:
            parts.append(f"cpu {', '.join(str(one) for one in cpus)}")
        if self.timings_are_real:
            parts.append(f"{len(self.contended)} where somebody waited")
        else:
            parts.append("waits shown, contention not judged")
        return "  ".join(parts)

    def _footnote(self) -> str:
        note = (
            "The sliver at the left of a row is the wait, which is how long the taking call took. "
            "The band after it is the hold. Width is a measurement and position from the left is "
            "call order rather than a clock, so two bands that look like they overlap may not "
            "have. Rows in one lane are separate calls stacked up, not one timeline."
        )
        note += " " + self._about_the_clock()
        note += (
            " Which lock each row is about is not in the trace. function_graph records that the "
            "call happened and not what it was called on."
        )
        return note

    def _about_the_clock(self) -> str:
        """Why the verdict column says what it says, which depends entirely on the tier.

        This paragraph is the reason the widget takes the argument at all. A wait of four
        microseconds is contention on a real machine and is the emulator being slow on Tier 0, and
        the two look identical in the trace, so the only honest thing to do is say which one the
        reader is looking at.
        """
        if self.timings_are_real is None:
            return (
                "Nobody said whether the clock behind this trace is a real one, so every wait is "
                "shown and none of them are called contention. The meta file next to the capture "
                "has the answer under timings_are_real, and passing it in fills this column."
            )
        if not self.timings_are_real:
            return (
                "The timings here are emulated, so no wait on this page means anybody queued. "
                "Tier 0 runs in v86 with one CPU, where taking an uncontended lock still costs "
                "microseconds because the emulator is slow and there is no second CPU to wait for."
            )
        if not self.contended:
            return (
                "Nothing here was contended. Every wait is a fraction of a microsecond, which is "
                "what taking an uncontended lock costs on a real machine."
            )
        return (
            f"{len(self.contended)} of these rows waited at least "
            f"{Hold.CONTENDED_US:g} us before the lock was theirs, which on a real machine means "
            "somebody else was holding it."
        )

    def text(self) -> str:
        if not self.holds:
            return "no locks taken and dropped inside one function"
        return "\n".join(one.alt() for one in self.holds)
