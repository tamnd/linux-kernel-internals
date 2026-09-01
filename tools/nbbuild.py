"""Build the lesson notebooks from the Python files that define them.

    python3 lessons/Z02/build.py            write lessons/Z02/Z02.ipynb
    python3 lessons/Z02/build.py --check    fail if the committed notebook is out of date
    python3 -m tools.nbbuild                build every lesson
    python3 -m tools.nbbuild --check        check every lesson

A `.ipynb` is JSON with the prose stored as lists of strings with the newlines left on. A machine
reads that happily and a person cannot. Change one word in a paragraph and the diff is unreadable,
every cell needs an id that is easy to duplicate by hand, and there is nowhere to write down why a
cell is the way it is.

So the source of truth for a lesson is `build.py` next to it, and the notebook is generated. The
notebook is committed anyway, because a reader clicking a Colab badge cannot run a build step
first, and `--check` is what stops the two from drifting apart.

## The claim rule

Every lesson has a `claims.toml`, and the claim ledger already checks that each claim names the
evidence behind it. This adds the part the ledger cannot see: where the claim sits in the lesson.

`lesson.claim("Z02-05")` hands back the claim's own words, so the prose reads as it would have,
and records the rule that **the evidence is the next code cell, and it has to arrive before the
next heading**. Without the second half every claim would find some cell further down and the
check would pass on a lesson that proves nothing.

Claims whose evidence is a citation or which are marked unobservable have no cell to point at, so
they are exempt. Those are the two kinds the reader cannot run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO = "tamnd/linux-kernel-internals"
BRANCH = "main"
LESSONS = "lessons"
RAW = "https://raw.githubusercontent.com"

# Evidence a reader runs. These are the kinds that need a code cell under the claim.
RUNNABLE_KINDS = {"trace", "proc", "experiment", "litmus"}

HEADING = re.compile(r"^\s{0,3}#{1,6}\s", re.MULTILINE)

NOTEBOOK_METADATA = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}


@dataclass
class Cell:
    kind: str
    source: str
    identifier: str
    note: str | None = None

    def to_json(self) -> dict:
        lines = self.source.strip("\n").split("\n")
        source = [line + "\n" for line in lines[:-1]] + [lines[-1]] if lines else []
        metadata: dict[str, object] = {"id": self.identifier}
        if self.note:
            metadata["note"] = self.note
        cell: dict[str, object] = {
            "cell_type": self.kind,
            "id": self.identifier,
            "metadata": metadata,
            "source": source,
        }
        if self.kind == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
        return cell


@dataclass
class Claim:
    identifier: str
    cell_index: int
    tail: str  # the part of the markdown cell that comes after the claim


@dataclass
class Lesson:
    """One lesson, built cell by cell and written out as a notebook."""

    slug: str
    stem: str | None = None
    root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    cells: list[Cell] = field(default_factory=list)
    claims_made: list[Claim] = field(default_factory=list)
    blocks: list[tuple[int, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.stem = self.stem or self.slug
        self.directory = self.root / LESSONS / self.slug
        self.path = self.directory / f"{self.stem}.ipynb"
        self.markdown_path = self.directory / "lesson.md"
        self._claims = self._load_claims()

    def _load_claims(self) -> dict[str, dict]:
        source = self.directory / "claims.toml"
        if not source.exists():
            return {}
        document = tomllib.loads(source.read_text(encoding="utf-8"))
        return {c["id"]: c for c in document.get("claims", [])}

    @property
    def badge(self) -> str:
        """The Colab badge, built from the path the notebook is about to be written to.

        Copying the last lesson and forgetting to change this link is the easiest mistake in a
        project like this one, so it is generated and cannot be got wrong.
        """
        target = f"{LESSONS}/{self.slug}/{self.stem}.ipynb"
        return (
            "[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)]"
            f"(https://colab.research.google.com/github/{REPO}/blob/{BRANCH}/{target})"
        )

    def image(self, name: str, alt: str) -> str:
        """A diagram from this lesson's `assets/`, by absolute URL.

        A relative path renders on GitHub and shows a broken image in Colab, because the notebook
        there was fetched on its own and has no directory around it. One absolute URL works in
        both places, so there is one form rather than two.
        """
        url = f"{RAW}/{REPO}/{BRANCH}/{LESSONS}/{self.slug}/assets/{name}"
        return f"![{alt}]({url})"

    def _next_id(self) -> str:
        return f"{str(self.stem).lower()}-{len(self.cells) + 1:02d}"

    def md(self, text: str) -> None:
        self.cells.append(Cell("markdown", text, self._next_id()))

    def block(self, name: str) -> None:
        """Open one of the five lesson blocks.

        The marker only reaches `lesson.md`, where `lintprose` reads it to apply the word caps.
        A reader in a notebook has no use for it.
        """
        self.blocks.append((len(self.cells), name))

    def code(self, source: str, note: str | None = None) -> None:
        """A code cell. `note` records why it is here, for a reader of the builder."""
        self.cells.append(Cell("code", source, self._next_id(), note))

    def claim(self, identifier: str) -> str:
        """Make a claim in the prose, by id, and record where it was made."""
        if identifier not in self._claims:
            raise KeyError(f"{identifier} is not in {self.slug}/claims.toml")
        self.claims_made.append(Claim(identifier, len(self.cells), ""))
        return str(self._claims[identifier]["text"]).rstrip(".")

    def _check_claims(self) -> list[str]:
        problems = []
        for claim in self.claims_made:
            kind = self._claims[claim.identifier].get("evidence_kind")
            if kind not in RUNNABLE_KINDS:
                continue
            found = False
            for cell in self.cells[claim.cell_index + 1 :]:
                if cell.kind == "code":
                    found = True
                    break
                if HEADING.search(cell.source):
                    break
            if not found:
                problems.append(
                    f"{claim.identifier} has no code cell before the next heading, "
                    "so the lesson asserts it and does not show it"
                )

        made = {c.identifier for c in self.claims_made}
        for identifier in self._claims:
            if identifier not in made:
                problems.append(f"{identifier} is in claims.toml and the lesson never makes it")
        return problems

    def to_json(self) -> str:
        notebook = {
            "cells": [cell.to_json() for cell in self.cells],
            "metadata": NOTEBOOK_METADATA,
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        return json.dumps(notebook, indent=1, ensure_ascii=False) + "\n"

    def to_markdown(self) -> str:
        """The same lesson as a markdown file, for reading on the web and for lintprose.

        One source, two outputs. A lesson whose prose lived in two files would have two versions
        of every paragraph within a month.
        """
        starts = dict((index, name) for index, name in self.blocks)
        out: list[str] = []
        for index, cell in enumerate(self.cells):
            if index in starts:
                out.append(f"<!-- block: {starts[index]} -->")
            if cell.kind == "markdown":
                out.append(cell.source.strip("\n"))
            else:
                out.append("```python\n" + cell.source.strip("\n") + "\n```")
        return "\n\n".join(out) + "\n"

    def save(self, argv: list[str] | None = None) -> int:
        args = list(sys.argv[1:] if argv is None else argv)
        checking = "--check" in args

        problems = self._check_claims()
        for problem in problems:
            print(f"{self.slug}: {problem}", file=sys.stderr)
        if problems:
            return 1

        outputs = {self.path: self.to_json(), self.markdown_path: self.to_markdown()}
        stale = [
            path
            for path, built in outputs.items()
            if (path.read_text(encoding="utf-8") if path.exists() else None) != built
        ]

        if checking:
            for path in stale:
                print(f"{path}: out of date, run `just build-lessons`", file=sys.stderr)
            if stale:
                return 1
            print(f"{self.slug}: up to date")
            return 0

        for path in stale:
            path.write_text(outputs[path], encoding="utf-8")
            print(f"wrote {path}")
        if not stale:
            print(f"{self.slug}: unchanged")
        return 0


def find_builders(root: Path) -> list[Path]:
    return sorted((root / LESSONS).glob("*/build.py"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nbbuild", description="Build the lesson notebooks.")
    ap.add_argument("--check", action="store_true", help="Fail if a notebook is out of date")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    builders = find_builders(root)
    if not builders:
        print("nbbuild: no lessons yet")
        return 0

    worst = 0
    for builder in builders:
        code = _run(builder, ["--check"] if args.check else [])
        worst = max(worst, code)
    return worst


def _run(builder: Path, argv: list[str]) -> int:
    """Run one builder in this process, with its arguments, and return its exit code."""
    saved = sys.argv
    sys.argv = [str(builder), *argv]
    try:
        source = builder.read_text(encoding="utf-8")
        namespace: dict[str, object] = {"__file__": str(builder), "__name__": "__main__"}
        exec(compile(source, str(builder), "exec"), namespace)  # noqa: S102
        return 0
    except SystemExit as stop:
        return int(stop.code or 0)
    finally:
        sys.argv = saved


if __name__ == "__main__":
    raise SystemExit(main())
