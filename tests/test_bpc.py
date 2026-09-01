"""Tests for bpc, the blueprint compiler.

Three of these matter more than the rest, and all three are about the same worry. A generated
section holds field offsets, and a wrong field offset looks exactly like a right one.

The first is the seal: edit a generated section by hand and the build fails. The second is the
regeneration check: reseal after editing it and the build still fails, because the content no
longer matches what the generator produces. The third is provenance: a section generated from
nothing, or from a fixture somebody wrote by hand, cannot appear in a blueprint that calls itself
complete.
"""

from pathlib import Path

import pytest

from tools import bpc, bpcgen

ROOT = Path(__file__).resolve().parents[1]

# A body has to carry a provenance line now, because a generated block with no source is a block
# nobody can trace back to anything. `evidence` is true here so the fixtures can reach `complete`,
# which is the state most of these tests are about.
EVIDENCE = bpcgen.Source("btf", "vmlinux", True, "v7.2.2", "x86_64")
NO_EVIDENCE = bpcgen.Source("none", "", False, "v7.2.2", "x86_64")


def body(number: int, source: bpcgen.Source = EVIDENCE) -> str:
    return f"{source.line()}\nGenerated section {number}. Held still for the tests."


BODY = {number: body(number) for number in bpc.GENERATED}


def blueprint(
    name="widget",
    status="stub",
    extra_header="",
    sections=None,
    invariant=None,
    bodies=None,
) -> str:
    sections = sections or {}
    bodies = bodies or BODY
    out = [
        "---",
        f"blueprint: {name}",
        "title: A thing",
        f"status: {status}",
        "pin: v7.2.2",
        "arch: x86_64",
        "lessons: []",
        "generated: [2, 5, 7]",
    ]
    if extra_header:
        out.append(extra_header)
    out += ["---", "", f"# {name}", ""]

    for number, title in bpc.SECTIONS:
        out += [f"## §{number} {title}", ""]
        if number in bodies:
            content = bodies[number]
            out += [
                f"<!-- bpc:generated section={number} hash={bpc.digest(content)} -->",
                content,
                f"<!-- bpc:end section={number} -->",
                "",
            ]
        elif number == 4:
            out += ["Three subsections.", ""]
            for tag, subtitle in bpc.SUBSECTIONS:
                out += [f"### §{tag} {subtitle}", ""]
                if tag == "4a":
                    out += [invariant or "1. The counter never goes backwards. [unchecked]", ""]
                else:
                    out += ["Written by hand.", ""]
        else:
            out += [sections.get(number, "Written by hand."), ""]
    return "\n".join(out)


def write(tmp_path: Path, text: str, name="widget.md") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def rules(findings) -> set[str]:
    return {f.rule for f in findings}


def messages(findings) -> str:
    return " | ".join(f.message for f in findings)


def test_a_well_formed_stub_passes(tmp_path):
    assert bpc.check(write(tmp_path, blueprint())) == []


def test_the_name_in_the_header_has_to_match_the_file(tmp_path):
    findings = bpc.check(write(tmp_path, blueprint(name="gadget")))
    assert "the file is 'widget'" in messages(findings)


def test_a_file_with_no_header_is_caught(tmp_path):
    findings = bpc.check(write(tmp_path, "# widget\n\nno header here\n"))
    assert "no header block" in messages(findings)


def test_complete_needs_a_reviewer(tmp_path):
    findings = bpc.check(write(tmp_path, blueprint(status="complete")))
    assert "complete needs reviewed-by" in messages(findings)


def test_an_unknown_status_is_refused(tmp_path):
    findings = bpc.check(write(tmp_path, blueprint(status="nearly")))
    assert "is not one of" in messages(findings)


def test_a_missing_section_is_caught(tmp_path):
    text = blueprint().replace("## §8 Configuration and architecture dependence", "## Config notes")
    assert "no section 8" in messages(bpc.check(write(tmp_path, text)))


def test_a_renamed_section_is_caught(tmp_path):
    text = blueprint().replace("## §3 Algorithms", "## §3 How it works")
    assert "should be titled 'Algorithms'" in messages(bpc.check(write(tmp_path, text)))


def test_sections_out_of_order_are_caught(tmp_path):
    lines = blueprint().split("\n")
    start = lines.index("## §9 Reimplementation notes")
    moved = lines[start:] + lines[:start]
    assert "out of order" in messages(bpc.check(write(tmp_path, "\n".join(moved))))


def test_hand_editing_a_generated_section_fails(tmp_path):
    text = blueprint().replace(BODY[2], BODY[2] + " And one more thing I added by hand.")
    findings = bpc.check(write(tmp_path, text))
    assert rules(findings) == {"seal"}
    assert "was hand edited" in messages(findings)


