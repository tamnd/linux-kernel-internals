"""Tests for the comparison that runs every recipe with the emulator and without it.

The comparison itself needs a browser, so what can be tested here is the part that decides what
counts as agreement. That part is worth testing on its own, because it is where every judgement
call in the whole check lives: which differences are real and which two honest runs are allowed to
have. A comparison that is too strict fails at random and gets turned off, and one that is too
loose passes while a lesson quietly tells two different stories.

The other thing tested here is that it refuses to pass when there was nothing to compare against.
That is the failure mode this module was most likely to have, because off a page both sides come
back as the recording and every recipe matches itself perfectly.
"""

from __future__ import annotations

from pathlib import Path

from kxbox import bothways, session
from kxray import trace

ROOT = Path(__file__).resolve().parents[1]

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


# -- what has to match ---------------------------------------------------------------------------


def test_the_same_trace_twice_is_the_same_shape():
    assert bothways.shape(tape()) == bothways.shape(tape())


def test_a_different_duration_is_not_a_difference():
    """Emulated time is not time, and no two runs of anything agree on it."""
    slower = TAPE.replace("1.250 us", "9.875 us").replace("4.500 us", "21.000 us")
    assert bothways.shape(tape()) == bothways.shape(tape(slower))
    assert bothways.differences(bothways.shape(tape()), bothways.shape(tape(slower))) == []


def test_a_different_call_is_a_difference_and_says_which_one():
    other = TAPE.replace("generic_perform_write", "shmem_file_write_iter")
    found = bothways.differences(bothways.shape(tape()), bothways.shape(tape(other)))
    assert len(found) == 1
    assert "generic_perform_write" in found[0]
    assert "shmem_file_write_iter" in found[0]
    assert "call 1" in found[0], "it should say where they stopped agreeing"


def test_the_same_calls_at_different_depths_are_a_difference():
    """The nesting is the answer in a function graph trace, not decoration on it."""
    flat = TAPE.replace("    generic_perform_write();", "  generic_perform_write();")
    found = bothways.differences(bothways.shape(tape()), bothways.shape(tape(flat)))
    assert found and "depth" in found[0]


def test_extra_calls_at_the_end_are_a_difference_and_say_how_many():
    longer = TAPE + " 0)  writebyte-42    |   0.500 us    |    shmem_write_end();\n"
    found = bothways.differences(bothways.shape(tape(longer)), bothways.shape(tape()))
    assert found and "1 more call" in found[0]
    assert "shmem_write_end" in found[0]


def test_a_frame_the_tracer_never_saw_the_end_of_is_part_of_the_shape():
    """Every capture ends with one, because tracing stopped before the closing brace."""
    closed = TAPE + " 0)  writebyte-42    |   2.000 us    |  }\n"
    found = bothways.differences(bothways.shape(tape()), bothways.shape(tape(closed)))
    assert found and "never saw the end of" in found[0]


def test_only_the_first_few_differences_are_spelled_out():
    """A shape that went wrong usually went wrong once and then stayed wrong."""
    lines = ["# tracer: function_graph", "#", "# CPU  DURATION  FUNCTION CALLS", "# |  |  |"]
    live = [*lines, *[f" 0)   1.0 us    |  live{i}();" for i in range(40)]]
    kept = [*lines, *[f" 0)   1.0 us    |  kept{i}();" for i in range(40)]]
    found = bothways.differences(
        bothways.shape(tape("\n".join(live) + "\n")),
        bothways.shape(tape("\n".join(kept) + "\n")),
    )
    assert len(found) == bothways.SHOWN + 1
    assert found[-1] == f"and {40 - bothways.SHOWN} more"


# -- what is allowed to differ -------------------------------------------------------------------


def test_the_things_allowed_to_differ_are_kept_rather_than_thrown_away():
    """They are not fatal and they are still worth printing next to a result."""
    varies = bothways.varies(tape())
    assert varies.duration_us > 0
    assert "us" in str(varies)
    assert "dropped" in str(varies)


# A timer tick landing in the middle of the write, which is what the emulator actually did on the
# run this was written for. Everything from `irq_enter_rcu` down belongs to the tick and none of it
# belongs to the write, and the depths say so: the tick nests wherever it happened to land.
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
    """The run this was written for. `page-fault` passed, then failed, then passed again.

    Whether an interrupt lands inside the window is not something the person tracing decides, so a
    check that noticed would be a check that failed about one time in three for no reason anybody
    could act on.
    """
    assert bothways.shape(tape()) == bothways.shape(tape(INTERRUPTED))
    assert bothways.differences(bothways.shape(tape()), bothways.shape(tape(INTERRUPTED))) == []


