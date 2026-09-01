"""Tests for the function_graph parser.

Two kinds of test here. The corpus tests check the parser against the committed artefacts and
against the numbers recorded in their `.meta.toml`, which is what stops a kernel bump or a parser
change from quietly altering what a lesson shows. The rest are small strings that pin one
behaviour each.
"""

import tomllib
from pathlib import Path

import pytest

from kxray.models import Comment, InterruptEntry, InterruptExit, TaskSwitch
from kxray.trace import parse, parse_file

CORPUS = Path(__file__).resolve().parents[1] / "corpora" / "traces" / "handwritten"
ARTEFACTS = sorted(CORPUS.glob("*.txt"))


def header(*rows: str) -> str:
    return "# tracer: function_graph\n#\n" + "\n".join(rows) + "\n"


def test_the_corpus_is_not_empty():
    assert ARTEFACTS, f"no trace artefacts found under {CORPUS}"


@pytest.mark.parametrize("artefact", ARTEFACTS, ids=lambda p: p.stem)
def test_artefact_matches_its_metadata(artefact):
    meta = tomllib.loads(artefact.with_suffix(".meta.toml").read_text())
    tape = parse_file(artefact)

    # The unparsed count is the important one. It is allowed to be non zero, and it is not
    # allowed to change without somebody saying why in a commit message.
    assert len(tape.unparsed) == meta["unparsed_lines"], [(u.line, u.reason) for u in tape.unparsed]
    assert tape.tracer == meta["tracer"]
    assert tape.frame_count == meta["frames"]
    assert len(tape.roots) == meta["roots"]
    assert tape.max_depth == meta["max_depth"]
    assert tape.cpus == meta["cpus"]


@pytest.mark.parametrize("artefact", ARTEFACTS, ids=lambda p: p.stem)
def test_handwritten_artefacts_are_not_evidence(artefact):
    # Nothing in this directory came off a real kernel, so nothing in it can back a claim.
    meta = tomllib.loads(artefact.with_suffix(".meta.toml").read_text())
    assert meta["source"] == "handwritten"
    assert meta["evidence"] is False


def test_the_write_path_comes_out_as_a_tree():
    tape = parse_file(CORPUS / "write-1byte.txt")
    root = tape.roots[0]

    assert root.name == "ksys_write"
    assert root.duration_us == 17.032
    assert root.marker == "+"
    assert [c.name for c in root.children] == ["fdget_pos", "vfs_write"]

    alloc = tape.find("shmem_alloc_folio")[0]
    assert alloc.path() == [
        "ksys_write",
        "vfs_write",
        "new_sync_write",
        "shmem_file_write_iter",
        "generic_perform_write",
        "shmem_write_begin",
        "shmem_get_folio_gfp",
        "shmem_alloc_folio",
    ]
    assert alloc.is_leaf


def test_self_time_excludes_the_children():
    tape = parse_file(CORPUS / "write-1byte.txt")
    root = tape.roots[0]
    # 17.032 total, 0.418 in fdget_pos and 16.157 in vfs_write.
    assert root.self_time_us == 0.457


def test_the_task_column_is_read_when_funcgraph_proc_is_on():
    tape = parse_file(CORPUS / "page-fault.txt")
    assert tape.roots[0].task == "stress-ng-2411"
    assert tape.roots[2].task == "swapper/1-0"


def test_interrupts_comments_and_switches_become_events():
    tape = parse_file(CORPUS / "page-fault.txt")
    kinds = [type(e) for e in tape.events]
    assert kinds == [Comment, InterruptEntry, InterruptExit, TaskSwitch]
    assert tape.touched_interrupt_context

    switch = tape.events[-1]
    assert switch.previous == "stress-ng-2411"
    assert switch.following == "swapper/1-0"


def test_a_frame_cut_off_by_the_end_of_the_buffer_is_marked_incomplete():
    tape = parse_file(CORPUS / "page-fault.txt")
    last = tape.roots[-1]
    assert last.name == "schedule_idle"
    assert last.complete is False
    assert last.duration_us is None
    assert last.self_time_us is None


def test_depth_is_tracked_per_cpu():
    # Two CPUs interleaved. One stack for the trace would nest these inside each other, which
    # looks fine and is nonsense.
    text = header(
        " 0)               |  vfs_write() {",
        " 1)               |  handle_mm_fault() {",
        " 0)   0.101 us    |    security_file_permission();",
        " 1)   8.221 us    |    do_anonymous_page();",
        " 1) + 10.346 us   |  }",
        " 0) + 16.157 us   |  }",
    )
    tape = parse(text)
    assert len(tape.roots) == 2
    assert [r.name for r in tape.roots] == ["vfs_write", "handle_mm_fault"]
    assert [c.name for c in tape.roots[0].children] == ["security_file_permission"]
    assert [c.name for c in tape.roots[1].children] == ["do_anonymous_page"]
    assert tape.cpus == [0, 1]


def test_slowness_markers_are_kept():
    text = header(
        " 0)   0.101 us    |  a();",
        " 0) + 16.157 us   |  b();",
        " 0) ! 123.400 us  |  c();",
        " 0) $ 2000000.000 us |  d();",
    )
    tape = parse(text)
    assert [(f.name, f.marker) for f in tape.walk()] == [
        ("a", None),
        ("b", "+"),
        ("c", "!"),
        ("d", "$"),
    ]


def test_funcgraph_tail_names_the_closing_brace():
    text = header(
        " 0)               |  vfs_write() {",
        " 0)   0.101 us    |    security_file_permission();",
        " 0) + 16.157 us   |  } /* vfs_write */",
    )
    tape = parse(text)
    assert tape.unparsed == []
    assert tape.roots[0].duration_us == 16.157


def test_a_closing_brace_that_names_the_wrong_function_is_reported():
    text = header(
        " 0)               |  vfs_write() {",
        " 0) + 16.157 us   |  } /* ksys_write */",
    )
    tape = parse(text)
    assert len(tape.unparsed) == 1
    assert "ksys_write" in tape.unparsed[0].reason


def test_funcgraph_args_does_not_break_the_name():
    text = header(
        " 0)               |  vfs_write(file=0xffff888003a0e000, count=1) {",
        " 0)   0.101 us    |    security_file_permission(file=0xffff888003a0e000);",
        " 0) + 16.157 us   |  }",
    )
    tape = parse(text)
    assert [f.name for f in tape.walk()] == ["vfs_write", "security_file_permission"]


def test_a_line_nobody_understands_does_not_stop_the_parse():
    text = header(
        " 0)               |  vfs_write() {",
        " 0)   what even is this",
        " 0)   0.101 us    |    security_file_permission();",
        " 0) + 16.157 us   |  }",
    )
    tape = parse(text)
    assert len(tape.unparsed) == 1
    assert tape.unparsed[0].line == 4
    assert tape.roots[0].name == "vfs_write"
    assert tape.roots[0].duration_us == 16.157


def test_a_closing_brace_with_nothing_open_is_reported_not_raised():
    tape = parse(header(" 0)   0.418 us    |  }"))
    assert len(tape.unparsed) == 1
    assert "no matching call" in tape.unparsed[0].reason
    assert tape.roots == []


def test_an_empty_trace_parses_to_an_empty_tape():
    tape = parse("# tracer: function_graph\n#\n")
    assert tape.roots == []
    assert tape.unparsed == []
    assert tape.frame_count == 0
    assert tape.total_duration_us == 0.0
