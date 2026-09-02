"""Tests for the storyboard rules and the manim adapter.

None of this needs manim. That is deliberate and it is most of the value: the rules about animation
only mean something if they run on every push, and a check that needs a video toolchain installed
is a check that gets skipped the first week CI gets slow.

The nine shapes the storyboards refer to live in `kxshapes` and are tested in `test_kxshapes.py`,
because `kxwidgets` draws them too and they stopped being an animation concern when that happened.
What is left here is the part that is genuinely about animation: a budget, a still that has to
exist, captions and alt text written by a person, and an adapter that is honest about which shapes
it cannot draw yet.

The manim adapter itself is a handful of dictionaries and one class definition, and the tests for
it are skipped when manim is not installed, which on most machines is always.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from kxmanim.scene import RENDERS, unrenderable
from kxmanim.storyboard import BUDGET_SECONDS, Beat, Storyboard, load_all
from kxray import btf
from kxshapes import PRIMITIVES, ObjectBox, OpsPlug, PointerThread

ROOT = Path(__file__).resolve().parents[1]
STORYBOARDS = ROOT / "kxmanim" / "storyboards"
BLOB = ROOT / "corpora" / "btf" / "handwritten" / "tiny.btf"


@pytest.fixture(scope="module")
def tiny():
    return btf.parse_file(BLOB)


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
