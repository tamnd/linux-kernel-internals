"""Tests for the reference checker.

The two rules that matter. A path this repository writes about has to exist or be declared as
planned, and a citation into the kernel is anchored on text rather than on a line number, because
a line number is right on the day it is typed and silently wrong after the next patch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import refcheck

ROOT = Path(__file__).resolve().parents[1]

PIN = """
schema = 1

[kernel]
version = "7.2.2"

[fallback]
version = "6.18.48"

[[profiles]]
name = "A-full"
"""

REFS = """
schema = 1

[[references]]
id = "Z02-R1"
path = "kernel/trace/trace_functions_graph.c"
anchor = "print_graph_entry_leaf"
kernel = "7.2.2"
confirmed = false
line = 0
"""

META = """
id = "Z02"
profile = "A-full"
"""


def repo(tmp_path: Path, *, docs: dict[str, str] | None = None, lesson: dict | None = None) -> Path:
    """A small repository with the pieces the checker looks for."""
    (tmp_path / "kxbox" / "kernel").mkdir(parents=True)
    (tmp_path / "kxbox" / "kernel" / "pin.toml").write_text(PIN)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "refcheck.py").write_text("")
    for name, text in (docs or {}).items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    if lesson is not None:
        directory = tmp_path / "lessons" / "Z02"
        directory.mkdir(parents=True)
        for name, text in lesson.items():
            (directory / name).write_text(text)
    return tmp_path


def messages(findings) -> str:
    return "\n".join(str(f) for f in findings)


def check(root: Path) -> str:
    return messages(refcheck.check(root)[0])


# -- the real repository ----------------------------------------------------------------------


def test_this_repository_is_clean():
    """The test that catches somebody moving a file and leaving forty documents behind."""
    findings, _ = refcheck.check(ROOT)
    assert findings == [], messages(findings)


def test_every_citation_in_this_repository_is_still_waiting_on_a_kernel_tree():
    """Written down as a test, so that confirming one is a deliberate act with a diff.

    There is no kernel tree on this machine. If this ever fails it is because somebody resolved a
    citation against a real tree, which is good news and worth reading the diff for.
    """
    _, references = refcheck.check(ROOT)
    assert references, "there should be citations by now"
    assert not any(r.confirmed for r in references)


# -- paths into this repository ---------------------------------------------------------------


def test_a_path_that_does_not_exist_is_found(tmp_path):
    root = repo(tmp_path, docs={"README.md": "See `tools/nothing_here.py` for details.\n"})
    assert "does not exist" in check(root)


def test_a_path_that_exists_is_fine(tmp_path):
    root = repo(tmp_path, docs={"README.md": "See `tools/refcheck.py` for details.\n"})
    assert check(root) == ""


def test_a_module_written_without_the_py_counts_as_found(tmp_path):
    """`tools/refcheck` is how a person writes a module they run with -m."""
    root = repo(tmp_path, docs={"README.md": "Run `tools/refcheck` before you push.\n"})
    assert check(root) == ""


def test_a_path_inside_a_code_fence_is_left_alone(tmp_path):
    """Half the paths in an example command are meant to be typed, not to exist."""
    text = "Try this:\n\n```\ncat `tools/whatever.txt`\n```\n"
    assert check(repo(tmp_path, docs={"README.md": text})) == ""


def test_a_placeholder_is_not_a_path(tmp_path):
    text = "A lesson goes in `lessons/<ID>/` and its assets in `lessons/<ID>/assets/`.\n"
    assert check(repo(tmp_path, docs={"README.md": text})) == ""


def test_a_path_that_is_not_ours_is_ignored(tmp_path):
    """`mm/memory.c` in prose is the kernel, not this repository, and is not ours to check."""
    assert check(repo(tmp_path, docs={"README.md": "The fault path is in `mm/memory.c`.\n"})) == ""


def test_a_planned_path_passes_when_it_says_why(tmp_path):
    root = repo(tmp_path, docs={"README.md": "Litmus tests live in `tools/memory-model/`.\n"})
    (root / "refcheck.toml").write_text(
        'schema = 1\n\n[[planned]]\npath = "tools/memory-model/"\n'
        'reason = "The litmus tests and their output, which arrive with the concurrency part."\n'
    )
    assert check(root) == ""


def test_a_planned_path_without_a_reason_fails(tmp_path):
    root = repo(tmp_path, docs={"README.md": "Litmus tests live in `tools/memory-model/`.\n"})
    (root / "refcheck.toml").write_text(
        'schema = 1\n\n[[planned]]\npath = "tools/memory-model/"\nreason = "later"\n'
    )
    assert "no reason" in check(root)


def test_a_planned_path_that_now_exists_has_to_be_taken_off_the_list(tmp_path):
    """Otherwise the list rots in the other direction and stops meaning anything."""
    root = repo(tmp_path, docs={"README.md": "See `tools/refcheck.py`.\n"})
    (root / "refcheck.toml").write_text(
        'schema = 1\n\n[[planned]]\npath = "tools/refcheck.py"\n'
        'reason = "This has existed for a while and nobody removed the entry saying it would not."\n'
    )
    assert "take it out" in check(root)


def test_a_finding_in_a_generated_lesson_says_where_to_fix_it(tmp_path):
    root = repo(tmp_path, lesson={"meta.toml": META, "lesson.md": "See `tools/gone.py`.\n"})
    assert "fix it there" in check(root)


# -- lesson metadata --------------------------------------------------------------------------


def test_a_lesson_that_names_no_profile_fails(tmp_path):
    root = repo(tmp_path, lesson={"meta.toml": 'id = "Z02"\n'})
    assert "no profile" in check(root)


def test_a_lesson_naming_a_profile_that_is_not_pinned_fails(tmp_path):
    root = repo(tmp_path, lesson={"meta.toml": 'id = "Z02"\nprofile = "Z-gone"\n'})
    assert "A-full" in check(root)


# -- citations into the kernel ------------------------------------------------------------------


def test_a_well_formed_citation_passes(tmp_path):
    assert check(repo(tmp_path, lesson={"meta.toml": META, "refs.toml": REFS})) == ""


def test_a_citation_with_a_line_number_in_the_path_fails(tmp_path):
    """The whole point. `mm/memory.c:5310` is right today and quietly wrong next week."""
    refs = REFS.replace(
        'path = "kernel/trace/trace_functions_graph.c"',
        'path = "mm/memory.c:5310"',
    )
    assert "line number is not an anchor" in check(
        repo(tmp_path, lesson={"meta.toml": META, "refs.toml": refs})
    )


def test_an_anchor_that_is_a_number_fails(tmp_path):
    refs = REFS.replace('anchor = "print_graph_entry_leaf"', 'anchor = "531012345678"')
    assert "line numbers move" in check(
        repo(tmp_path, lesson={"meta.toml": META, "refs.toml": refs})
    )


def test_an_anchor_too_short_to_be_useful_fails(tmp_path):
    refs = REFS.replace('anchor = "print_graph_entry_leaf"', 'anchor = "int"')
    assert "matches anywhere" in check(
        repo(tmp_path, lesson={"meta.toml": META, "refs.toml": refs})
    )


def test_a_path_that_is_not_in_a_kernel_tree_fails(tmp_path):
    refs = REFS.replace(
        'path = "kernel/trace/trace_functions_graph.c"', 'path = "kxray/trace/function_graph.py"'
    )
    assert "not in a kernel tree" in check(
        repo(tmp_path, lesson={"meta.toml": META, "refs.toml": refs})
    )


def test_an_absolute_path_fails(tmp_path):
    refs = REFS.replace(
        'path = "kernel/trace/trace_functions_graph.c"', 'path = "/home/me/linux/mm/memory.c"'
    )
    assert "absolute" in check(repo(tmp_path, lesson={"meta.toml": META, "refs.toml": refs}))


def test_a_citation_naming_a_kernel_that_is_not_pinned_fails(tmp_path):
    refs = REFS.replace('kernel = "7.2.2"', 'kernel = "5.10"')
    assert "not a pinned version" in check(
        repo(tmp_path, lesson={"meta.toml": META, "refs.toml": refs})
    )


def test_the_fallback_kernel_is_a_pinned_version_too(tmp_path):
    refs = REFS.replace('kernel = "7.2.2"', 'kernel = "6.18.48"')
    assert check(repo(tmp_path, lesson={"meta.toml": META, "refs.toml": refs})) == ""


def test_confirmed_with_no_line_fails(tmp_path):
    refs = REFS.replace("confirmed = false", "confirmed = true")
    assert "no line" in check(repo(tmp_path, lesson={"meta.toml": META, "refs.toml": refs}))


def test_a_line_without_a_confirmation_fails(tmp_path):
    """Somebody typing a line number in by hand is exactly what this format is here to stop."""
    refs = REFS.replace("line = 0", "line = 5310")
    assert "the line is a guess" in check(
        repo(tmp_path, lesson={"meta.toml": META, "refs.toml": refs})
    )


def test_an_id_that_does_not_belong_to_the_lesson_fails(tmp_path):
    refs = REFS.replace('id = "Z02-R1"', 'id = "S05-R1"')
    assert "should start with Z02-R" in check(
        repo(tmp_path, lesson={"meta.toml": META, "refs.toml": refs})
    )


# -- claims that rest on the source --------------------------------------------------------------


def source_claim(evidence: str, verified: str = "false") -> str:
    return (
        'schema = 1\nlesson = "Z02"\n\n[[claims]]\nid = "Z02-01"\ntext = "Something is true."\n'
        f'evidence_kind = "source"\n{evidence}verified = {verified}\n'
    )


def test_a_source_claim_may_cite_a_reference(tmp_path):
    lesson = {
        "meta.toml": META,
        "refs.toml": REFS,
        "claims.toml": source_claim('evidence = "Z02-R1"\n'),
    }
    assert check(repo(tmp_path, lesson=lesson)) == ""


def test_a_source_claim_citing_something_that_is_not_there_fails(tmp_path):
    lesson = {
        "meta.toml": META,
        "refs.toml": REFS,
        "claims.toml": source_claim('evidence = "Z02-R9"\n'),
    }
    assert "not in refs.toml" in check(repo(tmp_path, lesson=lesson))


def test_a_verified_source_claim_needs_a_confirmed_citation(tmp_path):
    """An unconfirmed citation is a guess about a file nobody has opened."""
    lesson = {
        "meta.toml": META,
        "refs.toml": REFS,
        "claims.toml": source_claim('evidence = "Z02-R1"\n', verified="true"),
    }
    assert "nobody has confirmed" in check(repo(tmp_path, lesson=lesson))


def test_a_verified_source_claim_with_no_citation_at_all_fails(tmp_path):
    lesson = {
        "meta.toml": META,
        "refs.toml": REFS,
        "claims.toml": source_claim("", verified="true"),
    }
    assert "with no citation" in check(repo(tmp_path, lesson=lesson))


# -- resolving against a real tree ---------------------------------------------------------------


def tree(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "linux" / "kernel" / "trace"
    path.mkdir(parents=True)
    (path / "trace_functions_graph.c").write_text(text)
    return tmp_path / "linux"


def one_reference(anchor: str = "print_graph_entry_leaf") -> refcheck.Reference:
    return refcheck.Reference(
        identifier="Z02-R1",
        path="kernel/trace/trace_functions_graph.c",
        anchor=anchor,
        kernel="7.2.2",
    )


def test_an_anchor_is_found_and_gives_back_the_line(tmp_path):
    where = tree(tmp_path, "one\ntwo\nstatic void print_graph_entry_leaf(void)\n")
    assert refcheck.resolve(one_reference(), where) == (3, "")


def test_an_anchor_that_moved_is_found_at_its_new_line(tmp_path):
    """The reason the anchor is text. Ten lines added above it changes nothing."""
    where = tree(tmp_path, "\n" * 10 + "static void print_graph_entry_leaf(void)\n")
    line, problem = refcheck.resolve(one_reference(), where)
    assert (line, problem) == (11, "")


def test_an_anchor_that_is_gone_says_so_with_the_file_and_the_text(tmp_path):
    where = tree(tmp_path, "nothing like it here\n")
    line, problem = refcheck.resolve(one_reference(), where)
    assert line is None
    assert "print_graph_entry_leaf" in problem
    assert "trace_functions_graph.c" in problem


def test_an_anchor_that_appears_twice_says_to_pick_a_longer_one(tmp_path):
    where = tree(tmp_path, "print_graph_entry_leaf\nprint_graph_entry_leaf\n")
    line, problem = refcheck.resolve(one_reference(), where)
    assert line == 1
    assert "appears 2 times" in problem


def test_a_file_that_is_not_in_the_tree_says_which_tree(tmp_path):
    where = tree(tmp_path, "anything\n")
    missing = refcheck.Reference("Z02-R1", "mm/memory.c", "handle_mm_fault", "7.2.2")
    line, problem = refcheck.resolve(missing, where)
    assert line is None
    assert "mm/memory.c is not in" in problem


def test_confirming_writes_the_line_and_the_flag_back_and_keeps_the_comments(tmp_path):
    root = repo(tmp_path, lesson={"meta.toml": META, "refs.toml": "# a comment\n" + REFS})
    where = tree(tmp_path, "\n" * 6 + "print_graph_entry_leaf\n")
    findings, resolved = refcheck.confirm(root, where, write=True)

    assert findings == []
    assert resolved == 1
    written = (root / "lessons" / "Z02" / "refs.toml").read_text()
    assert "line = 7" in written
    assert "confirmed = true" in written
    assert "# a comment" in written


def test_resolving_without_confirm_changes_nothing(tmp_path):
    root = repo(tmp_path, lesson={"meta.toml": META, "refs.toml": REFS})
    where = tree(tmp_path, "print_graph_entry_leaf\n")
    before = (root / "lessons" / "Z02" / "refs.toml").read_text()
    refcheck.confirm(root, where, write=False)
    assert (root / "lessons" / "Z02" / "refs.toml").read_text() == before


# -- the command line ------------------------------------------------------------------------


def test_main_is_clean_on_this_repository():
    assert refcheck.main(["--root", str(ROOT)]) == 0


def test_main_lists_the_planned_paths(capsys):
    assert refcheck.main(["--root", str(ROOT), "--list-planned"]) == 0
    assert "memory-model" in capsys.readouterr().out


def test_main_fails_when_something_is_wrong(tmp_path):
    root = repo(tmp_path, docs={"README.md": "See `tools/nope.py`.\n"})
    assert refcheck.main(["--root", str(root)]) == 1


@pytest.mark.parametrize("token", ["tools/refcheck.py", "lessons/Z02/meta.toml"])
def test_prose_paths_finds_a_backticked_path(token):
    assert refcheck.prose_paths(f"words `{token}` words\n") == [(1, token)]
