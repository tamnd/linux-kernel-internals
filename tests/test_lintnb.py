"""Tests for the notebook contract.

Every rule is tested twice: once on a cell that breaks it, and once on the cell somebody would
write instead. The second half is the half that matters. A rule with no test for the shape it is
supposed to allow gets switched off the first week it is wrong about somebody's correct cell, and
switching it off is a one line diff nobody argues with.
"""

from __future__ import annotations

import json

import pytest

from tools import lintnb

SETUP = """import sys
from pathlib import Path
%pip install --quiet kxray
import kxray"""

CAPTION = "A caption long enough to be a line of prose about this cell."


def cell(source: str, *, kind: str = "code", note: str = CAPTION, identifier: str = "x-01") -> dict:
    return {
        "cell_type": kind,
        "id": identifier,
        "metadata": {"id": identifier, "note": note},
        "source": source.splitlines(keepends=True),
    }


def notebook(path, *cells: dict, banner: bool = True) -> object:
    """A notebook on disk, with the setup and banner cells in front unless a test says otherwise."""
    front = [cell(SETUP, identifier="x-setup")]
    if banner:
        front.append(cell("kxray.banner()", identifier="x-banner"))
    target = path / "one.ipynb"
    target.write_text(
        json.dumps({"cells": [*front, *cells], "nbformat": 4, "nbformat_minor": 5}),
        encoding="utf-8",
    )
    return target


def problems(path, *cells: dict, banner: bool = True) -> list[str]:
    return [str(one) for one in lintnb.check(notebook(path, *cells, banner=banner))]


def rules(found: list[str]) -> set[str]:
    return {one.split(": ")[-2] for one in found}


# --- the lessons in the repository ------------------------------------------------------------


@pytest.mark.parametrize("path", lintnb.notebooks(), ids=lambda p: p.parent.name)
def test_every_lesson_keeps_the_contract(path):
    assert lintnb.check(path) == []


def test_there_are_lessons_to_check():
    # Otherwise the sweep above passes by checking nothing, which is the quietest way for a
    # parametrised test to stop meaning anything.
    assert len(lintnb.notebooks()) == 3


def test_the_checker_exits_zero_on_the_repository():
    assert lintnb.main([]) == 0


def test_asking_for_one_lesson_checks_only_that_one():
    assert lintnb.main(["Z02"]) == 0


def test_asking_for_a_lesson_that_is_not_there_says_so():
    assert lintnb.main(["Q99"]) == 1


def test_the_rules_can_be_printed():
    assert lintnb.main(["--rules"]) == 0


def test_there_are_seven_rules():
    assert len(lintnb.RULES) == 7


# --- rule 1, the banner -----------------------------------------------------------------------


def test_a_notebook_with_no_banner_is_refused(tmp_path):
    found = problems(tmp_path, cell("print('hello')"), banner=False)
    assert rules(found) == {"banner"}


def test_a_banner_after_the_first_real_cell_is_refused(tmp_path):
    found = problems(
        tmp_path,
        cell("print('hello')", identifier="x-02"),
        cell("kxray.banner()", identifier="x-03"),
        banner=False,
    )
    assert "x-02 runs before the banner in x-03" in found[0]


def test_two_banners_are_refused(tmp_path):
    found = problems(tmp_path, cell("kxray.banner()", identifier="x-02"))
    assert "more than one banner cell" in found[0]


def test_a_banner_straight_after_the_setup_cell_is_what_is_wanted(tmp_path):
    assert problems(tmp_path, cell("print('hello')")) == []


def test_the_setup_cell_does_not_count_as_a_cell_that_runs_first():
    # It has to run before the banner, because there is nothing to print a banner with until it
    # has. That is why the rule knows what a setup cell looks like.
    assert lintnb.Cell("x", "code", SETUP, CAPTION).looks_like_setup


def test_an_ordinary_cell_is_not_a_setup_cell():
    assert not lintnb.Cell("x", "code", "print('hello')", CAPTION).looks_like_setup


