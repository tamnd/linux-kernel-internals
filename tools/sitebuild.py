"""Build the published book out of the files that are already in the repository.

    python3 -m tools.sitebuild            stage the pages and write the generated files
    python3 -m tools.sitebuild --check    fail if a generated file is out of date

MkDocs can only see files underneath its `docs_dir`, and the lessons and the blueprints do not
live there. They live beside the code they are about, which is where a person editing them wants
them. So this stages copies into `site/docs/` and those copies are not committed, because a file
that exists twice in one repository is a file that will disagree with itself.

Three things are committed and generated: `site/mkdocs.yml`, which is the handwritten `head.yml`
with a navigation tree appended, and `site/docs/stylesheets/vocabulary.css`, which turns the one
list of colours into the one the site is painted with. Both are checked in CI, so a lesson that
gets added without the navigation being rebuilt fails rather than quietly not appearing.

The staging is a copy rather than a symlink on purpose. A symlink works locally, breaks on a
Windows checkout, and is followed by some tools and not others.
"""

from __future__ import annotations

import argparse
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from tools.bpc import parse_front_matter

SITE = "site"
DOCS = "docs"
LESSONS = "lessons"
BLUEPRINTS = "blueprints"
HEAD = "head.yml"
CONFIG = "mkdocs.yml"
STYLESHEET = Path("stylesheets") / "vocabulary.css"

REPO = "tamnd/linux-kernel-internals"
COLAB = "https://colab.research.google.com/github"

# The pages somebody wrote by hand, in the order they are read. Everything else in the navigation
# is worked out from what is on disk.
FRONT = (
    ("Home", "index.md"),
    ("How to read this", "how-to-read-this.md"),
    ("The two tiers", "tiers.md"),
)

# What a status means on a card, and the colour it is drawn in. Draft is not a failure state, it
# is a lesson that is honest about being unfinished, so it is drawn in a colour that says so
# without shouting.
STATUSES = {
    "published": ("#15803d", "#dcfce7"),
    "complete": ("#15803d", "#dcfce7"),
    "partial": ("#b45309", "#fef3c7"),
    "draft": ("#b45309", "#fef3c7"),
    "stub": ("#475569", "#e2e8f0"),
    "planned": ("#475569", "#e2e8f0"),
}


@dataclass(frozen=True)
class Lesson:
    """One lesson, as the site needs to know it."""

    identifier: str
    title: str
    status: str
    directory: Path

    @property
    def notebook(self) -> Path:
        return self.directory / f"{self.identifier}.ipynb"

    @property
    def page(self) -> str:
        # Staged as `index.ipynb` so the lesson lives at `/lessons/Z02/` rather than at
        # `/lessons/Z02/Z02/`, which is what the obvious name gives you.
        return f"{LESSONS}/{self.identifier}/index.ipynb"

    @property
    def colab(self) -> str:
        return f"{COLAB}/{REPO}/blob/main/{LESSONS}/{self.identifier}/{self.identifier}.ipynb"


@dataclass(frozen=True)
class Blueprint:
    """One blueprint, as the site needs to know it."""

    name: str
    title: str
    status: str
    pin: str
    arch: str
    path: Path

    @property
    def page(self) -> str:
        return f"{BLUEPRINTS}/{self.name}.md"


# -- what is on disk ------------------------------------------------------------------------------


def find_lessons(root: Path) -> list[Lesson]:
    found = []
    for meta_file in sorted((root / LESSONS).glob("*/meta.toml")):
        meta = tomllib.loads(meta_file.read_text(encoding="utf-8"))
        found.append(
            Lesson(
                identifier=str(meta.get("id", meta_file.parent.name)),
                title=str(meta.get("title", "")),
                status=str(meta.get("status", "planned")),
                directory=meta_file.parent,
            )
        )
    return found


def find_blueprints(root: Path) -> list[Blueprint]:
    found = []
    for path in sorted((root / BLUEPRINTS).glob("*.md")):
        if path.name in {"README.md", "NOTATION.md", "TEMPLATE.md"}:
            continue
        header, _ = parse_front_matter(path.read_text(encoding="utf-8").split("\n"))
        found.append(
            Blueprint(
                name=str(header.get("blueprint", path.stem)),
                title=str(header.get("title", path.stem)),
                status=str(header.get("status", "stub")),
                pin=str(header.get("pin", "")),
                arch=str(header.get("arch", "")),
                path=path,
            )
        )
    return found


