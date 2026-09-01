"""Tests for bpc, the blueprint compiler.

The one to keep is the seal: edit a generated section by hand and the build has to fail. Every
kernel book with field offsets in it is wrong within a release or two, and the reader has no way
to tell. The seal is how this project avoids joining them.
"""

from pathlib import Path

import pytest

from tools import bpc

ROOT = Path(__file__).resolve().parents[1]

BODY = {
    2: "Generated from BTF. Placeholder until the pinned kernel exists.",
    5: "Generated from the corpus. Placeholder until there are captures.",
    7: "Generated from BTF and the tree. Placeholder.",
}


def blueprint(name="widget", status="stub", extra_header="", sections=None, invariant=None) -> str:
    sections = sections or {}
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
        if number in BODY:
            content = BODY[number]
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
    path = write(tmp_path, blueprint().replace(BODY[7], "something else entirely"))
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
    body = "\n".join(f"- **{tag}.** Something true about it." for tag in bpc.EDGE_CASES)
    text = blueprint(
        status="complete",
        extra_header="reviewed-by: somebody who built one",
        sections={6: body},
    )
    assert bpc.check(write(tmp_path, text)) == []


def test_files_without_a_blueprint_header_are_not_blueprints(tmp_path):
    (tmp_path / "README.md").write_text("# Notes\n\nNo header.\n")
    write(tmp_path, blueprint())
    assert [p.name for p in bpc.find_blueprints([str(tmp_path)])] == ["widget.md"]


def test_the_repository_passes(monkeypatch):
    monkeypatch.chdir(ROOT)
    assert bpc.main([]) == 0
