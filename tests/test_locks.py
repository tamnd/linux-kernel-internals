"""Tests for finding locks in a trace and drawing them.

The Lock Timeline is the fourth signature artifact and it is the one with the most ways to be
quietly wrong, because the number it draws its conclusion from means two different things on the
two tiers. A `down_write` that took four microseconds is contention on a real machine and is the
emulator being slow on Tier 0, and nothing in the trace tells them apart. So the tests that matter
most in this file are not about drawing at all. They are about the widget refusing to answer.

The evidence for the rest is two real captures on the same machine that differ in one thing.
`tier1/multi-cpu-write.txt` has six writers on six files, so six inodes, so six locks, and nobody
waits. `tier1/contended-lock.txt` has four writers on one file, so one lock, and two of them wait
about ten milliseconds each. Same kernel, same architecture, same recipe apart from which file
gets written to.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kxray.models import Tape
from kxray.trace import function_graph
from kxshapes import LOCK_PAIRS, Hold, holds
from kxwidgets import LockTimeline
from kxwidgets.locks import CONTENDED, QUIET, UNKNOWN

ROOT = Path(__file__).resolve().parents[1]
TRACES = ROOT / "corpora" / "traces"


def load(name: str):
    path = TRACES / name
    return function_graph.parse(path.read_text(encoding="utf-8"), source=str(path))


@pytest.fixture(scope="module")
def contended():
    """Four writers, one file, a real clock. Two of them queued for about ten milliseconds."""
    return load("tier1/contended-lock.txt")


@pytest.fixture(scope="module")
def uncontended():
    """Six writers, six files, a real clock. Six different inode locks, so nobody waited."""
    return load("tier1/multi-cpu-write.txt")


@pytest.fixture(scope="module")
def emulated():
    """One CPU, no real clock. Every duration in here is a fact about v86."""
    return load("tier0/write-1byte.txt")


# -- finding the locks --------------------------------------------------------------------------


def test_a_lock_taken_and_dropped_in_one_function_is_found(contended):
    found = holds(contended)
    assert found
    assert {one.taken_by for one in found} == {"down_write"}
    assert {one.inside for one in found} == {"shmem_file_write_iter"}


def test_the_waits_and_the_holds_are_the_numbers_from_the_trace(contended):
    """The two ten millisecond waits, checked against the lines they came off.

    These are lines 398 and 419 of the capture, which say 10435.87 us and 14778.45 us. If the
    placement arithmetic ever starts scaling durations instead of reporting them, this fails.
    """
    waits = sorted(one.waited_us for one in holds(contended))
    assert waits[:4] == [0.25, 0.25, 0.25, 0.333]
    assert waits[-2:] == [10435.87, 14778.45]


def test_a_lock_taken_in_one_function_and_dropped_in_another_is_not_guessed_at():
    """Nothing in the trace says two calls in different subtrees are about the same lock."""
    text = "\n".join(
        [
            "# tracer: function_graph",
            " 0)              |  outer() {",
            " 0)              |    first() {",
            " 0)   0.100 us   |      down_write();",
            " 0)   0.300 us   |    }",
            " 0)              |    second() {",
            " 0)   0.100 us   |      up_write();",
            " 0)   0.300 us   |    }",
            " 0)   1.000 us   |  }",
        ]
    )
    assert holds(function_graph.parse(text)) == []


def test_the_table_of_which_call_takes_and_which_drops_can_be_replaced():
    text = "\n".join(
        [
            "# tracer: function_graph",
            " 0)              |  outer() {",
            " 0)   0.100 us   |    grab();",
            " 0)   0.500 us   |    work();",
            " 0)   0.100 us   |    drop();",
            " 0)   1.000 us   |  }",
        ]
    )
    tape = function_graph.parse(text)
    assert holds(tape) == []
    found = holds(tape, pairs={"grab": "drop"})
    assert len(found) == 1
    assert found[0].held_us == pytest.approx(0.5)


def test_the_default_table_covers_the_four_calls_a_lesson_will_meet_first():
    assert LOCK_PAIRS["down_write"] == "up_write"
    assert LOCK_PAIRS["mutex_lock"] == "mutex_unlock"
    assert set(LOCK_PAIRS) == {"down_write", "down_read", "mutex_lock", "_raw_spin_lock"}


# -- the part that has to refuse to answer -------------------------------------------------------


def test_the_same_number_is_contention_on_one_tier_and_nothing_on_the_other(emulated):
    """The whole reason `contended` takes an argument with no default.

    The Tier 0 capture has a `down_write` that took several microseconds, which on a real machine
    would be a lock somebody queued for. Here it is v86 being slow. There is one CPU in that
    emulator and nothing to queue behind, so reading the number as contention is not a small error,
    it is a claim about concurrency drawn from a machine that has none.
    """
    (one,) = holds(emulated)
    assert one.waited_us > Hold.CONTENDED_US

    assert one.contended(timings_are_real=True) is True
    assert one.contended(timings_are_real=False) is None
    assert one.contended(timings_are_real=None) is None


def test_a_widget_that_was_not_told_about_the_clock_shows_the_waits_and_draws_no_verdict(emulated):
    widget = LockTimeline(emulated)
    drawn = widget.html()

    assert widget.contended == []
    assert "cannot say" in drawn
    assert UNKNOWN in drawn
    assert "Nobody said whether the clock" in drawn
    assert "somebody waited" not in drawn


def test_a_widget_told_the_clock_is_emulated_says_so_in_those_words(emulated):
    drawn = LockTimeline(emulated, timings_are_real=False).html()
    assert "The timings here are emulated" in drawn
    assert "no wait on this page means anybody queued" in drawn
    assert "contention not judged" in drawn


def test_six_writers_on_six_files_wait_for_nothing(uncontended):
    """The control. Six inodes means six locks, and a lock nobody else wants is free."""
    widget = LockTimeline(uncontended, timings_are_real=True)
    assert len(widget.holds) == 12
    assert widget.contended == []
    assert sorted({one.cpu for one in widget.holds}) == [0, 1, 2, 3, 4, 5]
    assert "Nothing here was contended" in widget.html()


def test_four_writers_on_one_file_queue_behind_each_other(contended):
    """The experiment. One inode means one lock, and everybody after the first one waits."""
    widget = LockTimeline(contended, timings_are_real=True)
    assert len(widget.contended) == 2
    assert all(one.waited_us > 10_000 for one in widget.contended)
    assert "2 where somebody waited" in widget.html()


def test_both_verdicts_get_their_own_colour_and_only_when_they_are_earned(contended):
    drawn = LockTimeline(contended, timings_are_real=True).html()
    assert CONTENDED in drawn
    assert QUIET in drawn
    assert UNKNOWN not in drawn


# -- drawing ------------------------------------------------------------------------------------


def test_every_hold_gets_a_lane_on_the_cpu_it_ran_on(contended):
    widget = LockTimeline(contended, timings_are_real=True)
    lanes = widget.lanes()
    assert [lane.cpu for lane in lanes] == [0, 1, 2, 3]
    assert sum(len(lane.cells) for lane in lanes) == 2 * len(widget.holds)


def test_the_wait_and_the_hold_are_two_boxes_on_one_row(contended):
    """A row is a wait then a hold, and the hold starts where the wait finishes."""
    lane = next(lane for lane in LockTimeline(contended, timings_are_real=True).lanes())
    wait, hold = lane.cells[0], lane.cells[1]
    assert wait.row == hold.row == 0
    assert hold.left == pytest.approx(wait.left + wait.width)


def test_a_trace_with_no_locks_in_it_says_what_it_looked_for():
    drawn = LockTimeline(Tape(roots=[]), pairs={"grab": "drop"}).html()
    assert "nothing to draw" in drawn
    assert "grab with drop" in drawn


def test_the_widget_says_out_loud_that_it_does_not_know_which_lock(contended):
    """The limit that would otherwise be papered over with a plausible label."""
    drawn = LockTimeline(contended, timings_are_real=True).html()
    assert "Which lock each row is about is not in the trace" in drawn


def test_the_text_version_never_claims_contention(contended):
    """`alt()` is what a screen reader gets, and it has no clock to judge against."""
    written = LockTimeline(contended, timings_are_real=True).text()
    assert "waited 10435.870 us" in written
    assert "contended" not in written
