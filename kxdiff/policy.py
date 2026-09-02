"""What to leave out of a comparison before comparing anything.

This is one of the two halves of `kxdiff` and it is the half that is easy to get wrong quietly.
The other half, in `levels.py`, is how strictly to compare what is left. Keeping them apart is the
point of this package: `kxbox/bothways.py` used to do both in one function and the result was that
every time a comparison failed for a boring reason, the fix went into the same place as the rules
about what a trace means, and after seven of those nobody could see which was which.

Everything in here was arrived at by running two backends against each other and watching the
comparison fail. Nothing in it is a guess about what might vary. That matters, because a list of
things to ignore is exactly where a check stops being a check, and the only defence is that every
entry cost somebody an afternoon and is written down with the afternoon attached.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from kxray.models import Frame, Tape

# Work the operation did not cause. An interrupt is the machine doing something else with the CPU
# for a while, and whether one lands inside a traced window is not something the person tracing
# decides. A check that noticed would fail about one run in three for a reason no reader could act
# on.
#
# The scheduler is here on the same argument. Under CONFIG_PREEMPT the traced program does not
# always keep the CPU for the whole of one system call, and being preempted is not part of what a
# write does.
INTERRUPTS = (
    "irq_enter_rcu",
    "irq_exit_rcu",
    "do_softirq_own_stack",
    "__do_softirq",
    "handle_softirqs",
    "common_interrupt",
    "handle_level_irq",
    "handle_irq_event",
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
    # The switch itself. This runs while the CPU still belongs to the outgoing task, so the task
    # rule below cannot see it and it has to be named.
    "preempt_schedule_irq",
    "__traceiter_sched_switch",
    "save_fpregs_to_fpstate",
    "switch_mm_irqs_off",
    "__switch_to",
    "__switch_to_asm",
    "finish_task_switch",
    "finish_task_switch.isra.0",
)

# Work the operation did cause, whose presence is decided by the clock.
#
# A write updates the file's modification time, and the kernel skips that when the clock has not
# moved on since the last time it was set. So whether this subtree is in the trace depends on
# whether a coarse clock tick fell between the file being created and the byte being written, which
# is a few microseconds later. Over five runs of the first comparison it was there twice.
#
# This is a real concession and not bookkeeping, which is why it is not folded into the list above.
# What makes it acceptable is that no lesson makes a claim that rests on it: the lessons are about
# where a write goes and what allocates the page, and the timestamp is something the write does on
# the way past whose presence is a fact about when somebody ran it.
CLOCK_DEPENDENT = (
    "kiocb_modified",
    "file_modified",
    "file_modified_flags",
    "file_update_time",
    "inode_update_time",
    "mnt_get_write_access_file",
)

# Work the kernel had been putting off, done at whichever operation happens to be running when it
# decides it has put it off long enough. These took the longest to recognise, because they look
# exactly like the operation doing more work in one run than in another.
#
# `balance_dirty_pages_ratelimited` is the writeback throttle. Every write adds to a count of dirty
# pages and most writes do nothing else, and the write that pushes the count past a limit goes off
# and looks at how far behind writeback is. Which write that turns out to be depends on every write
# since the counters were reset, including the ones the boot did, so it is not a fact about the
# write in the lesson.
#
# `rcu_report_qs_rdp` and what it calls is this CPU saying it has passed through a quiescent state.
# That happens all the time. What varies is whether this CPU was the last one the current grace
# period was waiting for, because then the same call goes on to end the grace period and run
# everything waiting on it, which was sixteen extra frames on the run that caught it.
HOUSEKEEPING = (
    "balance_dirty_pages_ratelimited",
    "balance_dirty_pages_ratelimited_flags",
    "rcu_report_qs_rdp",
    "rcu_report_qs_rnp",
    "rcu_report_qs_rsp",
)


def owner(tape: Tape) -> str | None:
    """Whose trace this is, by the task most of it belongs to.

    None when the trace has no task column, in which case there is nothing to go on. Getting that
    column costs one `funcgraph-proc` in `trace_options` and it is worth it: without it the task
    rule below silently does nothing, and silently doing nothing is the worst behaviour available.
    """
    seen = Counter(frame.task for frame in tape.walk() if frame.task)
    return seen.most_common(1)[0][0] if seen else None


@dataclass(frozen=True)
class Policy:
    """Which frames of a trace a comparison is about.

    Two rules, and the second is the one that generalises.

    By name, in `ignore`: an entry point and everything nested below it, which is everything until
    the depth comes back to where the entry point was. Dropping an entry point and keeping its
    children would leave frames at depths with nothing above them, which is not a trace.

    By task, when `one_task` is set: anything belonging to a task other than the one whose trace
    this is. This covers the open ended half of the problem and it is why the task column is worth
    asking the kernel for. When the traced program is preempted, what runs next is whatever the
    scheduler picked, and the set of things it might pick is every function in the kernel. No list
    of names can be written for that in advance. The column says which frames those are and it says
    it for any program.
    """

    name: str
    ignore: frozenset[str] = field(default_factory=frozenset)
    one_task: bool = False

    def keep(self, tape: Tape) -> list[Frame]:
        """The frames this policy is about, in call order."""
        whose = owner(tape) if self.one_task else None
        kept: list[Frame] = []
        inside: int | None = None
        for frame in tape.walk():
            if inside is not None and frame.depth > inside:
                continue
            inside = None
            if frame.name in self.ignore or (whose and frame.task and frame.task != whose):
                inside = frame.depth
                continue
            kept.append(frame)
        return kept

    def dropped(self, tape: Tape) -> int:
        """How many frames this policy took out, so that taking them out is visible.

        Reporting a comparison without this would be the same comparison with less honesty. A
        reader looking at a pass is entitled to know it was a pass over ninety frames out of a
        hundred and fifty.
        """
        return sum(1 for _ in tape.walk()) - len(self.keep(tape))


def named(name: str, *groups: Iterable[str], one_task: bool = False) -> Policy:
    return Policy(name=name, ignore=frozenset().union(*groups), one_task=one_task)


# Compare the trace exactly as the kernel produced it. The right policy when the question is
# whether two files are the same file, and the wrong one for almost everything else.
EVERYTHING = Policy(name="everything")

# What one operation did, with the machine's own noise taken out. This is the policy the emulator
# on and off comparison runs under, and the one a lesson claim should be checked against.
SAME_OPERATION = named("same-operation", INTERRUPTS, CLOCK_DEPENDENT, HOUSEKEEPING, one_task=True)

# Only the interrupts. Useful when the question is about the kernel's own deferred work rather than
# about one operation, because it keeps the housekeeping in view instead of dropping it.
NO_INTERRUPTS = named("no-interrupts", INTERRUPTS, one_task=True)

POLICIES = {one.name: one for one in (EVERYTHING, SAME_OPERATION, NO_INTERRUPTS)}
