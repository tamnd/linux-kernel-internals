"""Tests for the /proc readers and for the stability ledger they all carry.

The corpus tests read the eight committed captures and compare them against the numbers in their
own metadata, so a kernel bump that changes any of them fails here rather than in a lesson. The
rest are small strings, and most of them are about the ways one of these files stops being the
simple thing it looks like: a value that is four values, a line with a field missing off the end
of it, and a command name with a bracket in it.
"""

import tomllib
from pathlib import Path

import pytest

from kxray import models, proc
from kxray.proc import keyed, maps, percpu, pidstat, stability, version

ROOT = Path(__file__).resolve().parents[1]
TIER0 = ROOT / "corpora" / "proc" / "tier0"

# The captures this package reads, with the file in /proc each one is a copy of. The lockdep and
# tracefs captures in the same directory belong to other readers and are not in here.
CAPTURES = {
    "version.txt": "/proc/version",
    "meminfo.txt": "/proc/meminfo",
    "interrupts.txt": "/proc/interrupts",
    "softirqs.txt": "/proc/softirqs",
    "self-maps.txt": "/proc/self/maps",
    "self-stat.txt": "/proc/self/stat",
    "self-status.txt": "/proc/self/status",
    "odd-comm-stat.txt": "/proc/self/stat",
}


def meta(name):
    return tomllib.loads((TIER0 / name).with_suffix(".meta.toml").read_text())


@pytest.fixture(scope="module")
def mem():
    return keyed.parse_file(TIER0 / "meminfo.txt", "/proc/meminfo")


@pytest.fixture(scope="module")
def status():
    return keyed.parse_file(TIER0 / "self-status.txt", "/proc/self/status")


@pytest.fixture(scope="module")
def irqs():
    return percpu.parse_file(TIER0 / "interrupts.txt", "/proc/interrupts")


@pytest.fixture(scope="module")
def softirqs():
    return percpu.parse_file(TIER0 / "softirqs.txt", "/proc/softirqs")


@pytest.fixture(scope="module")
def space():
    return maps.parse_file(TIER0 / "self-maps.txt", "/proc/self/maps")


@pytest.fixture(scope="module")
def ordinary():
    return pidstat.parse_file(TIER0 / "self-stat.txt", "/proc/self/stat")


@pytest.fixture(scope="module")
def odd():
    return pidstat.parse_file(TIER0 / "odd-comm-stat.txt", "/proc/self/stat")


# -- the committed captures --


@pytest.mark.parametrize("name", sorted(CAPTURES))
def test_every_capture_reads_with_nothing_left_over(name):
    found = proc.read(TIER0 / name, CAPTURES[name])
    assert found.lines.total == len((TIER0 / name).read_text().splitlines())
    assert found.lines.unparsed == meta(name)["unparsed_lines"]


@pytest.mark.parametrize("name", sorted(CAPTURES))
def test_every_capture_says_which_file_it_is_a_copy_of(name):
    assert meta(name)["path"] == CAPTURES[name]


@pytest.mark.parametrize("name", sorted(CAPTURES))
def test_every_capture_records_the_level_the_ledger_gives_it(name):
    assert meta(name)["stability"] == stability.classify(CAPTURES[name]).kind


@pytest.mark.parametrize("name", sorted(CAPTURES))
def test_every_capture_is_evidence_off_the_pinned_kernel(name):
    got = meta(name)
    assert got["evidence"] is True
    assert got["kernel"] == "7.2.2"
    assert got["arch"] == "i386"


def test_the_router_sends_each_capture_to_a_reader():
    for name, kernel_path in CAPTURES.items():
        assert proc.reader_for(kernel_path) is not None, name


def test_the_router_would_rather_say_nothing_than_guess():
    assert proc.reader_for("/proc/schedstat") is None
    with pytest.raises(LookupError):
        proc.read(TIER0 / "meminfo.txt", "/proc/schedstat")


# -- what the ledger says --


def test_nothing_in_this_corpus_is_documented_anywhere():
    # The claim the whole package is built on. If a kernel release ever writes an ABI entry for one
    # of these, this test is where anybody finds out, and that would be good news.
    for kernel_path in CAPTURES.values():
        assert stability.classify(kernel_path).kind == models.UNDOCUMENTED


def test_undocumented_is_not_the_same_as_unusable():
    found = stability.classify("/proc/meminfo")
    assert found.documented is False
    assert found.dependable is False
    assert "Documentation/ABI describes this path" in found.note


def test_the_two_files_the_readme_names_as_non_abi():
    for kernel_path in ("/proc/kallsyms", "/proc/config.gz"):
        found = stability.classify(kernel_path)
        assert found.kind == models.NOT_ABI
        assert found.entry == "Documentation/ABI/README"


