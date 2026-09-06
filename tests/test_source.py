"""Tests for reading the kernel's own source files.

Most of these run against `corpora/source/pinned`, which is five real files out of the pinned
tarball rather than anything written for a test. That is deliberate. A parser for a hand written
text format is only worth what it does on the real thing, and a fixture invented alongside the
parser agrees with the parser by construction.

The three worth reading are `test_one_star_stops_at_a_slash_where_fnmatch_crosses_it`,
`test_write_is_four_here_and_one_there` and `test_a_signature_that_stays_while_its_body_changes`.
Each is a case where the obvious implementation is wrong in a way nobody notices.
"""

import re
from pathlib import Path

import pytest

from kxray.source import citations, kconfig, maintainers, symbols, syscalls, tree

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "corpora" / "source" / "pinned"

READ_WRITE = "fs/read_write.c"


@pytest.fixture
def corpus():
    """The committed corpus, named directly rather than through `find`.

    `find` prefers a full unpacked tree, so a test that went through it would read 1.6 GB of Linux
    on a machine that has run `tree.sh` and five files on one that has not, and would be testing a
    different thing in each place.
    """
    return tree.Tree(root=PINNED, version="7.2.2", complete=False)


# -- the tree handle -----------------------------------------------------------------------------


def test_the_corpus_says_it_is_not_a_whole_kernel(corpus):
    assert corpus.present
    assert corpus.complete is False
    assert "handful of files" in corpus.describe()


def test_a_file_that_is_here_comes_back_whole(corpus):
    file = corpus.read(READ_WRITE)
    assert file.partial is False
    assert "vfs_write" in file.text
    assert len(file.lines) > 1000


def test_the_excerpt_suffix_carries_the_partiality(corpus):
    """Asking for MAINTAINERS finds MAINTAINERS.excerpt and says so on the way back.

    The point of the suffix is that nothing downstream has to remember. `partial` travels on the
    File, and `parse_file` copies it onto the Maintainers, so a caller three layers away still
    knows it is looking at a slice.
    """
    file = corpus.read("MAINTAINERS")
    assert file.partial is True
    assert "MAINTAINERS" in corpus.files()
    assert "MAINTAINERS.excerpt" not in corpus.files()


def test_a_missing_file_is_not_in_the_corpus_rather_than_not_in_the_kernel(corpus):
    """The wording is the test. `mm/memory.c` is very much in Linux and is not committed here."""
    assert corpus.open("mm/memory.c") is None
    with pytest.raises(FileNotFoundError) as raised:
        corpus.read("mm/memory.c")
    message = str(raised.value)
    assert "not in the committed corpus" in message
    assert tree.UNPACK in message


def test_no_tree_at_all_says_how_to_get_one(tmp_path):
    empty = tree.Tree(root=tmp_path / "nothing")
    assert empty.present is False
    with pytest.raises(FileNotFoundError) as raised:
        empty.read("MAINTAINERS")
    assert tree.UNPACK in str(raised.value)


def test_find_prefers_a_full_tree_and_falls_back_to_the_corpus(tmp_path):
    (tmp_path / "kxbox" / "kernel").mkdir(parents=True)
    (tmp_path / "kxbox" / "kernel" / "pin.toml").write_text('[kernel]\nversion = "7.2.2"\n')
    (tmp_path / "corpora" / "source" / "pinned").mkdir(parents=True)

    fallen_back = tree.find(tmp_path)
    assert fallen_back.complete is False
    assert fallen_back.version == "7.2.2"

    (tmp_path / tree.UNPACKED / "linux-7.2.2").mkdir(parents=True)
    assert tree.find(tmp_path).complete is True


# -- MAINTAINERS ---------------------------------------------------------------------------------


@pytest.fixture
def owners(corpus):
    return maintainers.load(corpus)


def test_the_excerpt_parses_with_nothing_left_over(owners):
    assert owners.partial is True
    assert owners.unparsed == ()
    assert len(owners.sections) == 13


def test_one_star_stops_at_a_slash_where_fnmatch_crosses_it(owners):
    """The trap the whole module exists for.

    FILESYSTEMS (VFS and infrastructure) carries `F: fs/*`, and a tool built on `fnmatch` reads
    that as everything under `fs/` and sends every proc patch to the VFS maintainers. The kernel's
    own header block says one star stops at a slash, so `fs/proc/base.c` is not theirs.
    """
    import fnmatch

    assert fnmatch.fnmatch("fs/proc/base.c", "fs/*") is True
    assert maintainers.covers("fs/*", "fs/proc/base.c") is False
    assert maintainers.covers("fs/*", "fs/read_write.c") is True
    assert maintainers.covers("fs/**", "fs/proc/base.c") is True

    names = [hit.section.name for hit in owners.specific("fs/proc/base.c")]
    assert "PROC FILESYSTEM" in names
    assert not any(name.startswith("FILESYSTEMS") for name in names)


