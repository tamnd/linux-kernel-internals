"""Compare two traces from a terminal, or show what the five levels do to real ones.

    python -m kxdiff a.txt b.txt
    python -m kxdiff a.txt b.txt --level counters --policy everything
    python -m kxdiff --demo

Exit status is 0 when they agree and 1 when they do not, so this is usable in a script. `--demo`
always exits 0, because it is showing what the levels do rather than checking anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kxdiff import diff
from kxdiff.levels import CHAIN, DISTRIBUTION, LEVELS
from kxdiff.policy import POLICIES, SAME_OPERATION
from kxray import trace

ROOT = Path(__file__).resolve().parents[1]
TIER0 = ROOT / "corpora" / "traces" / "tier0"


def load(path: Path):
    return trace.parse(path.read_text(encoding="utf-8"), source=path.name)


def demo() -> int:
    """All five levels against real traces, which is the M1 exit criterion for this tool.

    Two pairs, chosen because they say opposite things.

    A trace against itself agrees at every level. That is the boring result and the one that would
    be alarming if it were missing, because a level that cannot recognise a trace as itself is not
    a function of the trace.

    Two different recipes disagree, and the useful part is where. `write-1byte` and `two-writes`
    differ at every level that is about names: the second one writes to a pipe as well as to a file,
    so it reaches functions the first never does. They agree at `distribution`, because the time
    still goes to the same places in the same proportions. That is the whole argument for
    `distribution` not being in the chain, made on real traces rather than in a comment: it is not
    a looser `set`, it is a different question, and here it gives the opposite answer.
    """
    pairs = [
        ("write-1byte", "write-1byte"),
        ("write-1byte", "two-writes"),
    ]
    for left, right in pairs:
        one, other = load(TIER0 / f"{left}.txt"), load(TIER0 / f"{right}.txt")
        print(f"\n{left} against {right}")
        for level in (*CHAIN, DISTRIBUTION):
            answer = diff(one, other, level=level, policy=SAME_OPERATION, labels=(left, right))
            verdict = "same" if answer.same else "differs"
            print(f"  {level.name:<13} {verdict:<8} {len(answer.differences)} difference(s)")
            for line in answer.differences[:2]:
                print(f"                  {line}")
    print(
        "\nA trace agrees with itself at every level, which is the only result that is not "
        "\ninteresting and the only one that would be alarming if it were missing."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kxdiff", description=__doc__)
    parser.add_argument("left", nargs="?", type=Path)
    parser.add_argument("right", nargs="?", type=Path)
    parser.add_argument("--level", default="sequence", choices=sorted(LEVELS))
    parser.add_argument("--policy", default="same-operation", choices=sorted(POLICIES))
    parser.add_argument("--demo", action="store_true", help="show all five levels on real traces")
    args = parser.parse_args(argv)

    if args.demo:
        return demo()
    if not args.left or not args.right:
        parser.error("two traces, or --demo")

    answer = diff(
        load(args.left),
        load(args.right),
        level=LEVELS[args.level],
        policy=POLICIES[args.policy],
        labels=(args.left.name, args.right.name),
    )
    print(answer.summary())
    return 0 if answer.same else 1


if __name__ == "__main__":
    sys.exit(main())
