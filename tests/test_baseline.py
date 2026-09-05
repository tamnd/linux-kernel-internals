"""Tests for the unparsed line baseline.

The one that matters is `test_a_line_sliding_from_read_to_skipped_is_caught`. Everything else in
this project already fails loudly when a parser cannot read a line. Nothing fails when a parser
decides a line was never data in the first place, and that is the failure a reader finds instead
of CI.
"""

import tomllib
from pathlib import Path

import pytest

from kxray import kallsyms, lockdep, tracefs
from kxray.models import Lines
from kxray.trace import parse_file
from tools import baseline

ROOT = Path(__file__).resolve().parents[1]
CORPORA = ROOT / "corpora"


@pytest.fixture
def here(monkeypatch):
    monkeypatch.chdir(ROOT)


ARTEFACTS = sorted(
    one
    for one in CORPORA.rglob("*")
    if one.is_file() and one.suffix != ".toml" and one.with_suffix(".meta.toml").exists()
)


def test_the_corpus_is_not_empty():
    assert ARTEFACTS


@pytest.mark.parametrize("artefact", ARTEFACTS, ids=lambda p: p.relative_to(CORPORA).as_posix())
def test_every_artefact_has_a_reader(artefact, here):
    # An artefact nothing opens is how a file ends up committed that has never been read.
    assert baseline.route(artefact.relative_to(ROOT)) is not None


@pytest.mark.parametrize("artefact", ARTEFACTS, ids=lambda p: p.relative_to(CORPORA).as_posix())
def test_every_line_is_accounted_for(artefact, here):
    """read plus skipped plus unparsed is the number of lines in the file, or the reader is wrong.

    This is the check that makes the rest of the numbers mean anything. A reader that classifies
    some lines and forgets others can report zero unparsed lines forever while understanding less
    and less of the file.
    """
    reading = baseline.read_one(artefact.relative_to(ROOT))
    if reading.accounted is None:
        pytest.skip(f"{reading.reader} does not account for lines")
    assert reading.accounted.total == reading.lines


def test_the_committed_baseline_matches_the_corpus(here):
    assert baseline.main([]) == 0


def test_the_totals_are_the_sum_of_the_rows(here):
    recorded = tomllib.loads(baseline.BASELINE.read_text())
    rows = recorded["artefact"]
    assert recorded["totals"]["artefacts"] == len(rows)
    assert recorded["totals"]["lines"] == sum(one["lines"] for one in rows)
    for name in ("read", "skipped", "unparsed"):
        assert recorded["totals"][name] == sum(one.get(name, 0) for one in rows)


def test_nothing_in_the_corpus_is_unparsed_today(here):
    # Not a rule, a fact. The rule is that the number is written down, and a capture that needs a
    # non zero number here is allowed as long as the commit that adds it says so.
    assert tomllib.loads(baseline.BASELINE.read_text())["totals"]["unparsed"] == 0


# What the tool does when something moves.


def readings(**changes) -> list[baseline.Reading]:
    """One row, with some of it changed."""
    fields = {
        "path": "corpora/traces/tier0/write-1byte.txt",
        "reader": "function_graph",
        "lines": 10,
        "found": 4,
        "accounted": Lines(read=8, skipped=2),
    }
    fields.update(changes)
    return [baseline.Reading(**fields)]


def recorded(rows: list[baseline.Reading]) -> dict:
    return {"schema": baseline.SCHEMA, "artefact": [one.row() for one in rows]}


def test_a_matching_pair_has_nothing_to_say():
    assert baseline.compare(readings(), recorded(readings())) == []


def test_a_line_sliding_from_read_to_skipped_is_caught():
    """The headline case, and the only one nothing else in the build would notice.

    Total lines are the same, unparsed is still zero, no exception was raised and no warning was
    printed. The only evidence that a parser stopped understanding a line is that a number which
    was written down last week is a different number this week.
    """
    problems = baseline.compare(readings(accounted=Lines(read=7, skipped=3)), recorded(readings()))
    assert "read was 8, is now 7" in " ".join(problems)
    assert "skipped was 2, is now 3" in " ".join(problems)


