"""Tests for the tape diff, which is the widget for two traces rather than one.

The verdict is `kxdiff`'s and is tested in `test_kxdiff.py`. What is tested here is everything the
widget adds on top of it, and the three that matter are the three ways a comparison can look right
and be wrong.

Marking the wrong boxes, because a frame dropped by the policy shares a name with one that was
kept. Sharing a scale that is not shared, because one of the tapes has no total to scale against.
And drawing a pass over most of a trace as though it were a pass over all of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kxdiff import EVERYTHING, SAME_OPERATION, SET, diff
from kxray import trace
from kxwidgets import TapeDiff
from kxwidgets.tapediff import ONLY_LEFT, ONLY_RIGHT

ROOT = Path(__file__).resolve().parents[1]
TRACES = ROOT / "corpora" / "traces"


def load(name: str):
    path = TRACES / name
    return trace.parse(path.read_text(encoding="utf-8"), source=path.name)


@pytest.fixture(scope="module")
def one_write():
    return load("tier0/write-1byte.txt")


@pytest.fixture(scope="module")
def two_writes():
    """The same recipe with a second write, to a pipe rather than to a file."""
    return load("tier0/two-writes.txt")


@pytest.fixture(scope="module")
def busy():
    """A Tier 1 capture with several tasks in it, so `same-operation` has real work to do."""
    return load("tier1/contended-lock.txt")


@pytest.fixture(scope="module")
def to_a_file(two_writes):
    """One `vfs_write` that went to a file on tmpfs, 549.333 us of it."""
    return two_writes.roots[1]


@pytest.fixture(scope="module")
def to_a_pipe(two_writes):
    """The `vfs_write` in the same trace that went to a pipe instead, 121.875 us of it."""
    return two_writes.roots[2]


# -- what is only on one side --------------------------------------------------------------------


def test_a_trace_against_itself_has_nothing_only_on_one_side(one_write):
    widget = TapeDiff(one_write, one_write, labels=("a", "a"))
    assert widget.only_on_one_side() == (set(), set())
    assert widget.answer.same
    assert "agree" in widget.html()


def test_a_trace_against_itself_marks_no_boxes(one_write):
    """The result that is not interesting and would be alarming if it were missing."""
    drawn = TapeDiff(one_write, one_write, labels=("a", "a")).html()
    assert ONLY_LEFT not in drawn
    assert ONLY_RIGHT not in drawn


def test_the_extra_write_shows_up_as_functions_only_on_its_own_side(one_write, two_writes):
    """`two-writes` writes to a pipe as well as to a file, so it reaches the pipe code."""
    left, right = TapeDiff(one_write, two_writes).only_on_one_side()
    assert left == set()
    assert "anon_pipe_write" in right
    assert "kill_fasync" in right


def test_the_two_sides_get_two_different_rings(one_write, two_writes):
    """Something that appeared and something that went away are different news."""
    drawn = TapeDiff(two_writes, one_write, labels=("two", "one")).html()
    assert ONLY_LEFT in drawn
    assert ONLY_RIGHT not in drawn


def test_a_marked_box_is_marked_in_the_text_as_well_as_in_the_colour(one_write, two_writes):
    """A ring is a colour, and colour is never the only channel anything is said in here."""
    drawn = TapeDiff(one_write, two_writes).html()
    assert "• anon_pipe_write" in drawn
    assert "only on this side" in drawn


def test_the_same_syscall_to_a_file_and_to_a_pipe_barely_overlaps(to_a_file, to_a_pipe):
    """One `write` and another `write`, out of one trace, sharing almost no code below the VFS."""
    left, right = TapeDiff(to_a_file, to_a_pipe).only_on_one_side()
    assert "shmem_file_write_iter" in left
    assert "anon_pipe_write" in right
    assert "vfs_write" not in left | right


# -- what the policy took out ---------------------------------------------------------------------


def test_frames_the_policy_dropped_are_drawn_faintly_rather_than_left_out(busy):
    widget = TapeDiff(busy, busy, labels=("a", "a"))
    assert any(widget.answer.dropped)
    drawn = widget.html()
    assert "opacity:0.35" in drawn
    assert f"left out of the comparison by the {SAME_OPERATION.name} policy" in drawn
    assert "left out of the comparison" in widget._footnote()


def test_which_frames_were_dropped_is_decided_by_identity_and_not_by_name(busy):
    """The bug a name based answer would have, on the capture that has it.

    `same-operation` drops frames belonging to a task other than the one whose trace this is, and
    in this capture eight function names appear both inside the traced task and inside somebody
    else's. `vfs_write` is one of them. Fading every `vfs_write` would fade the frames that were
    compared, and keeping every `vfs_write` bright would show frames that were not.
    """
    widget = TapeDiff(busy, busy, labels=("a", "a"))
    compared = widget._in_the_comparison(busy)

    verdicts = {}
    for frame in busy.walk():
        verdicts.setdefault(frame.name, set()).add(id(frame) in compared)

    assert verdicts["vfs_write"] == {True, False}
    assert sum(1 for one in verdicts.values() if one == {True, False}) == 8


def test_a_looser_policy_compares_more_and_fades_nothing(busy):
    strict = TapeDiff(busy, busy, policy=SAME_OPERATION)
    everything = TapeDiff(busy, busy, policy=EVERYTHING)

    assert any(strict.answer.dropped)
    assert everything.answer.dropped == (0, 0)
    assert "opacity:0.35" not in everything.html()


# -- the scale ------------------------------------------------------------------------------------


def test_by_default_each_tape_is_a_hundred_percent_of_its_own(to_a_file, to_a_pipe):
    widget = TapeDiff(to_a_file, to_a_pipe)
    assert widget.widths() == (100.0, 100.0)
    assert widget.sharing() is False
    assert "the same share of its own trace" in widget.html()


def test_a_shared_scale_draws_the_shorter_one_short(to_a_file, to_a_pipe):
    """121.875 us against 549.333 us, which is where the 22 percent comes from."""
    widget = TapeDiff(to_a_file, to_a_pipe, labels=("file", "pipe"), shared_scale=True)
    left, right = widget.widths()

    assert left == 100.0
    assert right == pytest.approx(100.0 * 121.875 / 549.333, abs=0.01)
    assert widget.sharing() is True
    assert "drawn against file, which is the longer of the two" in widget.html()


def test_a_shared_scale_is_refused_rather_than_half_given(one_write, two_writes):
    """Both of these have an unclosed frame at the end, so neither has a total to scale against.

    Scaling on the roots that do have durations would produce a picture that looks like a shared
    scale and is not one, which is worse than not offering it.
    """
    widget = TapeDiff(one_write, two_writes, shared_scale=True)
    assert widget.widths() == (100.0, 100.0)
    assert widget.sharing() is False
    assert "could not be given" in widget.html()


def test_the_cells_are_placed_at_the_width_the_scale_says(to_a_file, to_a_pipe):
    """The boxes an animation of this comparison would get, so the two cannot drift apart."""
    left, right = TapeDiff(to_a_file, to_a_pipe, shared_scale=True).cells()
    assert left[0].width == 100.0
    assert right[0].width == pytest.approx(22.19, abs=0.01)


# -- the verdict is kxdiff's ----------------------------------------------------------------------


def test_the_level_and_the_policy_reach_the_verdict(one_write, two_writes):
    widget = TapeDiff(one_write, two_writes, level=SET, policy=EVERYTHING, labels=("a", "b"))
    expected = diff(one_write, two_writes, level=SET, policy=EVERYTHING, labels=("a", "b"))
    assert widget.answer == expected
    assert "at set, everything" in widget.html()


def test_the_marking_and_the_verdict_answer_different_questions(to_a_file, to_a_pipe):
    """A comparison can pass at one level while boxes are still marked, and that is not a bug.

    The marking is about which names appear where. The verdict is about whatever the level asked,
    and `set` does not care what order anything happened in while `sequence` does.
    """
    widget = TapeDiff(to_a_file, to_a_pipe, level=SET)
    assert not widget.answer.same
    assert widget.only_on_one_side() != (set(), set())


def test_the_text_version_says_the_verdict_and_both_lists(one_write, two_writes):
    written = TapeDiff(one_write, two_writes, labels=("one", "two")).text()
    assert "one and two differ" in written
    assert "only in one: nothing" in written
    assert "anon_pipe_write" in written


def test_an_empty_side_says_so_rather_than_drawing_a_blank(one_write):
    from kxray.models import Tape

    drawn = TapeDiff(one_write, Tape(roots=[]), labels=("one", "nothing")).html()
    assert "nothing on this side" in drawn
