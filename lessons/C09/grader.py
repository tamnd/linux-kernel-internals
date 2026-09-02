"""Grader for C09.

    python3 lessons/C09/grader.py my-splat.txt my-answers.toml [/proc/lockdep_stats]

Every check reads your own splat. There is no stored answer key, because the lock names, the task
name and the addresses all come from the module you built and the machine you ran it on, and a
grader that knew them in advance would be marking you against my run rather than against yours.

One check wants `/proc/lockdep_stats` as well. Without it the check says so instead of passing,
because a check that quietly skips is a check that reports success for work nobody did.

The grader refuses to run against the handwritten fixtures under `corpora/`. They exist so the
parser had something to parse. Grading somebody on a file nobody's kernel produced is the exact
thing this project promises not to do.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kxray import lockdep  # noqa: E402
from kxray.lockdep import Splat, Stats  # noqa: E402

HANDWRITTEN = ("corpora/oops/handwritten", "corpora/proc/handwritten")

QUESTIONS = {
    "prediction": "Before you load the module: will it hang? Write a sentence saying why.",
    "who": "Which task hit the report? Give the name from the header, without the pid.",
    "length": "How many lock classes are in the cycle? Give a number.",
    "cycle": "Name them in the order the edges run, as a list. A cycle has no start, so any "
    "starting point is fine.",
    "learned_in": "Which function taught lockdep the other edge? It is not the one that hit the "
    "report.",
    "checker": "After this report, is lockdep still checking? Answer on or off.",
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


def _clean(name: object) -> str:
    """A function or lock name with the decoration people paste along with it taken off."""
    text = str(name).strip().strip("(),;")
    return text.split("+")[0].strip().lower()


def rotations(names: list[str]) -> list[list[str]]:
    """Every way of writing the same cycle.

    A cycle has no first element. Somebody who reads the graph starting from the other lock has
    the same answer, and marking that wrong would be marking them on where their eye landed.
    """
    return [names[at:] + names[:at] for at in range(len(names))]


def other_edge(splat: Splat) -> str:
    """The function that recorded the edge the reporting thread did not record.

    This is the one worth finding. The thread that hits the splat is easy, it is in the header.
    The other half of the cycle was recorded somewhere else, often in a subsystem written by
    somebody who has never heard of this one, and finding it is the actual work.
    """
    held = splat.holding.name if splat.holding else ""
    for one in splat.chain:
        if one.name == held:
            return one.taken_in
    return ""


def check_prediction(splat: Splat, answers: dict, stats: Stats | None) -> Result:
    written = str(answers.get("prediction", "")).strip()
    if len(written.split()) < 5:
        return Result("prediction", False, "say what you expect before you load anything")
    return Result("prediction", True, "prediction recorded")


def check_who(splat: Splat, answers: dict, stats: Stats | None) -> Result:
    given = _clean(answers.get("who", "")).split("/")[0]
    actual = splat.task.lower()
    if given and given == actual:
        return Result("who", True, f"{splat.task} with pid {splat.pid} hit it")
    return Result("who", False, "the first line of the report names the task, before the slash")


def check_length(splat: Splat, answers: dict, stats: Stats | None) -> Result:
    given = _as_int(answers.get("length"))
    actual = splat.length
    if given == actual:
        return Result("length", True, f"{actual} lock classes in your cycle")
    return Result(
        "length",
        False,
        f"count the numbered entries in the chain, there are {actual} of them",
    )


def check_cycle(splat: Splat, answers: dict, stats: Stats | None) -> Result:
    given = answers.get("cycle")
    if not isinstance(given, (list, tuple)) or not given:
        return Result("cycle", False, "give a list of lock names, in the order the edges run")
    names = [_clean(one) for one in given]
    if names[0] == names[-1] and len(names) > 1:
        names = names[:-1]  # written closed, which is fine, it is the same cycle
    actual = [one.lower() for one in splat.classes]
    if names in rotations(actual):
        return Result("cycle", True, " -> ".join(splat.cycle))
    if sorted(names) == sorted(actual):
        return Result("cycle", False, "right locks, wrong order, read the chain from #0 upward")
    return Result("cycle", False, f"your chain has {len(actual)} entries, numbered from #0")


def check_learned_in(splat: Splat, answers: dict, stats: Stats | None) -> Result:
    actual = other_edge(splat)
    if not actual:
        return Result("learned_in", False, "no stack under the held lock, so nothing to find")
    given = _clean(answers.get("learned_in", ""))
    if given and given == _clean(actual):
        return Result("learned_in", True, f"{actual} recorded the edge that was already there")
    return Result(
        "learned_in",
        False,
        "look at the numbered entry for the lock you were holding, and skip the checker frames",
    )


def check_checker(splat: Splat, answers: dict, stats: Stats | None) -> Result:
    if stats is None:
        return Result("checker", False, "no lockdep statistics here, so there is nothing to read")
    if stats.debug_locks is None:
        return Result("checker", False, "these statistics have no debug_locks line in them")
    actual = "off" if stats.off else "on"
    given = str(answers.get("checker", "")).strip().lower()
    detail = f"debug_locks is {stats.debug_locks}, so the checker is {actual}"
    return Result("checker", given == actual, detail)


CHECKS = (
    check_prediction,
    check_who,
    check_length,
    check_cycle,
    check_learned_in,
    check_checker,
)


def grade(
    splat: Splat, answers: dict, stats: Stats | None = None, source: str = ""
) -> list[Result]:
    # The splat remembers where it was parsed from, so a caller who passes nothing still cannot
    # slip a fixture past the refusal by leaving the argument off.
    where = (source or splat.source).replace("\\", "/")
    if any(one in where for one in HANDWRITTEN):
        raise ValueError(
            f"{source} is a handwritten fixture and is not evidence, read your own dmesg"
        )
    return [check(splat, answers, stats) for check in CHECKS]


def passed(results: list[Result]) -> bool:
    return all(r.passed for r in results)


def report(results: list[Result]) -> str:
    lines = [str(r) for r in results]
    score = sum(1 for r in results if r.passed)
    lines.append("")
    lines.append(f"{score} of {len(results)} checks passed against your own report")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in (2, 3):
        print("usage: grader.py SPLAT ANSWERS.toml [LOCKDEP_STATS]", file=sys.stderr)
        return 2

    path = Path(args[0])
    try:
        splat = lockdep.parse_splat(path.read_text(encoding="utf-8", errors="replace"), str(path))
    except (lockdep.Truncated, lockdep.NotASplat) as refused:
        print(f"cannot grade this: {refused}", file=sys.stderr)
        return 2

    answers = tomllib.loads(Path(args[1]).read_text(encoding="utf-8"))
    stats = lockdep.parse_stats(Path(args[2]).read_text()) if len(args) == 3 else None
    results = grade(splat, answers, stats, str(path))
    print(report(results))
    return 0 if passed(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
