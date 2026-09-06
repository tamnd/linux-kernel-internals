"""Look at the corpus from a terminal.

    python3 -m kxray.corpus list                      every artefact and what reads it
    python3 -m kxray.corpus show traces/tier0/write-1byte        one artefact, in full
    python3 -m kxray.corpus normalize traces/tier0/write-1byte   the run taken out of it

`list` and `show` are for the moment somebody is looking for a capture and does not remember what
is in there. `normalize` is for the moment before writing a rule: run it, read the output next to
the original, and see whether the substitution did what it claimed. That reading is the whole check
on a normalisation rule, so it is worth making it one command.

Nothing here writes anything. The corpus is evidence and this only ever looks at it.
"""

from __future__ import annotations

import argparse
import sys

from kxray.corpus import index, normalize


def _list(args) -> int:
    rows = [f"{'id':44} {'reader':16} {'tier':>4} {'lines':>6} {'found':>6}"]
    for one in index.find():
        got = index.read(one)
        tier = "-" if one.tier is None else str(one.tier)
        rows.append(f"{one.id:44} {one.kind:16} {tier:>4} {got.lines:>6} {got.found:>6}")
    print("\n".join(rows))
    return 0


def _show(args) -> int:
    one = index.get(args.id)
    got = index.read(one)
    print(f"{one.id}\n{'=' * len(one.id)}\n")
    print(f"path      {one.path}")
    print(f"reader    {one.kind}")
    print(f"lines     {got.lines}")
    print(f"found     {got.found}")
    if got.accounted is not None:
        print(f"of those  {got.accounted}")
    for name in ("kernel", "arch", "profile", "tier", "captured", "path"):
        if name in one.meta:
            print(f"{name:9} {one.meta[name]}")
    if one.describes:
        print(f"\n{one.describes}")
    return 0


def _normalize(args) -> int:
    try:
        one = index.get(args.id)
        text, source = one.text(), one.id
    except LookupError:
        # Also take a plain path, because the point of this command is trying a rule out and the
        # file being tried is often not in the corpus yet.
        with open(args.id, encoding="utf-8") as handle:
            text, source = handle.read(), args.id
    rules = tuple(args.rules.split(",")) if args.rules else normalize.RULES
    done = normalize.of(text, rules=rules, time=args.time, source=source)
    print(done.text)
    if args.legend and done.legend.rows():
        print(f"\n{done.legend.table()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kxray.corpus", description="Look at the pinned captures.")
    subs = ap.add_subparsers(dest="command", required=True)

    subs.add_parser("list", help="Every artefact and what reads it").set_defaults(run=_list)

    show = subs.add_parser("show", help="One artefact, in full")
    show.add_argument("id", help="An artefact id, for example traces/tier0/write-1byte")
    show.set_defaults(run=_show)

    norm = subs.add_parser("normalize", help="One artefact with the run specific numbers replaced")
    norm.add_argument("id", help="An artefact id, or a path to any file")
    norm.add_argument(
        "--rules", default="", help=f"Comma separated, from {','.join(normalize.ALL)}"
    )
    norm.add_argument("--time", default="elide", choices=("elide", "bucket", "keep"))
    norm.add_argument("--legend", action="store_true", help="Print what each name stands for")
    norm.set_defaults(run=_normalize)

    args = ap.parse_args(argv)
    try:
        return args.run(args)
    except (LookupError, ValueError, OSError) as wrong:
        print(f"kxray.corpus: {wrong}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
