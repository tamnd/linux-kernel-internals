"""How strictly to compare two traces, once a policy has decided what to compare.

Five levels. Four of them are a chain: anything that agrees at `exact` agrees at `sequence`,
anything that agrees at `sequence` agrees at `counters`, and anything that agrees at `counters`
agrees at `set`. `tests/test_kxdiff.py` checks that on the real corpus rather than trusting the
argument, because it is the kind of property that is true when it is written and false two changes
later.

`distribution` is not in that chain and pretending otherwise would be the sort of tidy lie that
costs somebody a day. It is about the numbers, which every other level throws away, so a pair of
traces can agree at `sequence` and disagree at `distribution`, and the other way round.

Picking a level is a judgement about what claim is being checked, and the failure mode is picking
one too loose. A comparison that is too strict fails at random and gets turned off. One that is too
loose passes while a lesson quietly tells two different stories. So every level below says what it
is for and, more usefully, what it will not catch.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from kxray.models import Frame, Tape

# How many differences to spell out before saying how many are left. A trace that went wrong
# usually went wrong once and then stayed wrong, so the first few are the answer and the rest are
# the same answer repeated.
SHOWN = 8

# Below this share of the traced time, a function is not what the trace is about, and comparing its
# share is comparing noise. Five percent of a few hundred microseconds is a few microseconds, which
# on an emulated clock is one or two ticks.
FLOOR = 0.05

# How far two shares may drift and still count as the same, in percentage points. This is loose on
# purpose and it is the number to argue about first if `distribution` ever passes something it
# should not have. It is loose because the two backends this was written for disagree about the
# length of a microsecond by a factor of four, so only the proportions carry over at all.
TOLERANCE = 10.0


def _capped(found: list[str], limit: int) -> list[str]:
    if len(found) <= limit:
        return found
    return [*found[:limit], f"and {len(found) - limit} more"]


def _shares(frames: Sequence[Frame]) -> dict[str, float]:
    """What fraction of the traced time each function spent in itself.

    Self time and not duration, because durations nest: a `vfs_write` that took four microseconds
    and a `generic_perform_write` inside it that took one are not five microseconds of work. Adding
    durations up would count the inner one twice and make the outermost frame look like everything.
    """
    own: dict[str, float] = {}
    for frame in frames:
        own[frame.name] = own.get(frame.name, 0.0) + (frame.self_time_us or 0.0)
    total = sum(own.values())
    if total <= 0:
        return {}
    return {name: spent / total for name, spent in own.items() if spent / total >= FLOOR}


class Level:
    """One answer to the question of what it means for two traces to be the same."""

    name = "level"

    def read(self, frames: Sequence[Frame], tape: Tape) -> object:
        raise NotImplementedError

    def differences(self, one: object, other: object, labels: tuple[str, str]) -> list[str]:
        raise NotImplementedError


class Exact(Level):
    """Everything, including the durations and which CPU each frame ran on.

    For deciding whether two traces are the same trace, which is a question about files rather than
    about kernels. Two runs of anything will not agree here, because emulated time is not time and
    real time is not the same time twice, so a failure at this level says almost nothing on its own.

    What it will not catch: nothing, which is the problem. Used as a check on a live kernel it fails
    every time and therefore checks nothing at all.
    """

    name = "exact"

    def read(self, frames, tape):
        return (
            tuple(
                (f.depth, f.name, f.cpu, f.task, f.module, f.complete, f.duration_us)
                for f in frames
            ),
            tuple(tape.cpus),
        )

    def differences(self, one, other, labels):
        left, right = labels
        first, second = one[0], other[0]
        found = []
        if one[1] != other[1]:
            found.append(f"CPUs: {left} says {list(one[1])}, {right} says {list(other[1])}")
        # Lengths differing is one of the things being looked for, not an error, and the tail the
        # shorter one does not reach is reported below.
        for index, (a, b) in enumerate(zip(first, second, strict=False)):
            if a != b:
                found.append(f"call {index}: {left} has {a}, {right} has {b}")
        if len(first) != len(second):
            longer, side = (first, left) if len(first) > len(second) else (second, right)
            extra = longer[min(len(first), len(second)) :]
            found.append(f"{side} has {len(extra)} more call(s), starting with {extra[0][1]}")
        return _capped(found, SHOWN)


class SequenceLevel(Level):
    """The calls, in order, at the depths they were called at, with durations thrown away.

    The right level for almost every claim a lesson makes, because a lesson about a system call is
    a claim about the path the kernel took and the nesting is the answer rather than decoration on
    it. This is what the emulator on and off comparison runs at.

    What it will not catch: anything about time. A change that makes a function a hundred times
    slower without changing what it calls passes here without a murmur.
    """

    name = "sequence"

    def read(self, frames, tape):
        return (
            tuple((f.depth, f.name) for f in frames),
            tuple(f.name for f in frames if not f.complete),
            tuple(tape.cpus),
        )

    def differences(self, one, other, labels):
        left, right = labels
        found = []
        if one[2] != other[2]:
            found.append(f"CPUs: {left} says {list(one[2])}, {right} says {list(other[2])}")
        if one[1] != other[1]:
            found.append(
                f"frames the tracer never saw the end of: {left} {list(one[1])}, "
                f"{right} {list(other[1])}"
            )
        for index, (a, b) in enumerate(zip(one[0], other[0], strict=False)):
            if a != b:
                if a[1] != b[1]:
                    found.append(
                        f"call {index}: {left} ran {a[1]} at depth {a[0]}, "
                        f"{right} has {b[1]} at depth {b[0]}"
                    )
                else:
                    found.append(
                        f"call {index}: {a[1]} at depth {a[0]} in {left}, {b[0]} in {right}"
                    )
        if len(one[0]) != len(other[0]):
            longer, side = (one[0], left) if len(one[0]) > len(other[0]) else (other[0], right)
            extra = longer[min(len(one[0]), len(other[0])) :]
            found.append(f"{side} has {len(extra)} more call(s), starting with {extra[0][1]}")
        return _capped(found, SHOWN)


class Counters(Level):
    """How many times each function was called, with the order and the nesting thrown away.

    For traces where the order is not determined but the work is. Two CPUs doing the same work
    interleave differently every run and there is no useful sense in which one of the interleavings
    is correct, so comparing the sequence there is comparing the scheduler.

    What it will not catch: the order, which means it cannot tell a lock taken before a list is
    walked from one taken after. Do not check a locking claim at this level.
    """

    name = "counters"

    def read(self, frames, tape):
        return Counter(f.name for f in frames)

    def differences(self, one, other, labels):
        left, right = labels
        found = []
        for name in sorted(set(one) | set(other)):
            if one[name] != other[name]:
                found.append(f"{name}: {left} called it {one[name]} time(s), {right} {other[name]}")
        return _capped(found, SHOWN)


class SetLevel(Level):
    """Which functions appeared at all, with the counts thrown away too.

    The loosest of the name based levels, and the right one when a count depends on something the
    reader chooses. A loop that runs once per page has a different count for a one page write and a
    two page write, and the claim being checked is usually that the write goes through that loop at
    all rather than how many times.

    What it will not catch: a call happening once where it used to happen a thousand times, which is
    the shape of most performance regressions and of several correctness bugs.
    """

    name = "set"

    def read(self, frames, tape):
        return frozenset(f.name for f in frames)

    def differences(self, one, other, labels):
        left, right = labels
        found = [f"only {left} ran {name}" for name in sorted(one - other)]
        found += [f"only {right} ran {name}" for name in sorted(other - one)]
        return _capped(found, SHOWN)


class Distribution(Level):
    """Where the time went, as a share of the whole, for the functions that took any of it.

    The only level that looks at the numbers, and the only one that can compare two machines that
    disagree about the length of a microsecond. Shares survive that and absolute times do not: the
    emulator and the recording of the same write differ by a factor of four on the clock and agree
    closely on the proportions.

    For claims of the form "most of the time in a write is spent in X", which is a claim several
    lessons make and which no other level here can check at all.

    What it will not catch: anything about the path. A trace that reaches the same functions by a
    completely different route, or that skips a call entirely without that call having taken much
    time, passes here. Run it alongside `sequence` rather than instead of it.
    """

    name = "distribution"

    def __init__(self, tolerance: float = TOLERANCE):
        self.tolerance = tolerance

    def read(self, frames, tape):
        return _shares(frames)

    def differences(self, one, other, labels):
        left, right = labels
        if not one and not other:
            return []
        if not one or not other:
            side = left if not one else right
            return [
                f"{side} has no timed frames above {FLOOR:.0%} of the trace, "
                "so there is nothing to compare"
            ]
        found = []
        for name in sorted(set(one) | set(other)):
            a, b = one.get(name, 0.0) * 100, other.get(name, 0.0) * 100
            if abs(a - b) > self.tolerance:
                found.append(
                    f"{name}: {a:.0f}% of the time in {left}, {b:.0f}% in {right}, "
                    f"which is more than the {self.tolerance:.0f} point tolerance"
                )
        return _capped(found, SHOWN)


EXACT = Exact()
SEQUENCE = SequenceLevel()
COUNTERS = Counters()
SET = SetLevel()
DISTRIBUTION = Distribution()

# In order from strictest to loosest, for the four that are ordered. `distribution` is deliberately
# not in this tuple, because it is not comparable to the others and putting it at one end would
# invite somebody to treat it as stricter or looser than `set`.
CHAIN = (EXACT, SEQUENCE, COUNTERS, SET)

LEVELS = {one.name: one for one in (*CHAIN, DISTRIBUTION)}