def test_an_unsealed_block_asks_to_be_sealed(tmp_path):
    text = blueprint().replace(f"hash={bpc.digest(BODY[5])}", "hash=unsealed")
    assert "run bpc --reseal" in messages(bpc.check(write(tmp_path, text)))


def test_reseal_makes_a_hand_edited_file_pass_again(tmp_path):
    """Resealing gets the file past `check`, and that is on purpose rather than a hole.

    `check` reads one file and has no source to compare against, so a reseal is the last word
    there. What catches the edit after that is the regeneration pass further down, which runs the
    generator again and notices that the content is nobody's output.
    """
    edited = "Something else entirely, typed in by a person."
    path = write(tmp_path, blueprint().replace("Generated section 7.", edited))
    assert bpc.check(path)
    assert bpc.reseal(path) == 1
    assert bpc.check(path) == []


def test_a_generated_block_on_a_hand_written_section_is_refused(tmp_path):
    text = (
        blueprint()
        .replace("<!-- bpc:generated section=2", "<!-- bpc:generated section=3")
        .replace("<!-- bpc:end section=2 -->", "<!-- bpc:end section=3 -->")
    )
    assert "is not a generated section" in messages(bpc.check(write(tmp_path, text)))


def test_a_missing_generated_block_is_caught(tmp_path):
    lines = [ln for ln in blueprint().split("\n") if "section=5" not in ln and ln != BODY[5]]
    findings = bpc.check(write(tmp_path, "\n".join(lines)))
    assert "section 5 is generated and has no block" in messages(findings)


@pytest.mark.parametrize("phrase", ["as we saw", "Recall that", "see the chapter", "in the lesson"])
def test_pointing_at_the_lesson_fails(tmp_path, phrase):
    text = blueprint(sections={3: f"The steps, {phrase} in part S."})
    findings = bpc.check(write(tmp_path, text))
    assert rules(findings) == {"lesson-reference"}


def test_an_invariant_with_no_check_named_is_caught(tmp_path):
    text = blueprint(invariant="1. The counter never goes backwards.")
    assert "[unchecked]" in messages(bpc.check(write(tmp_path, text)))


def test_an_invariant_with_a_named_check_passes(tmp_path):
    text = blueprint(
        invariant="1. The lock is held. [checked: lockdep_assert_held(&mm->mmap_lock)]"
    )
    assert bpc.check(write(tmp_path, text)) == []


def test_the_edge_case_set_is_required_only_at_complete(tmp_path):
    thin = blueprint(status="partial", sections={6: "Only the ones I know so far."})
    assert bpc.check(write(tmp_path, thin)) == []

    finished = blueprint(
        status="complete",
        extra_header="reviewed-by: somebody who built one",
        sections={6: "Only the ones I know so far."},
    )
    findings = bpc.check(write(tmp_path, finished))
    assert rules(findings) == {"edge-cases"}
    assert "allocation-failure" in messages(findings)


def test_a_complete_blueprint_with_every_tag_passes(tmp_path):
    tags = "\n".join(f"- **{tag}.** Something true about it." for tag in bpc.EDGE_CASES)
    text = blueprint(
        status="complete",
        extra_header="reviewed-by: somebody who built one",
        sections={6: tags},
    )
    assert bpc.check(write(tmp_path, text)) == []


def test_files_without_a_blueprint_header_are_not_blueprints(tmp_path):
    (tmp_path / "README.md").write_text("# Notes\n\nNo header.\n")
    write(tmp_path, blueprint())
    assert [p.name for p in bpc.find_blueprints([str(tmp_path)])] == ["widget.md"]


def test_the_repository_passes(monkeypatch):
    monkeypatch.chdir(ROOT)
    assert bpc.main([]) == 0


# -- provenance ---------------------------------------------------------------------------------


def test_a_generated_block_that_does_not_say_where_it_came_from_is_caught(tmp_path):
    text = blueprint(bodies={2: "Some offsets.", 5: BODY[5], 7: BODY[7]})
    findings = bpc.check(write(tmp_path, text))
    assert rules(findings) == {"provenance"}
    assert "does not say what it was generated from" in messages(findings)


