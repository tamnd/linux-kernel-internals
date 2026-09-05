"""Descent: the eight layers, with the ones a call went through lit up.

This is the picture the whole book is organised around. A `write` starts in your program, goes
through the syscall doorway, through the VFS, into a filesystem, stops in the page cache, and
returns. The block layer, the driver and the disk are not on that path at all, and finding that out
is the single most surprising thing a beginner learns about writing a file.

    from kxwidgets import Descent

    Descent({
        "userspace": "write(fd, buf, 1)",
        "entry": "the register becomes a call",
        "vfs": "vfs_write",
        "fs": "shmem_file_write_iter",
        "pagecache": "the byte is copied into a folio, and the call returns",
    })

The bands that were not touched are still drawn, greyed out. A picture that only shows the layers a
call went through cannot show the layers it skipped, and the skipping is the lesson.

Frame cards go under the band they ran in, coloured by subsystem and badged by context, so the
answer to which layer and the answer to which context are the same picture rather than two.

    from kxshapes import FrameCard

    Descent(lit, cards={"fs": [FrameCard.of("shmem_file_write_iter", path="mm/shmem.c")]})
"""

from __future__ import annotations

from kxray.vocabulary import CONTEXTS
from kxshapes import ContextBadge, FrameCard, LayerDescent
from kxwidgets.html import LINE, Widget, card, style, tag
from kxwidgets.shapes import context_badge, frame_card, layer_band


class Descent(Widget):
    """One call falling down the eight layers.

    `lit` maps a layer key to what happened in that layer, in a few words. A layer that is not in
    the map is drawn dim. `cards` maps a layer key to the frame cards that belong under it, and it
    is optional, because naming which file a function lives in is work and most descents do not
    need it.
    """

    def __init__(
        self,
        lit: dict[str, str],
        *,
        cards: dict[str, list[FrameCard]] | None = None,
        title: str = "",
        footnote: str = "",
    ) -> None:
        self.descent = LayerDescent.of(lit)
        self.cards = cards or {}
        self.title = title or "Down through the layers"
        self.extra = footnote

    def html(self) -> str:
        body = ""
        for band in self.descent.bands:
            body += layer_band(band)
            under = self.cards.get(band.layer.key, [])
            if under:
                body += tag(
                    "div",
                    "".join(frame_card(one) for one in under),
                    style_=style(
                        margin="0 0 6px 14px",
                        padding_left="10px",
                        border_left=f"2px solid {LINE}",
                    ),
                )
        return card(self.title, self._subtitle(), body, self._footnote(), fallback=self.text())

    def _subtitle(self) -> str:
        touched = len(self.descent.path)
        return f"{touched} of the eight layers, top to bottom"

    def _footnote(self) -> str:
        note = (
            "The greyed out bands are the layers this call never reached. They are drawn anyway, "
            "because which layers a call skips is usually the thing worth noticing."
        )
        if self.extra:
            note += " " + self.extra
        return note

    def text(self) -> str:
        lines = [self.descent.alt(), ""]
        for band in self.descent.bands:
            mark = "*" if band.lit else " "
            said = band.label if band.lit else band.layer.blurb
            lines.append(f"{mark} {band.layer.name:<14} {said}")
            for one in self.cards.get(band.layer.key, []):
                lines.append(f"      {one.alt()}")
        return "\n".join(lines)


class ContextKey(Widget):
    """The six execution contexts, each with what it forbids, as a legend.

    Rule 7 says concurrency is never deferred, and the badges are how that shows up in every other
    picture. A frame card carries one, a trace cell carries one, and a reader who has not met them
    yet has nowhere to look them up. This is that place, and a lesson drops it in once.
    """

    def __init__(self, *, only: list[str] | None = None) -> None:
        keys = only or [one.key for one in CONTEXTS]
        self.badges = [ContextBadge.of(one) for one in keys]

    def html(self) -> str:
        body = "".join(context_badge(one, wordy=True) for one in self.badges)
        return card(
            "The six execution contexts",
            "what each one will not let you do",
            body,
            "The same function is correct in one of these and a bug in another, so a picture that "
            "does not say which context it is in is a picture that cannot be checked.",
            fallback=self.text(),
        )

    def text(self) -> str:
        return "\n".join(f"{one.glyph}  {one.alt()}" for one in self.badges)
