"""Tests for the comparison that runs every recipe with the emulator and without it.

What "identical" means used to live here and now lives in `kxdiff`, tested in
`tests/test_kxdiff.py`. What is left is this module's own job, which is smaller than it was and is
the part that could still go wrong quietly:

    which comparison it runs, because a looser one would pass and mean nothing
    that it refuses to pass when there was nothing to compare against
    that it can be given one recipe at a time, because a recording is of a guest that just booted

The middle one is the failure mode this module was always most likely to have. Off a page both
sides come back as the recording and every recipe matches itself perfectly.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import kxdiff
from kxbox import bothways, corpus, session
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

# The same write with a timer tick landing in the middle of it, which is what the emulator actually
# did on the run this was written for. Three frames of it belong to the tick and none to the write.
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


def tape(text: str = TAPE):
    return trace.parse(text, source="test")


# -- which comparison this is ---------------------------------------------------------------------


def test_it_compares_the_path_and_not_the_clock():
    """`sequence` and not `exact`, because emulated time is not time.

    Worth pinning here rather than leaving to whoever edits the constant next. `exact` would fail
    every single run, and the natural fix for a check that always fails is to stop running it.
    """
    assert bothways.LEVEL is kxdiff.SEQUENCE


def test_it_compares_one_operation_and_not_the_whole_machine():
    """`same-operation` and not `everything`.

    The other direction of the same worry. This is the loosest policy this comparison may use, and
    it is loose enough that its entries are argued for one at a time in `kxdiff/policy.py`.
    """
    assert bothways.POLICY is kxdiff.SAME_OPERATION


def test_a_difference_says_which_run_did_what():
    """A difference that does not name the sides is a difference nobody can act on."""
    assert bothways.SIDES == ("emulator", "recording")


def test_every_committed_recording_is_one_task_doing_one_thing():
    """Which is what makes the task rule in `kxdiff` safe to rely on here.

    A recipe runs one program through one system call with the tracer open for that call and no
    longer. If a recording ever arrives with two tasks in it, either the capture caught something
    it should not have or a recipe stopped being one operation, and both are worth stopping for.
    """
    # A recording is something the recording backend can hand back in place of a live run, and
    # everything the two backends compare is function_graph. The flat function tracer captures in
    # the same directory are read by lessons directly and are not recipes, so they are not this
    # test's business, and one of them is a second of timer interrupts with no single task in it
    # by design.
    found = [
        path
        for path in sorted((ROOT / "corpora" / "traces" / "tier0").glob("*.txt"))
        if tomllib.loads(path.with_suffix(".meta.toml").read_text())["tracer"] == "function_graph"
    ]
    assert found, "there should be committed recordings"
    for path in found:
        one = trace.parse(path.read_text(encoding="utf-8"), source=path.name)
        tasks = {frame.task for frame in one.walk() if frame.task}
        assert len(tasks) == 1, f"{path.name} has {sorted(tasks)}"


# -- what is reported next to a result ------------------------------------------------------------


def test_the_things_allowed_to_differ_are_kept_rather_than_thrown_away():
    """They are not fatal and they are still worth printing next to a result."""
    varies = bothways.varies(tape())
    assert varies.duration_us > 0
    assert "us" in str(varies)
    assert "dropped" in str(varies)


def test_the_dropped_work_is_counted_rather_than_only_dropped():
    """Throwing it away and reporting nothing would be the same check with less honesty."""
    assert bothways.varies(tape()).dropped == 0
    assert bothways.varies(tape(INTERRUPTED)).dropped == 3
    assert "3 frame(s) dropped" in str(bothways.varies(tape(INTERRUPTED)))


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


# -- one recipe at a time -------------------------------------------------------------------------


def test_the_recipes_can_be_named_one_at_a_time():
    """The page runs one per boot, because a recording is of a guest that had just booted."""
    every = bothways.names(root=ROOT)
    assert every, "the repository should have recipes"
    assert "write-1byte" in every


def test_asking_for_one_recipe_gets_one_recipe():
    """Not a filter applied afterwards. It has to not run the others, or the guest is not fresh."""
    replay = corpus.Corpus(ROOT)
    found = bothways.compare(replay, replay, ROOT, only="page-fault")
    assert [one.recipe for one in found] == ["page-fault"]


def test_asking_for_a_recipe_that_is_not_there_compares_nothing():
    """Better than silently comparing everything, which is what a falsy check would have done."""
    replay = corpus.Corpus(ROOT)
    assert bothways.compare(replay, replay, ROOT, only="no-such-recipe") == []
