"""Tests for the visual vocabulary and the nine shapes both renderers draw.

Nothing here imports manim or emits HTML. That is the point of `kxshapes` existing at all: the
arithmetic behind every picture in this project is worked out once, and these tests are what say it
is worked out correctly, on any machine, in a fraction of a second.

The vocabulary tests are in the same file because the shapes are built out of it. A subsystem
colour, a layer depth, a context badge and a type tag glyph are not decoration, they are the
meanings a reader learns once and then relies on, and a shape that used them inconsistently would
be a picture that lies quietly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import kxshapes
from kxray import btf
from kxray.layout import place
from kxray.models import Frame, OpsTable, Slot, Tape
from kxray.trace import function_graph
from kxray.vocabulary import (
    CONTEXTS,
    LAYER_KEYS,
    LAYERS,
    REFERENCES,
    SUBSYSTEMS,
    TYPE_TAGS,
    UNKNOWN,
    context,
    in_layer_order,
    layer,
    layer_depth,
    reference,
    subsystem_for,
    tags_for,
)
from kxshapes import (
    PRIMITIVES,
    ContextBadge,
    CpuLane,
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

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "corpora" / "traces" / "handwritten" / "write-1byte.txt"
BLOB = ROOT / "corpora" / "btf" / "handwritten" / "tiny.btf"


@pytest.fixture(scope="module")
def tape() -> Tape:
    return function_graph.parse(TRACE.read_text(encoding="utf-8"), source=str(TRACE))


@pytest.fixture(scope="module")
def tiny():
    return btf.parse_file(BLOB)


# -- the vocabulary ---------------------------------------------------------------------------


def test_every_coloured_thing_also_has_a_name():
    """Colour is never the only channel, because a printed page does not have colour."""
    for one in SUBSYSTEMS:
        assert one.name
        assert one.stroke.startswith("#")
        assert one.fill.startswith("#")


def test_no_two_subsystems_share_a_colour():
    strokes = [one.stroke for one in SUBSYSTEMS]
    assert len(set(strokes)) == len(strokes)


def test_a_path_finds_its_subsystem():
    assert subsystem_for("fs/read_write.c").key == "fs"
    assert subsystem_for("mm/filemap.c").key == "mm"
    assert subsystem_for("./block/blk-core.c").key == "block"


def test_the_scheduler_wins_over_anything_shorter():
    """`kernel/sched/` is listed before the general prefixes, and order decides the match."""
    assert subsystem_for("kernel/sched/core.c").key == "sched"


def test_a_missing_path_comes_back_unknown_rather_than_guessed():
    """A trace prints names and not paths, and guessing from the name is wrong too often."""
    assert subsystem_for(None) is UNKNOWN
    assert subsystem_for("") is UNKNOWN
    assert subsystem_for("ext4_file_write_iter") is UNKNOWN


def test_there_are_eight_layers_and_they_run_top_to_bottom():
    assert len(LAYERS) == 8
    assert LAYER_KEYS[0] == "userspace"
    assert LAYER_KEYS[-1] == "hardware"
    assert layer_depth("vfs") < layer_depth("pagecache") < layer_depth("block")


def test_layers_come_back_in_order_whatever_order_they_went_in():
    assert in_layer_order(["block", "vfs", "userspace"]) == ["userspace", "vfs", "block"]


def test_a_layer_that_does_not_exist_says_which_ones_do():
    with pytest.raises(KeyError, match="userspace"):
        layer("pagetable")


def test_there_are_six_contexts_and_each_one_says_what_it_forbids():
    assert len(CONTEXTS) == 6
    for one in CONTEXTS:
        assert one.badge
        assert one.forbids
    assert len({one.badge for one in CONTEXTS}) == 6


def test_atomic_context_forbids_sleeping():
    assert "sleep" in context("atomic").forbids


def test_a_user_pointer_is_tagged_from_the_type_name():
    tags = tags_for("char __user *")
    assert [one.marker for one in tags] == ["__user"]
    assert tags[0].glyph == "→U"


def test_a_field_can_carry_more_than_one_tag():
    assert len(tags_for("struct foo __rcu __percpu *")) == 2


def test_a_plain_type_carries_no_tags():
    assert tags_for("unsigned long") == []


def test_the_three_reference_kinds_have_three_different_line_styles():
    dashes = [one.dash for one in REFERENCES]
    assert len(set(dashes)) == 3
    assert reference("owning").dash == ()


def test_an_unknown_reference_kind_lists_the_three():
    with pytest.raises(KeyError, match="owning"):
        reference("weak")


def test_every_type_tag_explains_itself():
    for one in TYPE_TAGS:
        assert len(one.meaning.split()) >= 5


# -- the nine primitives ----------------------------------------------------------------------


def test_there_are_exactly_nine_primitives():
    """The set is closed. A tenth shape is how a visual language turns into a pile of pictures."""
    assert len(PRIMITIVES) == 9
    assert len(set(PRIMITIVES)) == 9


def test_every_primitive_class_claims_one_of_the_nine_names():
    classes = [
        FrameCard,
        kxshapes.LayerBand,
        ObjectBox,
        PointerThread,
        OpsPlug,
        TraceCell,
        CpuLane,
        ContextBadge,
        MemorySlot,
    ]
    assert sorted(one.primitive for one in classes) == sorted(PRIMITIVES)


def test_a_frame_card_says_its_subsystem_and_its_context_in_words():
    card = FrameCard.of("vfs_write", path="fs/read_write.c", ran_in="process")
    assert "vfs_write" in card.alt()
    assert "filesystem" in card.alt()
    assert "process context" in card.alt()


def test_a_frame_card_with_no_path_is_visibly_unattributed():
    card = FrameCard.of("ext4_file_write_iter")
    assert card.subsystem is UNKNOWN
    assert "not attributed" in card.alt()


def test_a_layer_descent_comes_out_top_to_bottom_however_it_went_in():
    descent = LayerDescent.of({"block": "submit_bio", "vfs": "vfs_write", "entry": "ksys_write"})
    assert [one.layer.key for one in descent.path] == ["entry", "vfs", "block"]


def test_a_layer_descent_draws_all_eight_bands_and_lights_the_ones_it_touched():
    descent = LayerDescent.of({"vfs": "vfs_write"})
    assert len(descent.bands) == 8
    assert sum(1 for one in descent.bands if one.lit) == 1
    assert "vfs_write" in descent.alt()


def test_an_object_box_takes_its_rows_out_of_btf(tiny):
    box = ObjectBox.of(tiny.layout("demo_task"))
    assert box.name == "struct demo_task"
    assert box.rows
    assert all(one.type_name for one in box.rows)


def test_an_object_box_can_show_a_few_fields_and_says_how_many_it_hid(tiny):
    layout = tiny.layout("demo_task")
    first = layout.fields[0].path
    box = ObjectBox.of(layout, show=[first])
    assert len(box.rows) == 1
    assert box.hidden == len(layout.fields) - 1
    assert "more fields not shown" in box.alt()


def test_a_lock_on_a_field_is_something_a_person_wrote_down(tiny):
    """BTF has no member annotations, so which lock covers which field cannot be derived."""
    layout = tiny.layout("demo_task")
    first = layout.fields[0].path
    box = ObjectBox.of(layout, locks={first: "task->alloc_lock"})
    assert "protected by task->alloc_lock" in box.alt()
    assert any("lock you must hold" in one for one in box.legend())


def test_a_pointer_thread_says_what_the_pointer_promises():
    thread = PointerThread.of("file", "f_inode", "inode", kind="borrowed")
    assert "no reference is held" in thread.alt()
    assert thread.reference.dash != ()


def test_an_ops_plug_with_nothing_plugged_in_says_so():
    table = OpsTable("file_operations", [Slot("write", "ssize_t (*write)(void)", 8)])
    plug = OpsPlug.of(table)
    assert plug.filled == ()
    assert "empty in this drawing" in plug.alt()


def test_an_ops_plug_from_btf_finds_the_sockets(tiny):
    plug = OpsPlug.of(tiny.ops("demo_ops"))
    assert [one.name for one in plug.sockets] == ["open", "write", "release"]


def test_an_ops_plug_shows_what_is_plugged_in(tiny):
    table = tiny.ops("demo_ops", instance="demo_shmem_ops").with_implementations(
        {"write": "demo_shmem_write"}
    )
    plug = OpsPlug.of(table)
    assert [one.name for one in plug.filled] == ["write"]
    assert "demo_shmem_write" in plug.alt()


def test_a_trace_cell_uses_the_same_arithmetic_the_widget_uses(tape):
    root = tape.roots[0]
    span = place(root)[0]
    cell = TraceCell.of(span, root.depth)
    assert cell.left == span.left
    assert cell.width == span.width
    assert cell.row == 0


def test_a_cell_placed_by_counting_says_so_in_its_alt_text():
    parent = Frame("a", 0, 0, 1, duration_us=None)
    parent.children = [Frame("b", 0, 1, 2, duration_us=None, parent=parent)]
    cells = [TraceCell.of(one) for one in place(parent)]
    assert "not by time" in cells[1].alt()


def test_a_tape_splits_into_one_lane_per_cpu(tape):
    got = lanes(tape)
    assert [one.cpu for one in got] == sorted(tape.cpus)
    assert sum(len(one.cells) for one in got) == tape.frame_count


def test_a_lane_knows_how_deep_it_goes():
    lane = CpuLane(0, (TraceCell("a", 0, 0, 100, 1.0, True), TraceCell("b", 2, 0, 50, 0.5, True)))
    assert lane.rows == 3


def test_an_empty_lane_has_no_rows():
    assert CpuLane(3).rows == 0


def test_a_context_badge_reads_as_what_it_forbids():
    badge = ContextBadge.of("hardirq")
    assert badge.glyph == "●"
    assert "no sleeping" in badge.alt()


def test_memory_slots_are_drawn_on_a_log_scale():
    """A struct file next to a huge page has to stay visible, and to scale it would not be."""
    small = MemorySlot("struct file", 232)
    page = MemorySlot("a page", 4096)
    huge = MemorySlot("a huge page", 2 * 1024 * 1024)
    assert small.width(huge.size_bytes) < page.width(huge.size_bytes) < 1.0
    # To scale a struct file would be one ten thousandth of the huge page. Here it is a fifth.
    assert small.width(huge.size_bytes) > 0.2


def test_the_biggest_slot_fills_the_width():
    assert MemorySlot("a page", 4096).width(4096) == 1.0


def test_a_slot_of_no_bytes_is_refused():
    with pytest.raises(ValueError, match="no width"):
        MemorySlot("nothing", 0)


def test_scaling_measures_everything_against_the_biggest():
    widths = dict(
        (one.label, round(width, 3))
        for one, width in scale([MemorySlot("a", 8), MemorySlot("b", 4096)])
    )
    assert widths["b"] == 1.0
    assert widths["a"] < 1.0


def test_scaling_nothing_is_not_an_error():
    assert scale([]) == []


def test_every_primitive_can_describe_itself_in_words(tiny, tape):
    """An animation that cannot be described in words is one half the readers get nothing from."""
    made = [
        FrameCard.of("vfs_write", path="fs/read_write.c"),
        kxshapes.LayerBand(layer("vfs"), "vfs_write", True),
        ObjectBox.of(tiny.layout("demo_task")),
        PointerThread.of("file", "f_inode", "inode"),
        OpsPlug.of(tiny.ops("demo_ops")),
        TraceCell.of(place(tape.roots[0])[0]),
        lanes(tape)[0],
        ContextBadge.of("process"),
        MemorySlot("a page", 4096),
    ]
    for one in made:
        assert len(one.alt().split()) >= 4, one
