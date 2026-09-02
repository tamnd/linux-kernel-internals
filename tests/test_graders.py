"""The rules every grader follows, checked against every grader that exists.

There is one of these per lesson already. `test_z02_grader.py`, `test_s05_grader.py` and
`test_c09_grader.py` each mark a set of answers against a trace, a symbol table or a lockdep
report, and each of them knows what its own subject is about. This file knows nothing about any
subject. It finds every `lessons/*/grader.py` on disk and checks the handful of things that have
to be true of all of them.

That distinction is the whole reason this file exists. Three lessons having a grader test each is
a coincidence that held three times. There are ten more milestones and most of them end in a boss
fight, and the first grader that ships with nothing behind it will not announce itself. The first
test below is the one that catches that: it fails on a lesson that has a grader and no test file,
which is a thing nobody would otherwise notice until a reader was marked by code no one had run.

The rest are the promises the graders make to a reader. Every question has a check behind it, so
a lesson cannot ask something it never marks. Every result is frozen, so a score cannot be edited
after it was worked out. Every grader names its evidence rather than a stored answer, which is
what the closing line of a report says out loud. And every one of them refuses a handwritten
fixture, because being marked against a file nobody captured is the one thing this project says
it will not do.
"""

import dataclasses
import importlib.util
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
GRADERS = sorted(ROOT.glob("lessons/*/grader.py"))

# What a grader is, as far as anything outside the lesson is concerned. A caller who has these can
# mark a submission, print the result and refuse a fixture without knowing which lesson it came
# from, which is what lets the notebook cell in every lesson be the same three lines.
CONTRACT = ("QUESTIONS", "CHECKS", "grade", "passed", "report", "main", "HANDWRITTEN")


def slug(path: Path) -> str:
    return path.parent.name


def load(path: Path):
    name = f"{slug(path).lower()}_grader_rules"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # A dataclass looks its own module up by name while it is being built, so the module has to be
    # in sys.modules before it runs rather than after.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def handwritten_paths(module) -> tuple[str, ...]:
    """The prefixes a grader refuses, as a tuple whether it wrote one or several."""
    where = module.HANDWRITTEN
    return (where,) if isinstance(where, str) else tuple(where)


@pytest.fixture(params=GRADERS, ids=slug)
def grader(request):
    return load(request.param)


def test_there_are_graders_to_check():
    """If the glob ever comes back empty, every test below passes for the wrong reason."""
    assert len(GRADERS) >= 3, "lessons/*/grader.py found nothing, so nothing here checked anything"


def test_every_grader_has_a_test_file_of_its_own():
    """The one that catches the next lesson rather than the three that are already here."""
    missing = [
        slug(path)
        for path in GRADERS
        if not (ROOT / "tests" / f"test_{slug(path).lower()}_grader.py").exists()
    ]
    assert not missing, (
        f"these lessons have a grader and no test: {missing}. "
        "A grader nobody has run will still mark somebody."
    )


def test_every_grader_exposes_the_same_names(grader):
    absent = [name for name in CONTRACT if not hasattr(grader, name)]
    assert not absent, f"{grader.__name__} is missing {absent}"


def test_every_question_has_a_check_behind_it(grader):
    """A lesson that asks something it never marks is worse than one that never asked."""
    marked = {check.__name__.removeprefix("check_") for check in grader.CHECKS}
    unmarked = set(grader.QUESTIONS) - marked
    assert not unmarked, f"{grader.__name__} asks {sorted(unmarked)} and marks none of them"


def test_every_check_says_which_question_it_answered(grader):
    """The id on a result has to be the question, or a report cannot be read next to the sheet."""
    for check in grader.CHECKS:
        assert check.__name__.startswith("check_"), check.__name__


def test_a_score_cannot_be_edited_after_it_was_worked_out(grader):
    """Frozen, so nothing downstream can turn a fail into a pass by assigning to it."""
    result = grader.Result("x", False, "no")
    assert dataclasses.is_dataclass(result)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.passed = True


def test_a_result_prints_the_mark_and_the_reason(grader):
    assert str(grader.Result("depth", False, "count the indentation")) == (
        "[fail] depth: count the indentation"
    )


def test_the_report_says_the_evidence_was_the_readers_own(grader):
    """There is no answer key anywhere in this repository, and the closing line says so."""
    assert "against your own" in grader.report([])


def test_the_report_counts_what_it_was_handed(grader):
    results = [grader.Result("a", True, ""), grader.Result("b", False, "")]
    assert "1 of 2 checks passed" in grader.report(results)
    assert grader.passed([results[0]])
    assert not grader.passed(results)


def test_every_handwritten_directory_a_grader_names_is_really_there(grader):
    """A refusal that names a path that moved is a refusal that stopped refusing."""
    for where in handwritten_paths(grader):
        assert (ROOT / where).is_dir(), (
            f"{grader.__name__} refuses {where}, which is not a directory"
        )
        assert list((ROOT / where).glob("*")), f"{where} is empty, so nothing is being refused"


def test_every_grader_refuses_a_handwritten_fixture(grader):
    """The same refusal in all three, checked without knowing what any of them grades.

    The evidence goes in as a stand in object carrying nothing but the path it came from, because
    that is the only field the refusal reads, and it has to be read before anything else happens.
    A grader that looked at the evidence first would fail here with something other than a
    ValueError, which is the right way to find out.
    """
    where = f"{handwritten_paths(grader)[0]}/whatever.txt"
    args = [SimpleNamespace(source=where), {}]
    kwargs = {"source": where} if "source" in inspect.signature(grader.grade).parameters else {}
    with pytest.raises(ValueError, match="not evidence"):
        grader.grade(*args, **kwargs)


def test_every_grader_prints_its_usage_rather_than_a_traceback(grader):
    """Run with no arguments at all, which is how somebody finds out how to run it."""
    assert grader.main([]) == 2
