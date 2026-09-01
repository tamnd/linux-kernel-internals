"""bpc, the blueprint compiler, version 0.1.

    python3 -m tools.bpc                    check every blueprint
    python3 -m tools.bpc blueprints/vfs.md  check one
    python3 -m tools.bpc --reseal PATH      recompute the seals on the generated sections

A blueprint is a specification of one mechanism, written so that somebody can implement against
it without reading the lesson. Nine sections, always the same nine, always in the same order, so
that a reader who has read one can find anything in any of the others.

Version 0.1 checks the shape and guards the generated sections. It does not generate anything
yet, because generating section 2 needs BTF from the pinned kernel and the pinned kernel is not
built. What it does do is make a hand edit to a generated section fail the build, which is the
property that has to be in place before the first generated section exists rather than after.

The seal is a hash of the content between the markers. `--reseal` recomputes it. That looks like
a way around the check and it is not the point of it: when the generator lands, resealing becomes
part of generating, and the check is what stops the output drifting from its source in between.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

BLUEPRINTS = "blueprints"

SECTIONS = (
    (1, "Purpose and boundary"),
    (2, "Data structures"),
    (3, "Algorithms"),
    (4, "Invariants, locking and context"),
    (5, "Observable behaviour"),
    (6, "Edge cases and failure modes"),
    (7, "Interfaces"),
    (8, "Configuration and architecture dependence"),
    (9, "Reimplementation notes"),
)

SUBSECTIONS = (
    ("4a", "Invariants"),
    ("4b", "Locking discipline"),
    ("4c", "Execution context"),
)

# The sections bpc produces once it can. Everything else is written by a person.
GENERATED = (2, 5, 7)

STATUSES = ("stub", "partial", "complete")

REQUIRED_KEYS = ("blueprint", "title", "status", "pin", "arch", "lessons", "generated")

# The fixed set from NOTATION.md. A blueprint at complete needs all nine.
EDGE_CASES = (
    "allocation-failure",
    "concurrent-entry",
    "wrong-context",
    "signal",
    "object-freed",
    "refcount-zero",
    "boundary-cases",
    "hostile-input",
    "bug-message",
)

# A blueprint may not lean on the lesson. If an implementer needs it, it goes in the blueprint.
LESSON_REFERENCES = (
    "as we saw",
    "as we have seen",
    "recall that",
    "recall from",
    "see the chapter",
    "see the lesson",
    "in the lesson",
    "earlier we",
    "as mentioned earlier",
)

SEAL_OPEN = re.compile(
    r"^<!--\s*bpc:generated\s+section=(\d+)\s+hash=([0-9a-f]{16}|unsealed)\s*-->\s*$"
)
SEAL_CLOSE = re.compile(r"^<!--\s*bpc:end\s+section=(\d+)\s*-->\s*$")
HEADING = re.compile(r"^##\s+§(\d)\s+(.+?)\s*$")
SUBHEADING = re.compile(r"^###\s+§(4[abc])\s+(.+?)\s*$")
NUMBERED = re.compile(r"^\s*\d+\.\s+\S")
INVARIANT_CHECK = re.compile(r"\[(checked:[^\]]+|unchecked)\]\s*$")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.message}"


@dataclass
class Seal:
    section: int
    declared: str
    open_line: int
    close_line: int
    content: str

    @property
    def actual(self) -> str:
        return digest(self.content)


def digest(content: str) -> str:
    """The seal. Sixteen hex characters is short enough to read and long enough to mean it."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def parse_front_matter(lines: list[str]) -> tuple[dict[str, object], int]:
    """Read the header block.

    A small subset of YAML on purpose: `key: value`, inline lists in brackets, and block lists of
    `- item`. The CI job that runs this has no dependencies, and a header that needs a parser
    library is a header nobody can check in the fast job.
    """
    if not lines or lines[0].strip() != "---":
        return {}, 0

    header: dict[str, object] = {}
    key = None
    for index, raw in enumerate(lines[1:], start=1):
        text = raw.rstrip()
        if text.strip() == "---":
            return header, index + 1
        if not text.strip():
            continue
        if text.lstrip().startswith("-") and key:
            item = text.lstrip()[1:].strip()
            values = header.setdefault(key, [])
            if isinstance(values, list):
                values.append(item)
            continue
        if ":" not in text:
            continue
        key, _, value = text.partition(":")
        key = key.strip()
        value = value.split(" #")[0].strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            header[key] = [v.strip() for v in inner.split(",") if v.strip()]
        elif value:
            header[key] = value
        else:
            header[key] = []
    return header, len(lines)


