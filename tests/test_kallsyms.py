"""Tests for the kernel symbol table reader.

The fixture is handwritten and says so, which is fine here, because what is being tested is the
parser rather than a claim about a kernel. S05 rests on the reader running this against their own
`/proc/kallsyms` and counting what is really there.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from kxray import kallsyms

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "corpora" / "proc" / "handwritten" / "kallsyms.txt"
META = FIXTURE.with_suffix(".meta.toml")


@pytest.fixture
def found():
    return kallsyms.parse(FIXTURE.read_text())


@pytest.fixture
def expected():
    return tomllib.loads(META.read_text())


def test_every_line_is_a_symbol(found, expected):
    assert len(found) == expected["symbols"]


def test_a_line_comes_apart_into_its_four_pieces(found):
    one = next(s for s in found if s.name == "e1000_netdev_ops")
    assert one.kind == "R"
    assert one.module == "e1000"
    assert one.address == 0


def test_a_symbol_from_the_kernel_itself_has_no_module(found):
    assert next(s for s in found if s.name == "vfs_write").module == ""


def test_the_ops_tables_are_found_by_name(found, expected):
    assert len(kallsyms.ops_tables(found)) == expected["ops_tables"]


def test_the_three_spellings_are_all_counted(found):
    assert set(kallsyms.families(found)) == {"operations", "ops", "fops"}


def test_the_families_come_back_most_common_first(found):
    counts = list(kallsyms.families(found).values())
    assert counts == sorted(counts, reverse=True)


def test_the_naming_convention_misses_some(found):
    """ext4_aops is an ops table and does not end in any of the three suffixes.

    Worth a test rather than a footnote. A count of ops tables taken from names is a lower bound,
    and a lesson that presented it as a total would be teaching something false.
    """
    assert not next(s for s in found if s.name == "ext4_aops").is_ops


def test_most_ops_tables_are_in_read_only_data(found, expected):
    tables = kallsyms.ops_tables(found)
    assert sum(1 for one in tables if one.readonly) == expected["readonly_ops"]


def test_a_writable_ops_table_is_not_read_only(found):
    one = next(s for s in found if s.name == "loop_mq_ops")
    assert one.writable
    assert not one.readonly


def test_zeroed_addresses_are_reported_as_hidden(found, expected):
    assert kallsyms.hidden(found) is expected["addresses_hidden"]


def test_real_addresses_are_not_reported_as_hidden():
    found = kallsyms.parse("ffffffff81000000 T vfs_write\n0000000000000000 T vfs_read\n")
    assert kallsyms.hidden(found) is False


def test_a_line_that_makes_no_sense_is_skipped_rather_than_fatal():
    text = "not a symbol at all\nffffffff81000000 T vfs_write\nzzzz T bad_address\n\n"
    found = kallsyms.parse(text)
    assert [one.name for one in found] == ["vfs_write"]


def test_searching_by_name_keeps_the_order_the_file_had(found):
    names = [one.name for one in kallsyms.named(found, "ext4")]
    assert names[0] == "ext4_file_operations"
    assert "ext4_file_write_iter" in names


def test_a_machine_with_no_proc_says_why(tmp_path):
    missing = tmp_path / "kallsyms"
    assert kallsyms.find(missing) is None
    assert kallsyms.available(missing) is False
    assert "kallsyms" in kallsyms.explain(missing)


def test_the_report_reads_a_file_when_there_is_one(tmp_path, capsys):
    copy = tmp_path / "kallsyms"
    copy.write_text(FIXTURE.read_text())
    text = kallsyms.report(copy)
    assert "13 tables named like one" in text
    assert "hidden, so you are not root" in text
    assert capsys.readouterr().out.strip() == text.strip()