def test_fewer_things_found_is_caught_even_when_the_lines_do_not_move():
    problems = baseline.compare(readings(found=3), recorded(readings()))
    assert "found was 4, is now 3" in " ".join(problems)


def test_an_artefact_that_is_new_and_one_that_is_gone_are_both_caught():
    problems = baseline.compare(readings(path="corpora/traces/tier0/new.txt"), recorded(readings()))
    assert "new.txt is in the corpus and not in the baseline" in " ".join(problems)
    assert "write-1byte.txt is in the baseline and not in the corpus" in " ".join(problems)


def test_a_baseline_written_by_an_older_tool_is_refused():
    was = recorded(readings())
    was["schema"] = 0
    assert "baseline schema is 0" in " ".join(baseline.compare(readings(), was))


def test_what_is_written_reads_back_as_what_was_measured(here):
    rows = baseline.survey()
    again = tomllib.loads(baseline.as_toml(rows))
    assert baseline.compare(rows, again) == []


def test_an_artefact_nothing_reads_is_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "corpora" / "mystery").mkdir(parents=True)
    (tmp_path / "corpora" / "mystery" / "thing.log").write_text("hello\n")
    (tmp_path / "corpora" / "mystery" / "thing.meta.toml").write_text("evidence = false\n")
    with pytest.raises(LookupError, match="no reader"):
        baseline.survey()


# The readers themselves, one case each for the distinction that reader exists to make.


def test_kallsyms_counts_a_line_it_cannot_read_rather_than_dropping_it():
    text = "c1000000 T do_sys_open\nnot a symbol at all\n\n"
    assert kallsyms.account(text) == Lines(read=1, skipped=1, unparsed=1)
    assert len(kallsyms.parse(text)) == 1


def test_the_lockdep_class_header_is_skipped_and_a_broken_row_is_not():
    text = "all lock classes:\nc1a0b100 FD:    1 BD:    1 ....: cpu_hotplug_lock\nc1a0b1a0 FD: ?\n"
    assert lockdep.account_classes(text) == Lines(read=1, skipped=1, unparsed=1)


def test_a_stats_line_with_no_number_on_it_is_unparsed():
    text = " lock-classes:   401 [max: 8192]\n in-hardirq chains:\n"
    assert lockdep.account_stats(text) == Lines(read=1, skipped=0, unparsed=1)


def test_a_ring_buffer_timestamp_is_skipped_and_not_counted_as_a_failure():
    # A counter this reader does not collect and a counter it could not read are different things,
    # and the old code could not tell them apart.
    text = "entries: 273\noldest event ts:     2.109723\nnonsense\n"
    assert tracefs.account_stats(text) == Lines(read=1, skipped=1, unparsed=1)
    assert tracefs.parse_stats(text) == {"entries": 273}


def test_a_trace_puts_its_header_and_its_separators_in_the_skipped_bucket():
    tape = parse_file(CORPORA / "traces" / "tier0" / "write-1byte.txt")
    assert tape.lines.skipped
    assert tape.lines.unparsed == 0
    assert tape.lines.total == len(
        (CORPORA / "traces" / "tier0" / "write-1byte.txt").read_text().splitlines()
    )


def test_an_unreadable_trace_line_lands_in_the_unparsed_bucket():
    tape = parse_file(CORPORA / "traces" / "tier0" / "write-1byte.txt")
    before = tape.lines.unparsed
    from kxray.trace import parse

    broken = parse(" 0)   1.234 us    |  what is this\n")
    assert broken.lines.unparsed == 1
    assert before == 0


def test_the_three_buckets_and_the_string_agree():
    counted = Lines()
    for verdict in ("read", "read", "skipped", "unparsed"):
        counted.count(verdict)
    assert counted.total == 4
    assert str(counted) == "2 read, 1 skipped, 1 unparsed"
