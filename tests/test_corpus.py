"""Tests for loading and normalising the pinned captures.

The two that carry the most weight are `test_the_line_count_never_changes` and
`test_normalising_twice_is_the_same_as_normalising_once`, and they run against every artefact in
the corpus rather than against a fixture. A normalisation rule is a regular expression, and a
regular expression is wrong in ways nobody predicts. Running all of them over all forty files is
the only check here that finds a rule doing something to a file its author never opened.

The other one worth reading is `test_a_second_run_of_the_same_work_normalises_to_the_same_text`.
That is the whole point of the module stated as a test: two captures of the same work, taken at
different moments with different pids at different addresses, come out identical.
"""

from pathlib import Path

import pytest

from kxray.corpus import index, normalize

ROOT = Path(__file__).resolve().parents[1]
CORPORA = ROOT / "corpora"


@pytest.fixture
def here(monkeypatch):
    monkeypatch.chdir(ROOT)


TEXTS = sorted(
    one
    for one in CORPORA.rglob("*")
    if one.is_file()
    and one.suffix not in (".toml", ".btf")
    and one.with_suffix(".meta.toml").exists()
)


# The two properties, over the whole corpus.


@pytest.mark.parametrize("artefact", TEXTS, ids=lambda p: p.relative_to(CORPORA).as_posix())
def test_the_line_count_never_changes(artefact):
    """Normalising is a substitution and not an edit.

    A rule that dropped a line or wrapped one would make the result impossible to read next to the
    original, and reading the two next to each other is how anybody checks a rule at all.
    """
    text = artefact.read_text(encoding="utf-8", errors="replace")
    assert len(normalize.of(text).lines) == len(text.split("\n"))


@pytest.mark.parametrize("artefact", TEXTS, ids=lambda p: p.relative_to(CORPORA).as_posix())
def test_normalising_twice_is_the_same_as_normalising_once(artefact):
    """A rule that matches its own output renames things forever, and is not a baseline."""
    once = normalize.of(artefact.read_text(encoding="utf-8", errors="replace"))
    assert normalize.of(once.text).text == once.text


# What it is for.


FIRST = """\
# tracer: function_graph
#
# CPU  DURATION                  FUNCTION CALLS
# |     |   |                     |   |   |   |
 1)               |  vfs_write() {
 1)   0.482 us    |    rw_verify_area();
 1) + 18.245 us   |  }
"""

# The same work again. Different lane, different durations, and the process is a different one.
AGAIN = """\
# tracer: function_graph
#
# CPU  DURATION                  FUNCTION CALLS
# |     |   |                     |   |   |   |
 3)               |  vfs_write() {
 3)   0.911 us    |    rw_verify_area();
 3) + 22.007 us   |  }
"""


def test_a_second_run_of_the_same_work_normalises_to_the_same_text():
    assert normalize.same(FIRST, AGAIN)


def test_without_normalising_the_two_runs_look_completely_different():
    # The reason this module exists. Three of the four lines with anything on them differ.
    pairs = zip(FIRST.split("\n"), AGAIN.split("\n"), strict=True)
    differ = [one for one, other in pairs if one != other]
    assert len(differ) == 3


def test_a_run_that_really_is_different_still_shows_up():
    changed = AGAIN.replace("rw_verify_area", "rw_verify_area_and_something_else")
    assert not normalize.same(FIRST, changed)


# The rules, one case each.


def test_a_printk_timestamp_goes_and_the_line_stays():
    assert normalize.of("[    3.041992] hello\n").text == "[TIME] hello\n"


def test_durations_can_be_bucketed_instead_of_taken_out():
    trace = " 0)   0.482 us    |    rw_verify_area();\n"
    assert "under 1us" in normalize.of(trace, time="bucket").text
    assert "DUR us" in normalize.of(trace, time="elide").text


def test_the_same_address_gets_the_same_name_and_a_different_one_does_not():
    text = "at c78250b8 and c78250b8 and c7825100\n"
    assert normalize.of(text).text == "at ptr#1 and ptr#1 and ptr#2\n"


def test_a_null_pointer_is_a_fact_rather_than_a_nonce():
    assert normalize.of("00000000 rw-p\n").text == "00000000 rw-p\n"


def test_a_decimal_number_that_is_eight_digits_long_is_not_an_address():
    # `utime` out of /proc/self/stat. Eight hex digits and eight decimal digits look the same when
    # none of the digits happens to be a letter, so a bare run has to have a hex letter in it.
    assert normalize.of("utime 13456789 stime 2\n").text == "utime 13456789 stime 2\n"


def test_an_address_range_is_a_range_whatever_digits_are_in_it():
    # The /proc/self/maps case, where a real address can be all decimal digits.
    assert normalize.of("08048000-08149000 r-xp\n").text == "ptr#1-ptr#2 r-xp\n"


def test_pointers_are_replaced_before_offsets_so_a_symbol_offset_is_not_mistaken_for_one():
    text = "  __mutex_lock+0x8c/0x230\n"
    assert normalize.of(text).text == "  __mutex_lock\n"


def test_the_offset_rule_on_its_own_leaves_the_symbol_alone():
    assert normalize.of("x+0x8c/0x230\n", rules=("offset",)).text == "x\n"


def test_a_cpu_becomes_a_lane_in_first_appearance_order():
    text = " 3)   |  a();\n 1)   |  b();\n 3)   |  c();\n"
    assert (
        normalize.of(text, rules=("cpu",)).text
        == " lane#1)   |  a();\n lane#2)   |  b();\n lane#1)   |  c();\n"
    )


