"""Tests for the S05 grader.

This file was missing when S05 was merged, which meant one of the three graders the milestone asks
for had nothing checking it. Nothing here asserts anything about what a kernel does. It asserts
that the grader marks an answer against whatever symbol table it was handed.

The symbol table below is written out here rather than read from `corpora/`, because the last test
checks that the grader refuses the corpus and it needs a real fixture path to refuse.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from kxray import kallsyms

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "corpora" / "proc" / "handwritten" / "kallsyms.txt"

# Six ops tables, five of them in read only data, addresses hidden the way an unprivileged read
# sees them. Small enough that every expected answer below can be counted by eye.
SYMBOLS = """\
00000000 T vfs_write
00000000 R ext4_file_operations
00000000 R shmem_file_operations
00000000 R pipefifo_fops
00000000 R tty_fops
00000000 R sysfs_dir_inode_operations
00000000 d nfs_rpc_ops
00000000 T ext4_file_write_iter
"""

ANSWERS = {
    "prediction": "I expect a few hundred tables and most of them constant",
    "tables": 10,
    "file_ops": 5,
    "readonly": "most",
    "hidden": True,
    "worker": "ext4_file_write_iter",
}

TRACE = """\
# tracer: function_graph
#
 0)               |  vfs_write() {
 0)   0.180 us    |    rw_verify_area();
 0)               |    ext4_file_write_iter() {
 0)   0.140 us    |      iomap_dio_rw();
 0) + 12.400 us   |    }
 0) ! 130.000 us  |  }
"""


def load():
    path = ROOT / "lessons" / "S05" / "grader.py"
    spec = importlib.util.spec_from_file_location("s05_grader", path)
    module = importlib.util.module_from_spec(spec)
    # A dataclass looks its own module up by name while it is being built, so the module has to
    # be in sys.modules before it runs, not after.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def grader():
    return load()


@pytest.fixture
def found():
    return kallsyms.parse(SYMBOLS)


@pytest.fixture
def tape():
    from kxray.trace import function_graph

    return function_graph.parse(TRACE, source="a reader capture")


def failed(results):
    return {r.id for r in results if not r.passed}


def test_a_correct_set_of_answers_passes(grader, found, tape):
    results = grader.grade(found, ANSWERS, tape, "/proc/kallsyms")
    assert failed(results) == set()
    assert grader.passed(results)


def test_a_prediction_of_a_few_words_is_not_a_prediction(grader, found, tape):
    results = grader.grade(found, {**ANSWERS, "prediction": "no idea"}, tape, "/proc/kallsyms")
    assert failed(results) == {"prediction"}


def test_the_count_is_forgiving_about_the_order_of_magnitude(grader, found, tape):
    """Six tables and an answer of ten is right. The reader was offered buckets, not a target."""
    assert failed(grader.grade(found, ANSWERS, tape, "/proc/kallsyms")) == set()
    off = {**ANSWERS, "tables": 1000}
    assert failed(grader.grade(found, off, tape, "/proc/kallsyms")) == {"tables"}


def test_the_file_operations_count_wants_both_spellings(grader, found, tape):
    """ext4, shmem and sysfs spell it _operations, pipefifo and tty spell it _fops.

    Five, and one of the five is an inode operations table rather than a file one. The name is all
    the grader has to go on, which is the same lower bound the lesson is careful to state.
    """
    assert len(grader.file_operations(found)) == 5
    wrong = {**ANSWERS, "file_ops": 3}
    assert failed(grader.grade(found, wrong, tape, "/proc/kallsyms")) == {"file_ops"}


def test_the_read_only_share_is_measured_rather_than_stored(grader, found, tape):
    results = grader.grade(found, {**ANSWERS, "readonly": "few"}, tape, "/proc/kallsyms")
    assert failed(results) == {"readonly"}
    assert "%" in next(r.detail for r in results if r.id == "readonly")


def test_a_table_in_writable_data_changes_the_share(grader, tape):
    mostly_writable = SYMBOLS.replace(" R ", " d ")
    found = kallsyms.parse(mostly_writable)
    assert failed(grader.grade(found, ANSWERS, tape, "/proc/kallsyms")) == {"readonly"}
    fixed = {**ANSWERS, "readonly": "few"}
    assert "readonly" not in failed(grader.grade(found, fixed, tape, "/proc/kallsyms"))


def test_visible_addresses_change_the_answer_to_the_root_question(grader, tape):
    found = kallsyms.parse(SYMBOLS.replace("00000000", "c1a4e0a0"))
    assert failed(grader.grade(found, ANSWERS, tape, "/proc/kallsyms")) == {"hidden"}
    seen = {**ANSWERS, "hidden": False}
    assert failed(grader.grade(found, seen, tape, "/proc/kallsyms")) == set()


def test_without_a_trace_the_worker_question_fails_rather_than_skips(grader, found):
    results = grader.grade(found, ANSWERS, None, "/proc/kallsyms")
    assert failed(results) == {"worker"}
    assert "no trace" in next(r.detail for r in results if r.id == "worker")


def test_a_trace_of_a_different_destination_has_a_different_answer(grader, found):
    from kxray.trace import function_graph

    pipe = function_graph.parse(TRACE.replace("ext4_file_write_iter", "pipe_write"))
    assert failed(grader.grade(found, ANSWERS, pipe, "/proc/kallsyms")) == {"worker"}
    right = {**ANSWERS, "worker": "pipe_write"}
    assert failed(grader.grade(found, right, pipe, "/proc/kallsyms")) == set()


def test_the_worker_check_forgives_brackets_and_case(grader, found, tape):
    loud = {**ANSWERS, "worker": "Ext4_File_Write_Iter();"}
    assert failed(grader.grade(found, loud, tape, "/proc/kallsyms")) == set()


def test_an_empty_answer_sheet_fails_everything(grader, found, tape):
    results = grader.grade(found, {}, tape, "/proc/kallsyms")
    assert failed(results) == {r.id for r in results}


def test_the_report_says_how_many_passed(grader, found, tape):
    text = grader.report(grader.grade(found, ANSWERS, tape, "/proc/kallsyms"))
    assert "6 of 6 checks passed against your own kernel" in text


def test_a_handwritten_symbol_table_cannot_be_graded(grader):
    found = kallsyms.parse(FIXTURE.read_text())
    with pytest.raises(ValueError, match="not evidence"):
        grader.grade(found, ANSWERS, None, str(FIXTURE))
