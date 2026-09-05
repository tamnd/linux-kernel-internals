"""Tests for the one conversion from a trace to a picture.

There is exactly one thing this file is guarding, and everything in it is a way of saying it: the
notebook, the blueprint and the animation of one capture have to be three renderings of one
arrangement rather than three arrangements. Before `kxshapes.scene` existed they were three, and
they agreed, and nothing anywhere would have noticed the day they stopped.

So the tests that matter are the ones that pin two things together. The tape widget draws the cells
the scene produced. The CPU lanes the scene builds are the cells `kxshapes.lanes` builds, one for
one. The hover text in the notebook is the same string the blueprint prints. Those are cheap to
write and they are the only reason any of the rest of this is worth anything.

The trace is the committed handwritten one for the ordinary cases and the real Tier 1 multi CPU
capture for anything about lanes, because Tier 0 is a uniprocessor emulator and a lane test on a
one CPU trace is a test that passes without doing anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kxray.models import Frame, Tape
from kxray.trace import function_graph, parse_file
from kxshapes import PRIMITIVES, TraceCell, lanes
from kxshapes.scene import Lane, Scene, cells, detail_of, scene_of, spans_of

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "corpora" / "traces" / "handwritten" / "write-1byte.txt"
MULTI = ROOT / "corpora" / "traces" / "tier1" / "multi-cpu-write.txt"


@pytest.fixture(scope="module")
def captured() -> Tape:
    return function_graph.parse(TRACE.read_text(encoding="utf-8"), source=str(TRACE))


@pytest.fixture(scope="module")
def many() -> Tape:
    """A real capture off a six CPU machine, which Tier 0 cannot produce at any setting."""
    return parse_file(MULTI)


def frame(name, duration=None, depth=0, cpu=0, marker=None, children=()):
    one = Frame(name=name, cpu=cpu, depth=depth, line=1, duration_us=duration, marker=marker)
    for child in children:
        child.parent = one
        one.children.append(child)
    return one


# -- the shape of a scene -----------------------------------------------------------------------


def test_a_lane_per_outermost_call_and_a_step_per_frame(captured):
    scene = scene_of(captured)
    assert len(scene.lanes) == len(captured.roots)
    assert sum(len(one.steps) for one in scene.lanes) == captured.frame_count


def test_the_order_runs_across_the_whole_scene_and_not_within_a_lane(captured):
    """An animation reveals along this number, so it has to be a single run with no repeats."""
    numbers = [one.order for one in scene_of(captured).steps]
    assert numbers == list(range(len(numbers)))


def test_max_depth_counts_from_each_outermost_call(captured):
    scene = scene_of(captured, max_depth=2)
    assert max(one.row for one in scene.steps) == 2
    assert max(one.row for one in scene_of(captured).steps) > 2


def test_a_bare_frame_is_a_scene_of_one_lane():
    """A lesson zooms in on one call, and that has to be the same object as a whole tape."""
    scene = scene_of(frame("outer", 10.0, children=[frame("inner", 4.0, depth=1)]))
    assert len(scene.lanes) == 1
    assert [one.shape.name for one in scene.steps] == ["outer", "inner"]
    assert scene.subject == "outer on cpu 0"


def test_an_empty_tape_is_a_scene_that_says_so_rather_than_one_that_raises():
    scene = scene_of(Tape())
    assert scene.empty
    assert scene.lanes == ()
    assert "nothing was captured" in scene.alt()
    assert scene.table().splitlines()[0].startswith("#")


# -- what the scene refuses to decide -----------------------------------------------------------


def test_one_missing_duration_takes_the_whole_scene_off_scale():
    """The caption is under the picture, so the flag that drives it belongs to the picture.

    A reader does not read a tape box by box. One guessed width shifts everything to the right of
    it, so a scene with a single guessed box in it is a scene whose horizontal axis cannot be read
    as time anywhere, and the footnote has to say so.
    """
    scene = scene_of(frame("a", 1.0, children=[frame("b", None, 1), frame("c", 0.5, 1)]))
    assert not scene.to_scale
    assert "some boxes were placed by call order" in scene.alt()
    assert any(not one.shape.to_scale for one in scene.steps)


def test_a_fully_timed_scene_says_so():
    scene = scene_of(frame("a", 4.0, children=[frame("b", 1.0, 1), frame("c", 2.0, 1)]))
    assert scene.to_scale
    assert "as wide as the call took" in scene.alt()


# -- the two arrangements -----------------------------------------------------------------------


def test_a_cpu_scene_holds_the_same_cells_as_the_lane_function(many):
    """The invariant that lets `_by_cpu` do its own walk instead of calling `lanes`.

    It does its own walk because it needs the frame each cell came from, to build the words, and a
    `CpuLane` hands back cells with the frames already dropped. Lining the two lists up by position
    would be right today and wrong the first time either walk changed what it filters. This is the
    check that keeps the two honest instead.
    """
    scene = scene_of(many, max_depth=2, by_cpu=True)
    built = lanes(many, max_depth=2)
    assert [one.cpu for one in built] == [int(one.label.split()[1]) for one in scene.lanes]
    for lane, other in zip(scene.lanes, built, strict=True):
        assert list(scene.cells(lane.index)) == list(other.cells)


def test_splitting_by_cpu_finds_six_lanes_where_splitting_by_call_finds_thirty_three(many):
    """The same file read two ways, and the numbers are read off the capture rather than picked."""
    assert len(scene_of(many, by_cpu=True).lanes) == 6
    assert len(scene_of(many).lanes) == 33


def test_a_uniprocessor_capture_has_no_cpu_lane_in_it_to_show(captured):
    """This is what stops a storyboard claiming CPU lanes over a Tier 0 trace.

    Tier 0 is a uniprocessor emulator and no setting changes that, so a beat that wants two lanes
    wants a capture from a real machine, and `uses()` is what says which it has been handed.
    """
    assert scene_of(captured, by_cpu=True).uses() == ["trace-cell"]


def test_a_real_multi_cpu_capture_does(many):
    assert scene_of(many, by_cpu=True).uses() == ["trace-cell", "cpu-lane"]


def test_everything_uses_returns_is_one_of_the_nine(many):
    for one in scene_of(many, by_cpu=True).uses():
        assert one in PRIMITIVES


# -- the words ----------------------------------------------------------------------------------


def test_the_detail_carries_the_numbers_that_do_not_fit_in_a_box():
    scene = scene_of(frame("slow", 120.0, marker="!"))
    detail = scene.steps[0].detail
    assert "slow()" in detail
    assert "120.000 us" in detail
    assert "marker !" in detail


def test_a_call_the_trace_cut_off_says_so_rather_than_reading_as_finished():
    one = frame("vfs_write", None)
    one.complete = False
    assert "never closed" in scene_of(one).steps[0].detail


def test_the_detail_is_one_function_and_not_three_copies(captured):
    """The whole point. Same string in the notebook, the blueprint and the transcript."""
    root = captured.roots[0]
    span = spans_of(root)[0]
    assert scene_of(captured).lanes[0].steps[0].detail == detail_of(span.frame, span)


def test_a_lane_describes_itself_in_words(many):
    lane = scene_of(many, by_cpu=True).lanes[0]
    assert lane.label in lane.alt()
    assert str(len(lane.steps)) in lane.alt()


# -- the table the blueprint prints ---------------------------------------------------------------


def test_the_table_has_a_row_per_step_and_a_header(captured):
    scene = scene_of(captured, max_depth=1)
    rows = scene.table().splitlines()
    assert rows[0].split() == ["#", "lane", "depth", "call", "took", "width", "note"]
    assert len(rows) == len(scene.steps) + 2  # header and the rule under it


def test_a_call_with_no_duration_prints_unknown_rather_than_a_number():
    table = scene_of(frame("a", None, children=[frame("b", None, 1)])).table()
    assert "unknown" in table
    assert "placed by call order" in table


def test_the_table_names_the_lane_each_row_is_in(many):
    table = scene_of(many, max_depth=0, by_cpu=True).table()
    for cpu in range(6):
        assert f"cpu {cpu}" in table


# -- the convenience ------------------------------------------------------------------------------


def test_cells_gives_the_same_boxes_the_scene_holds(captured):
    """A second route to the boxes is only safe if it is the same route with less on it."""
    scene = scene_of(captured, max_depth=2)
    assert cells(captured, max_depth=2) == [list(scene.cells(one.index)) for one in scene.lanes]
    assert all(isinstance(one, TraceCell) for group in cells(captured) for one in group)


def test_the_pieces_are_what_they_say_they_are(captured):
    scene = scene_of(captured)
    assert isinstance(scene, Scene)
    assert isinstance(scene.lane(0), Lane)
    assert scene.lane(0).steps[0].primitive == "trace-cell"
