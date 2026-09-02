"""Command line entry point.

Usage: python3 -m tools.lintprose lessons/ blueprints/ README.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .rules import ALL_RULES, check_file

# Directories that hold somebody else's writing. These rules are the house style of this
# repository and applying them to a vendored dependency or to an unpacked kernel tree is both
# meaningless and extremely loud: the first run after `tree.sh` reported a hundred and forty two
# findings, every one of them in a README that shipped with Linux. A directory named here is
# skipped wherever it turns up, at any depth.
NOT_OURS = {".git", "__pycache__", "node_modules", "vendor", "build"}


def collect(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out.extend(
                sorted(found for found in p.rglob("*.md") if not NOT_OURS.intersection(found.parts))
            )
        elif p.suffix == ".md":
            # A file named on the command line is checked whatever it is, because asking for it by
            # name is a person saying they meant this one.
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lintprose", description="House style rules for prose.")
    ap.add_argument("paths", nargs="+", help="Markdown files or directories to check")
    ap.add_argument("--list-rules", action="store_true", help="Print the rules and exit")
    args = ap.parse_args(argv)

    if args.list_rules:
        for rule in ALL_RULES:
            name = rule.__name__.removeprefix("rule_").replace("_", "-")
            doc = (rule.__doc__ or "").strip().split("\n")[0]
            print(f"{name:22} {doc}")
        return 0

    files = collect(args.paths)
    if not files:
        print("lintprose: nothing to check", file=sys.stderr)
        return 1

    findings = [f for path in files for f in check_file(path)]
    for f in findings:
        print(f)

    if findings:
        print(f"\n{len(findings)} finding(s) in {len(files)} file(s)", file=sys.stderr)
        return 1

    print(f"lintprose: {len(files)} file(s) clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
