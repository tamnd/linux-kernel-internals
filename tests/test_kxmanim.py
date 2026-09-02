"""Tests for the visual vocabulary, the nine primitives and the storyboard rules.

None of this needs manim. That is deliberate and it is most of the value: the rules about
animation only mean something if they run on every push, and a check that needs a video toolchain
installed is a check that gets skipped the first week CI gets slow.

The manim adapter itself is a handful of dictionaries and one class definition, and the tests for
it are skipped when manim is not installed, which on most machines is always.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from kxmanim import primitives
from kxmanim.primitives import (
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
from kxmanim.scene import RENDERS, unrenderable
from kxmanim.storyboard import BUDGET_SECONDS, Beat, Storyboard, load_all
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

ROOT = Path(__file__).resolve().parents[1]
STORYBOARDS = ROOT / "kxmanim" / "storyboards"
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
        primitives.LayerBand,
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
        primitives.LayerBand(layer("vfs"), "vfs_write", True),
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


# -- the storyboard rules ---------------------------------------------------------------------

GOOD = """
id = "demo"
idea = "One idea, stated as a whole sentence, which is the title"
still = "lessons/Z02/assets/one-file-two-stacks.svg"
status = "reviewed"
evidence = false
blocked_on = "nothing has been captured on a real machine yet"