# -- the generated files --------------------------------------------------------------------------


def badge(status: str) -> str:
    return f'<span class="kx-badge kx-status-{status}">{status}</span>'


def navigation(lessons: list[Lesson], blueprints: list[Blueprint]) -> str:
    """The `nav:` block, worked out from what is on disk rather than typed twice."""
    out = ["nav:"]
    for title, page in FRONT:
        out.append(f"  - {title}: {page}")

    out.append("  - Lessons:")
    out.append(f"      - All lessons: {LESSONS}/index.md")
    for lesson in lessons:
        out.append(f'      - "{lesson.identifier}: {lesson.title}": {lesson.page}')

    out.append("  - Blueprints:")
    out.append(f"      - All blueprints: {BLUEPRINTS}/index.md")
    out.append(f"      - Notation: {BLUEPRINTS}/NOTATION.md")
    for blueprint in blueprints:
        out.append(f'      - "{blueprint.title}": {blueprint.page}')
    return "\n".join(out) + "\n"


def config(root: Path, lessons: list[Lesson], blueprints: list[Blueprint]) -> str:
    """`mkdocs.yml`, which is `head.yml` with the navigation on the end."""
    head = (root / SITE / HEAD).read_text(encoding="utf-8").rstrip("\n")
    warning = (
        "# Generated by tools/sitebuild.py. Edit head.yml, or the navigation in sitebuild.py,\n"
        "# and run `just site`. An edit here is reverted by the next build.\n"
    )
    return f"{warning}\n{head}\n\n{navigation(lessons, blueprints)}"


def stylesheet() -> str:
    """The site colours, taken from the one list that the diagrams and the widgets also read."""
    from kxray import vocabulary

    out = [
        "/* Generated by tools/sitebuild.py from kxray/vocabulary.py. Do not edit. */",
        "",
        "/* A subsystem is the same colour in a diagram, in a widget and on this page. That is the",
        "   whole reason the list lives in one file and this one is written out of it. */",
        ":root {",
    ]
    for one in vocabulary.SUBSYSTEMS:
        out.append(f"  --kx-{one.key}-stroke: {one.stroke};")
        out.append(f"  --kx-{one.key}-fill: {one.fill};")
    for name, (stroke, fill) in STATUSES.items():
        out.append(f"  --kx-status-{name}-stroke: {stroke};")
        out.append(f"  --kx-status-{name}-fill: {fill};")
    out.append("}")
    out += [
        "",
        ".kx-badge {",
        "  border: 1px solid currentColor;",
        "  border-radius: 3px;",
        "  font-size: 0.75rem;",
        "  padding: 0.05rem 0.35rem;",
        "  white-space: nowrap;",
        "}",
        "",
    ]
    for name in STATUSES:
        out.append(f".kx-status-{name} {{")
        out.append(f"  color: var(--kx-status-{name}-stroke);")
        out.append(f"  background: var(--kx-status-{name}-fill);")
        out.append("}")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def lesson_index(lessons: list[Lesson]) -> str:
    out = [
        "# All lessons",
        "",
        "Every lesson is a notebook. The page here is that notebook with its output, and the Colab link opens the same file on a machine that can run it with nothing installed.",
        "",
        "A lesson marked draft is written and unverified. That is a real state and it is written down rather than hidden, because a lesson whose claims nobody has watched happen is not the same thing as one whose claims have been checked.",
        "",
        "| Lesson | Status | Run it |",
        "| --- | --- | --- |",
    ]
    for lesson in lessons:
        run = f"[Open in Colab]({lesson.colab})"
        out.append(
            f"| [{lesson.identifier}, {lesson.title}]"
            f"({lesson.identifier}/index.ipynb) | {badge(lesson.status)} | {run} |"
        )
    out += [
        "",
        f"{len(lessons)} written so far, of 103 planned.",
        "",
    ]
    return "\n".join(out)


