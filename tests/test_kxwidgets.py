"""Tests for the four widgets.

A widget draws a picture, and a test cannot look at a picture. So these check the three things
that can be checked: that the numbers behind the drawing are right, that the HTML around them is
well formed, and that the text version says the same thing as the picture.

The rule about no script and no style block is checked here too, on every widget, because it is
the promise that makes a widget survive Colab, nbconvert and the static site, and a promise nobody
checks is a promise that lasts about two months.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

from kxray import btf
from kxray.models import Field, Frame, Layout, OpsTable, Slot, Tape, UnparsedLine
from kxray.trace import function_graph
from kxwidgets import OpsExplorer, PredictionGate, StructMap, SyscallTape, Widget
from kxwidgets.html import attribute, card, details, page, style, tag, text
from kxwidgets.structmap import CACHE_LINE
from kxwidgets.tape import place

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "corpora" / "btf" / "handwritten" / "tiny.btf"
TRACE = ROOT / "corpora" / "traces" / "handwritten" / "write-1byte.txt"

VOID = {"area", "br", "col", "hr", "img", "input", "link", "meta", "source"}


class Balanced(HTMLParser):
    """Opens and closes, in order. Enough to catch a tag built out of an f-string wrong."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, name, attrs):
        if name not in VOID:
            self.stack.append(name)

    def handle_endtag(self, name):
        if not self.stack or self.stack[-1] != name:
            self.problems.append(f"</{name}> closes {self.stack[-1:] or ['nothing']}")
            return
        self.stack.pop()


def parses(markup: str) -> Balanced:
    checker = Balanced()
    checker.feed(markup)
    return checker


def frame(name, duration=None, depth=0, cpu=0, marker=None, children=()):
    one = Frame(name=name, cpu=cpu, depth=depth, line=1, duration_us=duration, marker=marker)
    for child in children:
        child.parent = one
        one.children.append(child)
    return one


def tree() -> Frame:
    """A parent that took ten microseconds, with two children that took two and six."""
    return frame(
        "outer",
        10.0,
        children=[frame("first", 2.0, depth=1), frame("second", 6.0, depth=1)],
    )


@pytest.fixture(scope="module")
def tiny():
    return btf.parse_file(FIXTURE)


@pytest.fixture(scope="module")
def captured():
    return function_graph.parse(TRACE.read_text(encoding="utf-8"), source=str(TRACE))


def every_widget(tiny, captured) -> list[Widget]:
    gate = PredictionGate("Which one?", options=["yes", "no"], answer="a", why="Because.")
    return [
        SyscallTape(captured),
        SyscallTape(Tape()),
        StructMap(tiny.layout("demo_task")),
        StructMap(tiny.layout("demo_value")),
        OpsExplorer(tiny.ops("demo_ops")),
        gate,
        gate.check("b"),
    ]


# -- the promise every widget makes ------------------------------------------------------------


def test_no_widget_emits_a_script_or_a_style_block(tiny, captured):
    """The whole design rests on this. Inline styling only, and nothing that has to execute."""
    for one in every_widget(tiny, captured):
        drawn = one.html().lower()
        assert "<script" not in drawn
        assert "<style" not in drawn
        assert "javascript:" not in drawn
        assert "onclick" not in drawn


def test_every_widget_produces_html_that_opens_and_closes(tiny, captured):
    for one in every_widget(tiny, captured):
        checker = parses(one.html())
        assert checker.problems == [], f"{type(one).__name__}: {checker.problems}"
        assert checker.stack == [], f"{type(one).__name__} left {checker.stack} open"


def test_every_widget_also_draws_itself_as_text(tiny, captured):
    """The version a screen reader gets, and the version a test can assert on."""
    for one in every_widget(tiny, captured):
        assert one.text().strip() != ""
        assert str(one) == one.text()


def test_every_widget_puts_its_text_version_in_the_output_too(tiny, captured):
    for one in every_widget(tiny, captured):
        assert "The same thing as text" in one.html()


def test_the_base_class_refuses_to_draw_nothing():
    with pytest.raises(NotImplementedError):
        Widget().html()
    with pytest.raises(NotImplementedError):
        Widget().text()


def test_a_widget_saves_itself_as_a_whole_page(tmp_path, tiny):
    out = StructMap(tiny.layout("demo_task")).save(tmp_path / "one.html")
    written = out.read_text(encoding="utf-8")
    assert written.startswith("<!doctype html>")
    assert "demo_task" in written


# -- the html helpers ---------------------------------------------------------------------------


def test_text_in_the_body_is_escaped():
    assert text("<b>") == "&lt;b&gt;"