def test_a_trailing_slash_means_the_whole_subtree(owners):
    assert maintainers.covers("fs/proc/", "fs/proc/base.c") is True
    assert maintainers.covers("fs/proc/", "fs/proc/vmcore/main.c") is True
    assert maintainers.covers("fs/proc/", "fs/read_write.c") is False


def test_a_path_has_more_than_one_owner_and_the_last_one_owns_everything(owners):
    """Any lookup that takes the first hit and stops is wrong, and quietly."""
    names = [hit.section.name for hit in owners.lookup("mm/memory.c")]
    assert "MEMORY MANAGEMENT" in names
    assert maintainers.CATCH_ALL in names
    assert names[-1] == maintainers.CATCH_ALL
    assert maintainers.CATCH_ALL not in [hit.section.name for hit in owners.specific("mm/memory.c")]


def test_the_catch_all_really_does_catch_everything(owners):
    rest = owners.get(maintainers.CATCH_ALL)
    assert rest is not None
    for path in ("mm/memory.c", "fs/proc/base.c", "arch/x86/entry/entry_32.S", "README"):
        assert any(maintainers.covers(pattern, path) for pattern in rest.files), path


def test_a_section_can_name_nobody_and_still_be_maintained(owners):
    """PROC FILESYSTEM has a status, two lists and no `M:` line at all.

    So `contacts` has to fall through to the lists rather than come back empty, because coming back
    empty reads as nobody looks after this and that is not what the file says.
    """
    proc = owners.get("PROC FILESYSTEM")
    assert proc is not None
    assert proc.maintainers == ()
    assert proc.status == "Maintained"
    assert proc.looked_after is True
    assert len(proc.lists) == 2
    assert proc.contacts == proc.lists


def test_an_exclusion_beats_a_match(owners):
    """`X:` is tested first, so a section can claim a directory and hand back part of it.

    ABI/API is why the tag is in the corpus at all. Its own two `X:` lines happen not to overlap
    its two `F:` lines, so the ordering itself is tested on a section written here, where the
    overlap is the whole point and is three lines long.
    """
    abi = owners.get("ABI/API")
    assert abi is not None
    assert abi.excluded == ("arch/*/include/uapi/", "include/uapi/")

    written = maintainers.parse(
        "Maintainers List\n"
        "----------------\n"
        "\n"
        "SOMETHING\n"
        "M:\tA Person <a@example.com>\n"
        "S:\tMaintained\n"
        "F:\tdrivers/thing/\n"
        "X:\tdrivers/thing/legacy/\n"
    )
    assert [hit.section.name for hit in written.lookup("drivers/thing/main.c")] == ["SOMETHING"]
    assert written.lookup("drivers/thing/legacy/old.c") == ()


def test_the_n_tag_is_a_regex_and_not_a_glob(owners):
    """`N: tegra` matches anywhere in the path, which is what the header block's example says."""
    tegra = [hit for hit in owners.lookup("drivers/soc/tegra/pmc.c") if hit.tag == "N"]
    assert [hit.section.name for hit in tegra] == ["TEGRA ARCHITECTURE SUPPORT"]
    assert not any(
        hit.section.name == "TEGRA ARCHITECTURE SUPPORT"
        for hit in owners.lookup("drivers/bus/arm-integrator-lm.c")
    )


def test_the_audit_content_pattern_does_not_match_what_it_looks_like(owners):
    """`\\baudit_[a-z_0-9]\\+\\b` has a literal plus in it, and the real script agrees.

    `scripts/get_maintainer.pl` applies `K:` patterns with perl's `/x`, where `\\+` is an escaped
    plus sign rather than the one-or-more of the basic regular expressions `grep` speaks. So a patch
    that touches `audit_log_start` does not reach the audit list through this tag. That is a fact
    about the file rather than a bug here, and it is a test so that nobody helpfully fixes it.
    """
    audit = owners.get("AUDIT SUBSYSTEM")
    assert audit is not None
    assert audit.content_patterns
    assert owners.content("call to audit_log_start(context);") == ()
    # What it does match: one character out of the class, then a real plus sign, then a word.
    assert any(hit.section.name == "AUDIT SUBSYSTEM" for hit in owners.content("audit_l+x"))


