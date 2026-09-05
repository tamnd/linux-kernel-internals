"""Tests for reading a recorded session back.

Two kinds of test in here, and the split is the point.

Most of them run against casts written out in the test, because the interesting cases are the ugly
ones and a real recording will not oblige by containing all of them. A shell too old to print the
mark that says a command started. A recording with no marks at all. A build log full of carriage
returns. A step that never finished because the recorder was killed.

The rest run against the committed recording, which is a real kernel build on a real machine, and
they are the ones that would catch this whole file being right about a format nobody uses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kxray import replay
from kxray.replay import cast as castmod
from kxray.replay import terminal
from kxray.replay.session import steps_of
from kxwidgets import SessionPlayer

ROOT = Path(__file__).resolve().parents[1]
RECORDING = ROOT / "corpora" / "replays" / "tier1" / "build-and-boot-uml.cast"

A = "\x1b]133;A\x07"
B = "\x1b]133;B\x07"
C = "\x1b]133;C\x07"


def D(code: int = 0) -> str:
    return f"\x1b]133;D;{code}\x07"


def cast_of(*moments: tuple[float, str], width: int = 100, title: str = "") -> str:
    """A cast file as text, from a list of when-and-what pairs."""
    header = {"version": 2, "width": width, "height": 30, "timestamp": 0}
    if title:
        header["title"] = title
    rows = [json.dumps(header)]
    rows += [json.dumps([when, "o", what]) for when, what in moments]
    return "\n".join(rows) + "\n"


def session_of(*moments: tuple[float, str], title: str = ""):
    return replay.of(castmod.parse(cast_of(*moments, title=title), source="<test>"))


# -- reading the file ----------------------------------------------------------------------------


def test_every_line_of_a_cast_is_accounted_for():
    text = cast_of((0.0, "hello"), (1.0, "world"))
    one = castmod.parse(text)
    assert one.lines.read == 3  # the header and the two moments
    assert one.lines.total == len(text.rstrip("\n").split("\n"))


def test_input_moments_are_skipped_rather_than_read_or_dropped_quietly():
    """asciinema records keystrokes too, and counting them would print every command twice."""
    text = cast_of((0.0, "ls\r\n"))
    text += json.dumps([0.5, "i", "ls\r"]) + "\n"
    one = castmod.parse(text)
    assert one.lines.skipped == 1
    assert one.lines.unparsed == 0
    assert one.text == "ls\r\n"


def test_a_line_that_is_not_a_moment_is_unparsed_rather_than_ignored():
    text = cast_of((0.0, "ok")) + "not json at all\n"
    assert castmod.parse(text).lines.unparsed == 1


def test_version_one_is_refused_rather_than_read_as_if_it_were_version_two():
    with pytest.raises(ValueError, match="asciinema v1"):
        castmod.parse('{"version": 1}\n', source="old.cast")


def test_a_file_that_does_not_start_with_a_header_says_so():
    with pytest.raises(ValueError, match="does not start with a header"):
        castmod.parse('[0.0, "o", "hi"]\n', source="headless.cast")


# -- what a terminal would have shown ------------------------------------------------------------


def test_a_carriage_return_draws_over_the_line_rather_than_starting_a_new_one():
    """This is the whole reason a build log cannot be read with `cat`."""
    assert terminal.render("  5%\r 40%\r100% done") == "100% done"


def test_colour_is_taken_out_because_a_lesson_shows_text():
    assert terminal.render("\x1b[32mCC\x1b[0m main.o") == "CC main.o"


def test_the_shell_marks_are_taken_out_too_since_they_are_not_meant_to_be_seen():
    assert terminal.render(f"{A}$ {B}ls{C}file{D()}") == "$ lsfile"


def test_a_tab_moves_to_the_next_multiple_of_eight():
    assert terminal.render("ab\tc") == "ab      c"


def test_a_tab_with_nothing_after_it_leaves_no_trailing_spaces():
    assert terminal.render("ab\t") == "ab"


def test_backspace_takes_one_character_back():
    assert terminal.render("cat\bp") == "cap"


def test_trailing_blank_lines_go_and_leading_ones_stay():
    assert terminal.lines("\nreal output\n\n\n") == ["", "real output"]


def test_a_line_wider_than_the_screen_carries_on_underneath_itself():
    assert terminal.lines("abcdefghij", 4) == ["abcd", "efgh", "ij"]


def test_with_no_width_given_nothing_wraps():
    assert terminal.lines("abcdefghij") == ["abcdefghij"]


def test_the_carriage_return_after_a_wrap_does_not_send_the_tail_onto_the_head():
    """The bug this width business exists for, in nine characters instead of a hundred.

    A shell echoing a command longer than the screen writes the character in the last column and
    then a carriage return, because the terminal has already moved down a line by itself. Read that
    with no right edge and `abcdefgh` comes back as `ghcdef`, which is not what anybody typed.
    """
    assert terminal.typed("abcdef\rgh", 6) == "abcdefgh"
    assert terminal.typed("abcdef\rgh") == "ghcdef"


def test_a_command_wraps_at_the_edge_of_the_screen_and_not_at_its_own_hundredth_character():
    """Two characters of prompt means the command has two characters less room, and it matters."""
    assert terminal.typed("abcd\ref", 6, terminal.column("$ ")) == "abcdef"


def test_the_column_typing_starts_in_is_the_width_of_the_prompt():
    assert terminal.column(f"{A}$ {B}") == 2


# -- cutting the stream into steps ----------------------------------------------------------------


def test_a_step_per_command_with_what_was_typed_and_what_came_back():
    one = session_of(
        (0.0, f"{A}$ {B}"),
        (0.1, f"uname -r{C}"),
        (0.2, f"6.8.0\r\n{D()}{A}$ {B}"),
        (0.3, f"false{C}"),
        (0.4, D(1)),
    )
    assert [step.command for step in one.steps] == ["uname -r", "false"]
    assert one.steps[0].rows == ["6.8.0"]
    assert one.steps[0].worked
    assert not one.steps[1].worked
    assert one.steps[1].exit_code == 1


def test_a_command_that_prints_nothing_still_took_the_time_it_took():
    """The trap that made every `sleep` in an early run of this look instant.

    The clock cannot start at the first byte of output, because a command that produces no output
    has no first byte, and one that produces its output at the end has it at the end. It starts at
    the mark that says the command began.
    """
    one = session_of(
        (0.0, f"{A}$ {B}"),
        (0.1, f"sleep 10{C}"),
        (10.2, D()),
    )
    assert one.steps[0].seconds == pytest.approx(10.1, abs=0.01)
    assert one.steps[0].took == "10.1s"


def test_a_shell_too_old_to_print_the_started_mark_is_still_read():
    """Bash has only printed that mark since 4.4, and the machine this was written on has 3.2."""
    one = session_of(
        (0.0, f"{A}$ {B}"),
        (0.1, "echo hi\r\n"),
        (0.2, f"hi\r\n{D()}"),
    )
    assert one.steps[0].command == "echo hi"
    assert one.steps[0].rows == ["hi"]
    assert one.steps[0].seconds == pytest.approx(0.1, abs=0.01)


def test_a_cast_with_no_marks_is_one_step_and_says_so_rather_than_guessing():
    """Looking for a dollar sign would find the ones inside a build log."""
    one = session_of((0.0, "$ make\r\n"), (1.0, "  CC init/main.o\r\n"))
    assert len(one.steps) == 1
    assert one.steps[0].command == ""
    assert not one.marked
    assert "one step rather than a walkthrough" in one.alt()


def test_a_step_the_recording_stops_in_the_middle_of_is_marked_incomplete():
    """The same thing `Frame.complete` says about a call the tracer window cut off."""
    one = session_of((0.0, f"{A}$ {B}"), (0.1, f"make{C}"), (0.2, "  CC init/main.o\r\n"))
    assert not one.steps[0].complete
    assert one.steps[0].status == "never finished"
    assert not one.steps[0].worked


def test_a_status_that_is_not_a_number_is_unknown_rather_than_zero():
    one = session_of((0.0, f"{A}$ {B}"), (0.1, f"x{C}"), (0.2, "\x1b]133;D\x07"))
    assert one.steps[0].exit_code is None
    assert one.steps[0].status == "status not recorded"
    assert not one.steps[0].worked


def test_the_marks_are_read_with_a_string_terminator_as_well_as_with_a_bell():
    """Both endings are legal and different shells pick different ones."""
    stepped = steps_of(
        castmod.parse(
            cast_of(
                (0.0, "\x1b]133;A\x1b\\$ \x1b]133;B\x1b\\"),
                (0.1, "id\x1b]133;C\x1b\\"),
                (0.2, "uid=0\r\n\x1b]133;D;0\x1b\\"),
            )
        )
    )
    assert [one.command for one in stepped] == ["id"]
    assert stepped[0].exit_code == 0


# -- how a session describes itself ---------------------------------------------------------------


def test_the_summary_names_the_step_that_ate_the_time():
    one = session_of(
        (0.0, f"{A}$ {B}"),
        (0.1, f"tar xf linux.tar.xz{C}"),
        (1.0, f"{D()}{A}$ {B}"),
        (1.1, f"make -j8{C}"),
        (601.1, D()),
        title="building a kernel",
    )
    assert "the longest being 'make -j8'" in one.alt()
    assert "10m 0s" in one.alt()
    assert "all successful" in one.alt()


def test_a_failure_is_counted_in_the_summary_rather_than_left_to_be_noticed():
    one = session_of((0.0, f"{A}$ {B}"), (0.1, f"false{C}"), (0.2, D(1)))
    assert "1 of them did not report success" in one.alt()
    assert one.failures[0].number == 0


def test_the_table_has_a_row_per_step_and_a_header():
    one = session_of(
        (0.0, f"{A}$ {B}"),
        (0.1, f"pwd{C}"),
        (0.2, f"/root\r\n{D()}{A}$ {B}"),
        (0.3, f"id{C}"),
        (0.4, D()),
    )
    rows = one.table().splitlines()
    assert rows[0].split() == ["#", "took", "status", "out", "command"]
    assert len(rows) == 4


def test_the_transcript_carries_the_output_and_the_note():
    one = replay.of(
        castmod.parse(
            cast_of((0.0, f"{A}$ {B}"), (0.1, f"uname{C}"), (0.2, f"Linux\r\n{D()}")),
            source="<test>",
        ),
        notes={0: "This is the machine the recording came off."},
    )
    written = one.transcript()
    assert "## 0. uname" in written
    assert "This is the machine the recording came off." in written
    assert "Linux" in written


# -- the widget ------------------------------------------------------------------------------------


def test_the_strip_is_as_wide_as_the_time_each_step_took():
    one = session_of(
        (0.0, f"{A}$ {B}"),
        (0.1, f"quick{C}"),
        (1.1, f"{D()}{A}$ {B}"),
        (1.2, f"slow{C}"),
        (10.1, D()),
    )
    drawn = SessionPlayer(one)
    shares = drawn.shares()
    assert shares[1] > shares[0] * 8
    assert sum(shares) == pytest.approx(100)


def test_a_step_too_short_to_see_is_widened_and_the_widget_says_it_was():
    one = session_of(
        (0.0, f"{A}$ {B}"),
        (0.1, f"true{C}"),
        (0.101, f"{D()}{A}$ {B}"),
        (0.102, f"make{C}"),
        (600.0, D()),
    )
    drawn = SessionPlayer(one)
    assert not drawn.to_scale
    assert min(drawn.shares()) >= 0.5
    assert "not quite to scale" in drawn._footnote()


def test_long_output_is_cut_in_the_middle_and_the_cut_says_how_much_it_took():
    body = "".join(f"  CC file{i}.o\r\n" for i in range(500))
    one = session_of((0.0, f"{A}$ {B}"), (0.1, f"make{C}"), (0.2, f"{body}{D()}"))
    drawn = SessionPlayer(one, head=2, tail=3)
    shown = drawn.rows(one.steps[0])
    assert shown[:2] == ["  CC file0.o", "  CC file1.o"]
    assert shown[2] == "... 495 lines not shown ..."
    assert shown[-1] == "  CC file499.o"


def test_short_output_is_not_cut_at_all():
    one = session_of((0.0, f"{A}$ {B}"), (0.1, f"id{C}"), (0.2, f"uid=0\r\n{D()}"))
    drawn = SessionPlayer(one, head=2, tail=3)
    assert drawn.rows(one.steps[0]) == ["uid=0"]


def test_the_widget_draws_itself_as_text_as_well_as_html():
    one = session_of((0.0, f"{A}$ {B}"), (0.1, f"id{C}"), (0.2, f"uid=0\r\n{D()}"))
    drawn = SessionPlayer(one)
    assert "id" in drawn.text()
    assert "<div" in drawn.html()
    assert "The same thing as text" in drawn.html()


def test_no_widget_in_this_package_ships_javascript_and_this_one_does_not_either():
    one = session_of((0.0, f"{A}$ {B}"), (0.1, f"id{C}"), (0.2, f"uid=0\r\n{D()}"))
    drawn = SessionPlayer(one).html()
    assert "<script" not in drawn
    assert "onclick" not in drawn


# -- the committed recording ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def recorded():
    return replay.load(RECORDING)


def test_the_committed_recording_reads_with_nothing_unparsed(recorded):
    assert recorded.cast.lines.unparsed == 0
    assert recorded.cast.lines.total == len(RECORDING.read_text().rstrip("\n").split("\n"))


def test_every_step_of_the_committed_recording_worked(recorded):
    """A recording of a session that failed would be a fine thing to ship, but not as this one."""
    assert [one for one in recorded.steps if not one.worked] == []


def test_the_committed_recording_builds_and_then_boots_a_kernel(recorded):
    commands = " ".join(one.command for one in recorded.steps)
    assert "tar xf" in commands
    assert "make ARCH=um" in commands
    assert "./linux" in commands


def test_the_recording_ends_on_the_boot_and_not_on_the_shell_being_shut_down(recorded):
    """Closing the shell is housekeeping, and a walkthrough should not end on a step about it."""
    assert recorded.steps[-1].command.startswith("./linux")
    assert all(one.complete for one in recorded.steps)


def test_the_long_command_in_the_recording_survived_the_edge_of_the_screen(recorded):
    """The one command in here that is wider than the terminal was, read back in one piece."""
    long = max(recorded.steps, key=lambda one: len(one.command))
    assert len(long.command) > recorded.cast.width
    assert long.command.endswith("libssl-dev libelf-dev xz-utils")


def test_the_build_is_the_step_that_took_the_time(recorded):
    """The claim the widget is built around, checked against the recording it is built around."""
    slow = recorded.slowest()
    assert "make ARCH=um -j" in slow.command
    assert slow.seconds > sum(one.seconds for one in recorded.steps if one is not slow)


def test_the_booted_kernel_says_it_is_the_pinned_version(recorded):
    """The point of the whole session. The kernel that answered is the one that was built."""
    boot = next(one for one in recorded.steps if one.command.startswith("./linux"))
    assert "Linux version 7.2.2" in "\n".join(boot.rows)
