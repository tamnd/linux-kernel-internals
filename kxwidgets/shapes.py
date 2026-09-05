"""How the nine shapes get drawn as HTML.

`kxshapes` works out what a shape is: which rows an object box has, how wide a memory slot is
against the biggest one beside it, which of the eight bands a descent lights up. It works none of
that out here and it never should, because `kxmanim` needs the same answers and two places working
out the same answer is two places that can disagree.

So this file is the other half, and it is deliberately thin. Each function takes one shape and
returns a fragment of HTML, and none of them decide anything. Colours come from `kxray.vocabulary`,
geometry comes from `kxshapes`, and what is left is tags and inline styling.

    from kxshapes import MemorySlot, scale
    from kxwidgets.shapes import memory_slot

    slots = [MemorySlot("a page", 4096), MemorySlot("struct file", 232)]
    "".join(memory_slot(one, width) for one, width in scale(slots))

`RENDERS` is the set of shapes that have a renderer here, and a test asserts it is all nine. That
test is the milestone criterion written down: a shape that an animation can draw and a widget
cannot is a shape a lesson has to be written around, and the point of a closed set of nine is that
no lesson ever has to be.

These return fragments rather than whole widgets. A fragment goes inside `html.card` along with a
title and the text fallback, and the widgets in this package are the things that do that. Nothing
here emits a `<style>` block or a line of JavaScript, for the reason in `html.style`.
"""

from __future__ import annotations

from kxray.vocabulary import LOCK_GLYPH
from kxshapes import (
    ContextBadge,
    CpuLane,
    FrameCard,
    LayerBand,
    MemorySlot,
    ObjectBox,
    OpsPlug,
    PointerThread,
    TraceCell,
)
from kxwidgets.html import (
    BAND,
    INK,
    LINE,
    MARKERS,
    MONO,
    MUTED,
    PAPER,
    SANS,
    style,
    tag,
    text,
)

# Trace cells are absolutely positioned, so a row has to be a number of pixels somewhere. It is
# here rather than in `kxshapes` because a shape is measured in percentages and rows, and how tall
# a row is on a screen is a fact about screens.
ROW_HEIGHT = 22
ROW_GAP = 2

# A band that the call went through, and a band it did not. The dim one is still drawn, because a
# descent that only shows the layers it touched hides the layers it skipped, and skipping the block
# layer entirely is the single most surprising thing about a buffered write.
LIT = "#cfe3f5"
DIM = "#f7fafc"

EMPTY_SOCKET = "#e8eef3"
FULL_SOCKET = "#d9edd2"


def _line_style(dash: tuple[int, ...]) -> str:
    """A CSS border style from the dash pattern the vocabulary gives a pointer.

    The pattern is the vocabulary's, and CSS only has three names for it, so this maps rather than
    invents. Nothing chooses a line style anywhere else in this package.
    """
    if not dash:
        return "solid"
    return "dotted" if dash[0] <= 2 else "dashed"


# -- 1. frame card ------------------------------------------------------------------------------


def frame_card(shape: FrameCard) -> str:
    """One function as a card, in its subsystem's colour, with its context badge on it."""
    head = tag(
        "span",
        text(shape.name),
        style_=style(font_family=MONO, font_size="12px", font_weight="600"),
    )
    badge = tag(
        "span",
        text(shape.context.badge),
        title=shape.context.describe(),
        style_=style(font_size="12px", color=shape.subsystem.stroke, margin_right="6px"),
    )
    where = tag(
        "div",
        text(shape.subsystem.name),
        style_=style(font_size="11px", color=MUTED, margin_top="2px"),
    )
    note = ""
    if shape.note:
        note = tag(
            "div",
            text(shape.note),
            style_=style(font_size="11px", color=INK, margin_top="4px", line_height="1.4"),
        )
    return tag(
        "div",
        badge + head + where + note,
        title=shape.alt(),
        style_=style(
            display="inline-block",
            vertical_align="top",
            background=shape.subsystem.fill,
            border=f"1px solid {shape.subsystem.stroke}",
            border_radius="4px",
            padding="6px 9px",
            margin="0 6px 6px 0",
            max_width="260px",
        ),
    )


