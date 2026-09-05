"""Tests for the coverage ledger.

The one that matters is `test_a_cited_path_with_no_owner_is_a_failure`. Everything else in this
file guards a rule that keeps that one true. A ledger nobody checks both ways stops describing the
repository within about a month, and then the headline rule is passing over a document that says
nothing.
"""

from __future__ import annotations

import pytest

from tools import coverage

REAL = coverage.load()
ENTRIES, DOCUMENT = REAL
CITED = coverage.citations()


def entry(
    name: str = "mm",
    status: str = "partial",
    paths: tuple[str, ...] = ("mm/filemap.c",),
    lessons: tuple[str, ...] = (),
    blueprints: tuple[str, ...] = ("page-fault",),
    reason: str = "",
    note: str = "",
) -> coverage.Subsystem:
    return coverage.Subsystem(
        name=name,
        status=status,
        paths=list(paths),
        lessons=list(lessons),
        blueprints=list(blueprints),
        reason=reason,
        note=note,
    )


def everything() -> coverage.Subsystem:
    """One entry owning every top-level directory, so a test only sees what it is testing."""
    return entry(
        name="everything",
        status="mentioned",
        paths=tuple(f"{one}/" for one in coverage.TOP_LEVEL),
        blueprints=(),
    )


def ledger(*entries: coverage.Subsystem) -> list[coverage.Subsystem]:
    # The catch-all goes last, so a test entry naming a longer prefix wins the file it claims.
    return [*entries, everything()]


def check(*entries: coverage.Subsystem, cited: list[coverage.Citation] | None = None) -> list[str]:
    return [str(one) for one in coverage.check(ledger(*entries), {"schema": 1}, cited or [])]


def cite(path: str, document: str = "Z02") -> list[coverage.Citation]:
    return [coverage.Citation(path, document)]


# --- the real ledger ------------------------------------------------------------------------


def test_the_ledger_in_the_repository_passes_its_own_checks():
    assert coverage.check(ENTRIES, DOCUMENT, CITED) == []


def test_the_checker_exits_zero_on_the_repository():
    assert coverage.main([]) == 0


@pytest.mark.parametrize("path", sorted({one.path for one in CITED}))
def test_every_cited_path_has_an_owner(path):
    assert coverage.owner(ENTRIES, path) is not None


@pytest.mark.parametrize("directory", coverage.TOP_LEVEL)
def test_every_top_level_directory_of_the_kernel_has_an_owner(directory):
    assert coverage.owner(ENTRIES, f"{directory}/") is not None


def test_the_project_cites_both_lessons_and_blueprints():
    documents = {one.document for one in CITED}
    assert {"Z02", "S05", "C09", "page-fault", "write-path"} <= documents


def test_nothing_is_taught_yet():
    # Not an aspiration. If this starts failing, a subsystem earned the status and this test is
    # the place to say so.
    assert [one.name for one in ENTRIES if one.status == "taught"] == []


def test_nothing_is_taught_because_no_blueprint_is_complete():
    statuses = {name: coverage.blueprint_status(name) for name in ("page-fault", "write-path")}
    assert "complete" not in statuses.values()


# --- the rule this file exists for ----------------------------------------------------------


def test_a_cited_path_with_no_owner_is_a_failure():
    problems = check(cited=cite("accel/drm/thing.c"))
    assert any("no subsystem in coverage.toml owns it" in one for one in problems)


def test_the_failure_says_what_to_do_about_it():
    problems = check(cited=cite("accel/drm/thing.c"))
    assert any("Add an entry, or stop citing it" in one for one in problems)


def test_the_failure_names_the_document_that_cited_it():
    problems = check(cited=cite("accel/drm/thing.c", "S05"))
    assert problems[0].startswith("S05: cites accel/drm/thing.c")


def test_a_document_reaching_into_a_subsystem_has_to_be_named_on_it():
    # The scope creep case. `net/` has an entry, so the citation is owned, and the ledger still has
    # to be edited before the build goes green.
    problems = check(
        entry(name="net", status="mentioned", paths=("net/",), blueprints=()),
        cited=cite("net/core/dev.c"),
    )
    assert "coverage.toml [net]: Z02 cites it and is not named on the entry" in problems


def test_an_entry_naming_a_document_that_cites_nothing_it_owns():
    problems = check(entry(lessons=("S05",), blueprints=()), cited=cite("mm/filemap.c", "S05"))
    assert problems == []
    stale = check(entry(lessons=("S05",), blueprints=()))
    assert "coverage.toml [mm]: names S05, which cites nothing it owns" in stale


# --- ownership ------------------------------------------------------------------------------


def test_the_longest_prefix_owns_the_file():
    entries = ledger(
        entry(name="mm", paths=("mm/",)),
        entry(name="writeback", paths=("mm/page-writeback.c",)),
    )
    assert coverage.owner(entries, "mm/page-writeback.c").name == "writeback"
    assert coverage.owner(entries, "mm/filemap.c").name == "mm"


def test_a_directory_prefix_does_not_reach_past_its_own_directory():
    assert entry(paths=("mm/",)).owns("mmc/core/core.c") is None


def test_a_prefix_matching_nothing_owns_nothing():
    assert entry(paths=("mm/",)).owns("fs/open.c") is None


def test_an_exact_path_owns_itself():
    assert entry(paths=("fs/open.c",)).owns("fs/open.c") == "fs/open.c"


def test_a_directory_written_without_its_slash_is_refused():
    problems = check(entry(name="x86", paths=("arch/x86",)))
    assert any("write it as arch/x86/" in one for one in problems)


