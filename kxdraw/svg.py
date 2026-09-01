"""Render a Scene as an SVG.

This is the one that goes in the lesson, because GitHub and MkDocs both show an SVG and neither
of them knows what an excalidraw file is. It is plain rather than hand drawn: no wobble, no
sketch filter, just rectangles and text that stay readable when somebody zooms in.

Accessibility is not an afterthought here. Every diagram carries a title and a description in the
SVG itself, so a screen reader gets something better than the file name.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from kxdraw.scene import LINE_HEIGHT, MUTED_TEXT, STYLES, TEXT_COLOUR, Arrow, Box, Note, Scene

SANS = "Inter, Segoe UI, Helvetica, Arial, sans-serif"
MONO = "SFMono-Regular, Menlo, Consolas, monospace"
ARROW_COLOUR = "#495057"


def _font(mono: bool) -> str:
    return MONO if mono else SANS


def _lines(text: str, x: float, y: float, size: float, anchor: str, mono: bool, fill: str) -> str:
    """One text element per line, because SVG has no line wrapping and never will."""
    rows = text.split("\n")
    step = size * LINE_HEIGHT
    out = []
    for i, row in enumerate(rows):
        out.append(
            f'<text x="{x:.1f}" y="{y + i * step:.1f}" font-family="{_font(mono)}" '
            f'font-size="{size:.1f}" fill="{fill}" text-anchor="{anchor}" '
            f'dominant-baseline="middle">{escape(row)}</text>'
        )
    return "\n  ".join(out)


def _box(item: Box) -> str:
    style = STYLES[item.style]
    fill = "none" if style["fill"] == "transparent" else style["fill"]
    dash = ' stroke-dasharray="8 6"' if item.dashed else ""
    parts = [
        f'<rect x="{item.x:.1f}" y="{item.y:.1f}" width="{item.width:.1f}" '
        f'height="{item.height:.1f}" rx="8" fill="{fill}" stroke="{style["stroke"]}" '
        f'stroke-width="2"{dash}/>'
    ]
    if item.label:
        rows = item.label.split("\n")
        step = item.font_size * LINE_HEIGHT
        first = item.y + item.height / 2 - (len(rows) - 1) * step / 2
        parts.append(
            _lines(
                item.label,
                item.x + item.width / 2,
                first,
                item.font_size,
                "middle",
                item.mono,
                style["stroke"],
            )
        )
    return "\n  ".join(parts)


def _note(item: Note) -> str:
    anchor = {"left": "start", "center": "middle", "right": "end"}[item.align]
    colour = MUTED_TEXT if item.muted else TEXT_COLOUR
    return _lines(item.text, item.x, item.y, item.font_size, anchor, item.mono, colour)


def _arrow(item: Arrow) -> str:
    (x1, y1), (x2, y2) = item.start, item.end
    dash = ' stroke-dasharray="8 6"' if item.dashed else ""
    parts = [
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{ARROW_COLOUR}" stroke-width="2"{dash} marker-end="url(#head)"/>'
    ]
    if item.label:
        mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
        # A label sitting on the line is unreadable, so nudge it off whichever way the line runs.
        if abs(x2 - x1) > abs(y2 - y1):
            parts.append(_lines(item.label, mid_x, mid_y - 12, 13, "middle", False, MUTED_TEXT))
        else:
            parts.append(_lines(item.label, mid_x + 10, mid_y, 13, "start", False, MUTED_TEXT))
    return "\n  ".join(parts)


def to_svg(scene: Scene, description: str = "") -> str:
    body = []
    for item in scene.elements:
        if isinstance(item, Box):
            body.append(_box(item))
        elif isinstance(item, Note):
            body.append(_note(item))
        else:
            body.append(_arrow(item))

    desc = f"\n  <desc>{escape(description)}</desc>" if description else ""
    drawing = "\n  ".join(body)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {scene.width:.0f} '
        f'{scene.height:.0f}" width="{scene.width:.0f}" height="{scene.height:.0f}" '
        f'role="img" aria-label="{escape(scene.title)}">\n'
        f"  <title>{escape(scene.title)}</title>{desc}\n"
        f"  <defs>\n"
        f'    <marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto-start-reverse">\n'
        f'      <path d="M 0 0 L 10 5 L 0 10 z" fill="{ARROW_COLOUR}"/>\n'
        f"    </marker>\n"
        f"  </defs>\n"
        f'  <rect width="100%" height="100%" fill="#ffffff"/>\n'
        f"  {drawing}\n"
        f"</svg>\n"
    )
