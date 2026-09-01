"""Tests for the claim ledger.

The one that matters is the last group: a claim cannot be verified against an artefact that says
it is not evidence. That is the rule the whole project rests on, and it is the rule most likely
to be broken by somebody in a hurry who is sure it is fine this once.
"""

from pathlib import Path

import pytest

from tools import claimledger

GOOD_CLAIM = """
schema = 1
lesson = "Z02"

[[claims]]
id = "Z02-01"
text = "The kernel records every function call when function_graph is on."
evidence_kind = "trace"
evidence = "{trace}"
verified = true
"""


@pytest.fixture
def lesson(tmp_path):
    """A lesson directory with a real corpus artefact beside it."""
    corpus = tmp_path / "corpora"
    corpus.mkdir()
    trace = corpus / "one.txt"
    trace.write_text("# tracer: function_graph\n")

    directory = tmp_path / "lessons" / "Z02"
    directory.mkdir(parents=True)
    (directory / "meta.toml").write_text('id = "Z02"\nstatus = "draft"\n')
    return directory, trace


def write(directory: Path, claims: str) -> Path:
    (directory / "claims.toml").write_text(claims)
    return directory


def meta_for(trace: Path, evidence: bool) -> None:
    trace.with_suffix(".meta.toml").write_text(
        f'source = "capture"\nevidence = {str(evidence).lower()}\n'
    )


def messages(findings) -> str:
    return " | ".join(f.message for f in findings)


def test_a_clean_lesson_has_no_findings(lesson, monkeypatch):
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])
    meta_for(trace, evidence=True)
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))
    assert claimledger.check_lesson(directory) == []


def test_a_handwritten_artefact_cannot_verify_a_claim(lesson, monkeypatch):
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])
    meta_for(trace, evidence=False)
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))

    findings = claimledger.check_lesson(directory)
    assert len(findings) == 1
    assert "cannot verify anything" in findings[0].message


def test_an_unverified_claim_may_point_at_a_handwritten_artefact(lesson, monkeypatch):
    # A draft is allowed to say where it expects the evidence to come from. It is not allowed to
    # say the evidence is already there.
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])
    meta_for(trace, evidence=False)
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt").replace("true", "false"))
    assert claimledger.check_lesson(directory) == []


def test_evidence_that_does_not_exist_is_caught(lesson, monkeypatch):
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])
    write(directory, GOOD_CLAIM.format(trace="corpora/nope.txt"))
    assert "does not exist" in messages(claimledger.check_lesson(directory))


def test_an_artefact_with_no_metadata_is_caught(lesson, monkeypatch):
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))
    assert "no .meta.toml" in messages(claimledger.check_lesson(directory))


def test_a_published_lesson_needs_every_claim_verified(lesson, monkeypatch):
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])
    meta_for(trace, evidence=True)
    (directory / "meta.toml").write_text('id = "Z02"\nstatus = "published"\n')
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt").replace("true", "false"))
    assert "marked published" in messages(claimledger.check_lesson(directory))


def test_a_draft_may_carry_unverified_claims(lesson, monkeypatch):
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])
    meta_for(trace, evidence=True)
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt").replace("true", "false"))
    assert claimledger.check_lesson(directory) == []


def test_ids_have_to_belong_to_the_lesson_and_be_unique(lesson, monkeypatch):
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])
    write(
        directory,
        """
schema = 1
lesson = "Z02"

[[claims]]
id = "S05-01"
text = "Wrong lesson."
evidence_kind = "experiment"

[[claims]]
id = "S05-01"
text = "Wrong lesson, again."
evidence_kind = "experiment"
""",
    )
    text = messages(claimledger.check_lesson(directory))
    assert "should start with Z02-" in text
    assert "duplicate id" in text


def test_an_unknown_evidence_kind_is_refused(lesson, monkeypatch):
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])
    write(
        directory,
        """
schema = 1
lesson = "Z02"

[[claims]]
id = "Z02-01"
text = "Somebody told me."
evidence_kind = "vibes"
""",
    )
    assert "is not one of" in messages(claimledger.check_lesson(directory))


def test_a_lesson_may_have_two_unobservable_claims_and_not_three(lesson, monkeypatch):
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])

    def claims(count: int) -> str:
        body = 'schema = 1\nlesson = "Z02"\n'
        for i in range(1, count + 1):
            body += (
                f'\n[[claims]]\nid = "Z02-{i:02d}"\n'
                f'text = "Something nobody can watch, number {i}."\n'
                'evidence_kind = "unobservable"\n'
            )
        return body

    write(directory, claims(2))
    assert claimledger.check_lesson(directory) == []

    write(directory, claims(3))
    assert "the limit is 2" in messages(claimledger.check_lesson(directory))


def test_unobservable_and_verified_cannot_both_be_true(lesson, monkeypatch):
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])
    write(
        directory,
        """
schema = 1
lesson = "Z02"

[[claims]]
id = "Z02-01"
text = "Nobody can watch this."
evidence_kind = "unobservable"
verified = true
""",
    )
    assert "cannot both be true" in messages(claimledger.check_lesson(directory))


def test_a_lesson_with_no_claims_is_a_problem(lesson, monkeypatch):
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])
    write(directory, 'schema = 1\nlesson = "Z02"\n')
    assert "tells the reader nothing" in messages(claimledger.check_lesson(directory))


def test_a_lesson_with_no_metadata_is_a_problem(tmp_path):
    directory = tmp_path / "Z02"
    directory.mkdir()
    assert "no meta.toml" in messages(claimledger.check_lesson(directory))


def test_the_repository_passes(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    assert claimledger.main([]) == 0
