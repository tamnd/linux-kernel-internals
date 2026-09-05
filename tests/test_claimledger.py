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


# What every lesson has to say about the machine its claims are about.
DECLARATION = 'kernel = "7.2.2"\narch = "x86"\nprofile = "A-full"\ntier = 0\n'

# A pin with two trees and three profiles on them, which is the shape of the real one.
PIN = """
[kernel]
version = "7.2.2"

[fallback]
version = "6.18.48"

[[profiles]]
name = "A-full"
kernel = "kernel"

[[profiles]]
name = "C-longterm"
kernel = "fallback"

[[profiles]]
name = "D-lockdep"
kernel = "kernel"
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
    (directory / "meta.toml").write_text(DECLARATION + 'id = "Z02"\nstatus = "draft"\n')
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
    (directory / "meta.toml").write_text(DECLARATION + 'id = "Z02"\nstatus = "published"\n')
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


# Which machine the lesson is about, and whether the evidence came off it.


def declare(directory: Path, **changes) -> None:
    """Rewrite the lesson declaration with some of it changed."""
    fields = {"kernel": "7.2.2", "arch": "x86", "profile": "A-full", "tier": 0}
    fields.update(changes)
    body = "".join(_line(name, value) for name, value in fields.items() if value is not None)
    (directory / "meta.toml").write_text(body + 'id = "Z02"\nstatus = "draft"\n')


def _line(name: str, value) -> str:
    return f'{name} = "{value}"\n' if isinstance(value, str) else f"{name} = {value}\n"


def machine_for(trace: Path, **fields) -> None:
    """Metadata on an artefact saying which machine it came off."""
    body = 'source = "capture"\nevidence = true\n'
    trace.with_suffix(".meta.toml").write_text(
        body + "".join(_line(name, value) for name, value in fields.items())
    )


@pytest.fixture
def pinned(lesson, monkeypatch, tmp_path):
    """The lesson fixture, with a pin.toml where the tool looks for one."""
    directory, trace = lesson
    (tmp_path / "kxbox" / "kernel").mkdir(parents=True)
    (tmp_path / claimledger.PIN).write_text(PIN)
    monkeypatch.chdir(tmp_path)
    return directory, trace


@pytest.mark.parametrize("missing", claimledger.DECLARED)
def test_a_lesson_has_to_say_which_machine_its_claims_are_about(pinned, missing):
    directory, trace = pinned
    declare(directory, **{missing: None})
    machine_for(trace)
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))
    assert f"no {missing}, so its claims are about no machine" in messages(
        claimledger.check_lesson(directory)
    )


def test_a_profile_nobody_builds_is_caught(pinned):
    directory, trace = pinned
    declare(directory, profile="A-wishful")
    machine_for(trace)
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))
    assert "'A-wishful' is not one of" in messages(claimledger.check_lesson(directory))


def test_a_profile_that_builds_another_kernel_is_caught(pinned):
    # This is the one that catches a stale lesson after somebody bumps the pin.
    directory, trace = pinned
    declare(directory, kernel="7.2.1")
    machine_for(trace)
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))
    assert "but profile 'A-full' builds '7.2.2'" in messages(claimledger.check_lesson(directory))


def test_a_profile_on_the_fallback_tree_is_held_to_the_fallback_version(pinned):
    # C-longterm is the whole point of reading the profile rather than the pin. It is a real
    # profile on a real tree and it is not on the version everything else is on.
    directory, trace = pinned
    machine_for(trace)
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))

    declare(directory, profile="C-longterm")
    assert "builds '6.18.48'" in messages(claimledger.check_lesson(directory))

    declare(directory, profile="C-longterm", kernel="6.18.48")
    assert claimledger.check_lesson(directory) == []


def test_there_is_no_tier_two(pinned):
    directory, trace = pinned
    declare(directory, tier=2)
    machine_for(trace)
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))
    assert "tier 2 is not 0 or 1" in messages(claimledger.check_lesson(directory))


def test_evidence_off_another_machine_needs_a_reason(pinned):
    directory, trace = pinned
    declare(directory)
    machine_for(trace, kernel="6.8.0-117-generic", arch="aarch64", profile="A-full", tier=1)
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))

    text = messages(claimledger.check_lesson(directory))
    assert "needs a why_not_pinned" in text
    assert "kernel '6.8.0-117-generic' rather than '7.2.2'" in text
    assert "arch 'aarch64' rather than 'x86'" in text
    assert "tier 1 rather than 0" in text


def test_a_reason_that_is_a_real_sentence_settles_it(pinned):
    directory, trace = pinned
    declare(directory)
    machine_for(trace, kernel="6.8.0-117-generic", arch="aarch64", tier=1)
    write(
        directory,
        GOOD_CLAIM.format(trace="corpora/one.txt")
        + 'why_not_pinned = "v86 is a uniprocessor emulator, so a trace with two CPUs in it '
        'cannot be captured on Tier 0 at any price."\n',
    )
    assert claimledger.check_lesson(directory) == []


def test_two_words_is_not_a_reason(pinned):
    # The length is arbitrary and the thing it is defending against is not. "n/a" is what somebody
    # writes when the checker is in their way, and a checker a person can wave through is decoration.
    directory, trace = pinned
    declare(directory)
    machine_for(trace, arch="aarch64")
    write(
        directory,
        GOOD_CLAIM.format(trace="corpora/one.txt") + 'why_not_pinned = "see above"\n',
    )
    assert "which is not a reason" in messages(claimledger.check_lesson(directory))


def test_a_reason_for_a_difference_that_is_gone_is_caught(pinned):
    # A wrong explanation is worse than none, because a reader believes it.
    directory, trace = pinned
    declare(directory)
    machine_for(trace, kernel="7.2.2", arch="x86", profile="A-full", tier=0)
    write(
        directory,
        GOOD_CLAIM.format(trace="corpora/one.txt")
        + 'why_not_pinned = "v86 is a uniprocessor emulator, so this had to be captured '
        'somewhere else."\n',
    )
    assert "explains a difference that is not there" in messages(
        claimledger.check_lesson(directory)
    )


def test_the_same_architecture_under_two_names_is_not_a_difference(pinned):
    directory, trace = pinned
    declare(directory, arch="x86")
    machine_for(trace, arch="i686")
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))
    assert claimledger.check_lesson(directory) == []


def test_an_architecture_nobody_has_heard_of_fails_rather_than_matches(pinned):
    directory, trace = pinned
    declare(directory, arch="x86")
    machine_for(trace, arch="sparc64")
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))
    assert "arch 'sparc64' rather than 'x86'" in messages(claimledger.check_lesson(directory))


def test_an_artefact_that_says_nothing_about_its_machine_is_not_a_disagreement(pinned):
    # Older artefacts predate this rule. Silence is not a claim, so it is not a conflict either.
    directory, trace = pinned
    declare(directory)
    machine_for(trace)
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))
    assert claimledger.check_lesson(directory) == []


def test_an_experiment_is_held_to_the_same_rule_as_a_trace(pinned):
    # `experiment` is not in FILE_KINDS, so nothing checks that its file exists. When it does exist
    # and has metadata beside it, the question of which machine it came off is exactly the same.
    directory, trace = pinned
    declare(directory)
    machine_for(trace, arch="aarch64", tier=1)
    write(
        directory,
        GOOD_CLAIM.format(trace="corpora/one.txt").replace('"trace"', '"experiment"'),
    )
    assert "needs a why_not_pinned" in messages(claimledger.check_lesson(directory))


def test_the_real_pin_has_the_profiles_the_lessons_name(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    built = claimledger.profiles()
    assert built["A-full"] == "7.2.2"
    assert built["D-lockdep"] == "7.2.2"
    assert built["C-longterm"] == "6.18.48"


def test_a_missing_pin_stops_the_profile_check_rather_than_the_run(lesson, monkeypatch):
    # The pin is read from the working directory, and a lesson checked from somewhere else should
    # report what it can rather than fail on a file it was never going to find.
    directory, trace = lesson
    monkeypatch.chdir(trace.parents[1])
    declare(directory, profile="A-wishful")
    machine_for(trace)
    write(directory, GOOD_CLAIM.format(trace="corpora/one.txt"))
    assert claimledger.check_lesson(directory) == []