def test_text_in_an_attribute_escapes_the_quotes_too():
    assert attribute('say "hi"') == "say &quot;hi&quot;"


def test_a_style_declaration_turns_underscores_into_hyphens():
    assert style(font_size="11px") == "font-size:11px"


def test_a_style_declaration_that_is_none_is_left_out():
    """So a caller can pass a border that is only sometimes there without an if around it."""
    assert style(border=None, color="red") == "color:red"


def test_a_tag_with_nothing_on_it_is_just_a_tag():
    assert tag("div") == "<div></div>"


def test_a_tag_escapes_what_goes_in_its_attributes():
    """A quote that got through would end the attribute early and break the rest of the tag."""
    assert tag("div", title='a "quoted" thing') == '<div title="a &quot;quoted&quot; thing"></div>'


def test_a_fold_is_closed_unless_it_is_asked_not_to_be():
    assert details("more", "body").startswith("<details>")
    assert details("more", "body", open_=True).startswith("<details open>")


def test_a_card_without_a_fallback_has_no_fold_in_it():
    assert "The same thing as text" not in card("title", "", "body")


def test_a_page_is_a_whole_document():
    written = page("title", "<p>body</p>")
    assert written.startswith("<!doctype html>")
    assert parses(written).problems == []


# -- SyscallTape ------------------------------------------------------------------------------


def test_a_child_gets_the_share_of_the_width_that_it_took_of_the_time():
    spans = place(tree())
    assert spans[1].width == pytest.approx(20.0)
    assert spans[2].width == pytest.approx(60.0)


def test_children_are_laid_out_from_the_left_in_call_order():
    spans = place(tree())
    assert spans[1].left == pytest.approx(0.0)
    assert spans[2].left == pytest.approx(20.0)


def test_the_gap_at_the_end_is_the_time_the_parent_spent_in_itself():
    """Two of ten microseconds are unaccounted for, so twenty percent is left blank."""
    spans = place(tree())
    used = spans[1].width + spans[2].width
    assert used == pytest.approx(80.0)


def test_a_child_with_no_duration_makes_the_whole_group_equal_width():
    parent = frame("outer", 10.0, children=[frame("a", 2.0, depth=1), frame("b", None, depth=1)])
    spans = place(parent)
    assert spans[1].width == pytest.approx(50.0)
    assert spans[2].width == pytest.approx(50.0)


def test_a_box_placed_by_counting_is_marked_as_such():
    parent = frame("outer", 10.0, children=[frame("a", None, depth=1)])
    assert place(parent)[1].to_scale is False


def test_children_that_add_up_to_more_than_their_parent_are_not_drawn_to_scale():
    """Impossible, so something is wrong with the numbers, and a picture would be a lie."""
    parent = frame("outer", 1.0, children=[frame("a", 5.0, depth=1), frame("b", 5.0, depth=1)])
    assert place(parent)[1].to_scale is False


def test_rounding_in_the_kernel_does_not_count_as_impossible():
    """Durations come out rounded to three decimals, so children can just about overshoot."""
    parent = frame("outer", 10.0, children=[frame("a", 5.001, depth=1), frame("b", 5.0, depth=1)])
    assert place(parent)[1].to_scale is True


def test_a_parent_placed_by_counting_keeps_its_children_that_way_too():
    """Once the scale is gone it does not come back, and every box below says so."""
    deep = frame("c", 1.0, depth=2)
    middle = frame("b", None, depth=1, children=[deep])
    spans = place(frame("a", 10.0, children=[middle]))
    assert [one.to_scale for one in spans] == [True, False, False]


def test_max_depth_counts_from_the_outermost_frame(captured):
    drawn = SyscallTape(captured, max_depth=2)
    assert max(one.frame.depth for one in drawn.spans()[0]) == 2


def test_a_tape_with_nothing_in_it_says_so_rather_than_drawing_an_empty_box():
    drawn = SyscallTape(Tape())
    assert "There is nothing in this tape" in drawn.html()
    assert drawn.text() == "no frames"


def test_one_frame_can_be_drawn_on_its_own():
    drawn = SyscallTape(tree())
    assert "outer on cpu 0" in drawn.html()
    assert len(drawn.spans()) == 1


def test_the_hover_text_carries_the_numbers_that_did_not_fit_in_the_box():
    drawn = SyscallTape(frame("slow", 120.0, marker="!")).html()
    assert "120.000 us" in drawn
    assert "over 100 us" in drawn


def test_a_frame_that_never_closed_says_so_on_hover():
    one = frame("cut", None)
    one.complete = False
    assert "never closed" in SyscallTape(one).html()


def test_the_footnote_says_that_position_is_not_a_clock(captured):
    assert "call order and not a clock" in SyscallTape(captured).html()


