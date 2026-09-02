"""Tests for the C09 grader.

Nothing in this file asserts anything about what a kernel does. It asserts that the grader marks an
answer against whatever splat it was handed, which is a property of the grader.

The splat below is written out here rather than read from `corpora/`, for the same reason the
grader refuses the corpus: the last test in this file checks that refusal, and it needs a real
fixture path to refuse.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from kxray import lockdep

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "corpora" / "oops" / "handwritten" / "lockdep-ab-ba.txt"

ANSWERS = {
    "prediction": "I think both threads finish and nothing hangs at all",
    "who": "abba_second",
    "length": 2,
    "cycle": ["lock_a", "lock_b"],
    "learned_in": "abba_first_thread",
    "checker": "off",
}

STATS_OFF = " lock-classes: 1183 [max: 8192]\n debug_locks: 0\n"
STATS_ON = " lock-classes: 1183 [max: 8192]\n debug_locks: 1\n"

# A three lock cycle, because two locks can only be rotated and a wrong order needs three to
# exist at all. Cycles longer than two are the normal case in a real kernel.
THREE = """\
======================================================
WARNING: possible circular locking dependency detected
7.2.2 #1 Not tainted
------------------------------------------------------
third/900 is trying to acquire lock:
c1a4e0a0 (lock_a){+.+.}-{4:4}, at: third_thread+0x50/0x90 [abc]

but task is already holding lock:
c1a4e020 (lock_c){+.+.}-{4:4}, at: third_thread+0x28/0x90 [abc]

which lock already depends on the new lock.

the existing dependency chain (in reverse order) is:

-> #2 (lock_c){+.+.}-{4:4}:
       __lock_acquire+0x4a1/0x1a30
       second_thread+0x30/0x90 [abc]

-> #1 (lock_b){+.+.}-{4:4}:
       __lock_acquire+0x4a1/0x1a30
       first_thread+0x30/0x90 [abc]

-> #0 (lock_a){+.+.}-{4:4}:
       __lock_acquire+0x4a1/0x1a30
       third_thread+0x50/0x90 [abc]