def test_btf_is_the_one_thing_here_that_carries_a_promise():
    found = stability.classify("/sys/kernel/btf/vmlinux")
    assert found.kind == models.TESTING
    assert found.dependable is True


def test_tracefs_is_undocumented_and_its_debugfs_copy_is_obsolete():
    assert stability.classify("/sys/kernel/tracing/trace").kind == models.UNDOCUMENTED
    assert stability.classify("/sys/kernel/debug/tracing/trace").kind == models.OBSOLETE


def test_the_specific_rules_come_before_the_wildcards():
    # /proc/kallsyms matches both its own rule and the /proc/* catch-all, and order is the only
    # thing that decides which one answers.
    assert stability.classify("/proc/kallsyms").pattern == "/proc/kallsyms"
    assert stability.classify("/proc/meminfo").pattern == "/proc/*"


def test_a_path_nobody_looked_up_is_undocumented_rather_than_an_error():
    found = stability.classify("/etc/passwd")
    assert found.kind == models.UNDOCUMENTED
    assert found.pattern == ""


def test_every_level_in_the_ledger_is_one_of_the_six():
    for _, kind, _, _ in stability.RULES:
        assert kind in models.LEVELS


def test_every_documented_rule_names_the_file_that_says_so():
    for pattern, kind, entry, note in stability.RULES:
        assert note, pattern
        if kind in (models.STABLE, models.TESTING, models.OBSOLETE, models.NOT_ABI):
            assert entry.startswith("Documentation/ABI/"), pattern


def test_the_ledger_prints_as_a_table():
    printed = stability.table()
    assert "written down in" in printed
    assert "nothing" in printed


# -- key and value files --


def test_meminfo_reads_every_line(mem):
    assert len(mem.entries) == meta("meminfo.txt")["keys"]
    assert mem.lines.unparsed == 0


def test_the_kernel_writes_kb_and_means_kib(mem):
    assert mem["MemTotal"].unit == "kB"
    assert mem.number("MemTotal") == meta("meminfo.txt")["mem_total_kb"]
    assert keyed.bytes_of(mem, "MemTotal") == meta("meminfo.txt")["mem_total_bytes"]


def test_a_missing_key_raises_and_says_which_kernel(mem):
    with pytest.raises(KeyError):
        mem["HugePages_Total"]
    assert mem.number("HugePages_Total") is None
    assert "HugePages_Total" not in mem


def test_a_status_file_has_values_that_are_not_one_number(status):
    got = meta("self-status.txt")
    assert len(status["Uid"].values) == got["uid_values"]
    assert len(status["State"].values) == got["state_values"]
    assert status["Uid"].number is None
    assert status["State"].number is None


def test_a_key_with_nothing_after_it_is_still_a_key(status):
    for key in meta("self-status.txt")["empty_keys"]:
        assert key in status
        assert status[key].values == ()
        assert status[key].number is None


def test_order_is_kept_because_the_kernel_groups_related_keys(status):
    keys = list(status.keys)
    assert keys.index("VmSize") < keys.index("VmRSS") < keys.index("Threads")


def test_a_line_with_no_colon_is_unparsed():
    found = keyed.parse("MemTotal: 8 kB\nthis is not a key\n")
    assert found.lines.read == 1
    assert found.lines.unparsed == 1
    assert found.lines.total == 2


def test_a_hex_value_still_comes_back_as_a_number():
    found = keyed.parse("untag_mask:\t0xffffffff\n")
    assert found.number("untag_mask") == 0xFFFFFFFF


def test_bytes_of_leaves_a_unitless_number_alone():
    found = keyed.parse("Threads:\t4\n")
    assert keyed.bytes_of(found, "Threads") == 4
    assert keyed.bytes_of(found, "Nothing") is None


# -- per cpu counter files --


def test_the_column_count_comes_off_the_header(irqs, softirqs):
    assert irqs.cpus == tuple(meta("interrupts.txt")["cpus"])
    assert softirqs.cpus == tuple(meta("softirqs.txt")["cpus"])
    assert irqs.cpu_count == 1


def test_interrupts_splits_into_hardware_lines_and_kernel_lines(irqs):
    got = meta("interrupts.txt")
    assert len(irqs.counters) == got["rows"]
    assert len(percpu.hardware(irqs)) == got["hardware_rows"]
    assert [one.label for one in percpu.named(irqs)] == got["named_rows"]


def test_a_hardware_line_keeps_the_device_on_the_end_of_it(irqs):
    timer = irqs.get("0")
    assert timer is not None
    assert "XT-PIC" in timer.detail
    assert timer.total > 0


