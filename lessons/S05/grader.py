"""Grader for S05.

    python3 lessons/S05/grader.py /proc/kallsyms my-answers.toml

Every check compares your answer against your own machine. There is no stored answer key, because
the number of ops tables in a kernel depends on what that kernel was built with, and a grader that
knew the answer in advance would be teaching you to match my machine rather than to read yours.

Two of the checks want a trace as well. Without one they say so instead of passing, because a
check that quietly skips is a check that reports success for work nobody did.

The grader refuses to run against the handwritten fixture in corpora/proc/handwritten/. That file
exists so the parser had something to test against. Grading somebody on it would be the exact
thing this project promises not to do.
"""

from __future__ import annotations

import math
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kxray import kallsyms  # noqa: E402
from kxray.kallsyms import Symbol  # noqa: E402
from kxray.models import Tape  # noqa: E402

HANDWRITTEN = "corpora/proc/handwritten"

# What "most" means, for the read only question. Two thirds, because the honest answer on a real
# kernel is a large majority rather than all of them, and a reader who says "most" is right.
MOST = 2 / 3

QUESTIONS = {
    "tables": "How many ops tables does your kernel have? Answer 10, 100, 1000 or 10000.",
    "file_ops": "How many of them are file operations? Give a number.",
    "readonly": "Are they in read only data? Answer most, half or few.",
    "hidden": "Were the addresses in /proc/kallsyms real numbers? true or false.",
    "worker": "Which function under vfs_write actually wrote your bytes?",
}


@dataclass(frozen=True)
class Result:
    id: str
    passed: bool
    detail: str

    def __str__(self) -> str:
        mark = "pass" if self.passed else "fail"
        return f"[{mark}] {self.id}: {self.detail}"


def _as_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _bucket(value: int) -> int:
    """Round to the nearest of 10, 100, 1000 and 10000, on a log scale."""
    if value < 1:
        return 0
    return 10 ** min(max(round(math.log10(value)), 1), 4)


def _clean(name: object) -> str:
    return str(name).strip().rstrip("();").lower()


def file_operations(found: list[Symbol]) -> list[Symbol]:
    """The tables that are file operations, in either of the two spellings for it."""
    return [one for one in kallsyms.ops_tables(found) if one.family in ("operations", "fops")]


def check_prediction(found: list[Symbol], answers: dict, tape: Tape | None) -> Result:
    written = str(answers.get("prediction", "")).strip()
    if len(written.split()) < 5:
        return Result("prediction", False, "write down what you expect before you count anything")
    return Result("prediction", True, "prediction recorded")


def check_tables(found: list[Symbol], answers: dict, tape: Tape | None) -> Result:
    given = _as_int(answers.get("tables"))
    actual = len(kallsyms.ops_tables(found))
    if given is None:
        return Result("tables", False, "no answer, give 10, 100, 1000 or 10000")
    if _bucket(given) == _bucket(actual):
        return Result("tables", True, f"your kernel has {actual}, same order of magnitude")
    return Result("tables", False, f"your kernel has {actual} symbols named like an ops table")


def check_file_ops(found: list[Symbol], answers: dict, tape: Tape | None) -> Result:
    given = _as_int(answers.get("file_ops"))
    actual = len(file_operations(found))
    if given == actual:
        return Result("file_ops", True, f"{actual} file operations tables on your machine")
    return Result(
        "file_ops",
        False,
        f"there are {actual}, counting both spellings, so _operations and _fops together",
    )


def check_readonly(found: list[Symbol], answers: dict, tape: Tape | None) -> Result:
    tables = kallsyms.ops_tables(found)
    if not tables:
        return Result("readonly", False, "no ops tables found, so there is nothing to measure")
    share = sum(1 for one in tables if one.readonly) / len(tables)
    actual = "most" if share >= MOST else "half" if share >= 0.4 else "few"
    given = str(answers.get("readonly", "")).strip().lower()
    detail = f"{share:.0%} of your ops tables are in read only data"
    return Result("readonly", given == actual, detail)


def check_hidden(found: list[Symbol], answers: dict, tape: Tape | None) -> Result:
    given = answers.get("hidden")
    actual = kallsyms.hidden(found)
    if isinstance(given, bool) and given == actual:
        if actual:
            zeroed = "zeroed, which is kptr_restrict and means you are not root"
            return Result("hidden", True, zeroed)
        return Result("hidden", True, "real addresses, so you are reading this as root")
    return Result(
        "hidden",
        False,
        "look at the first column. All zeros means the kernel is hiding them from you",
    )


def check_worker(found: list[Symbol], answers: dict, tape: Tape | None) -> Result:
    if tape is None or not tape.roots:
        return Result("worker", False, "no trace here yet, so there is nothing to look underneath")
    write = next((f for f in tape.walk() if f.name == "vfs_write"), None)
    if write is None or not write.children:
        return Result("worker", False, "vfs_write is not in your trace with anything under it")
    given = _clean(answers.get("worker", ""))
    names = {child.name.lower() for child in write.children}
    if given in names:
        return Result("worker", True, f"{given} is what ran under vfs_write in your trace")
    return Result("worker", False, f"the calls directly under vfs_write are {sorted(names)}")


CHECKS = (
    check_prediction,
    check_tables,
    check_file_ops,
    check_readonly,
    check_hidden,
    check_worker,
)


def grade(
    found: list[Symbol], answers: dict, tape: Tape | None = None, source: str = ""
) -> list[Result]:
    if HANDWRITTEN in source.replace("\\", "/"):
        raise ValueError(
            f"{source} is a handwritten fixture and is not evidence, read your own /proc/kallsyms"
        )
    return [check(found, answers, tape) for check in CHECKS]


def passed(results: list[Result]) -> bool:
    return all(r.passed for r in results)


def report(results: list[Result]) -> str:
    lines = [str(r) for r in results]
    score = sum(1 for r in results if r.passed)
    lines.append("")
    lines.append(f"{score} of {len(results)} checks passed against your own kernel")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: grader.py KALLSYMS ANSWERS.toml", file=sys.stderr)
        return 2

    path = Path(args[0])
    found = kallsyms.parse(path.read_text(encoding="utf-8", errors="replace"))
    answers = tomllib.loads(Path(args[1]).read_text(encoding="utf-8"))
    results = grade(found, answers, None, str(path))
    print(report(results))
    return 0 if passed(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