"""


def load():
    path = ROOT / "lessons" / "C09" / "grader.py"
    spec = importlib.util.spec_from_file_location("c09_grader", path)
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
def splat():
    return lockdep.parse_splat(FIXTURE.read_text(), "a reader dmesg")


@pytest.fixture
def stats():
    return lockdep.parse_stats(STATS_OFF)


def failed(results):
    return {r.id for r in results if not r.passed}


def test_a_correct_set_of_answers_passes(grader, splat, stats):
    results = grader.grade(splat, ANSWERS, stats)
    assert failed(results) == set()
    assert grader.passed(results)


def test_a_prediction_of_a_few_words_is_not_a_prediction(grader, splat, stats):
    results = grader.grade(splat, {**ANSWERS, "prediction": "no"}, stats)
    assert failed(results) == {"prediction"}


def test_the_task_name_comes_from_this_splat(grader, splat, stats):
    results = grader.grade(splat, {**ANSWERS, "who": "kworker/0:1"}, stats)
    assert failed(results) == {"who"}


def test_the_task_name_forgives_a_pasted_pid(grader, splat, stats):
    results = grader.grade(splat, {**ANSWERS, "who": "abba_second/1481"}, stats)
    assert failed(results) == set()


def test_a_cycle_written_from_the_other_lock_is_the_same_cycle(grader, splat, stats):
    """A cycle has no first element, so marking somebody on where they started reading is wrong."""
    results = grader.grade(splat, {**ANSWERS, "cycle": ["lock_b", "lock_a"]}, stats)
    assert failed(results) == set()


def test_a_cycle_written_closed_is_accepted(grader, splat, stats):
    answers = {**ANSWERS, "cycle": ["lock_a", "lock_b", "lock_a"]}
    assert failed(grader.grade(splat, answers, stats)) == set()


def test_the_right_locks_in_the_wrong_order_says_so(grader, stats):
    """Two locks can only be rotated, so this needs three to have a wrong order at all."""
    three = lockdep.parse_splat(THREE, "a reader dmesg")
    answers = {
        **ANSWERS,
        "who": "third",
        "length": 3,
        "cycle": ["lock_a", "lock_c", "lock_b"],
        "learned_in": "second_thread",
    }
    results = grader.grade(three, answers, stats)
    assert failed(results) == {"cycle"}
    assert "wrong order" in next(r.detail for r in results if r.id == "cycle")


def test_a_three_lock_cycle_grades_the_same_way(grader, stats):
    three = lockdep.parse_splat(THREE, "a reader dmesg")
    answers = {
        **ANSWERS,
        "who": "third",
        "length": 3,
        "cycle": ["lock_b", "lock_c", "lock_a"],
        "learned_in": "second_thread",
    }
    assert failed(grader.grade(three, answers, stats)) == set()


def test_a_cycle_that_is_not_a_list_fails(grader, splat, stats):
    results = grader.grade(splat, {**ANSWERS, "cycle": "lock_a then lock_b"}, stats)
    assert failed(results) == {"cycle"}


def test_the_length_is_counted_from_this_chain(grader, splat, stats):
    results = grader.grade(splat, {**ANSWERS, "length": 3}, stats)
    assert failed(results) == {"length"}
    assert "2" in next(r.detail for r in results if r.id == "length")


def test_the_other_edge_is_the_thread_that_did_not_report(grader, splat):
    """The reporting thread is in the header. The other one is the thing worth finding."""
    assert grader.other_edge(splat).startswith("abba_first_thread")
    results = grader.grade(splat, {**ANSWERS, "learned_in": "abba_second_thread"}, None)
    assert "learned_in" in failed(results)


def test_the_other_edge_forgives_an_offset(grader, splat, stats):
    answers = {**ANSWERS, "learned_in": "abba_first_thread+0x58/0xd0"}
    assert failed(grader.grade(splat, answers, stats)) == set()


def test_without_statistics_the_checker_question_fails_rather_than_skips(grader, splat):
    results = grader.grade(splat, ANSWERS, None)
    assert failed(results) == {"checker"}
    assert "nothing to read" in next(r.detail for r in results if r.id == "checker")


def test_a_machine_where_the_checker_is_still_on_has_a_different_answer(grader, splat):
    on = lockdep.parse_stats(STATS_ON)
    assert failed(grader.grade(splat, ANSWERS, on)) == {"checker"}
    assert failed(grader.grade(splat, {**ANSWERS, "checker": "on"}, on)) == set()


def test_an_empty_answer_sheet_fails_everything(grader, splat, stats):
    results = grader.grade(splat, {}, stats)
    assert failed(results) == {r.id for r in results}


def test_the_report_says_how_many_passed(grader, splat, stats):
    text = grader.report(grader.grade(splat, ANSWERS, stats))
    assert "6 of 6 checks passed against your own report" in text


def test_a_handwritten_splat_cannot_be_graded(grader):
    fixture = lockdep.parse_splat(FIXTURE.read_text(), str(FIXTURE))
    with pytest.raises(ValueError, match="not evidence"):
        grader.grade(fixture, ANSWERS)


def test_the_refusal_holds_even_when_no_source_is_passed_in(grader):
    """The splat carries where it came from, so leaving the argument off does not get round it."""
    fixture = lockdep.parse_splat(FIXTURE.read_text(), str(FIXTURE))
    with pytest.raises(ValueError):
        grader.grade(fixture, ANSWERS, None, "")


def test_every_rotation_of_a_cycle_is_the_same_cycle(grader):
    assert grader.rotations(["a", "b", "c"]) == [
        ["a", "b", "c"],
        ["b", "c", "a"],
        ["c", "a", "b"],
    ]
