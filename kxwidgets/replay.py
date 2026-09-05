"""Draw a recorded session as something a reader can walk through.

    from kxray import replay
    from kxwidgets import SessionPlayer

    SessionPlayer(replay.load("corpora/replays/tier1/build-and-boot-uml.cast"))

The word player is a slight overstatement and the shape of the widget is the reason. Nothing in
this package runs a line of JavaScript, so there is no play button and no scrubber that follows a
clock. What there is instead turns out to be more useful for reading a session afterwards.

Across the top is a strip with one segment per step, each as wide a share of the strip as that step
was a share of the session. On a kernel build that strip is one enormous green block with a dozen
slivers on either side of it, and a reader has learned the shape of a kernel build before they have
read a word. The point of a build session is not the commands. It is that one of them takes twenty
minutes and the rest take no time at all, and a transcript printed as text hides exactly that.

Under the strip is one row per step, and the output is behind a fold, because a build prints tens of
thousands of lines and a reader wants four of them.

## What gets left out, and how it says so

A fold holding forty thousand lines is a page that takes a second to scroll. So the output is cut
to the head and the tail, and the line that replaces the middle says how many lines were taken out.
Cutting silently would be the one thing this project does not do anywhere else, and a reader who
cannot tell a short command from a truncated one is being lied to about the size of a build.
"""

from __future__ import annotations

from kxray.replay.session import Session, Step
from kxwidgets.html import BAND, INK, LINE, MONO, MUTED, Widget, card, details, style, tag, text

# The strip colours. Green for a command that reported success, red for one that did not, grey for
# one whose status was never recorded, which is every step of a cast taken without the shell marks.
OK = "#9ec9a3"
BAD = "#d98b8b"
UNKNOWN = "#c8d2da"

# How much output a fold holds before it starts cutting. Twelve lines at the top because the first
# thing a command prints is usually what it is about, and forty at the bottom because the last
# thing it prints is usually whether it worked.
HEAD = 12
TAIL = 40

STRIP_HEIGHT = "22px"

# A segment narrower than this is invisible, so it is widened and the strip stops being to scale.
# Better a strip that says it is not to scale than a strip with nothing in it but one green block.
MIN_SHARE = 0.6


class SessionPlayer(Widget):
    """A recorded session, as a strip of steps and a list of folds under it."""

    def __init__(
        self,
        session: Session,
        *,
        title: str = "",
        subtitle: str = "",
        head: int = HEAD,
        tail: int = TAIL,
        open_step: int | None = None,
    ):
        self.session = session
        self.title = title or session.title or session.source or "A recorded session"
        self.subtitle = subtitle
        self.head = head
        self.tail = tail
        self.open_step = open_step

    # -- what the picture is ---------------------------------------------------------------

    def shares(self) -> list[float]:
        """Each step's width in the strip, as a fraction of one.

        Proportional to time, except that anything under `MIN_SHARE` per cent is widened so it can
        be seen and clicked. `to_scale` says whether that happened, and the footnote repeats it.
        """
        total = sum(one.seconds for one in self.session.steps)
        if total <= 0:
            count = max(len(self.session.steps), 1)
            return [1 / count] * count
        raw = [one.seconds / total * 100 for one in self.session.steps]
        floored = [max(one, MIN_SHARE) for one in raw]
        scale = 100 / sum(floored)
        return [one * scale for one in floored]

    @property
    def to_scale(self) -> bool:
        total = sum(one.seconds for one in self.session.steps)
        if total <= 0:
            return False
        return all(one.seconds / total * 100 >= MIN_SHARE for one in self.session.steps)

    def rows(self, step: Step) -> list[str]:
        """The output of one step, cut to the head and the tail, saying so where it was cut."""
        out = step.rows
        if len(out) <= self.head + self.tail + 1:
            return out
        cut = len(out) - self.head - self.tail
        return [*out[: self.head], f"... {cut} lines not shown ...", *out[-self.tail :]]

    # -- drawing ---------------------------------------------------------------------------

    def html(self) -> str:
        session = self.session
        subtitle = self.subtitle or session.alt()
        body = self._strip() + "".join(self._row(one) for one in session.steps)
        return card(self.title, subtitle, body, self._footnote(), fallback=self.text())

    def _strip(self) -> str:
        pieces = []
        for one, share in zip(self.session.steps, self.shares(), strict=True):
            pieces.append(
                tag(
                    "div",
                    text(one.number) if share > 2.5 else "",
                    title=one.alt(),
                    style_=style(
                        width=f"{share:.3f}%",
                        height=STRIP_HEIGHT,
                        background=_colour(one),
                        border_right=f"1px solid {LINE}",
                        box_sizing="border-box",
                        color=INK,
                        font_family=MONO,
                        font_size="11px",
                        text_align="center",
                        line_height=STRIP_HEIGHT,
                        overflow="hidden",
                    ),
                )
            )
        return tag(
            "div",
            "".join(pieces),
            title=self.session.alt(),
            style_=style(
                display="flex",
                border=f"1px solid {LINE}",
                border_radius="3px",
                overflow="hidden",
                margin_bottom="12px",
            ),
        )

    def _row(self, step: Step) -> str:
        head = tag(
            "span",
            text(step.command or "the whole recording"),
            style_=style(font_family=MONO, font_size="12px", color=INK),
        )
        head += tag(
            "span",
            text(f"  {step.took}  {step.status}"),
            style_=style(font_size="12px", color=MUTED),
        )
        summary = (
            tag(
                "span",
                text(step.number),
                style_=style(
                    display="inline-block",
                    width="18px",
                    height="18px",
                    line_height="18px",
                    text_align="center",
                    border_radius="3px",
                    background=_colour(step),
                    font_size="11px",
                    font_family=MONO,
                    margin_right="8px",
                ),
            )
            + head
        )
        pre = tag(
            "pre",
            text("\n".join(self.rows(step)) or "(no output)"),
            style_=style(
                font_family=MONO,
                font_size="12px",
                background=BAND,
                padding="8px",
                margin="6px 0 0 26px",
                overflow_x="auto",
                line_height="1.45",
            ),
        )
        note = ""
        if step.note:
            note = tag(
                "div",
                text(step.note),
                style_=style(
                    font_size="12px", color=MUTED, margin="4px 0 0 26px", line_height="1.5"
                ),
            )
        return tag(
            "div",
            details(summary, note + pre, open_=step.number == self.open_step),
            style_=style(border_top=f"1px solid {LINE}", padding="6px 0"),
        )

    def _footnote(self) -> str:
        out = []
        if not self.session.marked:
            out.append(
                "This recording has no shell marks in it, so it is one step rather than a "
                "walkthrough. See kxray.replay.record for what puts them there."
            )
        elif not self.to_scale:
            out.append(
                "The strip is not quite to scale. At least one step was too short to see at its "
                "real width and was widened, so the long steps are a little narrower than they "
                "should be."
            )
        else:
            out.append("Each segment is as wide a share of the strip as that step was of the time.")
        bad = self.session.failures
        if bad:
            out.append(
                f"{len(bad)} step(s) did not report success: "
                + ", ".join(str(one.number) for one in bad)
                + "."
            )
        return " ".join(out)

    def text(self) -> str:
        return self.session.table()


def _colour(step: Step) -> str:
    if not step.complete or step.exit_code is None:
        return UNKNOWN
    return OK if step.worked else BAD
