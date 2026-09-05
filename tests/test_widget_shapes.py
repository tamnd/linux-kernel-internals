"""Tests for the HTML renderer of each of the nine shapes.

The first test in this file is the milestone criterion written down: there is a renderer for all
nine, so no lesson ever has to be written around a shape that only exists in one medium.

The rest check the things that would be wrong quietly. A picture is not something a test can look
at, so what gets asserted on is the part of the drawing that carries meaning rather than the part
that carries taste. A dashed line is not a style choice, it is a promise about whether a reference
is held. A hollow socket is not a null pointer, it is an admission that nobody looked. A bar twice
as long is not a thing twice as big, because the scale is logarithmic. Those three are what the
shapes are for, and each one has a test here.

What is deliberately not tested is colour values, padding and rounding. Those change when somebody
has a better idea, and a test that pins them makes having a better idea expensive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kxray import btf
from kxray.trace import function_graph
from kxshapes import (
    PRIMITIVES,
    ContextBadge,
    FrameCard,
    LayerDescent,
    MemorySlot,
    ObjectBox,
    OpsPlug,
    PointerThread,
    TraceCell,
    lanes,
    scale,
)
from kxwidgets import OpsExplorer, SyscallTape
from kxwidgets.shapes import (
    RENDERERS,
    RENDERS,
    _line_style,
    context_badge,
    cpu_lane,
    frame_card,
    layer_band,
    memory_slot,
    object_box,
    ops_plug,
    pointer_thread,
    render,
    trace_cell,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "corpora" / "btf" / "handwritten" / "tiny.btf"
TRACE = ROOT / "corpora" / "traces" / "handwritten" / "write-1byte.txt"


@pytest.fixture(scope="module")
def tiny():
    return btf.parse_file(FIXTURE)


@pytest.fixture(scope="module")
def captured():
    return function_graph.parse(TRACE.read_text(encoding="utf-8"), source=str(TRACE))


# -- the criterion ------------------------------------------------------------------------------


def test_every_one_of_the_nine_shapes_can_be_drawn_as_a_widget():
    """The milestone exit criterion, as an assertion.

    A shape an animation can draw and a widget cannot is a shape that a lesson has to be written
    around, and a closed set of nine only pays for itself if all nine work everywhere.
    """
    assert set(PRIMITIVES) == RENDERS
    assert len(RENDERERS) == 9


def test_asking_to_draw_something_that_is_not_a_shape_is_refused():
    with pytest.raises(TypeError, match="not one of the nine"):
        render("a frame card, probably")


def test_render_dispatches_on_which_shape_it_was_given():
    badge = ContextBadge.of("atomic")
    assert render(badge) == context_badge(badge)


# -- 1. frame card ------------------------------------------------------------------------------


def test_a_frame_card_carries_its_subsystem_and_its_context():
    drawn = frame_card(FrameCard.of("shmem_write_begin", path="mm/shmem.c", ran_in="process"))
    assert "shmem_write_begin" in drawn
    assert "memory management" in drawn
    assert "▢" in drawn


def test_a_frame_nobody_looked_up_is_drawn_as_not_looked_up():
    """The dull grey is the point. A drawing full of it should look unfinished, because it is."""
    drawn = frame_card(FrameCard.of("some_function"))
    assert "not attributed to a subsystem" in drawn


# -- 2. layer band ------------------------------------------------------------------------------


def test_the_layers_a_call_skipped_are_still_drawn():
    """A descent that only shows the layers it touched cannot show the ones it did not.

    Which is the whole lesson of a buffered write. The call never reaches the block layer, the
    driver or the disk, and a picture that leaves those out has hidden the surprising part.
    """
    descent = LayerDescent.of({"vfs": "vfs_write"})
    drawn = "".join(layer_band(one) for one in descent.bands)
    for band in descent.bands:
        assert band.layer.name in drawn
    assert "block layer" in drawn
    assert "vfs_write" in drawn


def test_a_lit_band_says_what_happened_and_a_dim_one_says_what_it_is_for():
    descent = LayerDescent.of({"vfs": "vfs_write"})
    by_key = {one.layer.key: one for one in descent.bands}
    assert "vfs_write" in layer_band(by_key["vfs"])
    assert by_key["block"].layer.blurb in layer_band(by_key["block"])


# -- 3. object box ------------------------------------------------------------------------------


def test_an_object_box_says_how_many_fields_it_is_not_showing(tiny):
    """A box that shows two fields of a fifteen field struct and says nothing is lying quietly."""
    box = ObjectBox.of(tiny.layout("demo_task"), show=["pid", "mm"])
    drawn = object_box(box)
    assert "pid" in drawn
    assert f"{box.hidden} more fields" in drawn


def test_an_object_box_prints_real_offsets(tiny):
    drawn = object_box(ObjectBox.of(tiny.layout("demo_task"), show=["mm"]))
    assert "+24" in drawn


def test_a_locked_field_carries_the_lock_and_the_lock_glyph(tiny):
    box = ObjectBox.of(tiny.layout("demo_task"), show=["mm"], locks={"mm": "task.alloc_lock"})
    drawn = object_box(box)
    assert "task.alloc_lock" in drawn
    assert "\U0001f512" in drawn


# -- 4. pointer thread --------------------------------------------------------------------------


def test_the_three_promises_get_three_different_lines():
    """Solid, dashed and dotted are the difference between correct code and a use after free."""
    owning = pointer_thread(PointerThread.of("file", "f_op", "file_operations"))
    borrowed = pointer_thread(PointerThread.of("file", "f_inode", "inode", kind="borrowed"))
    rcu = pointer_thread(PointerThread.of("task", "cred", "cred", kind="rcu"))

    assert "2px solid" in owning
    assert "2px dashed" in borrowed
    assert "2px dotted" in rcu


def test_a_thread_writes_out_what_the_line_style_promises():
    drawn = pointer_thread(PointerThread.of("file", "f_inode", "inode", kind="borrowed"))
    assert "no reference is held" in drawn


def test_the_line_style_comes_from_the_vocabulary_and_not_from_taste():
    assert _line_style(()) == "solid"
    assert _line_style((6, 4)) == "dashed"
    assert _line_style((1, 3)) == "dotted"


# -- 5. ops plug --------------------------------------------------------------------------------


def test_an_empty_socket_is_drawn_hollow_rather_than_drawn_as_nothing(tiny):
    """An empty socket means nobody looked, not that the kernel leaves it null."""
    plug = OpsPlug.of(tiny.ops("demo_ops").with_implementations({"write": "demo_shmem_write"}))
    drawn = ops_plug(plug)
    assert "demo_shmem_write" in drawn
    assert "dashed" in drawn
    assert f"{len(plug.filled)} of {len(plug.sockets)} sockets" in drawn


def test_the_compact_ops_widget_draws_the_same_plug_the_animation_gets(tiny):
    """The rewiring, asserted. The widget does not build its own sockets any more."""
    widget = OpsExplorer(tiny.ops("demo_ops"), compact=True)
    assert ops_plug(widget.plug) in widget.html()


# -- 6. trace cell and 7. CPU lane ----------------------------------------------------------------


def test_a_cell_is_placed_where_kxshapes_says_and_not_where_the_widget_thinks(captured):
    from kxray.layout import place

    spans = place(captured.roots[0])
    cell = TraceCell.of(spans[1], captured.roots[0].depth)
    drawn = trace_cell(cell)
    assert f"left:{cell.left:.4f}%" in drawn
    assert f"width:{cell.width:.4f}%" in drawn


def test_a_cell_placed_by_counting_rather_than_by_timing_is_outlined_in_red(captured):
    """A box whose width is a guess has to look different from one whose width is a measurement."""
    cell = TraceCell("guessed", 0, 0.0, 50.0, None, to_scale=False)
    assert "#b04040" in trace_cell(cell)
    assert "#b04040" not in trace_cell(TraceCell("timed", 0, 0.0, 50.0, 4.0, to_scale=True))


def test_the_hover_text_is_the_widgets_to_give_and_the_shape_has_a_default(captured):
    cell = TraceCell("timed", 0, 0.0, 50.0, 4.0, to_scale=True)
    assert cell.alt() in trace_cell(cell)
    assert "cpu 0, depth 0" in trace_cell(cell, hover="cpu 0, depth 0")


def test_a_lane_is_labelled_with_its_cpu(captured):
    lane = lanes(captured)[0]
    assert f"cpu {lane.cpu}" in cpu_lane(lane)
    assert f"cpu {lane.cpu}" not in cpu_lane(lane, labelled=False)


def test_the_tape_widget_draws_the_cells_kxshapes_produced(captured):
    """Same rewiring as the ops plug. There is one implementation of a trace cell now."""
    widget = SyscallTape(captured, by_cpu=True)
    drawn = widget.html()
    for lane in widget.lanes():
        for cell in lane.cells:
            assert trace_cell(cell) in drawn


def test_asking_for_lanes_works_on_a_bare_frame_too(captured):
    """A tape and a single frame both have to work, because a lesson zooms in on one call."""
    widget = SyscallTape(captured.roots[0], by_cpu=True)
    assert widget.lanes()
    assert "cpu" in widget.html()


# -- 8. context badge ---------------------------------------------------------------------------


def test_a_badge_says_which_context_and_the_wordy_one_says_what_it_forbids():
    """The quiet one carries what it forbids in the hover text, and the wordy one prints it.

    Both is right. A badge stuck on the corner of a frame card has no room for a sentence, and a
    legend that only says the name of a context has not explained anything.
    """
    quiet = context_badge(ContextBadge.of("atomic"))
    wordy = context_badge(ContextBadge.of("atomic"), wordy=True)
    assert "spinlock is held" in quiet
    assert quiet.count("no sleeping") == 1
    assert wordy.count("no sleeping") == 2


# -- 9. memory slot -----------------------------------------------------------------------------


def test_a_log_scale_keeps_the_small_thing_visible():
    """The reason the scale is logarithmic at all.

    A struct next to a huge page is a ratio of about nine thousand to one. Drawn linearly the
    struct is a hairline and the reader learns nothing from it, so the widths compress and the
    caption carries the real number.
    """
    slots = [MemorySlot("struct file", 232), MemorySlot("a huge page", 2 * 1024 * 1024)]
    widths = dict(scale(slots))
    small = widths[slots[0]]
    linear = slots[0].size_bytes / slots[1].size_bytes

    assert linear < 0.001
    assert small > 0.3
    assert "232 bytes" in memory_slot(slots[0], small)


def test_the_real_size_is_always_printed_next_to_the_bar():
    """A log scale that does not admit to being one is a wrong picture, not a simplified one."""
    drawn = memory_slot(MemorySlot("a page", 4096, note="the unit almost everything works in"), 1.0)
    assert "4,096 bytes" in drawn
    assert "the unit almost everything works in" in drawn


def test_a_slot_with_no_bytes_in_it_is_refused():
    with pytest.raises(ValueError, match="zero has no width"):
        MemorySlot("nothing", 0)
