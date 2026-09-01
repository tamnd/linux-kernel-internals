"""Tests for the Z02 grader.

The fixture traces are handwritten, which is fine here and nowhere else. Nothing in this file
asserts anything about what a kernel does. It asserts that the grader compares an answer against
whatever trace it was handed, which is a property of the grader.

The last test is the one worth keeping: the grader refuses a handwritten trace outright, so
nobody can be graded on a trace nobody captured.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from kxray.trace import function_graph

ROOT = Path(__file__).resolve().parents[1]

TRACE = """\
# tracer: function_graph
#
# CPU  DURATION                  FUNCTION CALLS
# |     |   |                     |   |   |   |
 0)               |  vfs_write() {
 0)   0.180 us    |    rw_verify_area();
 0)               |    new_sync_write() {
 0)   0.140 us    |      generic_file_write_iter();
 0) + 12.400 us   |    }
 0) ! 130.000 us  |  }
"""

ANSWERS = {
    "prediction": "I think it goes through some virtual filesystem layer first",
    "frames": "10",
    "outermost": "vfs_write",
    "depth": 2,
    "reached_disk": False,
    "cpus": 1,
}


def load():
    path = ROOT / "lessons" / "Z02" / "grader.py"
    spec = importlib.util.spec_from_file_location("z02_grader", path)
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
def tape():
    return function_graph.parse(TRACE, source="a reader capture")


def failed(results):
    return {r.id for r in results if not r.passed}


def test_a_correct_set_of_answers_passes(grader, tape):
    results = grader.grade(tape, ANSWERS)
    assert failed(results) == set()
    assert grader.passed(results)


def test_a_prediction_of_a_few_words_is_not_a_prediction(grader, tape):
    results = grader.grade(tape, {**ANSWERS, "prediction": "dunno"})
    assert failed(results) == {"prediction"}


def test_the_wrong_order_of_magnitude_fails_and_says_the_real_count(grader, tape):
    results = grader.grade(tape, {**ANSWERS, "frames": "10000"})
    message = next(r.detail for r in results if r.id == "frames")
    assert str(tape.frame_count) in message


def test_a_function_from_somebody_elses_trace_fails(grader, tape):
    results = grader.grade(tape, {**ANSWERS, "outermost": "ksys_write"})
    assert failed(results) == {"outermost"}


def test_the_outermost_check_forgives_brackets_and_case(grader, tape):
    results = grader.grade(tape, {**ANSWERS, "outermost": "VFS_Write()"})
    assert failed(results) == set()


def test_depth_is_checked_against_this_trace_and_not_a_stored_number(grader, tape):
    results = grader.grade(tape, {**ANSWERS, "depth": 7})
    assert failed(results) == {"depth"}


def test_a_trace_with_block_layer_work_changes_the_right_answer(grader):
    with_disk = TRACE.replace("generic_file_write_iter();", "submit_bio();")
    tape = function_graph.parse(with_disk, source="a reader capture")
    assert grader.reached_disk(tape)
    assert failed(grader.grade(tape, ANSWERS)) == {"reached_disk"}
    assert failed(grader.grade(tape, {**ANSWERS, "reached_disk": True})) == set()


def test_the_cpu_count_comes_from_the_trace(grader):
    two = TRACE + " 1)   0.100 us    |  tick_sched_timer();\n"
    tape = function_graph.parse(two, source="a reader capture")
    assert failed(grader.grade(tape, ANSWERS)) == {"cpus"}
    assert failed(grader.grade(tape, {**ANSWERS, "cpus": 2})) == set()


def test_an_empty_answer_sheet_fails_everything(grader, tape):
    results = grader.grade(tape, {})
    assert failed(results) == {r.id for r in results}


def test_the_report_says_how_many_passed(grader, tape):
    text = grader.report(grader.grade(tape, ANSWERS))
    assert "6 of 6 checks passed against your own trace" in text


def test_a_handwritten_trace_cannot_be_graded(grader):
    path = ROOT / "corpora" / "traces" / "handwritten" / "write-1byte.txt"
    tape = function_graph.parse_file(path)
    with pytest.raises(ValueError, match="not evidence"):
        grader.grade(tape, ANSWERS)


def test_the_count_question_rounds_on_a_log_scale(grader):
    # The reader was offered four buckets, so a four call trace has to land in one of them.
    assert grader._bucket(4) == 10
    assert grader._bucket(120) == 100
    assert grader._bucket(400) == 1000
    assert grader._bucket(99999) == 10000
    assert grader._bucket(0) == 0


def test_every_question_has_a_check_behind_it(grader):
    ids = {r.id for r in grader.grade(function_graph.parse(TRACE, source="x"), ANSWERS)}
    assert set(grader.QUESTIONS) <= ids
