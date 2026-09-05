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
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from kxray import kallsyms, lockdep, tracefs
from kxray.btf import reader as btf
from kxray.models import Lines
from kxray.trace import events, formats, parse_file
from kxray.trace import function as trace_function

CORPORA = Path("corpora")
BASELINE = CORPORA / "BASELINE.toml"
SCHEMA = 1

# Which reader opens which artefact, first match winning. This table is the answer to "what reads
# this file", and it is here rather than in each artefact's metadata so that the whole mapping can
# be read at once.
ROUTES = (
    # Both tracers write `.txt` into the same directory and the file name is the only thing that
    # tells them apart, so the narrower pattern has to come first. `flat-` on the front of a
    # capture means the flat function tracer took it.
    ("corpora/traces/*/flat-*.txt", "function"),
    ("corpora/traces/*/events-*.txt", "events"),
    ("corpora/traces/*/*.txt", "function_graph"),
    ("corpora/events/*/*.format", "event-format"),
    ("corpora/proc/*/kallsyms.txt", "kallsyms"),
    ("corpora/proc/*/lockdep.txt", "lockdep-classes"),
    ("corpora/proc/*/lockdep_stats.txt", "lockdep-stats"),
    ("corpora/proc/*/lockdep-stats-*.txt", "lockdep-stats"),
    ("corpora/proc/*/ring-overrun.txt", "tracefs-stats"),
    ("corpora/oops/*/*.txt", "lockdep-splat"),
    ("corpora/btf/*/*.btf", "btf"),
    ("corpora/experiments/*/*.txt", "none"),
)


@dataclass(frozen=True)
class Reading:
    """What one reader got out of one artefact."""

    path: str
    reader: str
    lines: int
    found: int
    accounted: Lines | None

    def row(self) -> dict:
        row = {
            "path": self.path,
            "reader": self.reader,
            "lines": self.lines,
            "found": self.found,
        }
        if self.accounted is not None:
            row["read"] = self.accounted.read
            row["skipped"] = self.accounted.skipped
            row["unparsed"] = self.accounted.unparsed
        return row

    def adds_up(self) -> bool:
        return self.accounted is None or self.accounted.total == self.lines


def _function_graph(path: Path) -> tuple[int, Lines | None]:
    tape = parse_file(path)
    return tape.frame_count, tape.lines


def _function_flat(path: Path) -> tuple[int, Lines | None]:
    log = trace_function.parse_file(path)
    return len(log.calls), log.lines


def _events(path: Path) -> tuple[int, Lines | None]:
    # Read through every format in the corpus rather than through none, because an event that
    # stops binding to its format is exactly the drift this file exists to catch, and a reader
    # given no formats would not notice.
    log = events.parse_file(path, formats.load(CORPORA / "events" / "tier0"))
    return len(log.events), log.lines


def _event_format(path: Path) -> tuple[int, Lines | None]:
    return len(formats.parse_file(path).fields), formats.account(path.read_text(encoding="utf-8"))


def _kallsyms(path: Path) -> tuple[int, Lines | None]:
    text = path.read_text(encoding="utf-8")
    return len(kallsyms.parse(text)), kallsyms.account(text)


def _lockdep_classes(path: Path) -> tuple[int, Lines | None]:
    text = path.read_text(encoding="utf-8")
    return len(lockdep.parse_classes(text)), lockdep.account_classes(text)


def _lockdep_stats(path: Path) -> tuple[int, Lines | None]:
    text = path.read_text(encoding="utf-8")
    return len(lockdep.parse_stats(text).values), lockdep.account_stats(text)


def _tracefs_stats(path: Path) -> tuple[int, Lines | None]:
    text = path.read_text(encoding="utf-8")
    return len(tracefs.parse_stats(text)), tracefs.account_stats(text)


def _lockdep_splat(path: Path) -> tuple[int, Lines | None]:
    # A splat is a report spread over many lines rather than a file of rows, so there is no line
    # accounting to do. What is worth pinning is how many complete ones come out, because the
    # incomplete ones are dropped on purpose and a change there would be silent too.
    return len(lockdep.splats(path.read_text(encoding="utf-8"))), None


def _btf(path: Path) -> tuple[int, Lines | None]:
    # BTF is bytes, so it has no lines. The type count is the thing that would move. Index zero is
    # the void every BTF blob starts with rather than a type anybody declared, so it is not counted,
    # which is also how the artefact's own metadata counts them.
    return len(btf.parse_file(path).types) - 1, None


def _unread(path: Path) -> tuple[int, Lines | None]:
    # An artefact a person reads and no parser does. Its line count is still pinned, so a truncated
    # file is caught even here.
    return 0, None


READERS = {
    "function_graph": _function_graph,
    "function": _function_flat,
    "events": _events,
    "event-format": _event_format,
    "kallsyms": _kallsyms,
    "lockdep-classes": _lockdep_classes,
    "lockdep-stats": _lockdep_stats,
    "tracefs-stats": _tracefs_stats,
    "lockdep-splat": _lockdep_splat,
    "btf": _btf,
    "none": _unread,
}


def route(path: Path) -> str | None:
    """Which reader opens this artefact, or None when nothing claims it."""
    name = path.as_posix()
    return next((reader for pattern, reader in ROUTES if fnmatch(name, pattern)), None)


def artefacts(root: Path = CORPORA) -> list[Path]:
    """Every committed artefact, which means every file with a `.meta.toml` beside it."""
    found = [
        one
        for one in sorted(root.rglob("*"))
        if one.is_file() and one.suffix != ".toml" and one.with_suffix(".meta.toml").exists()
    ]
    return found


def read_one(path: Path) -> Reading:
    reader = route(path)
    if reader is None:
        raise LookupError(f"{path} has no reader in tools/baseline.py")
    found, accounted = READERS[reader](path)
    lines = 0 if reader == "btf" else len(path.read_text(encoding="utf-8").splitlines())
    return Reading(path.as_posix(), reader, lines, found, accounted)


def survey(root: Path = CORPORA) -> list[Reading]:
    return [read_one(one) for one in artefacts(root)]


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
        for name, value in one.row().items():
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
        for name, value in now[path].row().items():
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
        readings = survey()
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
