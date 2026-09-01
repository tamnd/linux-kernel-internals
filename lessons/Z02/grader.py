"""Grader for Z02.

    python3 lessons/Z02/grader.py my-trace.txt my-answers.toml

Every check in here compares your answer against your own trace. There is no stored answer key,
and there is nowhere for one to hide, because the correct value is computed from the file you
captured. A number that is right on my machine is not right on yours, and a grader that pretended
otherwise would be teaching you to match my output rather than to read yours.

The grader refuses to run against the handwritten traces in corpora/traces/handwritten/. Those
exist so the parser had something to test against. Grading somebody on a trace nobody captured
would be the exact thing this project promises not to do.
"""

from __future__ import annotations

import math
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kxray.models import Tape  # noqa: E402
from kxray.trace import function_graph  # noqa: E402

HANDWRITTEN = "corpora/traces/handwritten"

# Names that mean the write went past the page cache and towards a device. Not exhaustive, and it
# does not need to be: it is here to tell "the disk was involved" from "the disk was not".
BLOCK_LAYER = ("submit_bio", "blk_mq", "generic_make_request", "iomap_writepage", "writeback")

QUESTIONS = {
    "frames": "How many calls does writing one byte take? Answer 10, 100, 1000 or 10000.",
    "outermost": "What is the outermost kernel function in your trace?",
    "depth": "How deep does the call stack go?",
    "reached_disk": "Did the write reach the disk before write() returned? true or false.",
    "cpus": "How many CPUs appear in your trace?",
}


@dataclass(frozen=True)
class Result:
    id: str
    passed: bool
    detail: str

    def __str__(self) -> str:
        mark = "pass" if self.passed else "fail"
        return f"[{mark}] {self.id}: {self.detail}"


def reached_disk(tape: Tape) -> bool:
    """Whether anything in the trace belongs to the block layer."""
    return any(any(marker in f.name for marker in BLOCK_LAYER) for f in tape.walk())


def _bucket(value: int) -> int:
    """Round a count to the nearest of 10, 100, 1000 and 10000.

    Nearest on a log scale, because those are the choices the reader was offered. A trace with
    four calls in it belongs in the 10 bucket rather than in one that does not exist, and 400
    belongs with 1000 rather than with 100. An empty trace stays 0 so it matches nothing.
    """
    if value < 1:
        return 0
    return 10 ** min(max(round(math.log10(value)), 1), 4)


def _as_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _clean(name: object) -> str:
    return str(name).strip().rstrip("();").lower()


def check_prediction(tape: Tape, answers: dict) -> Result:
    """You have to have written something down before you ran anything.

    Nothing here can tell when you wrote it. The gate is honest about that: it asks for words,
    not for proof, and the person it is protecting is you.
    """
    written = str(answers.get("prediction", "")).strip()
    if len(written.split()) < 5:
        return Result(
            "prediction", False, "write down what you expect before you look at the trace"
        )
    return Result("prediction", True, "prediction recorded")


def check_frames(tape: Tape, answers: dict) -> Result:
    given = _as_int(answers.get("frames"))
    actual = tape.frame_count
    if given is None:
        return Result("frames", False, "no answer, give 10, 100, 1000 or 10000")
    if _bucket(given) == _bucket(actual):
        return Result("frames", True, f"your trace has {actual} calls, same order of magnitude")
    return Result(
        "frames",
        False,
        f"your trace has {actual} calls, and remember that a branch costs two lines and a leaf one",
    )


def check_outermost(tape: Tape, answers: dict) -> Result:
    names = {f.name.lower() for f in tape.roots}
    given = _clean(answers.get("outermost", ""))
    if not names:
        return Result("outermost", False, "your trace has no complete outermost call in it")
    if given in names:
        return Result("outermost", True, f"{given} is an outermost call in your trace")
    return Result("outermost", False, f"the outermost calls in your trace are {sorted(names)}")


def check_depth(tape: Tape, answers: dict) -> Result:
    given = _as_int(answers.get("depth"))
    actual = tape.max_depth
    if given == actual:
        return Result("depth", True, f"your trace goes {actual} levels deep")
    return Result("depth", False, f"your trace goes {actual} levels deep, count the indentation")


def check_reached_disk(tape: Tape, answers: dict) -> Result:
    given = answers.get("reached_disk")
    actual = reached_disk(tape)
    if isinstance(given, bool) and given == actual:
        return Result("reached_disk", True, f"block layer in this trace: {actual}")
    if actual:
        return Result("reached_disk", False, "there is block layer work in your trace, find it")
    return Result(
        "reached_disk",
        False,
        "no block layer function appears in your trace, so the byte stopped in the page cache",
    )


def check_cpus(tape: Tape, answers: dict) -> Result:
    given = _as_int(answers.get("cpus"))
    actual = len(tape.cpus)
    if given == actual:
        return Result("cpus", True, f"{actual} CPU(s) in your trace: {tape.cpus}")
    return Result("cpus", False, f"your trace has {actual} CPU(s), the numbers are in the brackets")


CHECKS = (
    check_prediction,
    check_frames,
    check_outermost,
    check_depth,
    check_reached_disk,
    check_cpus,
)


def grade(tape: Tape, answers: dict) -> list[Result]:
    if HANDWRITTEN in tape.source.replace("\\", "/"):
        raise ValueError(
            f"{tape.source} is a handwritten fixture and is not evidence, capture your own trace"
        )
    return [check(tape, answers) for check in CHECKS]


def passed(results: list[Result]) -> bool:
    return all(r.passed for r in results)


def report(results: list[Result]) -> str:
    lines = [str(r) for r in results]
    score = sum(1 for r in results if r.passed)
    lines.append("")
    lines.append(f"{score} of {len(results)} checks passed against your own trace")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: grader.py TRACE ANSWERS.toml", file=sys.stderr)
        return 2

    tape = function_graph.parse_file(Path(args[0]))
    answers = tomllib.loads(Path(args[1]).read_text(encoding="utf-8"))
    results = grade(tape, answers)
    print(report(results))
    return 0 if passed(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
