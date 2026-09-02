"""Tests for the two questions in a trace comparison: what to look at, and how strictly.

Almost every fixture in here is a real failure. The emulator on and off comparison in #44 was run
against a live kernel until it stopped disagreeing with its own recordings, and each time it
disagreed for a reason that was not the kernel, that reason became a case below. So these are not
constructed examples of what might go wrong, they are the seven things that did.

The one property worth stating on its own is the chain. `exact` implies `sequence` implies
`counters` implies `set`, and that is checked against the committed corpus rather than argued for,
because it is the kind of property that is true when it is written and quietly false two changes
later. `distribution` is deliberately outside it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import kxdiff
from kxdiff import levels, policy
from kxray import trace

ROOT = Path(__file__).resolve().parents[1]
TIER0 = ROOT / "corpora" / "traces" / "tier0"

# A real capture, cut down. Two frames, one of them left open the way every capture is at its end.
TAPE = """\
# tracer: function_graph
#
# CPU  TASK/PID         DURATION                  FUNCTION CALLS
# |      |    |          |   |                     |   |   |   |
 0)  writebyte-42    |               |  vfs_write() {
 0)  writebyte-42    |   1.250 us    |    generic_perform_write();
 0)  writebyte-42    |   4.500 us    |  }
 0)  writebyte-42    |               |  vfs_write() {
"""


def tape(text: str = TAPE):
    return trace.parse(text, source="test")


def corpus_tapes():
    return {
        path.stem: trace.parse(path.read_text(encoding="utf-8"), source=path.name)
        for path in sorted(TIER0.glob("*.txt"))
    }


# -- the levels ----------------------------------------------------------------------------------


def test_a_trace_agrees_with_itself_at_every_level():
    """The boring result, and the one that would be alarming if it were missing.

    A level that cannot recognise a trace as itself is not a function of the trace, which would
    make every other answer it gives meaningless rather than merely wrong.
    """
    for name, one in corpus_tapes().items():
        for level in levels.LEVELS.values():
            answer = kxdiff.diff(one, one, level=level, policy=kxdiff.EVERYTHING)
            assert answer.same, f"{name} disagreed with itself at {level.name}: {answer.summary()}"


def test_the_four_ordered_levels_are_a_chain():
    """Agreeing at a strict level has to mean agreeing at every looser one.

    Checked on the real corpus, every pair of committed traces, under both policies. This is the
    invariant that makes choosing a level a decision about strictness rather than a decision about
    which of five unrelated tools to reach for.
    """
    tapes = list(corpus_tapes().values())
    pairs = [(a, b) for a in tapes for b in tapes]
    for one, other in pairs:
        for chosen in (kxdiff.EVERYTHING, kxdiff.SAME_OPERATION):
            answers = [
                kxdiff.diff(one, other, level=level, policy=chosen).same for level in levels.CHAIN
            ]
            for stricter, looser in zip(answers[:-1], answers[1:], strict=True):
                assert not (stricter and not looser), (
                    f"agreed at a stricter level and not at a looser one, under {chosen.name}"
                )


def test_durations_are_a_difference_at_exact_and_not_at_sequence():
    """Which is the whole reason `exact` is not the default anywhere."""
    slower = TAPE.replace("1.250 us", "9.875 us").replace("4.500 us", "21.000 us")
    assert not kxdiff.diff(tape(), tape(slower), level=kxdiff.EXACT).same
    assert kxdiff.diff(tape(), tape(slower), level=kxdiff.SEQUENCE).same


def test_a_different_call_is_a_difference_and_says_which_one():
    other = TAPE.replace("generic_perform_write", "shmem_file_write_iter")
    found = kxdiff.diff(tape(), tape(other), labels=("live", "recorded")).differences
    assert len(found) == 1
    assert "generic_perform_write" in found[0]
    assert "shmem_file_write_iter" in found[0]
    assert "call 1" in found[0], "it should say where they stopped agreeing"
    assert "live" in found[0] and "recorded" in found[0], "and which side is which"


def test_the_same_calls_at_different_depths_are_a_difference():
    """The nesting is the answer in a function graph trace, not decoration on it."""
    flat = TAPE.replace("    generic_perform_write();", "  generic_perform_write();")
    found = kxdiff.diff(tape(), tape(flat)).differences
    assert found and "depth" in found[0]


def test_extra_calls_at_the_end_are_a_difference_and_say_how_many():
    longer = TAPE + " 0)  writebyte-42    |   0.500 us    |    shmem_write_end();\n"
    found = kxdiff.diff(tape(longer), tape()).differences
    assert found and "1 more call" in found[0]
    assert "shmem_write_end" in found[0]


def test_a_frame_the_tracer_never_saw_the_end_of_is_part_of_the_sequence():
    """Every capture ends with one, because tracing stopped before the closing brace."""
    closed = TAPE + " 0)  writebyte-42    |   2.000 us    |  }\n"
    found = kxdiff.diff(tape(), tape(closed)).differences
    assert found and "never saw the end of" in found[0]


def test_only_the_first_few_differences_are_spelled_out():
    """A trace that went wrong usually went wrong once and then stayed wrong."""
    lines = ["# tracer: function_graph", "#", "# CPU  DURATION  FUNCTION CALLS", "# |  |  |"]
    live = [*lines, *[f" 0)   1.0 us    |  live{i}();" for i in range(40)]]
    kept = [*lines, *[f" 0)   1.0 us    |  kept{i}();" for i in range(40)]]
    found = kxdiff.diff(tape("\n".join(live) + "\n"), tape("\n".join(kept) + "\n")).differences
    assert len(found) == levels.SHOWN + 1
    assert found[-1] == f"and {40 - levels.SHOWN} more"


def test_counters_ignores_the_order_and_sees_the_count():
    """For traces where the order is not determined but the work is."""
    swapped = """\
# tracer: function_graph
#
# CPU  DURATION  FUNCTION CALLS
# |  |  |
 0)   1.0 us    |  b();
 0)   1.0 us    |  a();
