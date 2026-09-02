"""Tests for the lock order reader.

All three fixtures are handwritten and say so. What is being tested here is the parser, not a claim
about a kernel, and C09 rests on the reader running the module on their own machine and reading
their own splat rather than on any of these files.

The tests that matter most are the ones about refusing. A splat that is half pasted is the normal
way people bring one of these to somebody else, and a parser that fills in the missing half is
inventing a lock ordering. Getting a clear error is worth more than getting an answer.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from kxray import lockdep

ROOT = Path(__file__).resolve().parents[1]
SPLAT = ROOT / "corpora" / "oops" / "handwritten" / "lockdep-ab-ba.txt"
STATS = ROOT / "corpora" / "proc" / "handwritten" / "lockdep_stats.txt"
CLASSES = ROOT / "corpora" / "proc" / "handwritten" / "lockdep.txt"


def expected(path: Path) -> dict:
    return tomllib.loads(path.with_suffix(".meta.toml").read_text())


@pytest.fixture
def splat():
    return lockdep.parse_splat(SPLAT.read_text(), str(SPLAT))


@pytest.fixture
def want():
    return expected(SPLAT)


# The splat


def test_the_header_says_who_hit_it(splat, want):
    assert splat.task == want["task"]
    assert splat.pid == want["pid"]
    assert splat.kernel == "7.2.2"


def test_the_two_locks_in_the_header_come_apart(splat, want):
    assert splat.acquiring.name == want["acquiring"]
    assert splat.holding.name == want["holding"]
    assert splat.acquiring.function == "abba_second_thread"


def test_the_cycle_comes_back_in_order(splat, want):
    assert list(splat.cycle) == want["cycle"]
    assert splat.length == want["chain_length"]


def test_the_cycle_closes_on_itself(splat):
    assert splat.cycle[0] == splat.cycle[-1]
    assert splat.edges() == [("lock_a", "lock_b"), ("lock_b", "lock_a")]


def test_each_link_says_where_the_edge_was_learned(splat, want):
    ordered = sorted(splat.chain, key=lambda one: one.index)
    assert [one.taken_in for one in ordered] == want["recorded_in"]


def test_the_checker_frames_are_not_offered_as_the_place_to_look(splat):
    """The top of a lockdep stack is lockdep. Reporting that as the caller helps nobody."""
    assert not splat.link("lock_a").taken_in.startswith("check_prev_add")
    assert splat.link("lock_a").stack[0].startswith("check_prev_add")


def test_the_scenario_is_two_columns_of_two_steps(splat, want):
    assert len(splat.scenario.columns) == want["scenario_cpus"]
    assert splat.scenario.column(0) == ["lock(lock_a);", "lock(lock_b);"]
    assert splat.scenario.column(1) == ["lock(lock_b);", "lock(lock_a);"]


def test_the_scenario_agrees_with_the_chain(splat):
    """The picture is drawn from the same graph, so it can never say something else.

    This is a test about the kernel's own consistency rather than about the parser, and it is here
    because the picture is what people read and the chain is what is true.
    """
    first = [step.removeprefix("lock(").rstrip(");") for step in splat.scenario.column(0)]
    assert first == list(splat.classes)


# Refusing


def test_a_splat_cut_off_in_the_middle_is_refused():
    half = "\n".join(SPLAT.read_text().splitlines()[:22])
    with pytest.raises(lockdep.Truncated):
        lockdep.parse_splat(half)


def test_a_chain_with_a_gap_in_it_is_refused():
    text = SPLAT.read_text().replace("-> #1 (lock_b)", "-> #2 (lock_b)")
    with pytest.raises(lockdep.Truncated, match="gap"):
        lockdep.parse_splat(text)


def test_a_chain_that_does_not_match_its_own_header_is_refused():
    """If the numbered chain and the header disagree, guessing which one is right is not on offer."""
    text = SPLAT.read_text().replace("-> #0 (lock_a)", "-> #0 (lock_c)")
    with pytest.raises(lockdep.Truncated, match="lock_c"):
        lockdep.parse_splat(text)


def test_text_with_no_report_in_it_is_refused():
    with pytest.raises(lockdep.NotASplat):
        lockdep.parse_splat("hello, this is a kernel log with nothing wrong in it\n")


def test_a_different_kind_of_lockdep_report_says_which_kind_it_is():
    text = "WARNING: possible recursive locking detected\n"
    with pytest.raises(lockdep.NotASplat, match="recursive"):
        lockdep.parse_splat(text)


def test_the_first_splat_in_a_ring_buffer_is_dropped_rather_than_repaired():
    """A dmesg buffer wraps, so its oldest report is usually missing its top half."""
    whole = SPLAT.read_text()
    log = "\n".join(whole.splitlines()[20:]) + "\n\n" + whole
    found = lockdep.splats(log)
    assert len(found) == 1
    assert found[0].cycle[0] == "lock_a"


# The printk prefix


def test_a_timestamp_in_front_of_every_line_changes_nothing(splat):
    bare = "\n".join(lockdep.unprefix(line) for line in SPLAT.read_text().splitlines())
    assert lockdep.parse_splat(bare).cycle == splat.cycle


def test_a_facility_marker_in_front_of_a_timestamp_is_also_dropped():
    assert lockdep.unprefix("<4>[  142.001238] abba") == "abba"


# The statistics


@pytest.fixture
def stats():
    return lockdep.parse_stats(STATS.read_text(), str(STATS))


def test_every_numbered_line_is_read(stats):
    assert len(stats.values) == expected(STATS)["values"]


def test_the_lines_with_a_limit_keep_their_limit(stats):
    assert len(stats.maxima) == expected(STATS)["lines_with_a_limit"]
    assert stats.maxima["lock_classes"] == 8192


def test_hyphens_and_spaces_end_up_spelled_the_same_way(stats):
    assert stats.values["lock_classes"] == expected(STATS)["lock_classes"]
    assert stats.values["direct_dependencies"] == expected(STATS)["direct_dependencies"]


def test_the_checker_reports_itself_as_off(stats):
    assert stats.debug_locks == 0
    assert stats.off is expected(STATS)["checker_off"]


def test_a_line_with_no_limit_has_no_headroom(stats):
    assert stats.headroom("debug_locks") is None
    assert stats.headroom("nothing at all") is None


def test_nothing_on_this_machine_is_near_a_limit(stats):
    assert stats.near_limits() == []
    assert stats.near_limits(0.25)[0][0] == "direct_dependencies"


# The lock classes


@pytest.fixture
def classes():
    return lockdep.parse_classes(CLASSES.read_text())


def test_every_class_line_is_read(classes):
    assert len(classes) == expected(CLASSES)["classes"]


def test_a_class_line_comes_apart_into_its_pieces(classes):
    one = next(c for c in classes if c.name == "lock_a")
    assert (one.forward, one.backward, one.usage) == (2, 1, "+.+.")


def test_one_line_of_source_can_be_two_lock_classes(classes):
    """The suffix is lockdep splitting a class by nesting depth, and it is why a report is about
    a line of code rather than about the object you were holding."""
    split = [c for c in classes if c.name.startswith("&sb->s_type->i_mutex_key")]
    assert len(split) == 2
    assert [c.subclass for c in split] == ["", "3"]


def test_the_busiest_class_is_the_one_with_the_most_below_it(classes):
    assert lockdep.busiest(classes, 1)[0].name == expected(CLASSES)["busiest"]


def test_reading_can_be_stopped_early(classes):
    assert len(lockdep.parse_classes(CLASSES.read_text(), limit=3)) == 3


# The runtime


def test_a_machine_without_lockdep_says_why():
    assert lockdep.explain(Path("/definitely/not/here")) != ""


def test_reading_statistics_that_are_not_there_gives_nothing_rather_than_raising():
    assert lockdep.read_stats(Path("/definitely/not/here")) is None


# The real capture
#
# Everything above this line runs against fixtures written by hand, which is what let the parser
# exist before there was a kernel to take a report off. These run against the report the pinned
# kernel actually printed, and they are here to catch the thing that keeps happening in this
# project, which is that a file written from reading the source disagrees with the machine.

REAL_SPLAT = ROOT / "corpora" / "oops" / "tier0" / "lockdep-ab-ba.txt"
BEFORE = ROOT / "corpora" / "proc" / "tier0" / "lockdep-stats-before.txt"
AFTER = ROOT / "corpora" / "proc" / "tier0" / "lockdep-stats-after.txt"


def test_the_real_report_parses_and_says_what_its_metadata_says():
    got = lockdep.parse_splat(REAL_SPLAT.read_text(), str(REAL_SPLAT))
    want = expected(REAL_SPLAT)
    assert got.task == want["task"]
    assert got.pid == want["pid"]
    assert got.holding.name == want["holding"]
    assert got.acquiring.name == want["acquiring"]
    assert list(got.cycle) == want["cycle"]


def test_the_run_that_produced_the_report_never_waited_for_anything():
    """C09-02. The module says so, on the line after the report rather than before it."""
    lines = REAL_SPLAT.read_text().splitlines()
    banner = next(i for i, one in enumerate(lines) if "circular locking dependency" in one)
    done = next(i for i, one in enumerate(lines) if "nothing waited for anything" in one)
    assert done > banner


def test_the_report_draws_two_cpus_on_a_machine_that_has_one():
    """Lockdep prints the interleaving that would deadlock, not the one that happened."""
    got = lockdep.parse_splat(REAL_SPLAT.read_text(), str(REAL_SPLAT))
    assert expected(REAL_SPLAT)["uniprocessor"] is True
    assert list(got.scenario.columns) == ["CPU0", "CPU1"]


def test_the_checker_was_on_before_the_report_and_off_after_it():
    """C09-04. Two readings, one boot, the insmod in between."""
    before = lockdep.parse_stats(BEFORE.read_text(), str(BEFORE))
    after = lockdep.parse_stats(AFTER.read_text(), str(AFTER))
    assert before.debug_locks == 1 and not before.off
    assert after.debug_locks == 0 and after.off


def test_switching_the_checker_off_did_not_shrink_the_graph():
    """Everything except debug_locks went up. The graph is bigger and nobody consults it."""
    before = lockdep.parse_stats(BEFORE.read_text(), str(BEFORE))
    after = lockdep.parse_stats(AFTER.read_text(), str(AFTER))
    for field in ("lock_classes", "direct_dependencies", "dependency_chains"):
        assert after.values[field] > before.values[field], field
