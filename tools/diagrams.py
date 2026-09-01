"""Build every diagram in the repository, or check that the built ones are current.

    python3 -m tools.diagrams            write the output files
    python3 -m tools.diagrams --check    fail if any output is out of date

A diagram source is a file named `*.diagram.py`. It has to define two things:

    ALT      one sentence describing the diagram for somebody who cannot see it
    scene()  a function returning a kxdraw Scene

`ALT` is not optional and there is no way to opt out of it. A diagram with no alt text is a
diagram that is missing for part of the audience, and the only version of that rule which
survives contact with a deadline is the one that fails the build.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from kxdraw import Scene, to_excalidraw, to_svg

ROOTS = ["lessons", "blueprints", "site"]
SUFFIX = ".diagram.py"


def find(roots: list[str]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        base = Path(root)
        if base.is_dir():
            found.extend(sorted(base.rglob(f"*{SUFFIX}")))
    return found


def load(path: Path) -> tuple[Scene, str]:
    spec = importlib.util.spec_from_file_location(path.stem.replace(".", "_"), path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{path}: not importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    alt = getattr(module, "ALT", None)
    if not alt or not isinstance(alt, str):
        raise RuntimeError(f"{path}: needs an ALT string describing the diagram")
    if not hasattr(module, "scene"):
        raise RuntimeError(f"{path}: needs a scene() function returning a Scene")

    built = module.scene()
    if not isinstance(built, Scene):
        raise RuntimeError(f"{path}: scene() returned {type(built).__name__}, expected a Scene")
    return built, alt


def render(path: Path) -> dict[Path, str]:
    """The files a diagram source produces, as paths to their content."""
    built, alt = load(path)
    stem = path.name[: -len(SUFFIX)]
    return {
        path.with_name(f"{stem}.svg"): to_svg(built, alt),
        path.with_name(f"{stem}.excalidraw"): json.dumps(to_excalidraw(built), indent=2) + "\n",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="diagrams", description="Build the diagrams.")
    ap.add_argument("--check", action="store_true", help="Fail if any output is out of date")
    ap.add_argument("roots", nargs="*", default=ROOTS, help="Where to look")
    args = ap.parse_args(argv)

    sources = find(args.roots or ROOTS)
    if not sources:
        print("diagrams: nothing to build")
        return 0

    stale: list[Path] = []
    written = 0
    for source in sources:
        for target, content in render(source).items():
            current = target.read_text(encoding="utf-8") if target.exists() else None
            if current == content:
                continue
            if args.check:
                stale.append(target)
                continue
            target.write_text(content, encoding="utf-8")
            written += 1
            print(f"wrote {target}")

    if args.check:
        if stale:
            print("These files are out of date. Run `just diagrams`.", file=sys.stderr)
            for target in stale:
                print(f"  {target}", file=sys.stderr)
            return 1
        print(f"diagrams: {len(sources)} source(s) up to date")
        return 0

    if not written:
        print(f"diagrams: {len(sources)} source(s) already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