def test_a_banner_first_with_no_setup_cell_at_all_is_fine(tmp_path):
    # A lesson that needs nothing installed is allowed, and then the banner is simply first.
    target = tmp_path / "one.ipynb"
    target.write_text(
        json.dumps(
            {
                "cells": [cell("kxray.banner()", identifier="x-01"), cell("print(1)")],
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )
    assert lintnb.check(target) == []


# --- rule 2, what a browser can finish ---------------------------------------------------------


def test_sleeping_is_refused(tmp_path):
    found = problems(tmp_path, cell("import time\ntime.sleep(30)"))
    assert rules(found) == {"timeout"}
    assert "sleeping looks exactly like hanging" in found[0]


def test_waiting_for_typing_is_refused(tmp_path):
    found = problems(tmp_path, cell("name = input('your name? ')"))
    assert rules(found) == {"timeout"}


def test_a_subprocess_with_no_timeout_is_refused(tmp_path):
    found = problems(tmp_path, cell("subprocess.run(['dmesg'], capture_output=True)"))
    assert "no timeout" in found[0]


def test_a_subprocess_with_a_timeout_is_fine(tmp_path):
    assert problems(tmp_path, cell("subprocess.run(['dmesg'], timeout=10)")) == []


def test_installing_outside_the_setup_cell_is_refused(tmp_path):
    found = problems(tmp_path, cell("%pip install pandas\nimport pandas"))
    assert rules(found) == {"timeout"}


def test_installing_inside_the_setup_cell_is_the_whole_point_of_it(tmp_path):
    assert problems(tmp_path) == []


# --- rule 3, captions -------------------------------------------------------------------------


def test_a_cell_with_no_note_is_refused(tmp_path):
    found = problems(tmp_path, cell("print('hello')", note=""))
    assert "no note in the builder" in found[0]


def test_a_note_that_is_not_a_line_is_refused(tmp_path):
    found = problems(tmp_path, cell("print('hello')", note="counts them"))
    assert "which is not a line" in found[0]


def test_a_note_over_two_lines_is_refused(tmp_path):
    note = "The first line of the caption, long enough.\nAnd a second line after it."
    found = problems(tmp_path, cell("print('hello')", note=note))
    assert "runs to more than one line" in found[0]


def test_a_note_that_is_one_good_line_is_accepted(tmp_path):
    assert problems(tmp_path, cell("print('hello')")) == []


# --- rule 4, widgets --------------------------------------------------------------------------


def test_printing_a_parsed_tape_is_refused(tmp_path):
    found = problems(tmp_path, cell("tape = function_graph.parse(raw)\nprint(tape)"))
    assert "prints tape, and SyscallTape draws that" in found[0]


def test_printing_a_number_off_a_tape_is_fine(tmp_path):
    # There is no widget for an integer, and a lesson counting things should say the number.
    assert (
        problems(tmp_path, cell("tape = function_graph.parse(raw)\nprint(tape.frame_count)")) == []
    )


def test_printing_the_raw_text_a_parser_is_about_to_read_is_encouraged(tmp_path):
    assert problems(tmp_path, cell("raw = colab.corpus_text('traces/x.txt')\nprint(raw)")) == []


def test_handing_a_tape_to_a_widget_is_the_shape_that_is_wanted(tmp_path):
    assert problems(tmp_path, cell("tape = function_graph.parse(raw)\nSyscallTape(tape)")) == []


# --- rule 5, length ---------------------------------------------------------------------------


def test_a_notebook_over_the_cap_is_refused(tmp_path):
    extra = [cell("print(1)", identifier=f"x-{n:02d}") for n in range(lintnb.MAX_CODE_CELLS)]
    found = problems(tmp_path, *extra)
    assert "is two lessons" in found[0]


def test_a_notebook_at_the_cap_is_accepted(tmp_path):
    # Z02 sits exactly here, so the boundary is not hypothetical.
    extra = [cell("print(1)", identifier=f"x-{n:02d}") for n in range(lintnb.MAX_CODE_CELLS - 2)]
    assert problems(tmp_path, *extra) == []


def test_markdown_does_not_count_against_the_cap(tmp_path):
    prose = [
        cell("# a heading\n", kind="markdown", note="", identifier=f"m-{n:02d}") for n in range(40)
    ]
    assert problems(tmp_path, *prose) == []


# --- rule 6, evidence -------------------------------------------------------------------------


def test_opening_a_capture_by_path_is_refused(tmp_path):
    found = problems(tmp_path, cell("raw = open('corpora/traces/tier0/x.txt').read()"))
    assert "opens 'corpora/traces/tier0/x.txt' by path" in found[0]


def test_building_a_path_to_a_capture_is_refused(tmp_path):
    found = problems(tmp_path, cell("raw = Path('corpora/traces/tier0/x.txt').read_text()"))
    assert rules(found) == {"evidence"}


def test_naming_a_capture_as_a_label_is_not_opening_it(tmp_path):
    # Every lesson does this, so a rule that could not tell the two apart would be deleted.
    source = "tape = function_graph.parse(raw, source='corpora/traces/tier0/x.txt')"
    assert problems(tmp_path, cell(source)) == []


def test_the_corpus_helper_is_the_way_in(tmp_path):
    assert problems(tmp_path, cell("raw = colab.corpus_text('traces/tier0/x.txt')")) == []


# --- rule 7, scratch --------------------------------------------------------------------------


def test_writing_to_a_bare_relative_path_is_refused(tmp_path):
    found = problems(tmp_path, cell("Path('abba.c').write_text(source)"))
    assert "writes wherever the reader started Jupyter" in found[0]


def test_writing_under_the_scratch_directory_is_fine(tmp_path):
    assert problems(tmp_path, cell("(colab.scratch('C09') / 'abba.c').write_text(source)")) == []


def test_the_scratch_directory_can_be_given_a_name_first(tmp_path):
    # Which is what every cell actually does, rather than repeating the call.
    source = "here = colab.scratch('C09')\n(here / 'abba.c').write_text(source)"
    assert problems(tmp_path, cell(source)) == []


def test_making_a_directory_outside_the_scratch_is_refused(tmp_path):
    found = problems(tmp_path, cell("Path('build').mkdir()"))
    assert rules(found) == {"scratch"}


# --- reading notebooks ------------------------------------------------------------------------


def test_a_cell_that_is_not_python_is_skipped_by_the_rules_that_need_a_tree():
    # `%pip install` is IPython and Colab needs it, so a cell that will not parse is not a failure.
    assert lintnb.Cell("x", "code", "%pip install kxray", CAPTION).tree() is None


def test_a_cell_that_is_python_parses():
    assert lintnb.Cell("x", "code", "print(1)", CAPTION).tree() is not None


def test_a_cell_that_will_not_parse_is_still_held_to_the_caption_rule(tmp_path):
    found = problems(tmp_path, cell("%matplotlib inline", note=""))
    assert rules(found) == {"caption"}


def test_reading_a_notebook_gets_the_note_off_the_metadata(tmp_path):
    cells = lintnb.read(notebook(tmp_path, cell("print(1)")))
    assert cells[-1].note == CAPTION