"""
    original = swapped.replace(
        " 0)   1.0 us    |  b();\n 0)   1.0 us    |  a();",
        " 0)   1.0 us    |  a();\n 0)   1.0 us    |  b();",
    )
    assert not kxdiff.diff(tape(original), tape(swapped), level=kxdiff.SEQUENCE).same
    assert kxdiff.diff(tape(original), tape(swapped), level=kxdiff.COUNTERS).same

    twice = swapped + " 0)   1.0 us    |  a();\n"
    found = kxdiff.diff(tape(twice), tape(swapped), level=kxdiff.COUNTERS).differences
    assert found and "a:" in found[0] and "2 time(s)" in found[0]


def test_set_ignores_the_count_and_sees_the_name():
    """The right level when a loop runs once per page and the reader chose how many pages."""
    once = """\
# tracer: function_graph
#
# CPU  DURATION  FUNCTION CALLS
# |  |  |
 0)   1.0 us    |  a();
"""
    twice = once + " 0)   1.0 us    |  a();\n"
    assert not kxdiff.diff(tape(once), tape(twice), level=kxdiff.COUNTERS).same
    assert kxdiff.diff(tape(once), tape(twice), level=kxdiff.SET).same

    other = once.replace("a()", "b()")
    found = kxdiff.diff(
        tape(once), tape(other), level=kxdiff.SET, labels=("one", "two")
    ).differences
    assert "only one ran a" in found
    assert "only two ran b" in found


# -- distribution, which is the level that is not on the ladder -----------------------------------

# The same two calls, with the time in a completely different place. Nothing about the path has
# changed, so every name based level says these are the same trace, and that is exactly right and
# exactly not the question a lesson about where the time goes is asking.
FAST_INNER = """\
# tracer: function_graph
#
# CPU  TASK/PID         DURATION                  FUNCTION CALLS
# |      |    |          |   |                     |   |   |   |
 0)  writebyte-42    |               |  vfs_write() {
 0)  writebyte-42    |   1.000 us    |    generic_perform_write();
 0)  writebyte-42    | 100.000 us    |  }
"""
SLOW_INNER = """\
# tracer: function_graph
#
# CPU  TASK/PID         DURATION                  FUNCTION CALLS
# |      |    |          |   |                     |   |   |   |
 0)  writebyte-42    |               |  vfs_write() {
 0)  writebyte-42    |  99.000 us    |    generic_perform_write();
 0)  writebyte-42    | 100.000 us    |  }