def test_the_interrupt_work_is_counted_rather_than_only_dropped():
    """Silently throwing it away and reporting nothing would be the same check with less honesty."""
    assert bothways.varies(tape()).interrupts == 0
    assert bothways.varies(tape(INTERRUPTED)).interrupts == 3
    assert "3 frame(s) dropped" in str(bothways.varies(tape(INTERRUPTED)))


def test_everything_under_an_interrupt_goes_with_it():
    """Dropping the entry point and keeping its children would leave orphans at wrong depths."""
    kept = [f.name for f in bothways.without_interrupts(tape(INTERRUPTED))]
    assert kept == ["vfs_write", "generic_perform_write", "vfs_write"]
    for name in ("irq_enter_rcu", "handle_softirqs", "rcu_core"):
        assert name not in kept


def test_a_call_that_only_shares_a_name_with_the_work_after_it_is_kept():
    """The rule is a subtree, not every frame that appears after an entry point."""
    after = INTERRUPTED.replace(
        " 0)  writebyte-42    |   1.250 us    |    generic_perform_write();",
        " 0)  writebyte-42    |   1.250 us    |    rcu_core();",
    )
    assert "rcu_core" in [f.name for f in bothways.without_interrupts(tape(after))]


# -- refusing to pass for the wrong reason ---------------------------------------------------------


def test_it_will_not_say_yes_when_there_was_no_emulator():
    """Off a page both sides are the recording, so every recipe matches itself.

    That reads as three of three agreeing and is the criterion not being measured rather than the
    criterion being met. `same` is None, which is a third answer on purpose, and the summary says
    where the check actually has to be run.
    """
    report = bothways.run(root=ROOT)
    assert report.live is False, "these tests do not run in a browser"
    assert report.same is None, "no emulator has to be a third answer, not a pass"
    assert "not measured" in report.summary()
    assert "browser" in report.summary()


def test_the_environment_is_put_back_afterwards(monkeypatch):
    """It sets KXBOX_DISABLE to force the second box to the recording, and has to undo that."""
    monkeypatch.setenv(session.DISABLE, "0")
    bothways.run(root=ROOT)
    import os

    assert os.environ[session.DISABLE] == "0"


def test_a_report_with_nothing_in_it_is_not_a_pass():
    assert bothways.Report("teaching", False, "no emulator").same is None
    assert bothways.Report("teaching", True, "").same is True


def test_a_recipe_that_threw_is_not_a_pass():
    """An error is a result, and it must not be able to look like agreement."""
    broken = bothways.Comparison("write-1byte", False, error="NotRecorded: no recording")
    report = bothways.Report("teaching", True, "", (broken,))
    assert report.same is False
    assert "[error]" in str(broken)


# -- the timestamp update, which is the concession that is not about interrupts ------------------

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
    assert bothways.shape(tape()) == bothways.shape(tape(TIMESTAMPED))
    assert bothways.varies(tape(TIMESTAMPED)).interrupts == 2


def test_the_concessions_are_named_separately():
    """They are dropped together and they are not the same argument, so they are defined apart.

    Interrupt work is not caused by the operation at all. The timestamp update is, and is here
    only because whether it happens is decided by the clock. Housekeeping is real work the kernel
    had been putting off and does at whatever operation is running when it decides to stop putting
    it off. Folding them into one list would lose that, and the next person adding a name would not
    know which case they were making.
    """
    lists = (bothways.INTERRUPTS, bothways.CLOCK_DEPENDENT, bothways.HOUSEKEEPING)
    assert "inode_update_time" in bothways.CLOCK_DEPENDENT
    assert "balance_dirty_pages_ratelimited" in bothways.HOUSEKEEPING
    assert set(bothways.NOT_THE_OPERATION) == set().union(*(set(one) for one in lists))
    for a, b in ((0, 1), (0, 2), (1, 2)):
        assert not set(lists[a]) & set(lists[b]), "a name belongs to one argument, not two"


# -- housekeeping, which is the concession that looks most like a real difference ----------------

# The writeback throttle going off inside the write, which is what it did on the run this was
# written for. The recording had thirty one calls under it and the emulator had none, which reads
# as the write doing much less work rather than as a counter having been somewhere else.
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
    """Which write trips the dirty page limit depends on every write since the counters were reset.

    Including the ones the boot did, so it is not a fact about the write the lesson is about.
    """
    assert bothways.shape(tape()) == bothways.shape(tape(THROTTLED))
    assert bothways.varies(tape(THROTTLED)).interrupts == 2


