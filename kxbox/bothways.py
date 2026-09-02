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

The whole thing turns on what "identical" is allowed to mean, so that is written down here rather
than left to whoever runs it.

What has to match, in `Shape`:

    the sequence of function calls, each with the depth it was called at, in call order
    which of those frames the tracer never saw the end of
    which CPUs appear

What is allowed to differ, kept and counted rather than thrown away silently:

    every duration, because emulated time is not time and no two runs of anything agree on it
    work the operation did not cause, in `INTERRUPTS`, which is interrupts, softirqs and the
      scheduler taking the CPU away
    work whose presence depends on the clock, in `CLOCK_DEPENDENT`, which is the timestamp update
    work the kernel had been putting off, in `HOUSEKEEPING`, drained by whichever operation was
      running when a threshold tripped
    work belonging to another task, which is what the scheduler handed the CPU to, found by the
      task column rather than by name because no list of names could cover it
    lines the parser could not read, because the count of those is checked elsewhere and a
    header line arriving or not arriving is not the lesson changing its mind

Every one of those is a concession and every one of them was arrived at by running this and
watching it fail, so what each one cost is written beside it where it is defined rather than only
claimed here. They are kept in separate lists because they are separate arguments. Interrupts are
easy to defend: nothing about when a timer tick lands is up to the person tracing. The timestamp
update is harder, because it really is part of what the write did, and it is here because whether
it happens is a question about what time it was rather than about what a write does. Housekeeping
is the same shape as the timestamp: the work is real and the kernel decides when to do it by
looking at a counter nobody tracing has any control over.

What they all have in common is that the alternative is a check that fails about half the time for
reasons a reader cannot act on, and a check like that is one everybody learns to run again rather
than to believe. What none of them is allowed to be is a way of making a difference go away
because it was inconvenient, which is why each list is short, each entry was seen failing before
it was written down, and the lesson claims are checked against what survives rather than against
the raw trace.

The first is also done in two places, because one is not enough. The bridge sets
`nofuncgraph-irqs`, which is the kernel not recording the interrupt at all and is much the better
of the two. That misses `irq_enter_rcu`, which runs before the flag it is tested against is set,
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
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from kxbox import session
from kxbox.corpus import load_recipes
from kxray.models import InterruptEntry, Tape

# How many differences to spell out before saying how many are left. A shape that went wrong
# usually went wrong once and then stayed wrong, so the first few are the informative ones and a
# thousand line diff is not.
SHOWN = 8

# Where interrupt work starts, so that it and everything under it can be left out of the shape.
#
# `nofuncgraph-irqs` in the bridge does most of this inside the kernel and cannot do all of it. The
# option skips functions traced while `in_hardirq()` is true, so the body of a hard interrupt
# handler never reaches the buffer. Two things get past it. `irq_enter_rcu` runs on the way in,
# before the flag it is tested against is set. Softirqs run after `irq_exit`, on their own stack,
# with `in_hardirq()` false, so a timer tick that queues RCU work puts the whole of
# `handle_softirqs` into the middle of whatever was being traced.
#
# It is a list of names, which will need adding to, and that is better than the alternative. There
# is no structural mark on these frames: an interrupt lands wherever it lands and nests at whatever
# depth the thing it interrupted had reached, so nothing in the trace itself says the next fifteen
# calls have nothing to do with what the reader asked about. A name arriving that is not on this
# list shows up as a difference with the name in it, which is a failure that says what to add.
INTERRUPTS = (
    "irq_enter_rcu",
    "irq_exit_rcu",
    "do_softirq_own_stack",
    "__do_softirq",
    "handle_softirqs",
    "common_interrupt",
    "handle_level_irq",
    "handle_irq_event",
    # The scheduler taking the CPU away, which is the same argument. The kernel these lessons use
    # is built `CONFIG_PREEMPT=y`, so a task can be preempted in the middle of a page fault, and one
    # run in three was before recipes were given a boot each. `__schedule` itself does not appear,
    # so these are siblings at the depth the fault had reached rather than one subtree, which is
    # why there are several of them rather than one.
    "__schedule",
    "preempt_schedule",
    "preempt_schedule_notrace",
    "rcu_note_context_switch",
    "update_rq_clock",
    "pick_task_fair",
    "pick_next_task_fair",
    "put_prev_task_fair",
    "set_next_task_fair",
    "dequeue_task_fair",
    "enqueue_task_fair",
    # The switch itself, which runs while the CPU still belongs to the outgoing task and so is not
    # caught by the task rule below.
    "preempt_schedule_irq",
    "__traceiter_sched_switch",
    "save_fpregs_to_fpstate",
    "switch_mm_irqs_off",
    "__switch_to",
    "__switch_to_asm",
    "finish_task_switch",
    "finish_task_switch.isra.0",
)

