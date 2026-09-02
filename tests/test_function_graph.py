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

TRACES = Path(__file__).resolve().parents[1] / "corpora" / "traces"
CORPUS = TRACES / "handwritten"
TIER0 = TRACES / "tier0"
TIER1 = TRACES / "tier1"
ARTEFACTS = sorted(CORPUS.glob("*.txt"))
CAPTURES = sorted(TIER0.glob("*.txt"))
TIER1_CAPTURES = sorted(TIER1.glob("*.txt"))
EVERY = ARTEFACTS + CAPTURES + TIER1_CAPTURES


def header(*rows: str) -> str:
    return "# tracer: function_graph\n#\n" + "\n".join(rows) + "\n"


def test_the_corpus_is_not_empty():
    assert ARTEFACTS, f"no trace artefacts found under {CORPUS}"
    assert CAPTURES, f"no captures found under {TIER0}"
    assert TIER1_CAPTURES, f"no captures found under {TIER1}"


@pytest.mark.parametrize("artefact", EVERY, ids=lambda p: f"{p.parent.name}/{p.stem}")
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


@pytest.mark.parametrize("artefact", CAPTURES, ids=lambda p: p.stem)
def test_a_capture_says_which_machine_it_came_off(artefact):
    """A recording that does not say what produced it is a recording nobody can take again.

    The `setup` list matters more than it looks. Half of what a function_graph trace contains is
    decided before the tracer starts, by which functions were filtered in, and a capture without
    that list is a picture with no way to reproduce it.
    """
    meta = tomllib.loads(artefact.with_suffix(".meta.toml").read_text())
    assert meta["source"] == "tier0"
    assert meta["evidence"] is True
    for key in ("kernel", "arch", "profile", "captured", "command", "describes"):
        assert meta.get(key), f"{artefact.name} has no {key}"
    assert meta["setup"], "no setup, so nobody can take this again"
    # Tier 0 is an emulator with no real clock, and a duration off it means nothing.
    assert meta["timings_are_real"] is False


@pytest.mark.parametrize("artefact", TIER1_CAPTURES, ids=lambda p: p.stem)
def test_a_tier_1_capture_says_which_real_machine_it_came_off(artefact):
    """Tier 1 captures come off whatever machine somebody had, so the metadata carries more.

    A Tier 0 capture can say `profile = "A-full"` and everybody knows which kernel that is, because
    this repository built it. There is no such shorthand for a real machine, so the version, the
    distribution, the architecture and the CPU count are all written out.
    """
    meta = tomllib.loads(artefact.with_suffix(".meta.toml").read_text())
    assert meta["source"] == "tier1"
    assert meta["evidence"] is True
    for key in ("kernel", "distribution", "arch", "cpu_count", "captured", "command", "describes"):
        assert meta.get(key), f"{artefact.name} has no {key}"
    assert meta["setup"], "no setup, so nobody can take this again"
    # A real machine has a real clock, which is most of the reason to go to Tier 1 at all.
    assert meta["timings_are_real"] is True


def test_the_multi_cpu_capture_really_does_interleave():
    """This is claim Z02-03, tested rather than asserted.

    The file is only worth committing if two lines next to each other can come from two different
    call stacks. If a future recapture comes out neatly sorted by CPU it still parses, still has
    six CPUs in it, and shows nothing, so the interleaving itself is what gets checked.
    """
    tape = parse_file(TIER1 / "multi-cpu-write.txt")

    assert tape.cpus == [0, 1, 2, 3, 4, 5]

    # Frames in the order the lines appear in the file, which is the order a reader meets them.
    ordered = sorted(tape.walk(), key=lambda f: f.line)
    changes = sum(1 for a, b in zip(ordered, ordered[1:], strict=False) if a.cpu != b.cpu)
    assert changes > 20, f"only {changes} CPU changes, this capture shows nothing"

    # And the switches happen part way through a call rather than only between whole trees. A
    # nested frame is one that has a parent, so a change between two nested frames on different
    # CPUs is the case that breaks anybody reading indentation as if it belonged to the file.
    mid_tree = [
        (a, b)
        for a, b in zip(ordered, ordered[1:], strict=False)
        if a.cpu != b.cpu and a.parent is not None and b.parent is not None
    ]
    assert mid_tree, "every CPU change is between whole trees, so nothing is interleaved"


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


def test_a_function_from_a_loadable_module_keeps_its_name_and_records_the_module():
    """ftrace prints `name [module]()` for anything that came from a loadable module.

    Nothing in a Tier 0 trace has one, because the pinned kernel has everything compiled in, so
    this went unnoticed until the first capture on a real machine. It cost 48 dropped lines out of
    288, and the drop was in the middle of a call tree, which is the shape of a bug that makes a
    lesson quietly wrong rather than obviously broken.
    """
    text = header(
        " 0)               |  vfs_write() {",
        " 0)               |    ovl_write_iter [overlay]() {",
        " 0)   0.250 us    |      ovl_copyattr [overlay]();",
        " 0)   4.125 us    |    } /* ovl_write_iter [overlay] */",
        " 0) + 16.157 us   |  }",
    )
    tape = parse(text)

    assert tape.unparsed == []
    names = [f.name for f in tape.walk()]
    assert names == ["vfs_write", "ovl_write_iter", "ovl_copyattr"]
    assert [f.module for f in tape.walk()] == [None, "overlay", "overlay"]
    # The closing brace names the module too, and that is not a mismatch.
    assert tape.roots[0].children[0].duration_us == 4.125


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
