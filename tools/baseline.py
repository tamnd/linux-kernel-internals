"""The unparsed line baseline.

    python3 -m tools.baseline            check the corpus against corpora/BASELINE.toml
    python3 -m tools.baseline --write    rewrite the baseline after a deliberate change
    python3 -m tools.baseline --show     print what the readers see, and stop

Every parser in this project is written to survive a line it does not understand. That is the
right behaviour, because these files come off kernels nobody writing this has seen, and a parser
that dies on line four hundred thousand helps nobody. It is also the behaviour that lets a lesson
go quietly wrong, because a parser that swallows a line looks exactly like a parser that had
nothing to swallow.

So every line of every committed artefact is put in one of three buckets and the numbers are
written down here. `read` turned into something. `skipped` was never data: a blank line, a
separator, a header the kernel prints above the rows. `unparsed` was meant to be data and was not
understood. The three have to add up to the number of lines in the file, and this tool checks that
before it checks anything else, because a reader whose numbers do not add up is a reader that is
guessing rather than counting.

The bucket that matters is not the last one. A rise in `unparsed` is a failure anybody would
notice, and the existing tests already catch it for traces. The dangerous move is a line sliding
from `read` to `skipped`, which is what happens when a format grows a field and a regular
expression stops matching. Nothing raises, nothing is logged, and the lesson shows the reader less
than it did last week. That drift is invisible unless the count was written down first, and
writing it down is all this file is.

One number here is deliberately not zero. `corpora/proc/tier0/ring-overrun.txt` has two lines the
reader skips because they are timestamps rather than counters. A tool that insisted on zero would
have made somebody either delete a true line from a real capture or teach the reader to lie about
it, so the rule is that the number is recorded rather than that the number is small.

An artefact that no reader claims is an error, not an omission. Adding a capture to `corpora/`
without saying what reads it is how a file ends up in the repository that nothing has ever opened.

The reading itself is not done here. `kxray.corpus.index` knows which reader opens which artefact
and runs it, because a lesson wants to open one file the same way this tool opens all of them, and
two copies of that knowledge is how the lesson and the baseline end up disagreeing. What is left in
this file is the comparison against `corpora/BASELINE.toml`, which is the only part that is about
the baseline rather than about the corpus.
"""

from __future__ import annotations

import argparse
import sys
import tomllib

from kxray.corpus import index
from kxray.corpus.index import CORPORA, Reading

BASELINE = CORPORA / "BASELINE.toml"
SCHEMA = 1


def row(one: Reading) -> dict:
    """The line this reading gets in the baseline file."""
    out = {"path": one.path, "reader": one.reader, "lines": one.lines, "found": one.found}
    if one.accounted is not None:
        out["read"] = one.accounted.read
        out["skipped"] = one.accounted.skipped
        out["unparsed"] = one.accounted.unparsed
    return out


def totals(readings: list[Reading]) -> dict[str, int]:
    counted = [one.accounted for one in readings if one.accounted is not None]
    return {
        "artefacts": len(readings),
        "lines": sum(one.lines for one in readings),
        "read": sum(one.read for one in counted),
        "skipped": sum(one.skipped for one in counted),
        "unparsed": sum(one.unparsed for one in counted),
    }


def as_toml(readings: list[Reading]) -> str:
    """The baseline file, written by hand rather than by a TOML library, so it reads well."""
    out = [HEADER, f"schema = {SCHEMA}", "", "[totals]"]
    out += [f"{name} = {value}" for name, value in totals(readings).items()]
    for one in readings:
        out += ["", "[[artefact]]"]
        for name, value in row(one).items():
            out.append(f'{name} = "{value}"' if isinstance(value, str) else f"{name} = {value}")
    return "\n".join(out) + "\n"


HEADER = """\
# How much of every committed artefact the parsers understand, written down so that a change to
# any of it is a build failure rather than something a reader finds.
#
# `read` turned into something, `skipped` was never data, `unparsed` was meant to be data and was
# not understood. The three add up to `lines` for every reader that accounts for lines. `found` is
# what the reader got: frames from a trace, symbols from kallsyms, counters from a stats file,
# complete splats from an oops, types from a BTF blob.
#
# Regenerate with `python3 -m tools.baseline --write`, and say in the commit message why a number
# moved. A number moving on its own is the failure this file exists to catch.
"""


def compare(readings: list[Reading], recorded: dict) -> list[str]:
    """Every way the corpus and the baseline disagree, in the order a reader wants them."""
    problems = []
    if recorded.get("schema") != SCHEMA:
        problems.append(f"baseline schema is {recorded.get('schema')!r}, this tool writes {SCHEMA}")

    was = {one["path"]: one for one in recorded.get("artefact", [])}
    now = {one.path: one for one in readings}

    for path in sorted(set(was) - set(now)):
        problems.append(f"{path} is in the baseline and not in the corpus")
    for path in sorted(set(now) - set(was)):
        problems.append(f"{path} is in the corpus and not in the baseline")

    for path in sorted(set(now) & set(was)):
        for name, value in row(now[path]).items():
            if was[path].get(name) != value:
                problems.append(f"{path}: {name} was {was[path].get(name)!r}, is now {value!r}")
    return problems


def show(readings: list[Reading]) -> str:
    rows = [f"{'artefact':44} {'reader':16} {'lines':>6} {'read':>6} {'skip':>5} {'unparsed':>8}"]
    for one in readings:
        counted = one.accounted
        numbers = (
            f"{counted.read:>6} {counted.skipped:>5} {counted.unparsed:>8}"
            if counted
            else f"{'-':>6} {'-':>5} {'-':>8}"
        )
        rows.append(f"{one.path:44} {one.reader:16} {one.lines:>6} {numbers}")
    counts = totals(readings)
    rows.append("")
    rows.append(
        f"{counts['artefacts']} artefacts, {counts['lines']} lines, {counts['read']} read, "
        f"{counts['skipped']} skipped, {counts['unparsed']} unparsed"
    )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="baseline", description="Check the unparsed line baseline.")
    ap.add_argument("--write", action="store_true", help="Rewrite the baseline")
    ap.add_argument("--show", action="store_true", help="Print what the readers see and stop")
    ap.add_argument("--check", action="store_true", help="Check, which is what it does anyway")
    args = ap.parse_args(argv)

    try:
        readings = index.survey()
    except LookupError as unclaimed:
        print(f"baseline: {unclaimed}", file=sys.stderr)
        return 1

    wrong = [one.path for one in readings if not one.adds_up()]
    if wrong:
        for path in wrong:
            print(f"baseline: {path} does not add up, so its reader is guessing", file=sys.stderr)
        return 1

    if args.show:
        print(show(readings))
        return 0

    if args.write:
        BASELINE.write_text(as_toml(readings), encoding="utf-8")
        counts = totals(readings)
        print(f"baseline: wrote {BASELINE}, {counts['artefacts']} artefact(s)")
        return 0

    if not BASELINE.exists():
        print(f"baseline: {BASELINE} does not exist, run --write", file=sys.stderr)
        return 1

    problems = compare(readings, tomllib.loads(BASELINE.read_text(encoding="utf-8")))
    for problem in problems:
        print(problem)
    if problems:
        print(
            f"\n{len(problems)} difference(s). If they are meant, run "
            "`python3 -m tools.baseline --write` and say why in the commit message.",
            file=sys.stderr,
        )
        return 1

    counts = totals(readings)
    print(
        f"baseline: {counts['artefacts']} artefact(s), {counts['lines']} line(s), "
        f"{counts['unparsed']} unparsed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
