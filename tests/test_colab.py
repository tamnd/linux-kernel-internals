"""Tests for the lesson loader.

Nothing here reaches the network. The download path is exercised with a stub, because a test that
needs GitHub to be up is a test that fails for reasons that have nothing to do with the code.
"""

from __future__ import annotations

import pytest

from kxray import colab


def checkout(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "lessons" / "Z99").mkdir(parents=True)
    return tmp_path


def test_repo_root_finds_the_checkout_it_is_running_in(tmp_path, monkeypatch):
    root = checkout(tmp_path)
    monkeypatch.chdir(root / "lessons" / "Z99")
    assert colab.repo_root() == root


def test_a_lessons_directory_without_a_pyproject_is_not_the_repository(tmp_path, monkeypatch):
    (tmp_path / "lessons").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(colab, "__file__", str(tmp_path / "kxray" / "colab.py"))
    assert colab.repo_root() is None


def test_a_local_file_is_used_and_nothing_is_fetched(tmp_path, monkeypatch):
    root = checkout(tmp_path)
    (root / "lessons" / "Z99" / "claims.toml").write_text("schema = 1\n")
    monkeypatch.chdir(root)
    monkeypatch.setattr(colab.urllib.request, "urlopen", _refuse)

    assert colab.lesson_text("Z99", "claims.toml") == "schema = 1\n"


def test_a_missing_file_is_fetched_from_the_repository(tmp_path, monkeypatch):
    root = checkout(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(colab, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(colab.urllib.request, "urlopen", _serve(b"schema = 1\n"))

    assert colab.lesson_text("Z99", "claims.toml") == "schema = 1\n"


def test_a_fetched_file_is_only_fetched_once(tmp_path, monkeypatch):
    root = checkout(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(colab, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(colab.urllib.request, "urlopen", _serve(b"one\n"))
    colab.lesson_text("Z99", "notes.txt")

    monkeypatch.setattr(colab.urllib.request, "urlopen", _refuse)
    assert colab.lesson_text("Z99", "notes.txt") == "one\n"


def test_the_url_is_the_default_branch_of_the_public_repository():
    url = colab.lesson_url("Z02", "grader.py")
    assert url.endswith("/tamnd/linux-kernel-internals/main/lessons/Z02/grader.py")


def test_a_lesson_module_is_importable_and_keeps_its_dataclasses(tmp_path, monkeypatch):
    """A dataclass looks itself up in sys.modules while its own class body runs.

    Leaving the module out of sys.modules gives you an AttributeError from inside the standard
    library, with nothing in the traceback pointing back at this loader.
    """
    root = checkout(tmp_path)
    (root / "lessons" / "Z99" / "thing.py").write_text(
        "from dataclasses import dataclass\n\n@dataclass\nclass Result:\n    value: int\n"
    )
    monkeypatch.chdir(root)

    module = colab.lesson_module("Z99", "thing")
    assert module.Result(3).value == 3


def _refuse(*args, **kwargs):
    raise AssertionError("this should not have gone to the network")


def _serve(payload: bytes):
    class Response:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(url):
        return Response()

    return urlopen


def test_in_colab_is_false_in_a_test_run():
    assert colab.in_colab() is False


@pytest.mark.parametrize("name", ["grader.py", "claims.toml"])
def test_the_real_z02_files_are_where_the_loader_looks(name):
    assert colab.lesson_file("Z02", name).exists()


@pytest.mark.parametrize(
    "relative",
    [
        "traces/tier0/write-1byte.txt",
        "traces/tier1/multi-cpu-write.txt",
        "proc/tier0/ring-overrun.txt",
        "experiments/tier1/tracer-cost.txt",
    ],
)
def test_the_captures_a_lesson_loads_are_where_the_loader_looks(relative):
    """Every artefact a notebook asks for by name, checked to be there.

    A lesson running in Colab downloads these one at a time from the default branch, so a file
    that gets moved or renamed does not fail here, it fails in somebody's browser halfway through
    a lesson with a 404. This is the check that catches it at the right end.
    """
    assert colab.corpus_file(relative).exists()


def test_a_missing_capture_is_fetched_from_the_repository(tmp_path, monkeypatch):
    root = checkout(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(colab, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(colab.urllib.request, "urlopen", _serve(b" 0)  |  vfs_write() {\n"))

    assert colab.corpus_text("traces/tier0/nothing-here.txt").startswith(" 0)")


def test_the_corpus_url_is_the_default_branch_of_the_public_repository():
    url = colab.repo_url("corpora/traces/tier1/multi-cpu-write.txt")
    assert url.endswith(
        "/tamnd/linux-kernel-internals/main/corpora/traces/tier1/multi-cpu-write.txt"
    )


def test_the_scratch_directory_is_made_when_it_is_asked_for(tmp_path, monkeypatch):
    monkeypatch.setattr(colab, "CACHE", tmp_path / "cache")
    here = colab.scratch("C09")
    assert here.is_dir()


def test_the_scratch_directory_is_the_same_one_every_time(tmp_path, monkeypatch):
    """So a reader who builds a module in it can find what they built afterwards."""
    monkeypatch.setattr(colab, "CACHE", tmp_path / "cache")
    assert colab.scratch("C09") == colab.scratch("C09")


def test_two_lessons_get_two_scratch_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(colab, "CACHE", tmp_path / "cache")
    assert colab.scratch("C09") != colab.scratch("Z02")


def test_the_scratch_directory_is_not_the_repository(tmp_path, monkeypatch):
    """Which is the whole point of it. A lesson does not leave files in your working tree."""
    monkeypatch.setattr(colab, "CACHE", tmp_path / "cache")
    root = colab.repo_root()
    assert root is None or root not in colab.scratch("C09").parents
