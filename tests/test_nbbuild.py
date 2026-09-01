"""Tests for the notebook builder.

The load bearing one is the claim rule. Everything else here is shape, and shape breaks loudly.
The claim rule breaks quietly, by passing a lesson that states something and shows nothing.
"""

from __future__ import annotations

import json

import pytest

from tools.nbbuild import Lesson


def lesson(tmp_path, claims: str = "", slug: str = "Z99", stem: str | None = None) -> Lesson:
    directory = tmp_path / "lessons" / slug
    directory.mkdir(parents=True)
    if claims:
        (directory / "claims.toml").write_text(claims, encoding="utf-8")
    return Lesson(slug, stem, root=tmp_path)


ONE_TRACE_CLAIM = """
schema = 1
lesson = "Z99"

[[claims]]
id = "Z99-01"
text = "The kernel writes a line when a function returns."
evidence_kind = "trace"
verified = false
"""

ONE_SOURCE_CLAIM = ONE_TRACE_CLAIM.replace('"trace"', '"source"')


def test_the_badge_points_at_the_notebook_it_is_about_to_write(tmp_path):
    built = lesson(tmp_path)
    assert "lessons/Z99/Z99.ipynb" in built.badge
    assert built.badge.startswith("[![Open In Colab]")


def test_the_badge_follows_the_stem_when_the_stem_is_not_the_slug(tmp_path):
    built = lesson(tmp_path, stem="your-first-trace")
    assert "lessons/Z99/your-first-trace.ipynb" in built.badge
    assert built.path.name == "your-first-trace.ipynb"


def test_an_image_gets_an_absolute_url_because_colab_has_no_directory(tmp_path):
    built = lesson(tmp_path)
    markup = built.image("map.svg", "a map")
    assert markup == (
        "![a map](https://raw.githubusercontent.com/tamnd/linux-kernel-internals/main/"
        "lessons/Z99/assets/map.svg)"
    )


def test_cells_come_out_as_a_notebook(tmp_path):
    built = lesson(tmp_path)
    built.md("# Hello")
    built.code("print(1)")

    notebook = json.loads(built.to_json())
    assert notebook["nbformat"] == 4
    assert [c["cell_type"] for c in notebook["cells"]] == ["markdown", "code"]
    assert notebook["cells"][1]["outputs"] == []
    assert notebook["cells"][1]["execution_count"] is None


def test_every_cell_has_its_own_id(tmp_path):
    built = lesson(tmp_path)
    for _ in range(4):
        built.md("text")

    ids = [c["id"] for c in json.loads(built.to_json())["cells"]]
    assert ids == ["z99-01", "z99-02", "z99-03", "z99-04"]


def test_source_keeps_the_newlines_a_notebook_expects(tmp_path):
    built = lesson(tmp_path)
    built.code("one\ntwo")

    source = json.loads(built.to_json())["cells"][0]["source"]
    assert source == ["one\n", "two"]


def test_a_claim_returns_the_words_from_the_ledger(tmp_path):
    built = lesson(tmp_path, ONE_TRACE_CLAIM)
    assert built.claim("Z99-01") == "The kernel writes a line when a function returns"


def test_a_claim_the_ledger_has_never_heard_of_is_an_error(tmp_path):
    built = lesson(tmp_path, ONE_TRACE_CLAIM)
    with pytest.raises(KeyError):
        built.claim("Z99-99")


def test_a_claim_needs_a_code_cell_under_it(tmp_path):
    built = lesson(tmp_path, ONE_TRACE_CLAIM)
    built.md(f"{built.claim('Z99-01')}.")
    built.code("print(1)")
    assert built._check_claims() == []


def test_a_claim_with_no_cell_at_all_fails(tmp_path):
    built = lesson(tmp_path, ONE_TRACE_CLAIM)
    built.md(f"{built.claim('Z99-01')}.")
    problems = built._check_claims()
    assert len(problems) == 1
    assert "no code cell" in problems[0]


def test_evidence_after_the_next_heading_does_not_count(tmp_path):
    """The whole point of the rule. Without this half, any cell further down would do."""
    built = lesson(tmp_path, ONE_TRACE_CLAIM)
    built.md(f"{built.claim('Z99-01')}.")
    built.md("## Something else entirely")
    built.code("print(1)")
    assert "no code cell" in built._check_claims()[0]


def test_a_source_claim_is_exempt_because_there_is_nothing_to_run(tmp_path):
    built = lesson(tmp_path, ONE_SOURCE_CLAIM)
    built.md(f"{built.claim('Z99-01')}.")
    assert built._check_claims() == []


def test_a_registered_claim_the_lesson_never_makes_is_an_error(tmp_path):
    built = lesson(tmp_path, ONE_TRACE_CLAIM)
    built.md("A lesson that says nothing.")
    problems = built._check_claims()
    assert "never makes it" in problems[0]


def test_the_markdown_carries_the_block_markers_and_the_notebook_does_not(tmp_path):
    built = lesson(tmp_path)
    built.block("hook")
    built.md("Why you should care.")
    built.code("print(1)")

    assert "<!-- block: hook -->" in built.to_markdown()
    assert "block: hook" not in built.to_json()


def test_the_markdown_fences_the_code_so_the_prose_rules_skip_it(tmp_path):
    built = lesson(tmp_path)
    built.code("print('obviously')")
    assert "```python\nprint('obviously')\n```" in built.to_markdown()


def test_save_writes_both_outputs(tmp_path):
    built = lesson(tmp_path)
    built.md("# Hello")
    assert built.save([]) == 0
    assert built.path.exists()
    assert built.markdown_path.read_text(encoding="utf-8") == "# Hello\n"


def test_check_fails_when_the_committed_notebook_is_stale(tmp_path):
    built = lesson(tmp_path)
    built.md("# Hello")
    built.save([])

    built.path.write_text("{}", encoding="utf-8")
    assert built.save(["--check"]) == 1


def test_check_passes_when_nothing_moved(tmp_path):
    built = lesson(tmp_path)
    built.md("# Hello")
    built.save([])
    assert built.save(["--check"]) == 0


def test_a_broken_claim_stops_the_write(tmp_path):
    built = lesson(tmp_path, ONE_TRACE_CLAIM)
    built.md(f"{built.claim('Z99-01')}.")
    assert built.save([]) == 1
    assert not built.path.exists()