def test_a_pid_becomes_a_name_in_first_appearance_order():
    assert normalize.of("pid=2792 tgid=2792 next_pid=41\n", rules=("identity",)).text == (
        "pid=pid#1 tgid=pid#1 next_pid=pid#2\n"
    )


def test_a_counter_is_made_relative_to_where_it_started():
    text = "jiffies=4294901760\njiffies=4294901765\n"
    assert normalize.of(text, rules=("counter",)).text == "jiffies=+0\njiffies=+5\n"


# Order, which is off unless asked for.


CONCURRENT = """\
[    1.000000] b
[    1.000000] a
[    2.000000] c
"""


def test_ordering_is_off_by_default():
    # Sorting a function_graph trace destroys the call tree, which is the thing being taught, so
    # this is never done on anybody's behalf.
    assert "b\n[TIME] a" in normalize.of(CONCURRENT).text


def test_ordering_sorts_lines_that_share_a_timestamp_when_it_is_asked_for():
    done = normalize.of(CONCURRENT, rules=(*normalize.RULES, normalize.ORDER)).text
    assert done.split("\n")[:3] == ["[TIME] a", "[TIME] b", "[TIME] c"]


def test_ordering_does_not_move_a_line_past_one_with_a_different_timestamp():
    done = normalize.of(CONCURRENT, rules=(*normalize.RULES, normalize.ORDER)).text
    assert done.split("\n")[2] == "[TIME] c"


# The legend.


def test_the_legend_says_what_every_name_stood_for():
    done = normalize.of("at c78250b8 and pid=2792\n")
    assert done.legend.original("ptr#1") == "c78250b8"
    assert done.legend.original("pid#1") == "2792"


def test_a_name_nothing_stands_for_comes_back_as_nothing():
    assert normalize.of("hello\n").legend.original("ptr#9") is None


def test_the_legend_prints_as_a_table():
    assert "was  c78250b8" in normalize.of("at c78250b8\n").legend.table()


def test_a_capture_with_nothing_to_rename_says_so_rather_than_printing_an_empty_table():
    assert normalize.of("hello\n").legend.table() == "nothing was renamed"


def test_a_rule_nobody_has_written_is_refused_rather_than_ignored():
    with pytest.raises(ValueError, match="no such rule: colour"):
        normalize.of("hello\n", rules=("time", "colour"))


# Loading.


def test_an_artefact_can_be_asked_for_by_id(here):
    one = index.get("traces/tier0/write-1byte")
    assert one.path == Path("corpora/traces/tier0/write-1byte.txt")
    assert one.kind == "function_graph"
    assert one.kernel == "7.2.2"
    assert one.tier == 0


def test_an_id_that_is_nearly_right_gets_told_what_it_nearly_was(here):
    with pytest.raises(LookupError, match="did you mean .*write-1byte"):
        index.get("traces/tier9/write-1byte")


def test_an_id_that_is_nothing_like_anything_still_raises(here):
    with pytest.raises(LookupError, match="no artefact called"):
        index.get("nothing/like/this")


def test_the_id_is_the_path_with_the_suffix_dropped():
    assert (
        index.identify(Path("corpora/traces/tier0/write-1byte.txt")) == "traces/tier0/write-1byte"
    )


def test_reading_an_artefact_runs_the_reader_that_belongs_to_it(here):
    got = index.read(index.get("traces/tier0/write-1byte"))
    assert got.reader == "function_graph"
    assert got.found > 0
    assert got.accounted.total == got.lines


def test_a_proc_file_is_told_which_file_in_proc_it_is_a_copy_of(here):
    # The name on disk does not decide how a capture is read. Only the metadata does.
    assert index.get("proc/tier0/self-maps").kernel_path == "/proc/self/maps"


def test_every_artefact_is_routed_to_a_reader_that_exists(here):
    for one in index.find():
        assert one.kind in index.READERS


def test_a_capture_with_no_metadata_beside_it_is_not_part_of_the_corpus(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "corpora" / "traces" / "tier0").mkdir(parents=True)
    (tmp_path / "corpora" / "traces" / "tier0" / "loose.txt").write_text("hello\n")
    assert index.find() == []


def test_an_artefact_nothing_claims_is_an_error_rather_than_an_omission(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "corpora" / "mystery").mkdir(parents=True)
    (tmp_path / "corpora" / "mystery" / "thing.log").write_text("hello\n")
    (tmp_path / "corpora" / "mystery" / "thing.meta.toml").write_text("evidence = false\n")
    with pytest.raises(LookupError, match="no reader"):
        index.find()


def test_the_narrower_route_wins_over_the_wider_one():
    # Both tracers write .txt into the same directory and the file name is all that tells them
    # apart, so this ordering is load bearing.
    assert index.route(Path("corpora/traces/tier1/flat-write.txt")) == "function"
    assert index.route(Path("corpora/traces/tier1/write.txt")) == "function_graph"


def test_lockdep_stats_is_not_read_as_a_pid_stat():
    # `*-stat.txt` would catch `lockdep-stats-*.txt` if the order in ROUTES ever moved.
    assert index.route(Path("corpora/proc/tier1/lockdep-stats-after.txt")) == "lockdep-stats"


# The two halves together, which is the only thing anybody actually wants.


def test_a_capture_can_be_loaded_and_normalised_without_knowing_what_kind_it_is(here):
    for id in ("traces/tier0/write-1byte", "oops/tier0/lockdep-ab-ba", "proc/tier0/self-maps"):
        one = index.get(id)
        done = normalize.of(one.text(), source=one.id)
        assert done.source == one.id
        assert len(done.lines) == len(one.text().split("\n"))
