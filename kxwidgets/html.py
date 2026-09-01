"""The pieces every widget is built out of: escaping, colours, and the card around it.

Nothing here knows about traces or structs. It knows how to put a box on a page in a way that
survives every renderer a reader might open the book in, which turns out to be the hard part.
"""

from __future__ import annotations

import html as _html
from pathlib import Path

# Ink on paper, and the lines between them. One place, so the four widgets look like they came
# from the same project rather than from four afternoons.
INK = "#1b2733"
MUTED = "#5b6b7a"
LINE = "#c2d0dc"
PAPER = "#ffffff"
BAND = "#f3f7fa"

# Field colours, used in order and then round again. Pale on purpose, because the labels sit on
# top of them in black and a saturated background makes small text hard to read.
FIELDS = [
    "#cfe3f5",
    "#d9edd2",
    "#fbe4c9",
    "#e6dbf2",
    "#cfeaea",
    "#f6d9dd",
    "#e6e8c4",
    "#dde3ea",
]

# Padding. Red, striped, and impossible to mistake for a field, which is the entire job. Stripes
# rather than a flat colour because a hole has to read as absence and a flat block reads as a
# field somebody forgot to name.
HOLE_STRIPES = "repeating-linear-gradient(45deg, #f2c4c4 0 4px, #e5aaaa 4px 8px)"

# The duration markers, coloured by how bad they are. The kernel prints the marker and not the
# threshold, so the colour is the only thing that makes a slow call jump out of a wall of boxes.
MARKERS = {
    "": "#dbe7f2",
    "+": "#f7e6bb",
    "!": "#f6d3a3",
    "#": "#f2b892",
    "*": "#e9a087",
    "@": "#e08585",
    "$": "#d16d6d",
}

MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS = "system-ui, -apple-system, Segoe UI, Helvetica, Arial, sans-serif"


def text(value: object) -> str:
    """Escape something for use between tags."""
    return _html.escape(str(value), quote=False)


def attribute(value: object) -> str:
    """Escape something for use inside double quotes in an attribute."""
    return _html.escape(str(value), quote=True)


def style(**declarations: object) -> str:
    """A style attribute from keyword arguments, with underscores turned into hyphens.

    Every widget writes its styling inline like this and none of them emit a `<style>` block or a
    line of JavaScript. That is a deliberate limit rather than laziness. Notebook output gets
    sanitised on its way through Colab, through nbconvert and through the static site, and what
    survives all three is plain HTML with inline styling. A widget that only works in a live
    kernel is invisible to every reader who reads the book instead of running it, and that is
    most of them.
    """
    parts = []
    for name, value in declarations.items():
        if value is None:
            continue
        parts.append(f"{name.replace('_', '-')}:{value}")
    return ";".join(parts)


def tag(name: str, body: str = "", *, style_: str = "", **attributes: object) -> str:
    """One element. `style_` is spelled with a trailing underscore because `style` is taken."""
    rendered = "".join(
        f' {key.rstrip("_").replace("_", "-")}="{attribute(value)}"'
        for key, value in attributes.items()
        if value is not None
    )
    if style_:
        rendered += f' style="{attribute(style_)}"'
    return f"<{name}{rendered}>{body}</{name}>"


def details(summary: str, body: str, *, open_: bool = False) -> str:
    """A fold that opens on a click, with no script behind it.

    `details` is the only interaction in this package, and it works in a notebook, in a static
    site, in a plain browser and in the markdown GitHub renders.
    """
    state = " open" if open_ else ""
    return (
        f"<details{state}>"
        + tag("summary", summary, style_=style(cursor="pointer", color=MUTED, font_size="13px"))
        + body
        + "</details>"
    )


class Widget:
    """The base class. A widget is a thing that can draw itself twice.

    Once as HTML, for a reader looking at it, and once as plain text, for a reader using a screen
    reader, a terminal, a diff, or a test. The text version is not a courtesy. It is what makes
    the widget checkable, because a test can assert on text and cannot assert on a picture.
    """

    def html(self) -> str:
        raise NotImplementedError

    def text(self) -> str:
        raise NotImplementedError

    def _repr_html_(self) -> str:
        return self.html()

    def __str__(self) -> str:
        return self.text()

    def save(self, path: str | Path) -> Path:
        """Write this widget to a standalone HTML file, mostly for looking at it while working."""
        path = Path(path)
        path.write_text(page(type(self).__name__, self.html()), encoding="utf-8")
        return path


def card(title: str, subtitle: str, body: str, footnote: str = "", *, fallback: str = "") -> str:
    """The frame every widget draws itself inside.

    The fallback goes in a fold at the bottom rather than being left out. A reader who cannot see
    the picture gets the same information in text, in the same output cell, without having to know
    that a text version exists.
    """
    head = tag("div", text(title), style_=style(font_weight="600", font_size="14px", color=INK))
    if subtitle:
        head += tag(
            "div",
            text(subtitle),
            style_=style(font_size="12px", color=MUTED, margin_top="2px"),
        )
    tail = ""
    if footnote:
        tail += tag(
            "div",
            text(footnote),
            style_=style(font_size="12px", color=MUTED, margin_top="8px", line_height="1.5"),
        )
    if fallback:
        pre = tag(
            "pre",
            text(fallback),
            style_=style(
                font_family=MONO,
                font_size="12px",
                background=BAND,
                padding="8px",
                overflow_x="auto",
                margin="6px 0 0 0",
            ),
        )
        tail += tag(
            "div",
            details("The same thing as text", pre),
            style_=style(margin_top="8px"),
        )
    return tag(
        "div",
        head + tag("div", body, style_=style(margin_top="10px")) + tail,
        style_=style(
            font_family=SANS,
            color=INK,
            background=PAPER,
            border=f"1px solid {LINE}",
            border_radius="6px",
            padding="12px 14px",
            margin="4px 0",
            max_width="960px",
        ),
    )


def page(title: str, body: str) -> str:
    """A whole HTML document around some widgets, for `python3 -m kxwidgets --preview`."""
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{text(title)}</title>\n</head>\n"
        + tag(
            "body",
            body,
            style_=style(font_family=SANS, margin="24px", background="#fbfdfe", color=INK),
        )
        + "\n</html>\n"
    )