def test_the_work_the_deferred_work_went_on_to_do_goes_with_it():
    """`inode_to_bdi` is in no list, and it is dropped because of what called it."""
    kept = [f.name for f in bothways.without_interrupts(tape(THROTTLED))]
    assert kept == ["vfs_write", "generic_perform_write", "vfs_write"]
    assert "inode_to_bdi" not in bothways.NOT_THE_OPERATION


# -- the other task, which is the concession no list of names could have covered ----------------

# The traced program preempted in the middle of its write, with the scheduler handing the CPU to
# something else that then did work of its own. The names of that work are not predictable, which
# is the whole difficulty: `kworker` here, a shell somewhere else, whatever the guest happened to
# have runnable. What is predictable is the column saying whose it is.
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
    """The run this was written for. Five runs of the comparison, three of them failed here.

    Whether the traced program keeps the CPU for the whole of one system call is a question about
    what else the guest had runnable at that moment, and under CONFIG_PREEMPT the answer is allowed
    to be no. No lesson makes a claim that rests on it.
    """
    assert bothways.shape(tape()) == bothways.shape(tape(PREEMPTED))
    assert bothways.differences(bothways.shape(tape()), bothways.shape(tape(PREEMPTED))) == []


def test_whose_trace_it_is_comes_from_the_task_column():
    assert bothways.owner(tape(PREEMPTED)) == "writebyte-42"


def test_a_trace_with_no_task_column_has_no_owner_and_keeps_everything():
    """The rule needs `funcgraph-proc`, and says so by not applying rather than by guessing."""
    plain = [
        "# tracer: function_graph",
        "#",
        "# CPU  DURATION  FUNCTION CALLS",
        "# |  |  |",
        " 0)   1.0 us    |  vfs_write();",
    ]
    without = tape("\n".join(plain) + "\n")
    assert bothways.owner(without) is None
    assert [f.name for f in bothways.without_interrupts(without)] == ["vfs_write"]


def test_the_other_task_work_is_dropped_by_who_did_it_and_not_by_name():
    """`wb_workfn` is in no list in this module, and that is the point of doing it this way.

    A name list cannot be written for this in advance. After the switch, what runs is whatever the
    scheduler picked, and the set of things it might pick is every function in the kernel.
    """
    kept = [f.name for f in bothways.without_interrupts(tape(PREEMPTED))]
    assert kept == ["vfs_write", "generic_perform_write", "vfs_write"]
    for name in ("wb_workfn", "blk_mq_run_work_fn"):
        assert name not in bothways.NOT_THE_OPERATION


def test_the_switch_itself_is_still_handled_by_name():
    """It runs while the CPU still belongs to the outgoing task, so the task rule cannot see it."""
    for name in ("preempt_schedule_irq", "__traceiter_sched_switch"):
        assert name in bothways.INTERRUPTS


def test_every_committed_recording_is_one_task_doing_one_thing():
    """Which is what makes the rule above a rule rather than a guess.

    A recipe runs one program through one system call with the tracer open for that call and no
    longer. If a recording ever arrives with two tasks in it, either the capture caught something
    it should not have or a recipe stopped being one operation, and both are worth stopping for.
    """
    found = sorted((ROOT / "corpora" / "traces" / "tier0").glob("*.txt"))
    assert found, "there should be committed recordings"
    for path in found:
        one = trace.parse(path.read_text(encoding="utf-8"), source=path.name)
        tasks = {frame.task for frame in one.walk() if frame.task}
        assert len(tasks) == 1, f"{path.name} has {sorted(tasks)}"


# -- one recipe at a time -------------------------------------------------------------------------


def test_the_recipes_can_be_named_one_at_a_time():
    """The page runs one per boot, because a recording is of a guest that had just booted."""
    every = bothways.names(root=ROOT)
    assert every, "the repository should have recipes"
    assert "write-1byte" in every


def test_asking_for_one_recipe_gets_one_recipe(tmp_path):
    """Not a filter applied afterwards. It has to not run the others, or the guest is not fresh."""
    from kxbox import corpus

    replay = corpus.Corpus(ROOT)
    found = bothways.compare(replay, replay, ROOT, only="page-fault")
    assert [one.recipe for one in found] == ["page-fault"]


def test_asking_for_a_recipe_that_is_not_there_compares_nothing():
    """Better than silently comparing everything, which is what a falsy check would have done."""
    from kxbox import corpus

    replay = corpus.Corpus(ROOT)
    assert bothways.compare(replay, replay, ROOT, only="no-such-recipe") == []