def test_two_entries_claiming_the_same_prefix_is_refused():
    problems = check(
        entry(name="mm", paths=("mm/",)),
        entry(name="memory", paths=("mm/",), blueprints=("write-path",)),
    )
    assert any("claims mm/, and so does mm" in one for one in problems)


def test_a_top_level_directory_with_no_owner_is_refused():
    problems = [str(one) for one in coverage.check([entry(paths=("mm/",))], {"schema": 1}, [])]
    assert any("nothing owns net/" in one for one in problems)


# --- statuses -------------------------------------------------------------------------------


def test_taught_needs_a_complete_blueprint():
    problems = check(entry(status="taught", lessons=("S05",), blueprints=("page-fault",)))
    assert any("taught needs a complete blueprint" in one for one in problems)


def test_taught_needs_a_lesson():
    problems = check(entry(status="taught", blueprints=("page-fault",)))
    assert any("taught with no lesson behind it" in one for one in problems)


def test_partial_needs_something_written_about_it():
    problems = check(entry(status="partial", blueprints=()))
    assert any("partial with nothing written about it" in one for one in problems)


def test_partial_is_happy_with_a_blueprint_and_no_lesson():
    # Which is where mm is today, and the reason partial does not insist on a lesson.
    assert (
        check(
            entry(status="partial", blueprints=("page-fault",)),
            cited=cite("mm/filemap.c", "page-fault"),
        )
        == []
    )


def test_mentioned_may_not_name_a_blueprint():
    problems = check(entry(status="mentioned", blueprints=("page-fault",)))
    assert any("mentioned owes no blueprint" in one for one in problems)


def test_out_of_scope_needs_a_reason():
    problems = check(entry(status="out-of-scope", blueprints=()))
    assert any("out of scope needs a reason" in one for one in problems)


def test_a_short_reason_is_not_a_reason():
    problems = check(entry(status="out-of-scope", blueprints=(), reason="not needed"))
    assert any("out of scope needs a reason" in one for one in problems)


def test_a_reason_in_a_sentence_is_accepted():
    long_enough = "Build plumbing with no runtime behaviour a reader can watch happen."
    assert check(entry(status="out-of-scope", blueprints=(), reason=long_enough)) == []


def test_citing_into_an_out_of_scope_subsystem_is_a_contradiction():
    reason = "Build plumbing with no runtime behaviour a reader can watch happen."
    problems = check(
        entry(name="certs", status="out-of-scope", paths=("certs/",), blueprints=(), reason=reason),
        cited=cite("certs/system_keyring.c"),
    )
    assert any("which certs declares out of scope" in one for one in problems)


def test_a_status_nobody_defined_is_refused():
    problems = check(entry(status="mostly", blueprints=()))
    assert any("is not one of" in one for one in problems)


# --- entries --------------------------------------------------------------------------------


def test_an_entry_with_no_paths_owns_nothing_and_says_so():
    problems = check(entry(paths=()))
    assert any("no paths, so it owns nothing" in one for one in problems)


def test_a_name_declared_twice_is_refused():
    problems = check(entry(paths=("mm/",)), entry(paths=("fs/open.c",)))
    assert any("declared twice" in one for one in problems)


def test_an_entry_with_no_name_is_refused():
    problems = check(entry(name="", blueprints=()))
    assert any("an entry with no name" in one for one in problems)


def test_an_entry_naming_a_lesson_that_does_not_exist():
    problems = check(entry(lessons=("Q99",)))
    assert any("names lesson Q99, which does not exist" in one for one in problems)


def test_an_entry_naming_a_blueprint_that_does_not_exist():
    problems = check(entry(blueprints=("not-a-blueprint",)))
    assert any("names blueprint not-a-blueprint, which does not exist" in one for one in problems)


def test_a_blueprint_that_does_not_exist_has_no_status():
    assert coverage.blueprint_status("not-a-blueprint") is None


def test_a_blueprint_that_exists_has_the_status_in_its_front_matter():
    assert coverage.blueprint_status("page-fault") == "partial"


# --- the file -------------------------------------------------------------------------------


def test_the_schema_is_checked():
    problems = [str(one) for one in coverage.check(ledger(), {"schema": 99}, [])]
    assert any("schema should be 1" in one for one in problems)


def test_an_empty_ledger_says_so_and_stops():
    problems = [str(one) for one in coverage.check([], {"schema": 1}, [])]
    assert problems == ["coverage.toml: no subsystems, so nothing is declared"]


def test_the_ledger_on_disk_is_the_schema_this_tool_writes():
    assert DOCUMENT["schema"] == coverage.SCHEMA


def test_every_entry_says_something_about_itself():
    # A ledger of bare statuses is a ledger nobody trusts, so every entry carries a sentence.
    assert [one.name for one in ENTRIES if not (one.note or one.reason)] == []


# --- output ---------------------------------------------------------------------------------


def test_show_groups_by_status_and_counts():
    printed = coverage.show(ENTRIES)
    assert "taught (0)" in printed
    assert "partial (7)" in printed


def test_show_says_when_there_is_nothing_behind_an_entry():
    assert "nothing yet" in coverage.show([entry(status="mentioned", blueprints=())])


def test_the_cited_table_names_the_owner_of_every_path():
    printed = coverage.cited_table(ENTRIES, CITED)
    assert "kernel/locking/lockdep.c" in printed
    assert "NOBODY" not in printed


def test_the_cited_table_says_nobody_when_nobody_owns_it():
    printed = coverage.cited_table([entry()], cite("accel/drm/thing.c"))
    assert "NOBODY" in printed


def test_show_and_cited_run_from_the_command_line():
    assert coverage.main(["--show"]) == 0
    assert coverage.main(["--cited"]) == 0