def test_the_footnote_only_mentions_red_outlines_when_there_are_some(captured):
    assert "red outline" not in SyscallTape(captured).html()
    assert "red outline" in SyscallTape(frame("a", 1.0, children=[frame("b", None, 1)])).html()


def test_the_subtitle_counts_the_lines_the_parser_did_not_understand():
    tape = Tape(roots=[frame("a", 1.0)], unparsed=[UnparsedLine(3, "?", "not a line")])
    assert "1 unparsed lines" in SyscallTape(tape).html()


def test_a_long_function_name_gets_cut_down_to_fit():
    long = "a_really_long_kernel_function_name_that_goes_on_and_on"
    assert "..." in SyscallTape(frame(long, 1.0)).html()


def test_the_text_version_of_a_tape_is_the_tree(captured):
    assert SyscallTape(captured).text() == captured.tree(None)


# -- StructMap ---------------------------------------------------------------------------------


def test_a_struct_is_cut_into_rows_of_the_asked_for_width(tiny):
    drawn = StructMap(tiny.layout("demo_task"), per_row=16)
    assert len(drawn.bands()) == 4


def test_a_field_that_crosses_a_row_boundary_is_drawn_in_both(tiny):
    """`comm` is sixteen bytes starting at eight, so it lands in two rows of sixteen."""
    drawn = StructMap(tiny.layout("demo_task"), per_row=16)
    rows = [band for band in drawn.bands() if any(s.label == "comm" for s in band.segments)]
    assert len(rows) == 2
    assert rows[1].segments[0].continued is True


def test_the_second_half_of_a_field_is_labelled_as_a_continuation(tiny):
    assert "..comm" in StructMap(tiny.layout("demo_task"), per_row=16).html()


def test_padding_is_drawn_and_is_not_mistaken_for_a_field(tiny):
    drawn = StructMap(tiny.layout("demo_task"))
    holes = [one for one in drawn.pieces() if "hole" in one.label]
    assert [one.length_bits for one in holes] == [6 * 8]
    assert "byte hole" in drawn.html()


def test_a_bitfield_is_drawn_narrower_than_a_byte(tiny):
    """Three flags in one byte are three slivers, not three bytes."""
    drawn = StructMap(tiny.layout("demo_flags"), per_row=1)
    widths = [one.length_bits for one in drawn.pieces()]
    assert widths == [1, 1, 6]


def test_a_union_is_drawn_one_field_to_a_row(tiny):
    drawn = StructMap(tiny.layout("demo_value"))
    assert drawn.is_union is True
    assert [band.label for band in drawn.bands()] == ["as_int", "as_ptr", "as_bytes"]


def test_a_union_says_why_it_is_drawn_that_way(tiny):
    assert (
        "every field of a union starts at offset 0" in StructMap(tiny.layout("demo_value")).html()
    )


def test_a_big_struct_is_cut_off_and_says_how_much_it_left_out(tiny):
    drawn = StructMap(tiny.layout("demo_pair"), per_row=16, max_bytes=32)
    assert len(drawn.bands()) == 2
    assert "Showing the first 32 bytes of 128" in drawn.html()


def test_a_struct_bigger_than_a_cache_line_gets_the_boundary_marked(tiny):
    drawn = StructMap(tiny.layout("demo_pair"), per_row=16)
    marked = [band.label for band in drawn.bands() if band.cache_line]
    assert marked == [str(CACHE_LINE)]
    assert "cache line boundary" in drawn.html()


def test_a_layout_with_no_size_falls_back_to_where_its_last_field_ends():
    layout = Layout(name="struct guess", size=None, pointer_size=8)
    layout.fields.append(Field(path="only", type_name="int", byte_offset=0, bit_offset=0, size=4))
    assert StructMap(layout).shown_bytes == 4
    assert "unknown size" in StructMap(layout).html()


def test_a_field_whose_size_is_unknown_is_left_out_of_the_drawing():
    """A pointer to a function has no size in BTF, and drawing it as zero bytes would be a lie."""
    layout = Layout(name="struct partial", size=8, pointer_size=8)
    layout.fields.append(
        Field(path="mystery", type_name="void ()", byte_offset=0, bit_offset=0, size=None)
    )
    assert StructMap(layout).pieces() == []


def test_the_pointer_size_is_written_down_because_the_file_does_not_record_one(tiny):
    assert "8 byte pointers" in StructMap(tiny.layout("demo_task")).html()
    narrow = btf.parse_file(FIXTURE, pointer_size=4)
    assert "4 byte pointers" in StructMap(narrow.layout("demo_task")).html()