def test_a_pattern_python_cannot_compile_does_not_take_the_lookup_down(owners):
    assert maintainers._search("(unclosed", "anything") is False


# -- the syscall tables --------------------------------------------------------------------------


@pytest.fixture
def tables(corpus):
    return syscalls.load(corpus, "i386"), syscalls.load(corpus, "x86_64")


def test_both_tables_parse_with_nothing_left_over(tables):
    for table in tables:
        assert table.unparsed == ()
        assert table.calls


def test_write_is_four_here_and_one_there(tables):
    """A syscall number with no architecture attached is not an identifier.

    The pinned box is 32 bit, so every number a lesson prints comes out of the first table, and a
    reader on their own machine comparing against the numbers they know finds different ones.
    """
    i386, x86_64 = tables
    assert i386.number_of("write") == 4
    assert x86_64.number_of("write") == 1
    assert i386.number_of("read") == 3
    assert x86_64.number_of("read") == 0
    assert i386.entry_of("write") == "sys_write"


def test_a_name_under_two_abis_has_no_single_number(tables):
    """None rather than the first hit, because the first hit is a wrong answer with no warning."""
    _, x86_64 = tables
    assert len(x86_64.by_name("rt_sigaction")) == 2
    assert x86_64.number_of("rt_sigaction") is None
    assert x86_64.number_of("rt_sigaction", abi="64") == 13
    assert "13 under 64" in syscalls._one(x86_64, "rt_sigaction")
    assert syscalls._one(x86_64, "break") == "not in this table"


def test_a_reserved_number_has_a_name_and_nothing_to_run(tables):
    """Those numbers stay claimed forever so an old binary gets ENOSYS rather than a surprise."""
    i386, _ = tables
    dead = i386.by_name("break")
    assert len(dead) == 1
    assert dead[0].number == 17
    assert dead[0].implemented is False
    assert len(i386.reserved) == 19


def test_the_dash_in_the_compat_column_is_not_an_entry_point(tables):
    """It holds the column open so that `noreturn` lands in the right place."""
    parsed = syscalls.parse("1\tcommon\texit\tsys_exit\t-\tnoreturn\n")
    only = parsed.calls[0]
    assert only.compat == ""
    assert only.noreturn is True
    assert only.implemented is True


def test_the_two_tables_have_different_numbers_of_abis(tables):
    i386, x86_64 = tables
    assert i386.abis == ("i386",)
    assert set(x86_64.abis) == {"common", "64", "x32"}


def test_asking_for_an_architecture_nobody_committed_says_which_ones_there_are(corpus):
    with pytest.raises(LookupError) as raised:
        syscalls.load(corpus, "arm64")
    assert "i386" in str(raised.value)


# -- Kconfig -------------------------------------------------------------------------------------


@pytest.fixture
def preempt(corpus):
    return kconfig.load(corpus, "kernel/Kconfig.preempt")


def test_the_preempt_file_parses_with_nothing_left_over(preempt):
    assert preempt.unparsed == ()
    assert len(preempt.symbols) == 15


def test_one_answer_pulls_in_two_more(preempt):
    """This is the whole explanation for a `.config` with symbols nobody chose in it."""
    assert "PREEMPT_BUILD" in [s.symbol for s in preempt["PREEMPT"].selects]
    assert "PREEMPTION" in [s.symbol for s in preempt["PREEMPT_BUILD"].selects]
    assert "CONFIG_" not in preempt["PREEMPT"].name
    assert preempt["PREEMPT"].config == "CONFIG_PREEMPT"
    assert preempt.get("CONFIG_PREEMPT") is preempt.get("PREEMPT")


def test_a_symbol_with_no_prompt_cannot_be_chosen_by_hand(preempt):
    """In a `.config` it looks exactly like something a person picked, and it never was."""
    build = preempt["PREEMPT_BUILD"]
    assert build.type == "bool"
    assert build.prompt == ""
    assert build.visible is False
    assert build in preempt.hidden
    assert len(preempt.hidden) == 6

    by = [s.name for s in preempt.selected_by("PREEMPT_BUILD")]
    assert "PREEMPT" in by
    assert "no prompt, so nobody chose it by hand" in kconfig.why(preempt, "PREEMPT_BUILD")


def test_the_choice_block_keeps_the_lines_that_belong_to_it(preempt):
    """The `default` lines above the first `config` are the choice's, not any symbol's.

    They were the last two unparsed lines in this file. The parser grew a Choice rather than the
    number being written down as acceptable.
    """
    assert len(preempt.choices) == 1
    block = preempt.choices[0]
    assert "Preemption Model" in block.prompt
    assert block.defaults
    assert "PREEMPT_NONE" in block.members
    assert preempt["PREEMPT_NONE"].choice == block.prompt


