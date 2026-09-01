"""Render a Scene as an excalidraw file.

The output opens in excalidraw.com or in the VS Code extension, so a diagram can be dragged
around when somebody is working out what it should look like. It is still output. The Python file
is the source, and `just diagrams` overwrites this without asking.

Everything here is deterministic. Excalidraw normally fills seeds and nonces with random numbers,
which would make every regeneration a diff, so they are derived from the element key instead.
"""

from __future__ import annotations

import hashlib
from typing import Any

from kxdraw.scene import (
    FONT_HAND,
    FONT_MONO,
    LINE_HEIGHT,
    STYLES,
    TEXT_COLOUR,
    Arrow,
    Box,
    Note,
    Scene,
)

SOURCE = "https://github.com/tamnd/linux-kernel-internals"

# Excalidraw has no metric for the fonts it ships, and neither do we, so text boxes are sized by
# the usual rough ratio. Excalidraw remeasures on load, so being a few pixels out costs nothing.
CHAR_WIDTH = 0.55


def _seed(key: str) -> int:
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16)


def _text_size(text: str, font_size: float) -> tuple[float, float]:
    lines = text.split("\n")
    width = max((len(line) for line in lines), default=0) * font_size * CHAR_WIDTH
    return width, len(lines) * font_size * LINE_HEIGHT


def _common(key: str, x: float, y: float, width: float, height: float) -> dict[str, Any]:
    seed = _seed(key)
    return {
        "id": key,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "angle": 0,
        "strokeColor": TEXT_COLOUR,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": seed,
        "version": 1,
        "versionNonce": seed,
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
    }


def _text_element(
    key: str,
    text: str,
    x: float,
    y: float,
    font_size: float,
    mono: bool,
    colour: str,
    align: str,
    container: str | None,
) -> dict[str, Any]:
    width, height = _text_size(text, font_size)
    element = _common(key, x, y, width, height)
    element.update(
        {
            "type": "text",
            "strokeColor": colour,
            "text": text,
            "originalText": text,
            "fontSize": font_size,
            "fontFamily": FONT_MONO if mono else FONT_HAND,
            "textAlign": align,
            "verticalAlign": "middle" if container else "top",
            "containerId": container,
            "autoResize": True,
            "lineHeight": LINE_HEIGHT,
        }
    )
    return element


def _box(item: Box) -> list[dict[str, Any]]:
    style = STYLES[item.style]
    rect = _common(item.key, item.x, item.y, item.width, item.height)
    rect.update(
        {
            "type": "rectangle",
            "strokeColor": style["stroke"],
            "backgroundColor": style["fill"],
            "strokeStyle": "dashed" if item.dashed else "solid",
            "roundness": {"type": 3},
        }
    )
    if not item.label:
        return [rect]

    text_key = f"{item.key}-text"
    width, height = _text_size(item.label, item.font_size)
    text = _text_element(
        text_key,
        item.label,
        item.x + (item.width - width) / 2,
        item.y + (item.height - height) / 2,
        item.font_size,
        item.mono,
        style["stroke"],
        "center",
        item.key,
    )
    rect["boundElements"] = [{"type": "text", "id": text_key}]
    return [rect, text]


def _note(item: Note) -> list[dict[str, Any]]:
    colour = "#5c5f66" if item.muted else TEXT_COLOUR
    return [
        _text_element(
            item.key, item.text, item.x, item.y, item.font_size, item.mono, colour, item.align, None
        )
    ]


def _arrow(item: Arrow) -> list[dict[str, Any]]:
    (x1, y1), (x2, y2) = item.start, item.end
    element = _common(item.key, x1, y1, x2 - x1, y2 - y1)
    element.update(
        {
            "type": "arrow",
            "strokeStyle": "dashed" if item.dashed else "solid",
            "points": [[0, 0], [x2 - x1, y2 - y1]],
            "lastCommittedPoint": None,
            "startBinding": None,
            "endBinding": None,
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "elbowed": False,
        }
    )
    if not item.label:
        return [element]

    label_key = f"{item.key}-text"
    width, height = _text_size(item.label, 13)
    label = _text_element(
        label_key,
        item.label,
        (x1 + x2) / 2 - width / 2,
        (y1 + y2) / 2 - height / 2,
        13,
        False,
        "#5c5f66",
        "center",
        item.key,
    )
    element["boundElements"] = [{"type": "text", "id": label_key}]
    return [element, label]


def to_excalidraw(scene: Scene) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    for item in scene.elements:
        if isinstance(item, Box):
            elements.extend(_box(item))
        elif isinstance(item, Note):
            elements.extend(_note(item))
        else:
            elements.extend(_arrow(item))

    return {
        "type": "excalidraw",
        "version": 2,
        "source": SOURCE,
        "elements": elements,
        "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
        "files": {},
    }
