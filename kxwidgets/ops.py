"""OpsExplorer: a struct of function pointers, which is how the kernel does polymorphism.

There is no `class` in C. When the kernel needs one interface with many implementations, it writes
a struct full of function pointers, makes one instance of it per implementation, and hangs a
pointer to the instance off the object. `file_operations` is that. So are `inode_operations`,
`net_device_ops`, `tty_operations` and about two hundred others. Reading one is a skill that pays
for itself across the whole tree.

    from kxray import btf
    from kxwidgets import OpsExplorer

    vmlinux = btf.parse_file("/sys/kernel/btf/vmlinux")
    OpsExplorer(vmlinux.ops("file_operations"))

Every slot starts empty and says so. What sits in a slot is a fact about a running kernel rather
than about a type, and BTF describes types. Filling them in takes either a dump from a live kernel
or a read of the instance in the source, and until one of those happens the honest drawing is a
list of empty slots with their signatures.
"""

from __future__ import annotations

from kxray.models import OpsTable, Slot
from kxwidgets.html import BAND, INK, LINE, MONO, MUTED, Widget, card, style, tag, text

EMPTY = "#e8eef3"
FULL = "#d9edd2"


class OpsExplorer(Widget):
    """An ops table, one row per slot, with the signature under the name.

    `only_filled` hides the empty slots, which is what you want on `file_operations` where a real
    filesystem fills eight of the thirty something and leaves the rest for the defaults.
    """

    def __init__(self, ops: OpsTable, *, only_filled: bool = False) -> None:
        self.ops = ops
        self.only_filled = only_filled

    @property
    def rows(self) -> list[Slot]:
        return self.ops.filled if self.only_filled else self.ops.slots

    def html(self) -> str:
        if not self.rows:
            body = tag(
                "div",
                "No slots to show. Either this struct has no function pointers in it, or every "
                "one of them is empty and only the filled ones were asked for.",
                style_=style(font_size="13px", color=MUTED),
            )
            return card(self._title(), self._subtitle(), body, fallback=self.text())
        body = "".join(self._row(slot) for slot in self.rows)
        return card(self._title(), self._subtitle(), body, self._footnote(), fallback=self.text())

    def _title(self) -> str:
        if self.ops.instance:
            return f"{self.ops.instance}, a {self.ops.name}"
        return self.ops.name

    def _subtitle(self) -> str:
        parts = [f"{len(self.ops.slots)} slots", f"{len(self.ops.filled)} filled"]
        if self.ops.data_fields:
            parts.append(f"{len(self.ops.data_fields)} fields that are not operations")
        if self.ops.size is not None:
            parts.append(f"{self.ops.size} bytes")
        return "  ".join(parts)

    def _row(self, slot: Slot) -> str:
        name = tag(
            "span",
            text(slot.name),
            style_=style(font_family=MONO, font_size="13px", font_weight="600"),
        )
        offset = tag(
            "span",
            text(f"offset {slot.byte_offset}"),
            style_=style(font_family=MONO, font_size="11px", color=MUTED, margin_left="8px"),
        )
        badge = tag(
            "span",
            text(slot.filled_by or "empty"),
            style_=style(
                font_family=MONO,
                font_size="11px",
                background=FULL if slot.filled else EMPTY,
                border=f"1px solid {LINE}",
                border_radius="10px",
                padding="1px 8px",
                float="right",
                color=INK if slot.filled else MUTED,
            ),
        )
        signature = tag(
            "div",
            text(slot.signature),
            style_=style(
                font_family=MONO,
                font_size="11px",
                color=MUTED,
                margin_top="2px",
                overflow_x="auto",
                white_space="nowrap",
            ),
        )
        return tag(
            "div",
            badge + name + offset + signature,
            style_=style(
                padding="6px 8px",
                border_bottom=f"1px solid {LINE}",
                background=BAND if slot.filled else None,
            ),
        )

    def _footnote(self) -> str:
        if self.ops.filled:
            return (
                "A filled slot names the function this instance actually points at. An empty one "
                "means the kernel falls back to whatever the caller does when the pointer is null, "
                "which is usually a default and occasionally an error."
            )
        return (
            "Every slot is empty because nothing has read a live instance of this struct yet. The "
            "shape comes from BTF, which describes types. What sits in a slot is a fact about a "
            "running kernel, and it gets filled in with with_implementations once there is one."
        )

    def text(self) -> str:
        return self.ops.table()