# -- 2. layer band ------------------------------------------------------------------------------


def layer_band(shape: LayerBand) -> str:
    """One of the eight bands, at the depth it always sits at, lit or not."""
    name = tag(
        "span",
        text(shape.layer.name),
        style_=style(
            font_family=MONO,
            font_size="12px",
            font_weight="600" if shape.lit else "400",
            color=INK if shape.lit else MUTED,
            display="inline-block",
            min_width="110px",
        ),
    )
    said = shape.label if shape.lit else shape.layer.blurb
    body = tag(
        "span",
        text(said),
        style_=style(font_size="12px", color=INK if shape.lit else MUTED),
    )
    return tag(
        "div",
        name + body,
        title=shape.alt(),
        style_=style(
            background=LIT if shape.lit else DIM,
            border=f"1px solid {LINE if shape.lit else DIM}",
            border_radius="3px",
            padding="6px 9px",
            margin_bottom="3px",
        ),
    )


# -- 3. object box ------------------------------------------------------------------------------


def object_box(shape: ObjectBox) -> str:
    """One struct as a box of rows, with the glyphs down the side and the hidden fields counted."""
    head = tag(
        "div",
        tag("span", text(shape.name), style_=style(font_family=MONO, font_weight="600"))
        + (
            tag(
                "span",
                text(f"{shape.size} bytes"),
                style_=style(font_size="11px", color=MUTED, margin_left="8px"),
            )
            if shape.size
            else ""
        ),
        style_=style(
            font_size="13px",
            padding="6px 9px",
            background=BAND,
            border_bottom=f"1px solid {LINE}",
        ),
    )

    rows = ""
    for row in shape.rows:
        offset = tag(
            "span",
            text(f"+{row.byte_offset}"),
            style_=style(
                font_family=MONO,
                font_size="11px",
                color=MUTED,
                display="inline-block",
                min_width="46px",
            ),
        )
        name = tag(
            "span",
            text(row.name),
            style_=style(font_family=MONO, font_size="12px", display="inline-block"),
        )
        type_name = tag(
            "span",
            text(row.type_name),
            style_=style(font_family=MONO, font_size="11px", color=MUTED, margin_left="8px"),
        )
        marks = "".join(row.glyphs)
        if row.lock:
            marks += LOCK_GLYPH
        annotations = (
            tag(
                "span",
                text(marks + (f" {row.lock}" if row.lock else "")),
                title=row.alt(),
                style_=style(font_size="11px", color=MUTED, float="right"),
            )
            if marks
            else ""
        )
        rows += tag(
            "div",
            annotations + offset + name + type_name,
            style_=style(padding="4px 9px", border_bottom=f"1px solid {LINE}"),
        )

    tail = ""
    if shape.hidden:
        tail = tag(
            "div",
            text(f"{shape.hidden} more fields, not shown"),
            style_=style(font_size="11px", color=MUTED, padding="5px 9px", font_style="italic"),
        )

    return tag(
        "div",
        head + rows + tail,
        style_=style(
            display="inline-block",
            vertical_align="top",
            background=PAPER,
            border=f"1px solid {LINE}",
            border_radius="4px",
            margin="0 8px 8px 0",
            min_width="300px",
        ),
    )


# -- 4. pointer thread --------------------------------------------------------------------------


def pointer_thread(shape: PointerThread) -> str:
    """One pointer, drawn as the line style its promise earns rather than the one that looks nice.

    Solid, dashed and dotted are not decoration here. They are the difference between a pointer you
    can hold on to, a pointer that is only good while somebody else is holding the target up, and a
    pointer that goes stale the moment you leave the read side.
    """
    source = tag(
        "span",
        text(f"{shape.from_object}.{shape.from_field}"),
        style_=style(font_family=MONO, font_size="12px"),
    )
    line = tag(
        "span",
        "",
        style_=style(
            display="inline-block",
            width="60px",
            margin="0 8px",
            vertical_align="middle",
            border_top=f"2px {_line_style(shape.reference.dash)} {INK}",
        ),
    )
    target = tag(
        "span",
        text(shape.to_object),
        style_=style(font_family=MONO, font_size="12px", font_weight="600"),
    )
    promise = tag(
        "div",
        text(shape.reference.describe()),
        style_=style(font_size="11px", color=MUTED, margin_top="2px", line_height="1.4"),
    )
    return tag(
        "div",
        source + line + target + promise,
        title=shape.alt(),
        style_=style(padding="6px 0", border_bottom=f"1px solid {LINE}"),
    )


