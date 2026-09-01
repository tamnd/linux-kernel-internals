"""Check every storyboard, or write out its captions.

    python3 -m kxmanim                       check every storyboard
    python3 -m kxmanim --captions build/vtt  write the caption track and the transcript

The check runs on any machine. It needs no manim, no ffmpeg and no cairo, which is the point:
the rules about animation are worth having only if they are enforced everywhere, and a check that
needs a video toolchain installed is a check that stops running the week CI gets slow.

What it looks at:

    the ninety second budget, and whether any single beat is long enough to be a slide instead
    whether the idea is a sentence rather than a label
    whether every beat has a caption and alt text, and whether the alt text says anything more
    whether every shape a beat asks for is one of the nine
    whether the still exists on disk, because no animation is load-bearing
    whether anything in it can actually be rendered yet
    whether the captions and the alt text pass the same house style rules the lessons pass
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kxmanim.scene import unrenderable
from kxmanim.storyboard import BUDGET_SECONDS, Storyboard, load_all
from tools.lintprose.rules import check_text

ROOT = Path(__file__).resolve().parents[1]
STORYBOARDS = Path(__file__).resolve().parent / "storyboards"


def faults(board: Storyboard) -> list[str]:
    """Everything wrong with a storyboard, including the parts that need the filesystem."""
    out = list(board.problems())
    if board.still and not (ROOT / board.still).exists():
        out.append(f"the still {board.still} is not there, so the point only lands if it moves")
    for one in board.inputs:
        if not (ROOT / one).exists():
            out.append(f"the input {one} is not there")
    # The captions and the alt text are prose a reader sees, so they get the same rules the
    # lessons get. The transcript is the convenient thing to check because it is every caption
    # and every piece of alt text in one document, generated from the same beats.
    for finding in check_text(board.transcript(), path=board.source):
        out.append(f"house style, {finding.rule}: {finding.message}")
    return out


def report(boards: list[Storyboard]) -> int:
    bad = 0
    for board in boards:
        problems = faults(board)
        name = Path(board.source).name
        if problems:
            bad += 1
            for one in problems:
                print(f"{name}: {one}")
            continue
        missing = unrenderable(board)
        note = f"{board.seconds:.0f}s of {BUDGET_SECONDS}, {len(board.beats)} beats, {board.status}"
        if missing:
            note += f", waiting on a renderer for {', '.join(missing)}"
        elif not board.renderable:
            note += ", not reviewed yet, so it will not render"
        print(f"{name}: {note}")

    if bad:
        print(f"kxmanim: {bad} storyboard(s) need work")
        return 1
    ready = sum(1 for one in boards if one.renderable and not unrenderable(one))
    print(f"kxmanim: {len(boards)} storyboard(s) clean, {ready} ready to render")
    return 0


def captions(boards: list[Storyboard], out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for board in boards:
        (out / f"{board.id}.vtt").write_text(board.vtt(), encoding="utf-8")
        (out / f"{board.id}.md").write_text(board.transcript(), encoding="utf-8")
        print(f"wrote {out / board.id}.vtt and .md")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--storyboards",
        default=str(STORYBOARDS),
        help="where the storyboards live, defaulting to kxmanim/storyboards",
    )
    parser.add_argument(
        "--captions",
        default="",
        help="write the caption track and the transcript for every storyboard into this directory",
    )
    args = parser.parse_args(argv)

    boards = load_all(args.storyboards)
    if not boards:
        print(f"kxmanim: no storyboards in {args.storyboards}")
        return 0
    if args.captions:
        return captions(boards, Path(args.captions))
    return report(boards)


if __name__ == "__main__":
    sys.exit(main())