def test_a_condition_is_kept_as_written_rather_than_evaluated(preempt):
    """Evaluating one needs every Kconfig in the tree, and reading it answers the question asked."""
    selects = {s.symbol: s.condition for s in preempt["PREEMPT"].selects}
    assert selects["PREEMPT_BUILD"] == "!PREEMPT_DYNAMIC"
    assert str(kconfig.Select("A", "B")) == "A if B"
    assert str(kconfig.Select("A")) == "A"


def test_asking_about_a_symbol_that_is_somewhere_else_says_so(preempt):
    assert "not declared" in kconfig.why(preempt, "MMU")
    with pytest.raises(KeyError):
        preempt["MMU"]


@pytest.fixture
def kfence(corpus):
    return kconfig.load(corpus, "lib/Kconfig.kfence")


def test_a_symbol_can_depend_on_something_it_never_mentions(kfence):
    """Seven of the eight KFENCE symbols have no `depends on` line and all seven depend on KFENCE.

    The dependency is on the `if KFENCE` wrapped round them. A reader looking at
    KFENCE_SAMPLE_INTERVAL alone sees a symbol with no conditions on it at all, and then cannot
    explain why it is missing from a build. This is the case the `within` stack exists for.
    """
    assert kfence.unparsed == ()
    assert len(kfence.symbols) == 8

    interval = kfence["KFENCE_SAMPLE_INTERVAL"]
    assert interval.depends == ()
    assert interval.within == ("KFENCE",)
    assert interval.conditions == ("KFENCE",)

    inside = [one for one in kfence.symbols if "KFENCE" in one.within]
    assert len(inside) == 6
    assert kfence["KFENCE"].within == ()

    # The one symbol in the block that does have its own `depends on` keeps both, block first,
    # because the block is the outer condition and reads that way on the page.
    unit = kfence["KFENCE_KUNIT_TEST"]
    assert unit.conditions == ("KFENCE", "TRACEPOINTS && KUNIT")


def test_the_only_place_the_kernel_says_what_a_number_may_be(kfence):
    """`range 1 65535` is not written anywhere else, and a fragment setting 0 gets no complaint."""
    objects = kfence["KFENCE_NUM_OBJECTS"]
    assert objects.type == "int"
    assert objects.ranges == ("1 65535",)
    assert objects.defaults == ("255",)


def test_the_architecture_says_which_checkers_a_32_bit_build_may_have(corpus):
    """Two lines of arch/x86/Kconfig are the whole reason there is no kasan profile.

    KASAN is selected only under X86_64 and KFENCE is selected under nothing, and Tier 0 is i386.
    Kconfig drops a symbol whose dependencies are unmet without printing anything, so a fragment
    asking for CONFIG_KASAN on this build produces a config without it and no error.
    """
    arch = kconfig.load(corpus, "arch/x86/Kconfig")
    under = {one.symbol: one.condition for one in arch["X86"].selects}
    assert under["HAVE_ARCH_KASAN"] == "X86_64"
    assert under["HAVE_ARCH_KFENCE"] == ""


# -- symbols -------------------------------------------------------------------------------------


def test_three_names_for_one_call_and_no_two_of_them_equal(corpus):
    """The table says `sys_write`, the source says `write`, the running kernel says
    `__ia32_sys_write`.

    And grepping the source for `sys_write` is worse than finding nothing, because it finds
    `ksys_write` twice, which is a different function three lines from the one that was wanted.
    """
    text = corpus.read(READ_WRITE).text
    assert re.findall(r"\bsys_write\b", text) == []
    assert sorted({m for m in re.findall(r"\w*sys_write\w*", text)}) == ["ksys_write"]
    assert "SYSCALL_DEFINE3(write" in text

    assert symbols.unwrap("__ia32_sys_write") == "write"
    assert symbols.unwrap("sys_write") == "write"
    assert symbols.unwrap("vfs_write") == "vfs_write"
    assert symbols.wrapped("__x64_sys_write") is True
    assert symbols.wrapped("vfs_write") is False


def test_a_wrapped_name_is_looked_for_both_ways(corpus):
    found = symbols.find(corpus, "__ia32_sys_write", (READ_WRITE,))
    assert [(f.kind, f.line) for f in found] == [("syscall", 747)]