"""


def test_the_path_can_be_identical_and_the_time_be_somewhere_else_entirely():
    """Which is the argument for `distribution` existing, on the smallest case that makes it."""
    assert kxdiff.diff(tape(FAST_INNER), tape(SLOW_INNER), level=kxdiff.SEQUENCE).same
    answer = kxdiff.diff(
        tape(FAST_INNER), tape(SLOW_INNER), level=kxdiff.DISTRIBUTION, labels=("fast", "slow")
    )
    assert not answer.same
    assert any("generic_perform_write" in line for line in answer.differences)
    assert any("%" in line for line in answer.differences)


def test_a_clock_four_times_faster_does_not_change_the_distribution():
    """The only reason this level can compare an emulator against a real machine at all.

    The two backends disagree about the length of a microsecond by about a factor of four. Shares
    survive that and absolute durations do not, which is why this compares shares.
    """
    import re

    def scale(text, by):
        return re.sub(r"(\d+\.\d+) us", lambda m: f"{float(m.group(1)) * by:.3f} us", text)

    assert kxdiff.diff(tape(FAST_INNER), tape(scale(FAST_INNER, 4)), level=kxdiff.DISTRIBUTION).same


def test_a_function_below_the_floor_is_not_compared():
    """Five percent of a few hundred microseconds is one or two ticks of an emulated clock."""
    shares = levels._shares(kxdiff.EVERYTHING.keep(tape(FAST_INNER)))
    assert "vfs_write" in shares
    assert "generic_perform_write" not in shares, "one percent of the time is not what it is about"


def test_a_trace_with_no_durations_says_so_rather_than_passing():
    """Silently agreeing because there was nothing to compare is the failure mode of this level."""
    none = """\