def find_seals(lines: list[str]) -> tuple[list[Seal], list[Finding]]:
    seals: list[Seal] = []
    problems: list[Finding] = []
    open_at: tuple[int, int, str] | None = None
    body: list[str] = []

    for number, raw in enumerate(lines, start=1):
        opened = SEAL_OPEN.match(raw.strip())
        closed = SEAL_CLOSE.match(raw.strip())
        if opened:
            if open_at:
                problems.append(
                    Finding("", number, "seal", "a generated block opened inside another")
                )
            open_at = (int(opened.group(1)), number, opened.group(2))
            body = []
            continue
        if closed:
            if not open_at:
                problems.append(
                    Finding("", number, "seal", "a generated block closed that never opened")
                )
                continue
            section, line, declared = open_at
            if int(closed.group(1)) != section:
                problems.append(
                    Finding(
                        "", number, "seal", f"section {closed.group(1)} closes section {section}"
                    )
                )
            seals.append(Seal(section, declared, line, number, "\n".join(body)))
            open_at = None
            continue
        if open_at:
            body.append(raw.rstrip("\n"))

    if open_at:
        problems.append(Finding("", open_at[1], "seal", "a generated block was never closed"))
    return seals, problems


def section_bounds(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Where each section starts and ends, by number, one indexed and end exclusive."""
    marks: list[tuple[str, int]] = []
    for number, raw in enumerate(lines, start=1):
        heading = HEADING.match(raw)
        sub = SUBHEADING.match(raw)
        if heading:
            marks.append((heading.group(1), number))
        elif sub:
            marks.append((sub.group(1), number))

    bounds: dict[str, tuple[int, int]] = {}
    for index, (name, start) in enumerate(marks):
        end = marks[index + 1][1] if index + 1 < len(marks) else len(lines) + 1
        bounds[name] = (start, end)
    return bounds


def _check_header(path: str, header: dict[str, object], stem: str) -> list[Finding]:
    found: list[Finding] = []
    if not header:
        return [Finding(path, 1, "front-matter", "no header block")]

    for key in REQUIRED_KEYS:
        if key not in header:
            found.append(Finding(path, 1, "front-matter", f"missing {key}"))

    name = str(header.get("blueprint", ""))
    if name and name.lower() != stem.lower():
        found.append(
            Finding(path, 1, "front-matter", f"blueprint is {name!r}, the file is {stem!r}")
        )

    status = str(header.get("status", ""))
    if status and status not in STATUSES:
        found.append(
            Finding(path, 1, "front-matter", f"status {status!r} is not one of {list(STATUSES)}")
        )
    if status == "complete" and not header.get("reviewed-by"):
        found.append(
            Finding(
                path, 1, "front-matter", "complete needs reviewed-by, and it has to be a person"
            )
        )

    declared = {str(s) for s in header.get("generated", []) if str(s)}
    if declared and declared != {str(s) for s in GENERATED}:
        found.append(
            Finding(
                path,
                1,
                "front-matter",
                f"generated is {sorted(declared)}, it has to be {list(GENERATED)}",
            )
        )
    return found


def _check_sections(
    path: str, lines: list[str]
) -> tuple[dict[str, tuple[int, int]], list[Finding]]:
    found: list[Finding] = []
    bounds = section_bounds(lines)

    order = [name for name, _ in sorted(bounds.items(), key=lambda item: item[1][0])]
    wanted = [str(number) for number, _ in SECTIONS]
    wanted_with_subs = []
    for number in wanted:
        wanted_with_subs.append(number)
        if number == "4":
            wanted_with_subs.extend(name for name, _ in SUBSECTIONS)

    for name in wanted_with_subs:
        if name not in bounds:
            found.append(Finding(path, 1, "sections", f"no section {name}"))

    present = [name for name in order if name in wanted_with_subs]
    expected = [name for name in wanted_with_subs if name in bounds]
    if present != expected:
        found.append(Finding(path, 1, "sections", f"sections are out of order: {present}"))

    titles = dict(SECTIONS)
    for number, title in SECTIONS:
        key = str(number)
        if key in bounds:
            heading = HEADING.match(lines[bounds[key][0] - 1])
            if heading and heading.group(2) != titles[number]:
                found.append(
                    Finding(
                        path,
                        bounds[key][0],
                        "sections",
                        f"section {key} should be titled {title!r}",
                    )
                )
    return bounds, found


def _check_seals(path: str, seals: list[Seal]) -> list[Finding]:
    found: list[Finding] = []
    sealed = {seal.section for seal in seals}
    for section in GENERATED:
        if section not in sealed:
            found.append(
                Finding(path, 1, "seal", f"section {section} is generated and has no block")
            )
    for seal in seals:
        if seal.section not in GENERATED:
            found.append(
                Finding(
                    path,
                    seal.open_line,
                    "seal",
                    f"section {seal.section} is not a generated section",
                )
            )
        elif seal.declared == "unsealed":
            found.append(Finding(path, seal.open_line, "seal", "unsealed, run bpc --reseal"))
        elif seal.declared != seal.actual:
            found.append(
                Finding(
                    path,
                    seal.open_line,
                    "seal",
                    f"section {seal.section} was hand edited, {seal.declared} is now {seal.actual}",
                )
            )
    return found


def _check_lesson_references(path: str, lines: list[str]) -> list[Finding]:
    found = []
    for number, raw in enumerate(lines, start=1):
        lowered = raw.lower()
        for phrase in LESSON_REFERENCES:
            if phrase in lowered:
                found.append(
                    Finding(
                        path,
                        number,
                        "lesson-reference",
                        f'"{phrase}" points at the lesson, put what the implementer needs here',
                    )
                )
    return found


def _check_invariants(
    path: str, lines: list[str], bounds: dict[str, tuple[int, int]]
) -> list[Finding]:
    if "4a" not in bounds:
        return []
    start, end = bounds["4a"]
    found = []
    for number in range(start, min(end, len(lines) + 1)):
        raw = lines[number - 1]
        if NUMBERED.match(raw) and not INVARIANT_CHECK.search(raw.rstrip()):
            found.append(
                Finding(
                    path,
                    number,
                    "invariant",
                    "an invariant ends with [checked: what checks it] or [unchecked]",
                )
            )
    return found


def _check_edge_cases(
    path: str, lines: list[str], bounds: dict[str, tuple[int, int]]
) -> list[Finding]:
    if "6" not in bounds:
        return []
    start, end = bounds["6"]
    text = "\n".join(lines[start - 1 : end - 1])
    missing = [tag for tag in EDGE_CASES if tag not in text]
    if missing:
        return [Finding(path, start, "edge-cases", f"section 6 is missing {missing}")]
    return []


def check(path: Path) -> list[Finding]:
    lines = path.read_text(encoding="utf-8").split("\n")
    name = str(path)
    header, _ = parse_front_matter(lines)
    status = str(header.get("status", ""))

    found = _check_header(name, header, path.stem)
    bounds, section_findings = _check_sections(name, lines)
    found.extend(section_findings)

    seals, seal_problems = find_seals(lines)
    found.extend(Finding(name, f.line, f.rule, f.message) for f in seal_problems)
    found.extend(_check_seals(name, seals))
    found.extend(_check_lesson_references(name, lines))
    found.extend(_check_invariants(name, lines, bounds))

    # A stub is allowed to be thin, and it says so in its header. Complete is not.
    if status == "complete":
        found.extend(_check_edge_cases(name, lines, bounds))

    return sorted(found, key=lambda f: (f.line, f.rule))


def reseal(path: Path) -> int:
    """Rewrite every seal to match the content it wraps. Returns how many changed."""
    lines = path.read_text(encoding="utf-8").split("\n")
    seals, _ = find_seals(lines)
    changed = 0
    for seal in seals:
        if seal.declared == seal.actual:
            continue
        index = seal.open_line - 1
        lines[index] = re.sub(
            r"hash=[0-9a-f]{16}|hash=unsealed", f"hash={seal.actual}", lines[index]
        )
        changed += 1
    if changed:
        path.write_text("\n".join(lines), encoding="utf-8")
    return changed


def find_blueprints(roots: Iterable[str]) -> list[Path]:
    """Every markdown file with a blueprint header. README and NOTATION have none."""
    found: list[Path] = []
    for root in roots:
        base = Path(root)
        candidates = [base] if base.is_file() else sorted(base.rglob("*.md"))
        for candidate in candidates:
            head = candidate.read_text(encoding="utf-8").split("\n", 3)[:3]
            if head and head[0].strip() == "---" and any("blueprint:" in line for line in head):
                found.append(candidate)
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bpc", description="Check the blueprints.")
    ap.add_argument("paths", nargs="*", default=[BLUEPRINTS], help="Blueprints or directories")
    ap.add_argument("--reseal", action="store_true", help="Recompute the generated section hashes")
    args = ap.parse_args(argv)

    blueprints = find_blueprints(args.paths or [BLUEPRINTS])
    if not blueprints:
        print("bpc: no blueprints yet")
        return 0

    if args.reseal:
        for path in blueprints:
            changed = reseal(path)
            print(f"{path}: {changed} seal(s) rewritten")
        return 0

    findings = [f for path in blueprints for f in check(path)]
    for finding in findings:
        print(finding)

    if findings:
        print(f"\n{len(findings)} problem(s) in {len(blueprints)} blueprint(s)", file=sys.stderr)
        return 1

    print(f"bpc: {len(blueprints)} blueprint(s) clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
