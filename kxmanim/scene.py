"""The thin layer that turns primitives into manim objects, and nothing else.

Everything above this file is arithmetic and can be tested anywhere. Everything in this file
needs manim, which needs cairo, which needs a working ffmpeg, which is a lot to ask of a laptop
and far too much to ask of CI on every push. So the rule is that this file stays thin. If you
find yourself working out a position in here, that arithmetic belongs in `primitives.py` where a
test can reach it.

manim is imported when a function that needs it runs, not when the module loads. That is what
lets `python3 -m kxmanim --check` validate every storyboard on a machine with no video toolchain
at all, which is the machine most people have.

Not every primitive has a renderer yet. `RENDERS` is the honest list of the ones that do, the
checker reads it, and a storyboard that asks for a shape nobody can draw yet fails the check
instead of failing halfway through a render at two in the morning.
"""

from __future__ import annotations

from typing import Any

from kxmanim.primitives import (
    ContextBadge,
    FrameCard,
    LayerDescent,
    TraceCell,
)
from kxmanim.storyboard import Storyboard

# Which of the nine can actually be drawn as video today. The other five are arithmetic with no
# renderer behind them yet, which is a smaller gap than it sounds and an honest one to state.
RENDERS: frozenset[str] = frozenset(
    {
        "frame-card",
        "layer-band",
        "trace-cell",
        "cpu-lane",
        "context-badge",
    }
)

INK = "#1b2733"
MUTED = "#5b6b7a"
PAPER = "#ffffff"
BAND = "#f3f7fa"

INSTALL = (
    "manim is not installed, so nothing can be rendered here. `uv pip install manim` pulls it in, "
    "and it needs ffmpeg and cairo on the machine as well. Everything except rendering works "
    "without it, including `python3 -m kxmanim --check`."
)


def require_manim() -> Any:
    """Import manim, or say plainly what is missing and what still works without it."""
    try:
        import manim
    except ImportError as exc:  # pragma: no cover - depends on what is installed
        raise RuntimeError(INSTALL) from exc
    return manim


def unrenderable(board: Storyboard) -> list[str]:
    """Primitives this storyboard asks for that have no renderer yet."""
    return [one for one in board.uses() if one not in RENDERS]


# -- the pieces ---------------------------------------------------------------------------------


def band_of(descent: LayerDescent, index: int) -> dict[str, Any]:
    """One layer band as position and colour, ready to hand to manim.

    The eight bands split the frame evenly top to bottom and the lit one is filled. Position is
    worked out here and not in the scene because a test can check a number and cannot check a
    rectangle that only exists inside a renderer.
    """
    band = descent.bands[index]
    top = 3.2 - index * 0.8
    return {
        "y": top,
        "height": 0.7,
        "width": 10.0,
        "label": band.layer.name,
        "note": band.label,
        "fill": BAND if not band.lit else "#dbeafe",
        "stroke": INK if band.lit else MUTED,
        "opacity": 1.0 if band.lit else 0.35,
    }


def card_of(card: FrameCard, x: float, y: float) -> dict[str, Any]:
    """One frame card as a box with a badge on it, in its subsystem's colour."""
    return {
        "x": x,
        "y": y,
        "width": 3.4,
        "height": 0.9,
        "label": card.name,
        "badge": card.context.badge,
        "fill": card.subsystem.fill,
        "stroke": card.subsystem.stroke,
        "subtitle": card.subsystem.name,
    }


def cell_of(
    cell: TraceCell, *, full_width: float = 12.0, row_height: float = 0.55
) -> dict[str, Any]:
    """One trace cell as a rectangle, using the same percentages the widget uses."""
    width = max(cell.width / 100.0 * full_width, 0.06)
    left = cell.left / 100.0 * full_width - full_width / 2
    return {
        "x": left + width / 2,
        "y": 2.0 - cell.row * row_height,
        "width": width,
        "height": row_height * 0.8,
        "label": cell.name,
        "stroke": INK if cell.to_scale else "#b04040",
        "fill": PAPER,
    }


def badge_of(badge: ContextBadge) -> dict[str, Any]:
    return {"glyph": badge.glyph, "label": badge.context.name, "colour": INK}


# -- the scene ----------------------------------------------------------------------------------


def scene_for(board: Storyboard, draw: Any) -> Any:
    """Build a manim Scene class for one storyboard.

    `draw` gets called once per beat with the beat and the scene, and puts whatever that beat is
    about on screen. The furniture around it, the title that is the idea and the caption strip
    along the bottom, is the same for every animation and is handled here, so no scene has to
    remember to put the caption up and none of them can forget.
    """
    manim = require_manim()

    missing = unrenderable(board)
    if missing:
        raise RuntimeError(f"{board.source} needs {', '.join(missing)}, which nothing can draw yet")
    if not board.renderable:
        raise RuntimeError(f"{board.source} is {board.status} and has not been reviewed")

    class Storyboarded(manim.Scene):  # pragma: no cover - needs manim and a video encoder
        def construct(self) -> None:
            self.camera.background_color = PAPER
            title = manim.Text(board.idea, font_size=28, color=INK).to_edge(manim.UP)
            self.add(title)
            caption = manim.Text("", font_size=20, color=MUTED).to_edge(manim.DOWN)
            self.add(caption)

            for beat in board.beats:
                new = manim.Text(beat.caption, font_size=20, color=MUTED).to_edge(manim.DOWN)
                self.play(manim.Transform(caption, new), run_time=0.4)
                draw(beat, self)
                self.wait(max(beat.seconds - 0.4, 0.1))

    Storyboarded.__name__ = _class_name(board.id)
    return Storyboarded


def _class_name(board_id: str) -> str:
    """`layer-descent` becomes `LayerDescent`, because manim scenes are picked by class name."""
    return "".join(part.capitalize() for part in board_id.replace("_", "-").split("-") if part)