# tracer: function_graph
#
# CPU  DURATION  FUNCTION CALLS
# |  |  |
 0)               |  vfs_write() {
"""
    answer = kxdiff.diff(tape(none), tape(FAST_INNER), level=kxdiff.DISTRIBUTION)
    assert not answer.same
    assert "nothing to compare" in answer.differences[0]


# -- the policy, which is the other half ----------------------------------------------------------

# A timer tick landing in the middle of the write, which is what the emulator actually did on the
# run this was written for. Everything from `irq_enter_rcu` down belongs to the tick.
INTERRUPTED = """\
# tracer: function_graph
#
# CPU  TASK/PID         DURATION                  FUNCTION CALLS
# |      |    |          |   |                     |   |   |   |
 0)  writebyte-42    |               |  vfs_write() {
 0)  writebyte-42    |               |    irq_enter_rcu() {
 0)  writebyte-42    |               |      handle_softirqs() {
 0)  writebyte-42    |   9.000 us    |        rcu_core();
 0)  writebyte-42    |  12.000 us    |      }
 0)  writebyte-42    |  15.000 us    |    }
 0)  writebyte-42    |   1.250 us    |    generic_perform_write();
 0)  writebyte-42    |   4.500 us    |  }
 0)  writebyte-42    |               |  vfs_write() {
"""


def test_a_timer_tick_in_the_middle_is_not_the_trace_changing_its_mind():
    """`page-fault` passed, then failed, then passed again, on this.

    Whether an interrupt lands inside the window is not something the person tracing decides, so a
    check that noticed would fail about one time in three for no reason anybody could act on.
    """
    assert kxdiff.diff(tape(), tape(INTERRUPTED)).same
    assert not kxdiff.diff(tape(), tape(INTERRUPTED), policy=kxdiff.EVERYTHING).same


def test_everything_under_an_interrupt_goes_with_it():
    """Dropping the entry point and keeping its children would leave orphans at wrong depths."""
    kept = [f.name for f in kxdiff.SAME_OPERATION.keep(tape(INTERRUPTED))]
    assert kept == ["vfs_write", "generic_perform_write", "vfs_write"]
    for name in ("irq_enter_rcu", "handle_softirqs", "rcu_core"):
        assert name not in kept


def test_a_call_that_only_shares_a_name_with_the_work_after_it_is_kept():
    """The rule is a subtree, not every frame that appears after an entry point."""
    after = INTERRUPTED.replace(
        " 0)  writebyte-42    |   1.250 us    |    generic_perform_write();",
        " 0)  writebyte-42    |   1.250 us    |    rcu_core();",
    )
    assert "rcu_core" in [f.name for f in kxdiff.SAME_OPERATION.keep(tape(after))]


def test_the_dropped_frames_are_counted_rather_than_only_dropped():
    """A pass over three frames of six is a different pass from one over all six."""
    assert kxdiff.SAME_OPERATION.dropped(tape()) == 0
    assert kxdiff.SAME_OPERATION.dropped(tape(INTERRUPTED)) == 3
    answer = kxdiff.diff(tape(), tape(INTERRUPTED))
    assert answer.dropped == (0, 3)
    assert "left out by the policy" in answer.summary()


TIMESTAMPED = """\
# tracer: function_graph
#
# CPU  TASK/PID         DURATION                  FUNCTION CALLS
# |      |    |          |   |                     |   |   |   |
 0)  writebyte-42    |               |  vfs_write() {
 0)  writebyte-42    |               |    inode_update_time() {
 0)  writebyte-42    |   2.000 us    |      inode_set_ctime_current();
 0)  writebyte-42    |   3.000 us    |    }
 0)  writebyte-42    |   1.250 us    |    generic_perform_write();
 0)  writebyte-42    |   4.500 us    |  }
 0)  writebyte-42    |               |  vfs_write() {
"""


def test_the_timestamp_update_is_not_the_trace_changing_its_mind():
    """It fires when the clock has moved on since the file was made, and not otherwise.

    Which is a question about what time somebody ran it. Over five runs of the comparison it was
    there twice, and no lesson makes a claim that rests on it.
    """
    assert kxdiff.diff(tape(), tape(TIMESTAMPED)).same
    assert kxdiff.SAME_OPERATION.dropped(tape(TIMESTAMPED)) == 2


# The traced program preempted in the middle of its write, with the scheduler handing the CPU to
# something else that then did work of its own. The names of that work are not predictable, which
# is the whole difficulty. What is predictable is the column saying whose it is.
PREEMPTED = """\
# tracer: function_graph
#
# CPU  TASK/PID         DURATION                  FUNCTION CALLS
# |      |    |          |   |                     |   |   |   |
 0)  writebyte-42    |               |  vfs_write() {
 0)  writebyte-42    |               |    preempt_schedule_irq() {
 0)  writebyte-42    |   3.000 us    |      __traceiter_sched_switch();
 0)  writebyte-42    |   9.000 us    |    }
 0)  kworker/0-9     |   2.000 us    |    wb_workfn();
 0)  kworker/0-9     |   1.000 us    |    blk_mq_run_work_fn();
 0)  writebyte-42    |   1.250 us    |    generic_perform_write();
 0)  writebyte-42    |   4.500 us    |  }
 0)  writebyte-42    |               |  vfs_write() {
"""


def test_another_task_running_in_the_window_is_not_the_trace_changing_its_mind():
    """Five runs of the comparison, three of them failed here.

    Whether the traced program keeps the CPU for the whole of one system call is a question about
    what else the guest had runnable, and under CONFIG_PREEMPT the answer is allowed to be no.
    """
    assert kxdiff.diff(tape(), tape(PREEMPTED)).same


def test_whose_trace_it_is_comes_from_the_task_column():
    assert kxdiff.owner(tape(PREEMPTED)) == "writebyte-42"


def test_a_trace_with_no_task_column_has_no_owner_and_keeps_everything():
    """The rule needs `funcgraph-proc`, and says so by not applying rather than by guessing."""
    plain = """\
# tracer: function_graph
#
# CPU  DURATION  FUNCTION CALLS
# |  |  |
 0)   1.0 us    |  vfs_write();