def test_the_deferred_work_is_mostly_timers_and_rcu(softirqs):
    got = meta("softirqs.txt")
    assert len(softirqs.counters) == got["rows"]
    assert len(softirqs.quiet()) == got["quiet_rows"]
    assert softirqs.total("RCU") == got["rcu"]
    assert softirqs.total("TIMER") == got["timer"]


def test_softirq_rows_have_no_description_because_the_kernel_prints_none(softirqs):
    assert all(one.detail == "" for one in softirqs.counters)


def test_the_column_count_decides_where_the_numbers_stop():
    # The same row read as one CPU and as two. With two columns the word `Non-maskable` is asked to
    # be a number and the row does not parse, which is the failure worth having rather than a row
    # that quietly keeps half its counts.
    row = " NMI:          7  Non-maskable interrupts"
    one = percpu.parse("      CPU0\n" + row + "\n")
    assert one.get("NMI").counts == (7,)
    assert one.get("NMI").detail == "Non-maskable interrupts"
    two = percpu.parse("      CPU0       CPU1\n" + row + "\n")
    assert two.lines.unparsed == 1


def test_a_counter_file_with_no_header_reads_nothing():
    found = percpu.parse("   0:   12  XT-PIC  timer\n")
    assert found.cpus == ()
    assert found.lines.unparsed == 1


def test_counts_add_up_across_cpus():
    found = percpu.parse("      CPU0   CPU1\n  RCU:  4   6\n")
    assert found.total("RCU") == 10
    assert found.get("RCU").on(1) == 6
    assert found.get("RCU").fired is True


# -- an address space --


def test_the_capture_has_the_regions_its_metadata_claims(space):
    got = meta("self-maps.txt")
    assert len(space.regions) == got["regions"]
    assert [one.path for one in space.named()] == got["named_regions"]
    assert len(space.gaps()) == got["gaps"]
    assert space.total_size == got["total_bytes"]


def test_the_program_is_mapped_twice_with_different_permissions(space):
    both = space.find("busybox")
    assert len(both) == 2
    assert both[0].executable and not both[0].writable
    assert both[1].writable and not both[1].executable


def test_the_anonymous_region_is_the_one_with_no_name(space):
    anonymous = [one for one in space.regions if one.anonymous]
    assert len(anonymous) == meta("self-maps.txt")["anonymous_regions"]
    assert anonymous[0].label == "anonymous"
    assert anonymous[0].special is False


def test_a_line_with_no_path_still_has_all_its_fields():
    # The trap, stated as a test. The kernel pads to a fixed column and prints nothing, so the line
    # ends in a space and a whitespace split comes back one field short.
    line = "b7f8f000-b7f9f000 rw-p 00000000 00:00 0 "
    assert len(maps.naive_fields(line)) == 5
    found = maps.parse(line + "\n")
    assert found.lines.read == 1
    assert found.regions[0].path == ""


def test_a_line_with_a_path_has_six_fields_and_looks_identical():
    line = "08048000-08149000 r-xp 00000000 00:03 11         /bin/busybox"
    assert len(maps.naive_fields(line)) == 6
    assert maps.parse(line + "\n").regions[0].path == "/bin/busybox"


def test_a_filename_with_a_space_in_it_is_kept_whole():
    line = "08048000-08149000 r-xp 00000000 00:03 11    /tmp/od) d ma"
    assert maps.parse(line + "\n").regions[0].path == "/tmp/od) d ma"


def test_an_address_is_either_in_a_region_or_in_a_hole(space):
    text = space.regions[0]
    assert space.at(text.start) is text
    assert space.at(text.end - 1) is text
    assert space.at(text.end) is not text
    assert space.at(0x50000000) is None


def test_most_of_the_address_space_is_gap(space):
    biggest = max(size for _, size in space.gaps())
    assert biggest > space.total_size * 100


def test_sizes_come_out_in_whole_pages(space):
    for one in space.regions:
        assert one.size % maps.PAGE == 0
        assert one.pages == one.size // maps.PAGE


def test_the_table_names_every_region(space):
    printed = space.table()
    for one in space.regions:
        assert one.label in printed


# -- the one line file --


def test_the_ordinary_case_reads_the_way_anybody_would_expect(ordinary):
    got = meta("self-stat.txt")
    assert ordinary.pid == got["pid"]
    assert ordinary.comm == got["comm"]
    assert ordinary.state == got["state"]
    assert len(ordinary.values) == got["fields"]
    assert ordinary.extra == ()
    assert pidstat.trapped(ordinary) is got["trapped_by_naive_split"]


