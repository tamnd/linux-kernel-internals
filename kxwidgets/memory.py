"""MemoryScale: several sizes side by side, at widths you can actually compare.

Kernel sizes span six orders of magnitude in the same sentence. A `struct file` is a couple of
hundred bytes, a page is four thousand, a huge page is two million, and a lesson about the page
cache says all three in one paragraph. Drawn to scale, the file and the page are both hairlines
next to the huge page and the reader learns nothing.

    from kxwidgets import MemoryScale

    MemoryScale({
        "struct file": 232,
        "a page": 4096,
        "a transparent huge page": 2097152,
    })

So the widths are logarithmic, worked out once in `kxshapes` so that a drawn one and an animated
one agree. The ordering survives, every bar stays visible, and the caption prints the real byte
count on every row, because a log scale that does not admit to being one is a wrong picture rather
than a simplified one.
"""

from __future__ import annotations

from kxshapes import MemorySlot, scale
from kxwidgets.html import MUTED, Widget, card, style, tag
from kxwidgets.shapes import memory_slot


class MemoryScale(Widget):
    """A set of sizes as bars, measured against the biggest one in the set.

    Takes either a plain mapping of label to bytes, which is what most lessons want, or a list of
    `MemorySlot` when a row needs a note on it.
    """

    def __init__(
        self,
        slots: dict[str, int] | list[MemorySlot],
        *,
        title: str = "",
        footnote: str = "",
    ) -> None:
        if isinstance(slots, dict):
            slots = [MemorySlot(label, size) for label, size in slots.items()]
        self.slots = list(slots)
        self.title = title or "Sizes, on a log scale"
        self.extra = footnote

    def html(self) -> str:
        if not self.slots:
            body = tag(
                "div",
                "Nothing to measure. A scale with no sizes on it has no scale.",
                style_=style(font_size="13px", color=MUTED),
            )
            return card(self.title, "", body, fallback=self.text())
        body = "".join(memory_slot(one, width) for one, width in scale(self.slots))
        return card(self.title, self._subtitle(), body, self._footnote(), fallback=self.text())

    def _subtitle(self) -> str:
        smallest = min(one.size_bytes for one in self.slots)
        largest = max(one.size_bytes for one in self.slots)
        if smallest == largest:
            return f"{len(self.slots)} things, all {largest:,} bytes"
        return f"{len(self.slots)} things, from {smallest:,} bytes to {largest:,}"

    def _footnote(self) -> str:
        note = (
            "Bar width is logarithmic, so a bar twice as long is not a thing twice as big. The "
            "byte count on each row is the real number. A linear scale was tried first and it "
            "turned everything under a megabyte into the same hairline."
        )
        if self.extra:
            note += " " + self.extra
        return note

    def text(self) -> str:
        if not self.slots:
            return "nothing to measure"
        return "\n".join(one.alt() for one in self.slots)
