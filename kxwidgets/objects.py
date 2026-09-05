"""ObjectGraph: a few structs, the fields worth looking at, and what points at what.

`StructMap` beside this draws one struct as its bytes, which is the picture you want when the
question is about padding, holes and cache lines. This is the other picture. It draws two or three
structs as boxes of named fields and then draws the pointers between them, which is the picture you
want when the question is how the kernel gets from a file descriptor to the bytes on a disk.

    from kxray import btf
    from kxshapes import ObjectBox, PointerThread
    from kxwidgets import ObjectGraph

    vmlinux = btf.parse_file("/sys/kernel/btf/vmlinux")
    ObjectGraph(
        [ObjectBox.of(vmlinux.layout("file"), show=["f_op", "f_inode", "f_pos"])],
        [PointerThread.of("file", "f_inode", "inode", kind="borrowed")],
    )

The line style on a thread is the whole reason this widget exists. Solid means a reference is held
and the target cannot go away underneath you. Dashed means one is not, so the pointer is only good
while something else keeps the target alive. Dotted means RCU, and the answer is stale the moment
you leave the read side. Those three are the difference between correct code, a leak and a use
after free, and a picture that draws all pointers the same way has hidden the only part that
matters.

Which lock covers which field is not in BTF, because the format has nowhere to put it. It is passed
in by hand or it is absent, and an absent lock is drawn as nothing rather than guessed at.
"""

from __future__ import annotations

from kxshapes import ObjectBox, PointerThread
from kxwidgets.html import MUTED, Widget, card, style, tag, text
from kxwidgets.shapes import object_box, pointer_thread


class ObjectGraph(Widget):
    """Some object boxes, and the threads between them.

    Threads are given rather than worked out. A pointer field in BTF says what type it points at
    and says nothing about whether a reference is held, so the promise is something a person reads
    out of the source and writes down. Working it out here would mean inventing it.
    """

    def __init__(
        self,
        boxes: list[ObjectBox],
        threads: list[PointerThread] | None = None,
        *,
        title: str = "",
    ) -> None:
        self.boxes = list(boxes)
        self.threads = list(threads or [])
        self.title = title or "Objects and what they point at"

    def html(self) -> str:
        if not self.boxes:
            body = tag(
                "div",
                "No objects to draw. Either nothing was passed in, or every field was filtered "
                "out before it got here.",
                style_=style(font_size="13px", color=MUTED),
            )
            return card(self.title, self._subtitle(), body, fallback=self.text())

        body = "".join(object_box(one) for one in self.boxes)
        if self.threads:
            body += tag(
                "div",
                tag(
                    "div",
                    text("pointers out of these objects"),
                    style_=style(font_size="12px", color=MUTED, margin_bottom="4px"),
                )
                + "".join(pointer_thread(one) for one in self.threads),
                style_=style(margin_top="6px"),
            )
        body += self._legend()
        return card(self.title, self._subtitle(), body, self._footnote(), fallback=self.text())

    def _subtitle(self) -> str:
        fields = sum(len(one.rows) for one in self.boxes)
        parts = [f"{len(self.boxes)} objects", f"{fields} fields shown"]
        if self.threads:
            parts.append(f"{len(self.threads)} pointers")
        return "  ".join(parts)

    def _legend(self) -> str:
        """What every glyph in this picture means, gathered from the boxes that used one."""
        seen: list[str] = []
        for box in self.boxes:
            for line in box.legend():
                if line not in seen:
                    seen.append(line)
        if not seen:
            return ""
        rows = "".join(
            tag("div", text(one), style_=style(font_size="11px", color=MUTED)) for one in seen
        )
        return tag("div", rows, style_=style(margin_top="8px"))

    def _footnote(self) -> str:
        if self.threads:
            return (
                "Line style is a promise and not a decoration. Solid means a reference is held. "
                "Dashed means one is not, so the pointer is only valid while something else keeps "
                "the target alive. Dotted means RCU, valid inside the read side and stale outside "
                "it."
            )
        return (
            "Offsets and types come from the BTF of the kernel that was actually built, so they "
            "are what that kernel has rather than what a book said. No pointers were passed in, "
            "and nothing here guesses at one."
        )

    def text(self) -> str:
        if not self.boxes:
            return "no objects"
        lines = [one.alt() for one in self.boxes]
        if self.threads:
            lines.append("")
            lines.extend(one.alt() for one in self.threads)
        return "\n".join(lines)