def test_the_naive_split_agrees_on_the_ordinary_case(ordinary):
    # Which is exactly why the wrong parse survives. It is right almost always.
    assert ordinary.naive_state == ordinary.state


def test_the_bracket_in_a_command_name_moves_every_field_after_it(odd):
    got = meta("odd-comm-stat.txt")
    assert odd.comm == got["comm"]
    assert odd.state == got["state"]
    assert odd.naive_state == got["naive_state"]
    assert odd.state != odd.naive_state
    assert len(odd.naive) == got["naive_fields"]
    assert pidstat.trapped(odd) is True


def test_both_captures_have_the_same_fields_despite_the_names(ordinary, odd):
    assert len(ordinary.values) == len(odd.values) == 50
    assert set(ordinary.values) == set(odd.values)


def test_the_field_names_are_the_ones_the_documentation_lists():
    assert len(models.STAT_FIELDS) == 52
    assert models.STAT_FIELDS[:3] == ("pid", "tcomm", "state")
    assert models.STAT_FIELDS[-1] == "exit_code"


def test_the_mappings_and_the_one_line_file_agree_on_the_size(space, ordinary):
    # vsize is the sum of the sizes of the mappings, so two files taken from two runs of the same
    # program are two views of one fact. If either reader drifts, they stop agreeing.
    assert ordinary.number("vsize") == space.total_size


def test_a_field_the_kernel_added_lands_in_extra():
    # Fifty named fields after the command, and then one more that no kernel prints yet.
    line = "1 (init) " + " ".join(["S", *["0"] * 49, "88"])
    found = pidstat.parse(line)
    assert found.comm == "init"
    assert len(found.values) == 50
    assert found.extra == ("88",)


def test_a_line_with_no_bracket_is_unparsed():
    found = pidstat.parse("37 cat R 1 0\n")
    assert found.lines.unparsed == 1
    assert found.pid == 0


def test_an_empty_file_is_skipped_rather_than_failed():
    found = pidstat.parse("")
    assert found.lines.skipped == 1
    assert found.lines.unparsed == 0


def test_split_comm_takes_the_first_bracket_and_the_last():
    assert pidstat.split_comm("7 (a) b) R 1") == ("7 ", "a) b", " R 1")
    assert pidstat.split_comm("no brackets here") is None


def test_the_faults_pair_is_the_one_the_page_fault_blueprint_counts(ordinary):
    minor, major = ordinary.faults
    assert minor > 0
    assert major == 0


# -- the banner --


def test_the_release_comes_out_and_the_compiler_stays_text():
    got = meta("version.txt")
    banner = version.parse_file(TIER0 / "version.txt", "/proc/version")
    assert banner.release == got["release"]
    assert list(banner.parts) == got["parts"]
    assert banner.build == got["build"]
    assert "gcc" in banner.rest


def test_the_running_kernel_is_the_one_the_profile_asked_for():
    banner = version.parse_file(TIER0 / "version.txt", "/proc/version")
    assert "PREEMPT" in banner.rest


def test_versions_compare_as_numbers_and_not_as_strings():
    older = version.parse("Linux version 6.9.0 (a@b) (gcc) #1\n")
    newer = version.parse("Linux version 6.10.0 (a@b) (gcc) #1\n")
    assert newer.parts > older.parts
    assert newer.release < older.release
    assert newer.at_least(6, 10) is True
    assert older.at_least(6, 10) is False


def test_a_distribution_suffix_stops_the_tuple_rather_than_breaking_it():
    banner = version.parse("Linux version 6.1.0-13-amd64 (a@b) (gcc) #1 SMP\n")
    assert banner.parts == (6, 1, 0)


def test_a_banner_that_is_not_one_is_unparsed():
    banner = version.parse("something else entirely\n")
    assert banner.lines.unparsed == 1
    assert banner.release == ""
    assert banner.parts == ()


# -- what every reader has in common --


@pytest.mark.parametrize("name", sorted(CAPTURES))
def test_every_reader_prints_a_banner_naming_the_file_and_the_level(name):
    found = proc.read(TIER0 / name, CAPTURES[name])
    printed = found.banner()
    assert CAPTURES[name] in printed
    assert models.UNDOCUMENTED in printed


@pytest.mark.parametrize("name", sorted(CAPTURES))
def test_every_reader_accounts_for_every_line(name):
    text = (TIER0 / name).read_text()
    module = proc.reader_for(CAPTURES[name])
    assert module.account(text).total == len(text.splitlines())


def test_a_reader_given_no_path_still_works_and_says_it_looked_nothing_up():
    found = keyed.parse("MemTotal: 8 kB\n")
    assert found.promise.kind == models.UNDOCUMENTED
    assert found.promise.pattern == ""