# -- 5. ops plug --------------------------------------------------------------------------------


def ops_plug(shape: OpsPlug) -> str:
    """A function pointer table as a row of sockets, hollow where nobody has looked.

    A hollow socket is not a null pointer and the drawing must not imply that it is. BTF knows the
    socket exists and what shape a plug has to be. What is in it is a fact about a running kernel.
    """
    sockets = ""
    for socket in shape.sockets:
        filled = bool(socket.filled_by)
        name = tag(
            "div",
            text(socket.name),
            style_=style(font_family=MONO, font_size="11px", font_weight="600"),
        )
        who = tag(
            "div",
            text(socket.filled_by or "empty"),
            style_=style(font_family=MONO, font_size="10px", color=INK if filled else MUTED),
        )
        sockets += tag(
            "div",
            name + who,
            title=f"{socket.alt()}\n{socket.signature}",
            style_=style(
                display="inline-block",
                background=FULL_SOCKET if filled else EMPTY_SOCKET,
                border=f"1px {'solid' if filled else 'dashed'} {LINE}",
                border_radius="3px",
                padding="4px 7px",
                margin="0 5px 5px 0",
            ),
        )
    counted = tag(
        "div",
        text(f"{len(shape.filled)} of {len(shape.sockets)} sockets have a function in them"),
        style_=style(font_size="11px", color=MUTED, margin_top="2px"),
    )
    return tag("div", sockets + counted, title=shape.alt())


# -- 6. trace cell and 7. CPU lane ----------------------------------------------------------------


def trace_cell(shape: TraceCell, *, hover: str = "", marked: str = "", faded: bool = False) -> str:
    """One call, as wide as it took, at the depth it was called from.

    `left` and `width` are percentages and they come out of `kxshapes`, which got them out of
    `kxray.layout`. Nothing in this file decides where a box goes, which is why an animated tape
    and a drawn tape put the wide box in the same place.

    A cell already spends its fill on the duration marker and its border on whether the width is a
    measurement, so the two things a comparison needs to add get channels of their own rather than
    a third meaning stacked onto one of those. `marked` draws a ring around the box in the colour
    it is given, and puts a dot in front of the name so the ring is not the only way to see it.
    `faded` dims the whole box, for a frame that is drawn but was not part of the comparison.
    """
    colour = MARKERS.get(shape.marker, MARKERS[""])
    border = "#ffffff" if shape.to_scale else "#b04040"
    label = tag(
        "span",
        text(("• " if marked else "") + _shorten(shape.name)),
        style_=style(
            font_family=MONO,
            font_size="11px",
            line_height=f"{ROW_HEIGHT}px",
            padding_left="4px",
        ),
    )
    return tag(
        "div",
        label,
        title=hover or shape.alt(),
        style_=style(
            position="absolute",
            left=f"{shape.left:.4f}%",
            width=f"{shape.width:.4f}%",
            top=f"{shape.row * (ROW_HEIGHT + ROW_GAP)}px",
            height=f"{ROW_HEIGHT}px",
            min_width="2px",
            box_sizing="border-box",
            background=colour,
            border=f"1px solid {border}",
            border_radius="2px",
            outline=f"2px solid {marked}" if marked else None,
            opacity="0.35" if faded else None,
            overflow="hidden",
            white_space="nowrap",
            color=INK,
        ),
    )


