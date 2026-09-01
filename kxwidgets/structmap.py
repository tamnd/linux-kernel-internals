"""StructMap: a struct drawn at the size it really is, with the padding shown.

`pahole` prints a struct and tells you where the holes are. This draws the same answer, because a
hole is a spatial fact and a list of offsets is a bad way to see one.

    from kxray import btf
    from kxwidgets import StructMap

    vmlinux = btf.parse_file("/sys/kernel/btf/vmlinux")
    StructMap(vmlinux.layout("task_struct"), max_bytes=128)

Everything is measured in bits and then divided down, which is what makes a bitfield come out
narrower than a byte instead of being rounded up into one. Three flags packed into a byte are
drawn as three slivers sharing a byte, because that is what they are.

A union is drawn one field per row rather than as a grid, since every field of a union starts at
offset zero and drawing them in a grid puts all of them on top of each other.
"""

from __future__ import annotations

from dataclasses import dataclass

from kxray.models import Layout
from kxwidgets.html import (
    BAND,
    FIELDS,
    HOLE_STRIPES,
    INK,
    LINE,
    MONO,
    MUTED,
    Widget,
    card,
    style,
    tag,
    text,
)

ROW_HEIGHT = 24
CACHE_LINE = 64


@dataclass(frozen=True)
class Segment:
    """A piece of one field, clipped to one row. Offsets and lengths are in bits."""

    label: str
    start_bit: int
    length_bits: int
    colour: str
    title: str
    continued: bool = False


@dataclass(frozen=True)
class Band:
    """One row of the drawing: what it is called, which bits it covers, what is in it."""

    label: str
    start_bit: int
    length_bits: int
    segments: list[Segment]
    cache_line: bool = False


