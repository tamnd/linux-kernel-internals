"""A storyboard is the animation. The video is just what it looks like.

Every rule the visual system has about animation is here as a check rather than as advice,
because advice about animation loses every argument it has with someone who is enjoying making
one. The rules, and what each one turns into:

    ninety seconds, maximum          the beats are timed and the total is checked
    one idea per scene               there is one `idea` field and it is the title
    reuse the nine primitives        `shows` is validated against the closed set
    captions written by the author   every beat needs a caption, and it is checked for length
    alt text written by the author   same, and it has to say more than the caption does
    no animation is load-bearing     every storyboard names a still that carries the same point
    reviewed before rendering        `status` starts at draft and rendering refuses a draft

The last two are the ones that actually matter. A reader on a phone with data saving on, a reader
printing the page, and a reader using a screen reader all get the still and the alt text and none
of the motion, and there are more of those readers than there are of the other kind. If the point
only lands when it moves, the point has not been made.

Captions and the transcript come out of the same beats, so an animation cannot ship with a caption
track that says something different from the page it sits on.

    from kxmanim.storyboard import Storyboard

    board = Storyboard.load("kxmanim/storyboards/layer-descent.toml")
    board.check()
    print(board.vtt())
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from kxshapes import PRIMITIVES

# Ninety seconds. Not a round number picked for tidiness: past about a minute and a half a viewer
# has stopped holding the beginning of the animation in their head, so the end of it is landing
# against nothing.
BUDGET_SECONDS = 90

# A caption that is three words long is a label, and a label does not explain anything. An alt
# text that is shorter than the caption is a caption that got pasted twice.
MIN_CAPTION_WORDS = 5
MIN_ALT_WORDS = 8


@dataclass(frozen=True)
class Beat:
    """One moment of the animation, with what it shows, what it says and what it reads as."""

    seconds: float
    caption: str
    alt: str
    shows: tuple[str, ...]
    starts_at: float = 0.0

    @property
    def ends_at(self) -> float:
        return self.starts_at + self.seconds

    def problems(self) -> list[str]:
        out = []
        if self.seconds <= 0:
            out.append(f"a beat lasts {self.seconds} seconds, which is not a length of time")
        if self.seconds > 20:
            out.append(
                f"a beat lasts {self.seconds} seconds, and one held shot that long is a slide"
            )
        if len(self.caption.split()) < MIN_CAPTION_WORDS:
            out.append(f"caption is too short to explain anything: {self.caption!r}")
        if len(self.alt.split()) < MIN_ALT_WORDS:
            out.append(f"alt text is too short to stand in for the picture: {self.alt!r}")
        if self.alt.strip() == self.caption.strip():
            out.append("alt text is the caption pasted again, so it adds nothing")
        if not self.shows:
            out.append(f"beat {self.caption!r} does not say which primitives it uses")
        for one in self.shows:
            if one not in PRIMITIVES:
                out.append(f"{one!r} is not one of the nine primitives")
        return out


@dataclass(frozen=True)
class Storyboard:
    """One animation, planned out, before anything is rendered."""

    id: str
    idea: str
    still: str
    beats: tuple[Beat, ...]
    status: str = "draft"
    inputs: tuple[str, ...] = ()
    evidence: bool = False
    blocked_on: str = ""
    source: str = "<text>"

    # -- loading ---------------------------------------------------------------------------

    @classmethod
    def loads(cls, text: str, *, source: str = "<text>"):
        raw = tomllib.loads(text)
        beats: list[Beat] = []
        clock = 0.0
        for one in raw.get("beat", []):
            beat = Beat(
                seconds=float(one.get("seconds", 0)),
                caption=one.get("caption", ""),
                alt=one.get("alt", ""),
                shows=tuple(one.get("shows", [])),
                starts_at=clock,
            )
            clock += beat.seconds
            beats.append(beat)
        return cls(
            id=raw.get("id", ""),
            idea=raw.get("idea", ""),
            still=raw.get("still", ""),
            beats=tuple(beats),
            status=raw.get("status", "draft"),
            inputs=tuple(raw.get("inputs", [])),
            evidence=bool(raw.get("evidence", False)),
            blocked_on=raw.get("blocked_on", ""),
            source=source,
        )

    @classmethod
    def load(cls, path: str | Path):
        path = Path(path)
        return cls.loads(path.read_text(encoding="utf-8"), source=str(path))

    # -- the rules -------------------------------------------------------------------------

    @property
    def seconds(self) -> float:
        return sum(one.seconds for one in self.beats)

    def problems(self) -> list[str]:
        """Everything wrong with this storyboard, in the order a person would fix it."""
        out = []
        if not self.id:
            out.append("no id, so nothing can refer to this animation")
        if not self.idea:
            out.append("no idea, and one idea per animation means there has to be one")
        elif len(self.idea.split()) < MIN_CAPTION_WORDS:
            out.append(f"the idea is a label rather than a sentence: {self.idea!r}")
        if not self.still:
            out.append(
                "no still, and no animation is load-bearing, so there has to be one picture "
                "that carries the same point without moving"
            )
        if not self.beats:
            out.append("no beats, so there is nothing to render")
        if self.seconds > BUDGET_SECONDS:
            out.append(
                f"{self.seconds:.0f} seconds long, and the budget is {BUDGET_SECONDS}, "
                "so something in here is a second animation"
            )
        if self.status not in ("draft", "reviewed"):
            out.append(f"status is {self.status!r}, and it is either draft or reviewed")
        if not self.evidence and not self.blocked_on:
            out.append(
                "evidence is false and blocked_on is empty, so this does not say what it is "
                "waiting for"
            )
        for beat in self.beats:
            out.extend(beat.problems())
        return out

    def check(self) -> None:
        problems = self.problems()
        if problems:
            joined = "\n  ".join(problems)
            raise ValueError(f"{self.source} is not ready:\n  {joined}")

    @property
    def renderable(self) -> bool:
        """Whether this may be turned into a video yet."""
        return self.status == "reviewed" and not self.problems()

    # -- what comes out of it --------------------------------------------------------------

    def uses(self) -> list[str]:
        """Which of the nine primitives appear, in the order the nine are listed in."""
        seen = {name for beat in self.beats for name in beat.shows}
        return [one for one in PRIMITIVES if one in seen]

    def vtt(self) -> str:
        """The caption track, WebVTT, generated from the same beats as everything else."""
        lines = ["WEBVTT", ""]
        for index, beat in enumerate(self.beats, start=1):
            lines.append(str(index))
            lines.append(f"{_clock(beat.starts_at)} --> {_clock(beat.ends_at)}")
            lines.append(beat.caption)
            lines.append("")
        return "\n".join(lines)

    def transcript(self) -> str:
        """The whole animation as text, which is what most readers of the book will get."""
        lines = [f"# {self.idea}", ""]
        if self.still:
            lines += [f"Still: {self.still}", ""]
        for index, beat in enumerate(self.beats, start=1):
            lines.append(f"{index}. {beat.caption}")
            lines.append(f"   {beat.alt}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def _clock(seconds: float) -> str:
    """Seconds as WebVTT wants them, which is always hours, minutes, seconds and milliseconds."""
    whole = int(seconds)
    ms = round((seconds - whole) * 1000)
    return f"{whole // 3600:02d}:{whole // 60 % 60:02d}:{whole % 60:02d}.{ms:03d}"


def load_all(directory: str | Path) -> list[Storyboard]:
    """Every storyboard in a directory, sorted by file name."""
    return [Storyboard.load(one) for one in sorted(Path(directory).glob("*.toml"))]