def test_a_plain_function_is_found_where_it_is_defined(corpus):
    found = symbols.find(corpus, "vfs_write", (READ_WRITE,))
    assert [(f.kind, f.line) for f in found] == [("function", 667)]


def test_a_declaration_is_not_a_definition():
    """A header is full of lines that name a function and are not where it lives."""
    assert (
        symbols.search("ssize_t vfs_write(struct file *, const char __user *);", "vfs_write") == ()
    )


def test_being_in_kallsyms_and_being_callable_from_a_module_are_different_questions(corpus):
    """`vfs_write` is in the symbol table of the running box and a module still cannot call it."""
    assert symbols.exported(corpus, "vfs_write", (READ_WRITE,)) == ()
    assert symbols.exported(corpus, "rw_verify_area", (READ_WRITE,))


def test_looking_in_a_file_the_corpus_does_not_have_is_quiet(corpus):
    assert symbols.find(corpus, "handle_mm_fault", ("mm/memory.c",)) == ()


# -- citations -----------------------------------------------------------------------------------


ANCHOR = "ssize_t vfs_write(struct file *file"


def test_an_anchor_resolves_to_a_line_and_a_hash(corpus):
    hit = citations.resolve(corpus.read(READ_WRITE).text, ANCHOR)
    assert hit.found is True
    assert hit.line == 667
    assert hit.unique is True
    assert hit.problem == ""
    assert re.fullmatch(r"[0-9a-f]{12}", hit.context)


def test_a_signature_that_stays_while_its_body_changes(corpus):
    """The failure the anchor alone cannot catch, and the reason the hash exists.

    An anchor is usually a signature, a signature is the most stable line in a function, and the
    body underneath it is the part people edit. So a citation supporting a sentence about what the
    function does goes stale with the anchor sitting exactly where it always was.
    """
    lines = corpus.read(READ_WRITE).lines
    before = citations.resolve("\n".join(lines), ANCHOR)

    edited = list(lines)
    edited[before.line] = edited[before.line] + " /* a change two lines down */"
    after = citations.resolve("\n".join(edited), ANCHOR)

    assert after.line == before.line
    assert after.context != before.context
    assert citations.changed(before.context, after.context) is True
    assert "the lines around it have changed" in citations.compare(before.context, after.context)


def test_reindenting_does_not_fire_and_renaming_does():
    """A checker that cries at every reformat gets switched off, which is worse than not having
    one."""
    original = "one\n    two\nthree anchor here\n\tfour\nfive"
    respaced = "one\n\ttwo\nthree anchor here\n    four\n  five"
    renamed = "one\n    two\nthree anchor here\n\tfour_renamed\nfive"

    assert citations.hash_text(original, "anchor here") == citations.hash_text(
        respaced, "anchor here"
    )
    assert citations.hash_text(original, "anchor here") != citations.hash_text(
        renamed, "anchor here"
    )


def test_an_edit_outside_the_window_is_not_this_citation_going_stale():
    body = [f"line {n}" for n in range(40)]
    body[20] = "the anchor is here"
    first = citations.resolve("\n".join(body), "the anchor is here")

    body[35] = "something else entirely"
    second = citations.resolve("\n".join(body), "the anchor is here")
    assert second.context == first.context


def test_the_window_is_clipped_rather_than_padded():
    """Padding would make two different short windows at two ends of a file hash the same."""
    lines = ["a", "b", "c", "d", "e", "f", "g"]
    assert citations.window(lines, 0) == ["a", "b", "c", "d"]
    assert citations.window(lines, 6) == ["d", "e", "f", "g"]
    assert citations.window(lines, 3) == lines


def test_an_anchor_in_two_places_still_answers_and_says_to_pick_a_longer_one():
    hit = citations.resolve("x\nsame line\ny\nsame line\n", "same line")
    assert hit.line == 2
    assert hit.count == 2
    assert hit.unique is False
    assert "pick a longer anchor" in hit.problem


def test_a_missing_anchor_is_not_found_and_has_no_hash():
    hit = citations.resolve("nothing to see", "an anchor")
    assert hit.found is False
    assert hit.context == ""
    assert citations.hash_text("nothing to see", "an anchor") == ""


def test_no_recorded_hash_is_not_a_failure():
    """Every citation written before this existed has none, and turning those red on the day the
    checker landed would have meant a rule nobody could switch on."""
    assert citations.changed("", "abc123abc123") is False
    assert citations.compare("", "abc123abc123") == "no context recorded yet"
    assert citations.compare("abc123abc123", "").startswith("nothing to compare")
    assert citations.compare("abc123abc123", "abc123abc123") == "unchanged"