"""
    assert kxdiff.owner(tape(plain)) is None
    assert [f.name for f in kxdiff.SAME_OPERATION.keep(tape(plain))] == ["vfs_write"]


def test_the_other_task_work_is_dropped_by_who_did_it_and_not_by_name():
    """`wb_workfn` is in no list in this package, and that is the point of doing it this way.

    A name list cannot be written for this in advance. After the switch, what runs is whatever the
    scheduler picked, and the set of things it might pick is every function in the kernel.
    """
    kept = [f.name for f in kxdiff.SAME_OPERATION.keep(tape(PREEMPTED))]
    assert kept == ["vfs_write", "generic_perform_write", "vfs_write"]
    for name in ("wb_workfn", "blk_mq_run_work_fn"):
        assert name not in kxdiff.SAME_OPERATION.ignore


def test_the_switch_itself_is_still_handled_by_name():
    """It runs while the CPU still belongs to the outgoing task, so the task rule cannot see it."""
    for name in ("preempt_schedule_irq", "__traceiter_sched_switch"):
        assert name in policy.INTERRUPTS


# The writeback throttle going off inside the write. The recording had thirty one calls under it
# and the emulator had none, which reads as the write doing much less work rather than as a counter
# having been somewhere else.
THROTTLED = """\
# tracer: function_graph
#
# CPU  TASK/PID         DURATION                  FUNCTION CALLS
# |      |    |          |   |                     |   |   |   |
 0)  writebyte-42    |               |  vfs_write() {
 0)  writebyte-42    |   1.250 us    |    generic_perform_write();
 0)  writebyte-42    |               |    balance_dirty_pages_ratelimited() {
 0)  writebyte-42    |   2.000 us    |      inode_to_bdi();
 0)  writebyte-42    |   7.000 us    |    }
 0)  writebyte-42    |   4.500 us    |  }
 0)  writebyte-42    |               |  vfs_write() {
"""


def test_deferred_work_landing_in_the_window_is_not_the_trace_changing_its_mind():
    """Which write trips the dirty page limit depends on every write since the counters reset.

    Including the ones the boot did, so it is not a fact about the write the lesson is about.
    """
    assert kxdiff.diff(tape(), tape(THROTTLED)).same
    assert kxdiff.SAME_OPERATION.dropped(tape(THROTTLED)) == 2


def test_the_work_the_deferred_work_went_on_to_do_goes_with_it():
    """`inode_to_bdi` is in no list, and it is dropped because of what called it."""
    kept = [f.name for f in kxdiff.SAME_OPERATION.keep(tape(THROTTLED))]
    assert kept == ["vfs_write", "generic_perform_write", "vfs_write"]
    assert "inode_to_bdi" not in kxdiff.SAME_OPERATION.ignore


def test_the_concessions_are_named_separately():
    """They are dropped together and they are not the same argument, so they are defined apart.

    Interrupt work is not caused by the operation at all. The timestamp update is, and is here only
    because whether it happens is decided by the clock. Housekeeping is real work the kernel had
    been putting off. Folding them into one list would lose that, and the next person adding a name
    would not know which case they were making.
    """
    groups = (policy.INTERRUPTS, policy.CLOCK_DEPENDENT, policy.HOUSEKEEPING)
    assert "inode_update_time" in policy.CLOCK_DEPENDENT
    assert "balance_dirty_pages_ratelimited" in policy.HOUSEKEEPING
    assert kxdiff.SAME_OPERATION.ignore == frozenset().union(*groups)
    for a, b in ((0, 1), (0, 2), (1, 2)):
        assert not set(groups[a]) & set(groups[b]), "a name belongs to one argument, not two"


def test_a_policy_that_forgives_nothing_forgives_nothing():
    """The one that is right when the question is whether two files are the same file."""
    assert kxdiff.EVERYTHING.ignore == frozenset()
    assert kxdiff.EVERYTHING.dropped(tape(PREEMPTED)) == 0


# -- the command line ------------------------------------------------------------------------------


def test_the_demo_runs_every_level_on_real_traces(capsys):
    """The M1 exit criterion for this tool, checked rather than claimed."""
    from kxdiff.__main__ import main

    assert main(["--demo"]) == 0
    printed = capsys.readouterr().out
    for name in levels.LEVELS:
        assert name in printed


def test_comparing_a_trace_with_itself_exits_zero_and_a_different_one_exits_one(capsys):
    from kxdiff.__main__ import main

    same = [str(TIER0 / "write-1byte.txt"), str(TIER0 / "write-1byte.txt")]
    assert main(same) == 0
    assert "agree" in capsys.readouterr().out

    other = [str(TIER0 / "write-1byte.txt"), str(TIER0 / "two-writes.txt")]
    assert main(other) == 1
    assert "differ" in capsys.readouterr().out


def test_it_refuses_rather_than_guessing_when_given_one_trace():
    from kxdiff.__main__ import main

    with pytest.raises(SystemExit):
        main([str(TIER0 / "write-1byte.txt")])