def test_the_hover_text_on_a_hole_says_what_it_comes_after(tiny):
    assert "after waiting" in StructMap(tiny.layout("demo_task")).html()


def test_the_text_version_of_a_struct_is_the_pahole_style_table(tiny):
    layout = tiny.layout("demo_task")
    assert StructMap(layout).text() == layout.table()


# -- OpsExplorer -------------------------------------------------------------------------------


def test_every_slot_gets_a_row(tiny):
    drawn = OpsExplorer(tiny.ops("demo_ops"))
    for name in ("open", "write", "release"):
        assert name in drawn.html()


def test_an_empty_slot_is_drawn_as_empty(tiny):
    assert ">empty<" in OpsExplorer(tiny.ops("demo_ops")).html()


def test_a_filled_slot_names_what_is_in_it(tiny):
    table = tiny.ops("demo_ops").with_implementations({"open": "demo_shmem_open"})
    assert "demo_shmem_open" in OpsExplorer(table).html()


def test_only_the_filled_slots_can_be_asked_for(tiny):
    table = tiny.ops("demo_ops").with_implementations({"open": "demo_shmem_open"})
    assert [one.name for one in OpsExplorer(table, only_filled=True).rows] == ["open"]


def test_an_instance_is_named_in_the_title(tiny):
    table = tiny.ops("demo_ops", instance="demo_shmem_ops")
    assert "demo_shmem_ops, a struct demo_ops" in OpsExplorer(table).html()


def test_a_table_with_nothing_in_it_explains_itself(tiny):
    assert "No slots to show" in OpsExplorer(tiny.ops("demo_ops"), only_filled=True).html()


def test_an_unfilled_table_says_why_every_slot_is_empty(tiny):
    assert "nothing has read a live instance" in OpsExplorer(tiny.ops("demo_ops")).html()


def test_a_filled_table_explains_what_an_empty_slot_means_instead(tiny):
    table = tiny.ops("demo_ops").with_implementations({"open": "demo_shmem_open"})
    assert "falls back to whatever the caller does" in OpsExplorer(table).html()


def test_the_fields_that_are_not_operations_are_counted_in_the_subtitle(tiny):
    assert "1 fields that are not operations" in OpsExplorer(tiny.ops("demo_ops")).html()


def test_the_text_version_of_an_ops_table_is_the_slot_table():
    table = OpsTable("struct demo", [Slot("open", "int (*open)(void)", 0)])
    assert OpsExplorer(table).text() == table.table()


# -- PredictionGate ----------------------------------------------------------------------------


def gate() -> PredictionGate:
    return PredictionGate(
        "How many calls?",
        options={"a": "about ten", "b": "about a hundred"},
        answer="b",
        why="A cached write is about a hundred calls deep.",
    )


def test_the_right_answer_comes_back_right():
    assert gate().check("b").correct is True


def test_the_wrong_answer_comes_back_wrong_and_still_gets_the_explanation():
    verdict = gate().check("a")
    assert verdict.correct is False
    assert "hundred calls deep" in verdict.html()


def test_case_and_space_do_not_count():
    assert gate().check("  B ").correct is True


def test_the_verdict_says_what_you_said_and_what_the_answer_was():
    drawn = gate().check("a").html()
    assert "You said: about ten" in drawn
    assert "The answer is: about a hundred" in drawn


def test_options_given_as_a_list_get_letters():
    asked = PredictionGate("Which?", options=["first", "second"], answer="b", why="Because.")
    assert asked.options == {"a": "first", "b": "second"}


def test_an_answer_that_is_not_one_of_the_options_is_refused():
    with pytest.raises(KeyError, match="not one of the options"):
        PredictionGate("Which?", options=["first"], answer="z", why="Because.")


def test_a_question_with_no_options_is_a_free_text_one():
    asked = PredictionGate("Name the outermost function.", answer="ksys_write", why="It is.")
    assert "picking from a list is not the same" in asked.html()
    assert asked.check("ksys_write").correct is True


def test_the_answer_is_behind_a_fold_and_the_question_is_not():
    drawn = gate().html()
    before, _, after = drawn.partition("<details>")
    assert "How many calls?" in before
    assert "about a hundred" in after


def test_the_gate_says_out_loud_that_it_is_a_speed_bump_and_not_a_lock():
    assert "A prediction you got wrong is a thing you remember" in gate().html()


def test_the_text_version_of_a_gate_has_the_question_the_options_and_the_answer():
    written = gate().text()
    assert "How many calls?" in written
    assert "a  about ten" in written
    assert "answer: b" in written


def test_the_text_version_of_a_verdict_says_which_way_it_went():
    assert "verdict:        right" in gate().check("b").text()
    assert "verdict:        not this one" in gate().check("a").text()