def test_complete_is_refused_when_a_generated_section_rests_on_nothing(tmp_path):
    """The check the whole generator exists for.

    A field table produced from a handwritten fixture reads exactly like one produced from a
    kernel. Nothing in the shape of the output tells them apart, so the difference has to be
    recorded and enforced, and `complete` is where it gets enforced.
    """
    text = blueprint(
        status="complete",
        extra_header="reviewed-by: somebody who built one",
        sections={6: "\n".join(f"- **{tag}.** Yes." for tag in bpc.EDGE_CASES)},
        bodies={2: body(2, NO_EVIDENCE), 5: BODY[5], 7: BODY[7]},
    )
    findings = bpc.check(write(tmp_path, text))
    assert rules(findings) == {"provenance"}
    assert "section 2 came from nothing, which is not evidence" in messages(findings)


def test_partial_is_allowed_to_rest_on_nothing(tmp_path):
    text = blueprint(status="partial", bodies={n: body(n, NO_EVIDENCE) for n in bpc.GENERATED})
    assert bpc.check(write(tmp_path, text)) == []


def test_a_source_line_survives_being_written_and_read_back():
    source = bpcgen.Source("btf", "corpora/btf/handwritten/tiny.btf", False, "v7.2.2", "x86_64")
    again = bpcgen.parse_source(f"{source.line()}\nSome content.")
    assert again == source


# -- generating with nothing to read from -------------------------------------------------------


def generated(path: Path, section: int) -> str:
    seals, _ = bpc.find_seals(path.read_text().split("\n"))
    return next(seal.content for seal in seals if seal.section == section)


def test_generating_with_no_btf_writes_the_empty_state_and_names_what_is_missing(tmp_path):
    path = write(tmp_path, blueprint(extra_header="structures: [vm_fault, mm_struct]"))
    changed, problems = bpc.generate(path, root=tmp_path)

    assert changed == 3
    assert problems == []
    section = generated(path, 2)
    assert "no BTF to read" in section
    assert "`vm_fault`" in section and "`mm_struct`" in section
    assert bpcgen.parse_source(section).evidence is False


def test_generating_leaves_the_file_passing_its_own_check(tmp_path):
    path = write(tmp_path, blueprint(extra_header="structures: [vm_fault]"))
    bpc.generate(path, root=tmp_path)
    assert bpc.check(path) == []


def test_generating_twice_changes_nothing_the_second_time(tmp_path):
    path = write(tmp_path, blueprint(extra_header="structures: [vm_fault]"))
    bpc.generate(path, root=tmp_path)
    changed, _ = bpc.generate(path, root=tmp_path)
    assert changed == 0


# -- generating from BTF ------------------------------------------------------------------------

TINY = ROOT / "corpora" / "btf" / "handwritten" / "tiny.btf"


def test_section_two_from_btf_holds_the_offsets_the_corpus_promises():
    request = bpcgen.Request(pin="v7.2.2", arch="x86_64", structures=("demo_task",))
    rendered = bpcgen.render(2, request, root=ROOT, btf_path=TINY)

    assert rendered.problems == []
    # The numbers the corpus metadata says this blob has to produce. Reading them out of the
    # generated markdown rather than out of the reader is the point: this is the last step before
    # a person sees them.
    assert "64 bytes" in rendered.text
    assert "6 bytes of padding" in rendered.text
    assert "| 24 | 8 | `mm` | `struct demo_mm *` |" in rendered.text


def test_a_field_with_a_type_tag_gets_its_glyph_and_a_legend():
    request = bpcgen.Request(pin="v7.2.2", arch="x86_64", structures=("demo_arg",))
    rendered = bpcgen.render(2, request, root=ROOT, btf_path=TINY)
    assert "→U" in rendered.text
    assert "Glyphs in the type column" in rendered.text


def test_a_fixture_blob_is_marked_as_not_being_evidence():
    request = bpcgen.Request(pin="v7.2.2", arch="x86_64", structures=("demo_task",))
    rendered = bpcgen.render(2, request, root=ROOT, btf_path=TINY)
    assert rendered.source.evidence is False
    assert "is not evidence" in rendered.text
    assert "Not a dump from a kernel" in rendered.text


def test_a_structure_the_blob_does_not_have_is_reported_and_not_hidden():
    request = bpcgen.Request(pin="v7.2.2", arch="x86_64", structures=("vm_fault",))
    rendered = bpcgen.render(2, request, root=ROOT, btf_path=TINY)
    assert rendered.problems and "vm_fault" in rendered.problems[0]
    assert "Not in" in rendered.text


def test_the_pointer_size_follows_the_architecture():
    thirty_two = bpcgen.Request(arch="i386", structures=("demo_arg",))
    rendered = bpcgen.render(2, thirty_two, root=ROOT, btf_path=TINY)
    assert "4 byte pointers" in rendered.text
    assert "| 0 | 4 | `name` |" in rendered.text