def blueprint_index(blueprints: list[Blueprint]) -> str:
    out = [
        "# All blueprints",
        "",
        "A blueprint specifies one mechanism well enough to implement it without reading the lesson, and no blueprint is allowed to send you to one.",
        "",
        "Sections 2, 5 and 7 are generated out of the kernel rather than typed, which is what stops the field offsets in this book from going stale the way they do in every other one. A blueprint is only complete when those three came from a real build, and until then it says partial and says why.",
        "",
        "| Blueprint | Status | Kernel | Architecture |",
        "| --- | --- | --- | --- |",
    ]
    for one in blueprints:
        out.append(
            f"| [{one.title}]({one.name}.md) | {badge(one.status)} "
            f"| {one.pin or 'not pinned'} | {one.arch or 'not stated'} |"
        )
    out += [
        "",
        f"{len(blueprints)} written so far, of 60 planned.",
        "",
    ]
    return "\n".join(out)


# -- staging ---------------------------------------------------------------------------------------


def stage(root: Path, lessons: list[Lesson], blueprints: list[Blueprint]) -> list[Path]:
    """Copy the lessons and the blueprints under `site/docs/`, and write the index pages.

    Everything this writes is ignored by git. It is a build directory that happens to sit inside
    a source one, because that is where MkDocs insists on looking.
    """
    docs = root / SITE / DOCS
    written: list[Path] = []

    lessons_dir = docs / LESSONS
    _clear(lessons_dir)
    for lesson in lessons:
        into = lessons_dir / lesson.identifier
        into.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lesson.notebook, into / "index.ipynb")
        written.append(into / "index.ipynb")
        written += _copy_assets(lesson.directory / "assets", into / "assets")
    written.append(_write(lessons_dir / "index.md", lesson_index(lessons)))

    blueprints_dir = docs / BLUEPRINTS
    _clear(blueprints_dir)
    blueprints_dir.mkdir(parents=True, exist_ok=True)
    for one in blueprints:
        shutil.copy2(one.path, blueprints_dir / one.path.name)
        written.append(blueprints_dir / one.path.name)
    notation = root / BLUEPRINTS / "NOTATION.md"
    if notation.exists():
        shutil.copy2(notation, blueprints_dir / notation.name)
        written.append(blueprints_dir / notation.name)
    written += _copy_assets(root / BLUEPRINTS / "assets", blueprints_dir / "assets")
    written.append(_write(blueprints_dir / "index.md", blueprint_index(blueprints)))

    return written


def _copy_assets(source: Path, into: Path) -> list[Path]:
    """Copy the pictures a page points at, and nothing else that happens to be beside them."""
    if not source.is_dir():
        return []
    into.mkdir(parents=True, exist_ok=True)
    out = []
    for one in sorted(source.iterdir()):
        if one.suffix not in {".svg", ".png"}:
            continue
        shutil.copy2(one, into / one.name)
        out.append(into / one.name)
    return out


def _clear(directory: Path) -> None:
    if directory.is_dir():
        shutil.rmtree(directory)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# -- the command line ------------------------------------------------------------------------------


def build(root: Path, *, check: bool = False) -> tuple[int, list[str]]:
    """Write everything, or say what is out of date. Returns a count and what to print."""
    lessons = find_lessons(root)
    blueprints = find_blueprints(root)
    lines: list[str] = []

    wanted = {
        root / SITE / CONFIG: config(root, lessons, blueprints),
        root / SITE / DOCS / STYLESHEET: stylesheet(),
    }

    stale = 0
    for path, text in wanted.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        stale += 1
        if check:
            lines.append(f"{path.relative_to(root)} is out of date, run `just site`")
        else:
            _write(path, text)
            lines.append(f"wrote {path.relative_to(root)}")

    if not check:
        staged = stage(root, lessons, blueprints)
        lines.append(
            f"sitebuild: {len(lessons)} lesson(s), {len(blueprints)} blueprint(s), "
            f"{len(staged)} file(s) staged"
        )
    elif not stale:
        lines.append(f"sitebuild: {len(lessons)} lesson(s), {len(blueprints)} blueprint(s), clean")

    return stale, lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sitebuild", description="Build the published book.")
    ap.add_argument("--check", action="store_true", help="Fail if a generated file is stale")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    stale, lines = build(root, check=args.check)
    for line in lines:
        print(line)
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