# The other thing two honest runs disagree about, and it needs its own name because the argument
# for dropping it is a different argument.
#
# A write updates the file's modification time, and the kernel skips that when the clock has not
# moved on since the last time it was set. So whether `inode_update_time` and everything under it
# is in the trace depends on whether a coarse clock tick happened to fall between the file being
# created and the byte being written, which is a few microseconds later. Over five runs of the
# comparison it was there twice.
#
# Unlike an interrupt this really is part of what the write did, so dropping it is a concession and
# not bookkeeping, and it is listed separately rather than quietly folded in above. What makes it
# acceptable is that no lesson makes a claim that rests on it: the lessons are about where a write
# goes and what allocates the page, and the timestamp is bookkeeping the write does on the way past
# whose presence is a fact about when somebody ran it. What would not be acceptable is a comparison
# that fails three times in five with nothing a reader could do about it, because that is a check
# everybody learns to run again rather than to believe.
CLOCK_DEPENDENT = (
    "kiocb_modified",
    "file_modified",
    "file_modified_flags",
    "file_update_time",
    "inode_update_time",
    "mnt_get_write_access_file",
)

# Work the kernel had been putting off, which it does at whichever operation happens to be running
# when it decides it has put it off long enough. Two of these turned up, each once in about fifteen
# runs, and they took the longest to recognise because they look exactly like the operation doing
# more work in one run than in another.
#
# `balance_dirty_pages_ratelimited` is the writeback throttle. Every write adds to a per CPU count
# of dirty pages and most writes do nothing else, and the write that pushes the count past a limit
# goes off and looks at how far behind writeback is. Which write that turns out to be depends on
# every write the guest has done since the counters were last reset, including the ones the boot
# did, so it is not a fact about the write in the lesson.
#
# `rcu_report_qs_rdp` and the two calls under it are this CPU saying it has passed through a
# quiescent state. That much happens all the time. What varies is whether this CPU was the last one
# the current grace period was waiting for, because then the same call goes on to end the grace
# period and run everything that was waiting for it, which was sixteen extra frames on the run that
# caught it. Whether it is the last one is a question about what the other CPUs have been doing.
#
# Both are real work and neither is caused by the operation being traced, and no lesson makes a
# claim that rests on either.
HOUSEKEEPING = (
    "balance_dirty_pages_ratelimited",
    "balance_dirty_pages_ratelimited_flags",
    "rcu_report_qs_rdp",
    "rcu_report_qs_rnp",
    "rcu_report_qs_rsp",
)

# All three lists, which is what actually gets dropped by name. Kept apart above so that the three
# reasons stay readable and so that adding to one does not look like adding to another.
NOT_THE_OPERATION = INTERRUPTS + CLOCK_DEPENDENT + HOUSEKEEPING


@dataclass(frozen=True)
class Shape:
    """A trace with everything a second run is allowed to change taken out of it."""

    frames: tuple[tuple[int, str], ...]
    incomplete: tuple[str, ...]
    cpus: tuple[int, ...]

    def __len__(self) -> int:
        return len(self.frames)


@dataclass(frozen=True)
class Varies:
    """The parts two honest runs are expected to disagree about."""

    duration_us: float
    interrupts: int
    unparsed: int

    def __str__(self) -> str:
        return (
            f"{self.duration_us:.1f}us, {self.interrupts} frame(s) dropped, "
            f"{self.unparsed} unparsed"
        )