def test_section_seven_renders_an_ops_table_with_every_slot_empty():
    request = bpcgen.Request(pin="v7.2.2", arch="x86_64", ops=("demo_ops",))
    rendered = bpcgen.render(7, request, root=ROOT, btf_path=TINY)
    assert "| 16 | `write` |" in rendered.text
    assert "no instance has been read" in rendered.text
    assert "a fact about a running machine" in rendered.text


# -- generating from the corpus -----------------------------------------------------------------


def test_section_five_reads_the_trace_and_writes_out_the_call_tree():
    request = bpcgen.Request(pin="v7.2.2", artefacts=("traces/handwritten/page-fault",))
    rendered = bpcgen.render(5, request, root=ROOT)

    assert rendered.problems == []
    assert rendered.source.kind == "corpus"
    assert rendered.source.evidence is False
    assert "exc_page_fault" in rendered.text
    assert "do_anonymous_page" in rendered.text
    assert "An interrupt landed inside this recording" in rendered.text


def test_an_artefact_that_is_not_in_the_corpus_is_reported():
    request = bpcgen.Request(artefacts=("traces/handwritten/nothing-like-this",))
    rendered = bpcgen.render(5, request, root=ROOT)
    assert "nothing-like-this" in " ".join(rendered.problems)


def test_naming_no_artefacts_says_nothing_is_observed_rather_than_going_quiet():
    rendered = bpcgen.render(5, bpcgen.Request(), root=ROOT)
    assert "Nothing here is observed" in rendered.text
    assert rendered.source.evidence is False


# -- the regeneration pass ----------------------------------------------------------------------


def test_a_hand_edit_that_was_resealed_is_still_caught(tmp_path):
    """The one the checklist item is about.

    A seal alone can be recomputed, and somebody who edits a generated section and then runs
    `--reseal` gets a file that passes every text level check. Running the generator again is what
    catches it, because the content is not what any source produces.
    """
    path = write(tmp_path, blueprint(extra_header="structures: [vm_fault]"))
    bpc.generate(path, root=tmp_path)
    path.write_text(path.read_text().replace("`vm_fault`", "`vm_fault`, which is 144 bytes"))
    bpc.reseal(path)

    assert bpc.check(path) == []
    changed, problems = bpc.generate(path, root=tmp_path, dry_run=True)
    assert changed == 1
    assert "hand edited or its source moved" in " ".join(f.message for f in problems)


def test_a_dry_run_writes_nothing(tmp_path):
    path = write(tmp_path, blueprint(extra_header="structures: [vm_fault]"))
    before = path.read_text()
    bpc.generate(path, root=tmp_path, dry_run=True)
    assert path.read_text() == before


def test_a_dry_run_with_no_btf_leaves_a_section_that_came_from_btf_alone(tmp_path):
    """CI has no kernel, so it must not report a real field table as drift.

    Regenerating a BTF section without BTF would produce the empty state, and calling that a
    difference would mean the build asking for the good content to be deleted.
    """
    text = blueprint(
        extra_header="structures: [demo_task]",
        bodies={n: body(n, NO_EVIDENCE) for n in bpc.GENERATED},
    )
    path = write(tmp_path, text)
    changed, _ = bpc.generate(path, root=tmp_path, dry_run=True)
    assert changed == 3

    bpc.generate(path, root=ROOT, btf_path=TINY)
    changed, _ = bpc.generate(path, root=tmp_path, dry_run=True)
    assert changed == 0


# -- what is actually in the repository ----------------------------------------------------------

PAGE_FAULT = ROOT / "blueprints" / "page-fault.md"


def test_the_page_fault_blueprint_is_partial_and_says_why():
    lines = PAGE_FAULT.read_text().split("\n")
    header, _ = bpc.parse_front_matter(lines)
    assert header["status"] == "partial"
    assert header["pin"] == "v7.2.2"

    for section in bpc.GENERATED:
        source = bpcgen.parse_source(generated(PAGE_FAULT, section))
        assert source is not None
        assert source.evidence is False, f"section {section} claims evidence it does not have"


def test_the_page_fault_blueprint_carries_all_nine_edge_cases():
    text = PAGE_FAULT.read_text()
    for tag in bpc.EDGE_CASES:
        assert f"**{tag}.**" in text, f"section 6 has no {tag} entry"


def test_the_page_fault_blueprint_names_the_structures_it_will_generate_from():
    header, _ = bpc.parse_front_matter(PAGE_FAULT.read_text().split("\n"))
    request = bpcgen.Request.from_header(header)
    assert "vm_fault" in request.structures
    assert "handle_mm_fault" in request.interfaces
    assert request.artefacts == ("traces/handwritten/page-fault",)