def cpu_lane(shape: CpuLane, *, labelled: bool = True) -> str:
    """One CPU's row of cells, with the CPU number beside it.

    One of these per CPU rather than one per trace file. The file interleaves every CPU into one
    stream, so a reader following the indentation down the page is following two call stacks at
    once and has no way to tell.
    """
    height = max(shape.rows, 1) * (ROW_HEIGHT + ROW_GAP)
    cells = "".join(trace_cell(one) for one in shape.cells)
    strip = tag(
        "div",
        cells,
        style_=style(
            position="relative",
            height=f"{height}px",
            background=BAND,
            border_radius="3px",
        ),
    )
    if not labelled:
        return tag("div", strip, style_=style(margin_bottom="10px"))
    name = tag(
        "div",
        text(f"cpu {shape.cpu}"),
        style_=style(font_family=MONO, font_size="11px", color=MUTED, margin_bottom="2px"),
    )
    return tag("div", name + strip, title=shape.alt(), style_=style(margin_bottom="10px"))


def _shorten(name: str, limit: int = 34) -> str:
    """Kernel function names get long, and a box is only so wide."""
    return name if len(name) <= limit else name[: limit - 3] + "..."


# -- 8. context badge ---------------------------------------------------------------------------


def context_badge(shape: ContextBadge, *, wordy: bool = False) -> str:
    """Which of the six contexts this is, as a pill.

    It goes on other shapes as often as it stands alone, which is why it is a fragment with no card
    around it. `wordy` prints what the context forbids as well, which is what a legend wants and
    what a badge stuck on the corner of a frame card does not.
    """
    glyph = tag("span", text(shape.glyph), style_=style(margin_right="5px"))
    name = tag("span", text(shape.context.name), style_=style(font_size="11px"))
    pill = tag(
        "span",
        glyph + name,
        title=shape.alt(),
        style_=style(
            display="inline-block",
            background=BAND,
            border=f"1px solid {LINE}",
            border_radius="10px",
            padding="2px 9px",
            font_family=SANS,
            color=INK,
        ),
    )
    if not wordy:
        return pill
    forbids = tag(
        "span",
        text(shape.context.forbids),
        style_=style(font_size="11px", color=MUTED, margin_left="8px"),
    )
    return tag("div", pill + forbids, style_=style(margin_bottom="5px"))


# -- 9. memory slot -----------------------------------------------------------------------------


def memory_slot(shape: MemorySlot, width: float) -> str:
    """A chunk of memory at a width you can compare, with the real size printed beside it.

    The width is logarithmic, worked out in `kxshapes`, and the caption always prints the byte
    count, because a log scale that does not say it is a log scale is a wrong picture.
    """
    label = tag(
        "div",
        tag("span", text(shape.label), style_=style(font_family=MONO, font_size="12px"))
        + tag(
            "span",
            text(f"{shape.size_bytes:,} bytes"),
            style_=style(font_size="11px", color=MUTED, margin_left="8px"),
        ),
        style_=style(margin_bottom="2px"),
    )
    bar = tag(
        "div",
        "",
        style_=style(
            width=f"{width * 100:.2f}%",
            height="14px",
            background=LIT,
            border=f"1px solid {LINE}",
            border_radius="2px",
        ),
    )
    note = ""
    if shape.note:
        note = tag(
            "div",
            text(shape.note),
            style_=style(font_size="11px", color=MUTED, margin_top="2px"),
        )
    return tag("div", label + bar + note, title=shape.alt(), style_=style(margin_bottom="9px"))


# -- the whole set ------------------------------------------------------------------------------

# One renderer per shape, by the name a storyboard uses. A test asserts this covers all nine, and
# that assertion is the milestone criterion written down. A shape that an animation can draw and a
# widget cannot is a shape a lesson has to be written around.
RENDERERS = {
    "frame-card": frame_card,
    "layer-band": layer_band,
    "object-box": object_box,
    "pointer-thread": pointer_thread,
    "ops-plug": ops_plug,
    "trace-cell": trace_cell,
    "cpu-lane": cpu_lane,
    "context-badge": context_badge,
    "memory-slot": memory_slot,
}

RENDERS = frozenset(RENDERERS)


def render(shape, **options) -> str:
    """Draw any of the nine, dispatching on which one it is.

    Most callers name the renderer directly, because they know what they are drawing. This is for
    the ones that do not, such as the preview page walking a list of mixed shapes.
    """
    primitive = getattr(shape, "primitive", None)
    if primitive not in RENDERERS:
        raise TypeError(f"{type(shape).__name__} is not one of the nine shapes")
    return RENDERERS[primitive](shape, **options)