def owner(tape: Tape) -> str | None:
    """Whose trace this is, by the task most of it belongs to.

    Every committed recording has exactly one task in it, which is what makes this a rule rather
    than a guess: a recipe traces one program doing one thing, and the window is a few hundred
    microseconds long. A second task appearing means the first one was preempted and somebody
    else's work landed in the middle, and `tests/test_bothways.py` holds the committed recordings
    to having one task each so that this cannot quietly start meaning something else.

    None when the trace has no task column at all, in which case there is nothing to go on and the
    rule does not apply.
    """
    seen = Counter(frame.task for frame in tape.walk() if frame.task)
    return seen.most_common(1)[0][0] if seen else None


def without_interrupts(tape: Tape) -> list:
    """Every frame except the ones two honest runs are allowed to disagree about, in call order.

    Two rules, and the second is the one that generalises.

    By name: an entry point from `NOT_THE_OPERATION` and everything nested below it, which is
    everything until the depth comes back to where the entry point was. Dropping the entry point
    and keeping its children would leave frames at depths with nothing above them.

    By task: anything belonging to a task other than the one whose trace this is. That covers the
    open ended half of the problem. When the traced program is preempted, what runs next is
    whatever the scheduler picked, and no list of names can be written for that in advance. The
    task column says which frames those are and it says it for any program, which is why this is
    worth having even though the name list stays necessary for the switch itself.
    """
    whose = owner(tape)
    kept, inside = [], None
    for frame in tape.walk():
        if inside is not None and frame.depth > inside:
            continue
        inside = None
        if frame.name in NOT_THE_OPERATION or (whose and frame.task and frame.task != whose):
            inside = frame.depth
            continue
        kept.append(frame)
    return kept


def shape(tape: Tape) -> Shape:
    """The part of a trace that has to be the same whoever produced it."""
    frames = without_interrupts(tape)
    return Shape(
        frames=tuple((f.depth, f.name) for f in frames),
        incomplete=tuple(f.name for f in frames if not f.complete),
        cpus=tuple(tape.cpus),
    )


def varies(tape: Tape) -> Varies:
    """Counting the interrupt frames rather than only dropping them, so the drop is visible."""
    dropped = sum(1 for _ in tape.walk()) - len(without_interrupts(tape))
    return Varies(
        duration_us=tape.total_duration_us,
        interrupts=dropped + sum(1 for e in tape.events if isinstance(e, InterruptEntry)),
        unparsed=len(tape.unparsed),
    )


def differences(live: Shape, replay: Shape, limit: int = SHOWN) -> list[str]:
    """Where two shapes stop agreeing, in words rather than as two dumps to eyeball."""
    found = []

    if live.cpus != replay.cpus:
        found.append(f"CPUs: emulator says {list(live.cpus)}, recording says {list(replay.cpus)}")
    if live.incomplete != replay.incomplete:
        found.append(
            f"frames the tracer never saw the end of: emulator {list(live.incomplete)}, "
            f"recording {list(replay.incomplete)}"
        )

    # `strict=False` on purpose. Two shapes of different lengths is one of the things being looked
    # for, not an error, and the tail the shorter one does not reach is reported just below.
    for index, (one, other) in enumerate(zip(live.frames, replay.frames, strict=False)):
        if one != other:
            found.append(
                f"call {index}: emulator ran {one[1]} at depth {one[0]}, "
                f"recording has {other[1]} at depth {other[0]}"
            )

    longer, shorter = (live, replay) if len(live) > len(replay) else (replay, live)
    if len(longer) != len(shorter):
        who = "emulator" if longer is live else "recording"
        extra = [name for _, name in longer.frames[len(shorter) :]]
        found.append(
            f"{who} has {len(longer) - len(shorter)} more call(s), starting with {extra[0]}"
        )

    if len(found) > limit:
        return [*found[:limit], f"and {len(found) - limit} more"]
    return found


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

        seen, kept = shape(fresh), shape(recorded)
        gap = differences(seen, kept)
        out.append(
            Comparison(
                recipe=one.name,
                same=not gap,
                differences=tuple(gap),
                live=varies(fresh),
                replay=varies(recorded),
                calls=len(kept),
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
