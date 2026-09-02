"""Comparing two traces, on purpose rather than by eye.

Two questions, and the whole of this package is the claim that they are two questions and not one.

What are we comparing? That is `policy.py`. A trace of one system call contains work the operation
did not cause, work whose presence is decided by the clock, and work the kernel had been putting
off, and a comparison that does not say which of those it is looking at is not repeatable.

How strictly? That is `levels.py`. The same two traces are the same trace or not depending on
whether the question is about the path, the amount of work, the places reached, or where the time
went, and all four are reasonable questions.

`kxbox/bothways.py` was the first caller and it used to answer both questions in one function, with
one policy and one level, both hardcoded. That was fine while there was one comparison. It stopped
being fine the moment a second one was wanted, and the seven defects it found on the way are why
the reasons are written down at length in the two modules rather than summarised here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kxdiff.levels import (
    CHAIN,
    COUNTERS,
    DISTRIBUTION,
    EXACT,
    LEVELS,
    SEQUENCE,
    SET,
    Level,
)
from kxdiff.policy import (
    CLOCK_DEPENDENT,
    EVERYTHING,
    HOUSEKEEPING,
    INTERRUPTS,
    NO_INTERRUPTS,
    POLICIES,
    SAME_OPERATION,
    Policy,
    owner,
)
from kxray.models import Tape

__all__ = [
    "CHAIN",
    "CLOCK_DEPENDENT",
    "COUNTERS",
    "DISTRIBUTION",
    "EVERYTHING",
    "EXACT",
    "HOUSEKEEPING",
    "INTERRUPTS",
    "LEVELS",
    "NO_INTERRUPTS",
    "POLICIES",
    "SAME_OPERATION",
    "SEQUENCE",
    "SET",
    "Diff",
    "Level",
    "Policy",
    "diff",
    "owner",
]


@dataclass(frozen=True)
class Diff:
    """What one comparison found.

    `dropped` is here rather than left out because a pass over ninety frames of a hundred and fifty
    is a different pass from one over all hundred and fifty, and a reader is entitled to know which
    they are looking at without going and reading the policy.
    """

    level: str
    policy: str
    labels: tuple[str, str]
    differences: list[str] = field(default_factory=list)
    kept: tuple[int, int] = (0, 0)
    dropped: tuple[int, int] = (0, 0)

    @property
    def same(self) -> bool:
        return not self.differences

    def summary(self) -> str:
        left, right = self.labels
        how = f"at {self.level}, {self.policy}"
        seen = f"{self.kept[0]} and {self.kept[1]} frame(s) compared"
        if any(self.dropped):
            seen += f", {self.dropped[0]} and {self.dropped[1]} left out by the policy"
        if self.same:
            return f"{left} and {right} agree {how} ({seen})"
        return f"{left} and {right} differ {how} ({seen}): {'; '.join(self.differences)}"

    def __str__(self) -> str:
        return self.summary()


def diff(
    one: Tape,
    other: Tape,
    level: Level = SEQUENCE,
    policy: Policy = SAME_OPERATION,
    labels: tuple[str, str] = ("left", "right"),
) -> Diff:
    """Compare two traces under one policy at one strictness, and say where they stop agreeing.

    The defaults are the question worth asking most often: did one operation take the same path
    both times, with the machine's own noise left out. They are defaults and not the only option,
    and picking a looser level than the claim needs is the way this gets quietly useless.
    """
    kept = (policy.keep(one), policy.keep(other))
    return Diff(
        level=level.name,
        policy=policy.name,
        labels=labels,
        differences=level.differences(level.read(kept[0], one), level.read(kept[1], other), labels),
        kept=(len(kept[0]), len(kept[1])),
        dropped=(policy.dropped(one), policy.dropped(other)),
    )
