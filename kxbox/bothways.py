"""Run every Tier 0 recipe with the emulator and again without it, and see whether they agree.

    import kxbox.bothways as bothways

    report = bothways.run()
    print(report.summary())

M0 asks whether all three lessons produce identical normalised output with the emulator on and
with `KXBOX_DISABLE=1`. That question is really about the recordings. A lesson never asks the
emulator for anything directly: it asks for a named recipe, the live backend runs the command
behind that name and the corpus backend hands back the file that was captured under it. So if
every recipe gives the same answer both ways, every lesson does, and if one of them does not then
some lesson is quietly telling two different stories depending on who is reading it.

The whole thing turns on what "identical" is allowed to mean. That used to be written down here,
because here was the only place that asked. It now lives in `kxdiff`, which splits the question in
two: a policy saying which frames a comparison is about, and a level saying how strictly to compare
what is left. This file picks one of each, at the top, and that pair is the whole of what this
comparison means.

The level is `sequence`: the calls in order, at the depths they were called at, with the durations
thrown away, because emulated time is not time and no two runs of anything agree on it.

The policy is `same-operation`: interrupt work, work whose presence is decided by the clock, work
the kernel had been putting off, and anything belonging to a task other than the one being traced.
Each of those is a concession, each was arrived at by running this and watching it fail, and the
afternoon each one cost is written beside it in `kxdiff/policy.py`.

Interrupts are handled in two places, because one is not enough.

The bridge sets `nofuncgraph-irqs`, which is the kernel not recording the interrupt at all and is
much the better of the two, since a frame that was never written cannot be compared wrong. That
misses `irq_enter_rcu`, which runs before the flag it is tested against is set,
and it misses every softirq, which runs after `irq_exit` with `in_hardirq()` false.

What none of this is for is the guest being in a different state. Every recording was taken as the
first thing a freshly booted guest did, so `compare` is given one recipe at a time and the page
reloads between them. Loosening the check to paper over that would have hidden a real difference.

The other thing worth saying out loud is that this refuses to pass when there is nothing to
compare against. Off a browser there is no emulator for `kxbox.boot()` to find, so both sides come
back as the corpus and every recipe matches itself perfectly. That is not the criterion being met,
it is the criterion not being measured, and `Report.live` is False in that case with `Report.same`
left as None rather than True.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import kxdiff
from kxbox import session
from kxbox.corpus import load_recipes
from kxray.models import InterruptEntry, Tape

# The two halves of the question, named here so that this file says which comparison it is running
# and `kxdiff` says what that comparison means. They used to be the same code and separating them
# is most of what M1 is for.
LEVEL = kxdiff.SEQUENCE
POLICY = kxdiff.SAME_OPERATION
SIDES = ("emulator", "recording")


@dataclass(frozen=True)
class Varies:
    """The parts two honest runs are expected to disagree about, counted rather than hidden.

    Reporting the drop matters. A pass over forty three frames out of a hundred and eight is a
    different pass from one over all hundred and eight, and silently throwing the rest away and
    saying "same" would be the same check with less honesty.
    """

    duration_us: float
    dropped: int
    unparsed: int

    def __str__(self) -> str:
        return (
            f"{self.duration_us:.1f}us, {self.dropped} frame(s) dropped, {self.unparsed} unparsed"
        )


def varies(tape: Tape) -> Varies:
    return Varies(
        duration_us=tape.total_duration_us,
        dropped=POLICY.dropped(tape) + sum(1 for e in tape.events if isinstance(e, InterruptEntry)),
        unparsed=len(tape.unparsed),
    )


@dataclass(frozen=True)
class Comparison:
    """One recipe, run both ways."""

    recipe: str
    same: bool
    differences: tuple[str, ...] = ()
    live: Varies | None = None
    replay: Varies | None = None
    calls: int = 0
    error: str = ""

    def __str__(self) -> str:
        if self.error:
            return f"[error] {self.recipe}: {self.error}"
        mark = "same" if self.same else "DIFFERENT"
        tail = f"{self.calls} call(s), emulator {self.live}, recording {self.replay}"
        return f"[{mark}] {self.recipe}: {tail}"


@dataclass(frozen=True)
class Report:
    """What the whole comparison found, and whether it was in a position to find anything."""

    profile: str
    live: bool
    why: str
    comparisons: tuple[Comparison, ...] = ()

    @property
    def same(self) -> bool | None:
        """True, False, or None when there was no emulator and nothing was really compared."""
        if not self.live:
            return None
        return all(one.same and not one.error for one in self.comparisons)

    def summary(self) -> str:
        if not self.live:
            return (
                f"not measured: {self.why}\n"
                "Both sides would be the recording, so they would match for the wrong reason. "
                "This has to run in a browser tab, which is what kxbox/web/both-ways.py is for."
            )
        lines = [str(one) for one in self.comparisons]
        agreed = sum(1 for one in self.comparisons if one.same and not one.error)
        lines.append("")
        lines.append(
            f"{agreed} of {len(self.comparisons)} recipe(s) give the same answer both ways, "
            f"profile {self.profile}"
        )
        for one in self.comparisons:
            for line in one.differences:
                lines.append(f"  {one.recipe}: {line}")
        return "\n".join(lines)


def compare(
    live: session.Box,
    replay: session.Box,
    root: Path | None = None,
    only: str | None = None,
) -> list[Comparison]:
    """Every recipe for this profile, run on both boxes, in the order they are listed.

    `only` narrows it to one recipe, and the caller that uses it is the browser page, which runs
    one recipe per boot. That is not an optimisation, it is the only way this is a fair comparison.
    Every recording was taken as the first thing a freshly booted guest did, and a guest that has
    already run a recipe is not that guest. Some of what changes is obvious, like a file that now
    exists, which is what `repeatable` in the recipe list is about. Some of it is not obvious at
    all: whether a write updates the file's timestamp depends on whether anything has looked at
    that timestamp since it was last set, so `two-writes` grew a whole `inode_update_time` subtree
    on the runs where `write-1byte` had gone first, and did not on the runs where it had not.
    Chasing those one at a time is chasing the symptom. Running each recipe on the guest its
    recording was taken on is the fix.
    """
    root = root or session.repo_root()
    recipes = [one for one in load_recipes(root) if one.profile == replay.profile]
    if only is not None:
        recipes = [one for one in recipes if one.name == only]

    out = []
    for one in recipes:
        try:
            fresh = live.trace(
                one.name,
                lambda one=one: live.sh(one.command),
                functions=one.functions,
                owns_window=one.owns_window,
            )
            recorded = replay.trace(one.name)
        except Exception as error:  # noqa: BLE001 - the message is the result here
            out.append(Comparison(one.name, False, error=f"{type(error).__name__}: {error}"))
            continue

        answer = kxdiff.diff(fresh, recorded, level=LEVEL, policy=POLICY, labels=SIDES)
        out.append(
            Comparison(
                recipe=one.name,
                same=answer.same,
                differences=tuple(answer.differences),
                live=varies(fresh),
                replay=varies(recorded),
                calls=answer.kept[1],
            )
        )
    return out


def names(profile: str = "teaching", root: Path | None = None) -> list[str]:
    """The recipes this profile has, in order. What a caller doing one per boot iterates over."""
    root = root or session.repo_root()
    return [one.name for one in load_recipes(root) if one.profile == profile]


def run(profile: str = "teaching", root: Path | None = None, only: str | None = None) -> Report:
    """Boot both backends in one process and compare them.

    The order matters. The live box is taken first, while the environment is untouched, and then
    `KXBOX_DISABLE` is set to force the second one to the recording. Setting it first would give
    two recordings, which is exactly the mistake this module exists to avoid making quietly.
    """
    root = root or session.repo_root()
    was = os.environ.get(session.DISABLE)

    live = session.boot(profile, root=root)
    if not live.live:
        return Report(profile, False, live.why or "no emulator in this page")

    try:
        os.environ[session.DISABLE] = "1"
        replay = session.boot(profile, root=root)
        return Report(profile, True, "", tuple(compare(live, replay, root, only)))
    finally:
        if was is None:
            os.environ.pop(session.DISABLE, None)
        else:
            os.environ[session.DISABLE] = was