class StructMap(Widget):
    """A memory layout, drawn.

    `per_row` is how many bytes go on a line, and 16 is the default because it makes a 64 byte
    cache line exactly four rows. `max_bytes` stops a 9000 byte `task_struct` from turning into
    six hundred rows of nothing, and the drawing says how much it left out.
    """

    def __init__(
        self,
        layout: Layout,
        *,
        per_row: int = 16,
        max_bytes: int = 512,
    ) -> None:
        self.layout = layout
        self.per_row = per_row
        self.max_bytes = max_bytes

    @property
    def is_union(self) -> bool:
        return self.layout.name.startswith("union ")

    @property
    def shown_bytes(self) -> int:
        """How many bytes get drawn, which is not the size when the struct is a big one."""
        size = self.layout.size or self._implied_size()
        return min(size, self.max_bytes)

    def _implied_size(self) -> int:
        """The size when the file does not record one: as far as the last field reaches."""
        ends = [one.end for one in self.layout.fields if one.end is not None]
        return max(ends, default=0)

    # -- working out what goes where ---------------------------------------------------------

    def pieces(self) -> list[Segment]:
        """Every field and every hole, as one flat list, before anything is cut into rows."""
        out = []
        for index, one in enumerate(self.layout.fields):
            if one.is_bitfield:
                start, length = one.bit_offset, one.bitfield_size
            elif one.size is None:
                continue
            else:
                start, length = one.byte_offset * 8, one.size * 8
            size = f"{one.bitfield_size} bits" if one.is_bitfield else f"{one.size} bytes"
            out.append(
                Segment(
                    label=one.path,
                    start_bit=start,
                    length_bits=length,
                    colour=FIELDS[index % len(FIELDS)],
                    title=f"{one.path}\n{one.type_name}\noffset {one.byte_offset}\n{size}",
                )
            )
        for hole in self.layout.holes:
            out.append(
                Segment(
                    label=f"{hole.size} byte hole",
                    start_bit=hole.byte_offset * 8,
                    length_bits=hole.size * 8,
                    colour=HOLE_STRIPES,
                    title=(
                        f"{hole.size} bytes of padding at offset {hole.byte_offset}, "
                        f"after {hole.after}"
                    ),
                )
            )
        return sorted(out, key=lambda piece: (piece.start_bit, piece.length_bits))

    def bands(self) -> list[Band]:
        """The rows, with each piece clipped to the row it appears in."""
        pieces = self.pieces()
        if self.is_union:
            width = (self.layout.size or self._implied_size()) * 8
            return [Band(piece.label, 0, width, [piece]) for piece in pieces]

        rows = []
        row_bits = self.per_row * 8
        for start in range(0, self.shown_bytes * 8, row_bits):
            inside = []
            for piece in pieces:
                end = piece.start_bit + piece.length_bits
                if end <= start or piece.start_bit >= start + row_bits:
                    continue
                clipped_start = max(piece.start_bit, start)
                clipped_end = min(end, start + row_bits)
                inside.append(
                    Segment(
                        label=piece.label,
                        start_bit=clipped_start,
                        length_bits=clipped_end - clipped_start,
                        colour=piece.colour,
                        title=piece.title,
                        continued=piece.start_bit < start,
                    )
                )
            byte = start // 8
            rows.append(
                Band(
                    label=str(byte),
                    start_bit=start,
                    length_bits=row_bits,
                    segments=inside,
                    cache_line=byte % CACHE_LINE == 0 and byte > 0,
                )
            )
        return rows

    # -- drawing ------------------------------------------------------------------------------

    def html(self) -> str:
        rows = "".join(self._row(band) for band in self.bands())
        body = tag(
            "table",
            self._ruler() + rows,
            style_=style(border_collapse="collapse", width="100%"),
        )
        return card(
            self.layout.name,
            self._subtitle(),
            body,
            self._footnote(),
            fallback=self.text(),
        )

    def _subtitle(self) -> str:
        size = "unknown size" if self.layout.size is None else f"{self.layout.size} bytes"
        parts = [
            size,
            f"{len(self.layout.fields)} fields",
            f"{self.layout.padding} bytes padding",
            f"{self.layout.pointer_size} byte pointers",
        ]
        return "  ".join(parts)

    def _ruler(self) -> str:
        """The byte scale across the top, so a reader can count without counting."""
        if self.is_union:
            return ""
        ticks = []
        for byte in range(0, self.per_row, 4):
            ticks.append(
                tag(
                    "span",
                    str(byte),
                    style_=style(
                        position="absolute",
                        left=f"{byte / self.per_row * 100:.4f}%",
                        font_family=MONO,
                        font_size="10px",
                        color=MUTED,
                    ),
                )
            )
        return self._cells(
            "byte",
            tag("div", "".join(ticks), style_=style(position="relative", height="14px")),
        )

    def _row(self, band: Band) -> str:
        boxes = "".join(self._segment(band, piece) for piece in band.segments)
        inner = tag(
            "div",
            boxes,
            style_=style(
                position="relative",
                height=f"{ROW_HEIGHT}px",
                background=BAND,
                border_top=f"2px solid {INK}" if band.cache_line else None,
            ),
        )
        return self._cells(band.label, inner)

    def _cells(self, gutter: str, body: str) -> str:
        label = tag(
            "td",
            tag(
                "span",
                text(gutter),
                style_=style(font_family=MONO, font_size="11px", color=MUTED),
            ),
            style_=style(
                width="64px", text_align="right", padding="0 8px 0 0", vertical_align="middle"
            ),
        )
        return tag("tr", label + tag("td", body, style_=style(padding="1px 0")))

    def _segment(self, band: Band, piece: Segment) -> str:
        left = (piece.start_bit - band.start_bit) / band.length_bits * 100
        width = piece.length_bits / band.length_bits * 100
        label = (".." if piece.continued else "") + piece.label
        return tag(
            "div",
            tag(
                "span",
                text(label),
                style_=style(
                    font_family=MONO,
                    font_size="11px",
                    line_height=f"{ROW_HEIGHT}px",
                    padding_left="3px",
                ),
            ),
            title=piece.title,
            style_=style(
                position="absolute",
                left=f"{left:.4f}%",
                width=f"{width:.4f}%",
                top="0",
                height=f"{ROW_HEIGHT}px",
                min_width="2px",
                box_sizing="border-box",
                background=piece.colour,
                border=f"1px solid {LINE}",
                overflow="hidden",
                white_space="nowrap",
                color=INK,
            ),
        )

    def _footnote(self) -> str:
        notes = ["Striped red is padding the compiler added, and nobody declared it."]
        if self.is_union:
            notes.append("One row per field, because every field of a union starts at offset 0.")
        else:
            notes.append(f"{self.per_row} bytes to a row.")
            if (self.layout.size or 0) > CACHE_LINE:
                notes.append("The thick line every 64 bytes is a cache line boundary.")
        size = self.layout.size or self._implied_size()
        if size > self.shown_bytes:
            notes.append(f"Showing the first {self.shown_bytes} bytes of {size}.")
        notes.append(
            f"Laid out for {self.layout.pointer_size} byte pointers, which BTF does not record, "
            "so the same types give a different picture on a 32 bit kernel."
        )
        return " ".join(notes)

    def text(self) -> str:
        return self.layout.table()
