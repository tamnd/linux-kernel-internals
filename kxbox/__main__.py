"""What Tier 0 can do on this machine, and whether the recordings hold together.

    python3 -m kxbox              what backend you would get here, and what it knows how to do
    python3 -m kxbox --check      fail if a recipe points at a file that is not there
    python3 -m kxbox --both-ways  run every recipe with the emulator and without it

The check is what CI runs. A recipe naming a capture that nobody committed is a lesson cell that
works for the person who wrote it and fails for everybody else, and it fails at the moment a
reader is trying to learn something rather than at the moment somebody could fix it.

`--both-ways` is here so that somebody who wants the M0 comparison finds out where to run it. It
needs an emulator and there is not one outside a browser tab, so on a terminal it prints what is
missing and returns 2 rather than pretending. `kxbox/web/both-ways.py` is the same code with a
kernel behind it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from kxbox.corpus import CORPORA, Recipe, evidence_of, load_recipes
from kxbox.session import boot, repo_root


def check(root: Path) -> list[str]:
    """Everything wrong with the recipe list, in the words of somebody who has to fix it."""
    problems: list[str] = []
    recipes = load_recipes(root)

    seen: dict[str, str] = {}
    for one in recipes:
        if not one.name:
            problems.append("a recipe has no name, so nothing can ask for it")
            continue
        key = f"{one.profile}/{one.name}"
        if key in seen:
            problems.append(f"{key} is listed twice, and the second one would never be reached")
        seen[key] = one.name
        problems.extend(_check_files(root, one))
    return problems


def _check_files(root: Path, one: Recipe) -> list[str]:
    problems = []
    for label, relative in [("trace", one.trace), *sorted(one.files.items())]:
        if not relative:
            continue
        if not (root / CORPORA / relative).exists():
            problems.append(f"{one.name}: {label} points at {relative}, which is not committed")
    if not one.command:
        problems.append(f"{one.name}: no command, so nobody can tell what was recorded")
    if not one.describes:
        problems.append(f"{one.name}: no description, so the banner has nothing to say")
    return problems


def report(root: Path) -> str:
    box = boot(root=root)
    lines = [box.banner(), ""]
    recipes = load_recipes(root)
    if not recipes:
        lines.append("no recordings yet")
        return "\n".join(lines)

    lines.append(f"{len(recipes)} recording(s):")
    for one in sorted(recipes, key=lambda r: (r.profile, r.name)):
        mark = "real" if one.trace and evidence_of(root, one.trace) else "handwritten"
        lines.append(f"  {one.profile}/{one.name}  {mark}  {one.describes}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kxbox", description="What Tier 0 can do here.")
    ap.add_argument("--check", action="store_true", help="Fail if a recording is missing")
    ap.add_argument(
        "--both-ways", action="store_true", help="Compare the emulator against the recordings"
    )
    args = ap.parse_args(argv)

    root = repo_root()
    if args.both_ways:
        from kxbox import bothways

        found = bothways.run(root=root)
        print(found.summary())
        # Three outcomes and three codes, because "nothing was measured" is not a pass and is not
        # a failure either. A caller that treated it as one of those two would be the exact
        # mistake this whole module is written to avoid.
        return {None: 2, True: 0, False: 1}[found.same]

    if not args.check:
        print(report(root))
        return 0

    problems = check(root)
    for one in problems:
        print(f"kxbox: {one}")
    if not problems:
        print(f"kxbox: {len(load_recipes(root))} recipe(s) clean")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