[[beat]]
seconds = 10
caption = "The first thing that happens, said in a whole sentence"
alt = "A picture of the first thing that happens, described for somebody who cannot see it"
shows = ["cpu-lane"]
"""


def board(**changes) -> Storyboard:
    """The good storyboard with one top level field changed, which is how each rule gets tested."""
    lines = GOOD.splitlines()
    for key, value in changes.items():
        for index, line in enumerate(lines):
            if line.startswith(f"{key} = "):
                lines[index] = f"{key} = {value}"
                break
    return Storyboard.loads("\n".join(lines))


def test_a_good_storyboard_has_nothing_wrong_with_it():
    assert board().problems() == []
    assert board().renderable


def test_beats_are_clocked_one_after_another():
    got = Storyboard.loads(GOOD + '\n[[beat]]\nseconds = 5\ncaption = "a"\nalt = "b"\nshows = []\n')
    assert [one.starts_at for one in got.beats] == [0.0, 10.0]
    assert got.seconds == 15.0


def test_an_animation_over_the_budget_is_two_animations():
    long = GOOD + "".join(
        '\n[[beat]]\nseconds = 20\ncaption = "a caption long enough to pass the check"\n'
        'alt = "alt text that is long enough to stand in for the picture itself"\n'
        'shows = ["cpu-lane"]\n'
        for _ in range(5)
    )
    got = Storyboard.loads(long)
    assert got.seconds > BUDGET_SECONDS
    assert any("second animation" in one for one in got.problems())


def test_a_single_beat_held_too_long_is_a_slide():
    beat = Beat(30, "a caption long enough to pass", "alt text long enough to stand in for it", ())
    assert any("is a slide" in one for one in beat.problems())


def test_an_idea_that_is_a_label_rather_than_a_sentence_is_refused():
    assert any("a label" in one for one in board(idea='"Interleaving"').problems())


def test_an_animation_with_no_still_is_refused():
    """No animation is load-bearing, so there has to be a picture that works without motion."""
    assert any("load-bearing" in one for one in board(still='""').problems())


def test_a_short_caption_is_refused():
    got = Storyboard.loads(
        GOOD.replace("The first thing that happens, said in a whole sentence", "It moves")
    )
    assert any("too short to explain" in one for one in got.problems())


def test_alt_text_that_is_the_caption_again_is_refused():
    line = "The first thing that happens, said in a whole sentence"
    got = Storyboard.loads(
        GOOD.replace(
            "A picture of the first thing that happens, described for somebody who cannot see it",
            line,
        )
    )
    assert any("pasted again" in one for one in got.problems())


def test_a_shape_that_is_not_one_of_the_nine_is_refused():
    got = Storyboard.loads(GOOD.replace('"cpu-lane"', '"sankey-diagram"'))
    assert any("not one of the nine" in one for one in got.problems())


def test_a_beat_that_does_not_say_what_it_shows_is_refused():
    got = Storyboard.loads(GOOD.replace('shows = ["cpu-lane"]', "shows = []"))
    assert any("does not say which primitives" in one for one in got.problems())


def test_saying_there_is_no_evidence_means_saying_what_it_is_waiting_for():
    assert any("waiting for" in one for one in board(blocked_on='""').problems())


def test_a_draft_does_not_render_even_when_everything_else_is_right():
    got = board(status='"draft"')
    assert got.problems() == []
    assert not got.renderable


def test_a_status_nobody_recognises_is_refused():
    assert any("draft or reviewed" in one for one in board(status='"nearly"').problems())


def test_check_raises_with_every_problem_at_once():
    got = Storyboard.loads('id = "x"\n')
    with pytest.raises(ValueError) as caught:
        got.check()
    assert "no idea" in str(caught.value)
    assert "no beats" in str(caught.value)


def test_the_caption_track_is_generated_from_the_beats():
    vtt = board().vtt()
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:10.000" in vtt
    assert "The first thing that happens" in vtt


def test_the_clock_survives_a_long_animation():
    got = Storyboard.loads(GOOD.replace("seconds = 10", "seconds = 75.5"))
    assert "00:01:15.500" in got.vtt()


def test_the_transcript_carries_the_idea_the_still_and_the_alt_text():
    text = board().transcript()
    assert "One idea, stated as a whole sentence" in text
    assert "one-file-two-stacks.svg" in text
    assert "cannot see it" in text


def test_a_storyboard_lists_the_primitives_it_uses_in_the_canonical_order():
    got = Storyboard.loads(
        GOOD.replace('shows = ["cpu-lane"]', 'shows = ["memory-slot", "frame-card"]')
    )
    assert got.uses() == ["frame-card", "memory-slot"]


# -- the renderer, and what it cannot draw yet ------------------------------------------------


def test_the_renderer_covers_a_subset_of_the_nine_and_says_which():
    assert set(PRIMITIVES) > RENDERS
    assert "cpu-lane" in RENDERS


def test_a_storyboard_asking_for_a_shape_nobody_can_draw_is_flagged():
    got = Storyboard.loads(GOOD.replace('"cpu-lane"', '"memory-slot"'))
    assert unrenderable(got) == ["memory-slot"]


def test_an_object_box_is_laid_out_with_a_row_per_field_and_the_hidden_ones_counted(tiny):
    """The count of hidden fields has to survive into the drawing.

    A box that shows four fields of a forty field struct and does not say so tells the reader the
    struct is small, and that is a picture being wrong rather than a picture being simple.
    """
    from kxmanim.scene import box_of

    layout = tiny.layout("demo_task")
    first = layout.fields[0].path
    drawn = box_of(ObjectBox.of(layout, show=[first]), 0.0, 2.0)

    assert len(drawn["rows"]) == 1
    assert drawn["hidden"] == len(layout.fields) - 1
    assert drawn["rows"][0]["offset"] == layout.fields[0].byte_offset
    # Rows go downwards from the header, so every one of them sits below where the box starts.
    assert all(row["y"] < drawn["y"] for row in drawn["rows"])


def test_a_pointer_thread_is_drawn_by_what_it_promises_rather_than_by_taste():
    from kxmanim.scene import thread_of

    owning = thread_of(PointerThread.of("file", "f_op", "file_operations"), (0, 0), (3, 0))
    borrowed = thread_of(
        PointerThread.of("file", "f_inode", "inode", kind="borrowed"), (0, 0), (3, 0)
    )

    assert owning["dash"] == []
    assert borrowed["dash"] != []
    assert "no reference is held" in borrowed["promise"]


def test_an_ops_plug_draws_a_socket_per_slot_and_marks_the_empty_ones(tiny):
    """An empty socket is not a null pointer, and the drawing must not imply that it is.

    What sits in a function pointer is a fact about a running machine. BTF can say the socket
    exists and what shape a plug has to be, and nothing else can say what is in it, so a socket
    nobody has looked up is drawn hollow rather than drawn as nothing.
    """
    from kxmanim.scene import plug_of

    table = tiny.ops("demo_ops", instance="demo_shmem_ops").with_implementations(
        {"write": "demo_shmem_write"}
    )
    drawn = plug_of(OpsPlug.of(table), 0.0, 2.0)

    assert len(drawn["sockets"]) == 3
    assert drawn["filled"] == 1
    assert drawn["empty"] == 2
    filled = [one for one in drawn["sockets"] if one["filled_by"]]
    assert [one["label"] for one in filled] == ["write"]
    assert filled[0]["stroke"] != drawn["sockets"][0]["stroke"]


def test_the_three_lessons_of_this_milestone_each_have_an_animation():
    """One animation each for Z02, S05 and C09, which is what the milestone asks for.

    The link is the still. Every storyboard names one, no animation is load-bearing, and the still
    lives in the lesson it belongs to, so the lesson a storyboard is for is not a field somebody
    can forget to update.
    """
    stills = {one.still for one in load_all(STORYBOARDS)}
    for slug in ("Z02", "S05", "C09"):
        assert any(one.startswith(f"lessons/{slug}/") for one in stills), slug


def test_the_shipped_storyboards_only_ask_for_shapes_that_exist():
    for one in load_all(STORYBOARDS):
        assert unrenderable(one) == [], one.source


# -- what is actually in the repository -------------------------------------------------------


def test_there_is_at_least_one_storyboard():
    assert load_all(STORYBOARDS)


def test_every_storyboard_in_the_repository_passes_its_own_rules():
    for one in load_all(STORYBOARDS):
        one.check()


def test_every_storyboard_names_a_still_that_is_really_there():
    for one in load_all(STORYBOARDS):
        assert (ROOT / one.still).exists(), one.still


def test_every_storyboard_names_inputs_that_are_really_there():
    for one in load_all(STORYBOARDS):
        for name in one.inputs:
            assert (ROOT / name).exists(), name


def test_no_storyboard_claims_evidence_it_does_not_have():
    """Same rule as the corpus and the citations, and it used to be simpler than this.

    Every storyboard was once `evidence = false`, because nothing here had run on a real kernel.
    One of them can say true now, and the rule that matters is unchanged: a storyboard either
    names inputs that are evidence, or it says in `blocked_on` what it is waiting for. Neither
    means it is drawn from nothing and nobody wrote down that it was.
    """
    for one in load_all(STORYBOARDS):
        if one.evidence:
            assert one.inputs, f"{one.source} claims evidence and names no inputs"
            for name in one.inputs:
                meta = (ROOT / name).with_suffix(".meta.toml")
                assert meta.exists(), f"{name} backs a storyboard and has no metadata"
                assert tomllib.loads(meta.read_text())["evidence"] is True, name
        else:
            assert one.blocked_on, f"{one.source} has no evidence and does not say what it wants"


# -- the manim adapter, which most machines cannot run -----------------------------------------


def test_the_adapter_builds_a_scene_class_named_after_the_storyboard():
    pytest.importorskip("manim")
    from kxmanim.scene import scene_for

    built = scene_for(board(), lambda beat, scene: None)
    assert built.__name__ == "Demo"


def test_the_adapter_refuses_a_draft():
    pytest.importorskip("manim")
    from kxmanim.scene import scene_for

    with pytest.raises(RuntimeError, match="has not been reviewed"):
        scene_for(board(status='"draft"'), lambda beat, scene: None)
