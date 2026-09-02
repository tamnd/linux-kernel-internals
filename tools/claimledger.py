"""The claim ledger.

    python3 -m tools.claimledger              check every lesson
    python3 -m tools.claimledger lessons/Z02  check one

This project makes one promise that matters more than the rest: nothing is asserted that the
reader cannot watch happen. A promise like that is worth nothing as a habit, because habits go
first when a deadline arrives, so it is a file format and a checker instead.

Every lesson has a `claims.toml` listing what it tells the reader is true, and what backs each
one. The checker enforces the parts that a tired reviewer would wave through:

* a claim backed by a trace has to point at a file that exists
* a claim cannot be marked verified against an artefact that is not evidence, which is what stops
  a handwritten fixture from quietly becoming a fact
* a lesson can have at most two claims nobody can observe
* a published lesson has to have every claim verified, so drafts are allowed to be honest about
  what is still missing and published lessons are not

The rule about handwritten artefacts is the important one. `corpora/traces/handwritten/` holds
traces nobody captured, written so the parser had something to test against. They are useful and
they are not evidence, their metadata says so, and this checker is what makes that stick.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SCHEMA = 1
LESSONS = "lessons"

# What can back a claim. Anything not on this list is not evidence.
EVIDENCE_KINDS = {
    "trace": "a capture committed under corpora/",
    "proc": "a /proc or /sys snapshot committed under corpora/",
    "oops": "a report the kernel printed to dmesg, committed under corpora/",
    "source": "a citation into the pinned kernel tree",
    "litmus": "a litmus test and its herd7 output",
    "experiment": "something the reader runs and sees for themselves",
    "unobservable": "nobody can watch this happen, and we say so out loud",
}

# Kinds whose evidence is a file in the repository. Being on this list is what makes the ledger go
# and look: the path has to exist, it has to have a `.meta.toml` beside it, and that metadata has
# to say `evidence = true`. A kind not on this list is a claim about something with no file to
# point at, and the ledger takes the lesson's word for it.
FILE_KINDS = {"trace", "proc", "oops", "litmus"}

UNOBSERVABLE_LIMIT = 2


@dataclass(frozen=True)
class Finding:
    path: str
    claim: str
    message: str

    def __str__(self) -> str:
        where = f"{self.path}" + (f" [{self.claim}]" if self.claim else "")
        return f"{where}: {self.message}"


def _load(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def artefact_is_evidence(path: Path) -> bool | None:
    """Whether a corpus artefact is allowed to back a claim.

    Returns None when the artefact has no metadata, which is its own problem and reported
    separately.
    """
    meta = path.with_suffix(".meta.toml")
    if not meta.exists():
        return None
    return bool(_load(meta).get("evidence", False))


def check_lesson(directory: Path) -> list[Finding]:
    """Check one lesson directory. Returns every problem found rather than the first."""
    found: list[Finding] = []
    claims_file = directory / "claims.toml"
    meta_file = directory / "meta.toml"

    if not meta_file.exists():
        return [Finding(str(directory), "", "no meta.toml, so nobody knows if this is published")]
    if not claims_file.exists():
        return [Finding(str(directory), "", "no claims.toml")]

    meta = _load(meta_file)
    document = _load(claims_file)
    where = str(claims_file)

    if document.get("schema") != SCHEMA:
        found.append(Finding(where, "", f"schema should be {SCHEMA}"))
    if document.get("lesson") != directory.name:
        found.append(Finding(where, "", f"lesson should be {directory.name!r}"))

    claims = document.get("claims", [])
    if not claims:
        found.append(Finding(where, "", "no claims, so this lesson tells the reader nothing"))

    published = meta.get("status") == "published"
    seen: set[str] = set()
    unobservable = 0

    for claim in claims:
        identifier = claim.get("id", "")
        if not identifier.startswith(f"{directory.name}-"):
            found.append(Finding(where, identifier, f"id should start with {directory.name}-"))
        if identifier in seen:
            found.append(Finding(where, identifier, "duplicate id"))
        seen.add(identifier)

        if not claim.get("text", "").strip():
            found.append(Finding(where, identifier, "no text, so there is no claim"))

        kind = claim.get("evidence_kind")
        if kind not in EVIDENCE_KINDS:
            found.append(
                Finding(
                    where,
                    identifier,
                    f"evidence_kind {kind!r} is not one of {sorted(EVIDENCE_KINDS)}",
                )
            )
            continue

        if kind == "unobservable":
            unobservable += 1

        found.extend(_check_evidence(where, identifier, claim, kind))

        if published and not claim.get("verified", False):
            found.append(
                Finding(where, identifier, "not verified, and this lesson is marked published")
            )

    if unobservable > UNOBSERVABLE_LIMIT:
        found.append(
            Finding(
                where,
                "",
                f"{unobservable} claims nobody can observe, the limit is {UNOBSERVABLE_LIMIT}",
            )
        )

    return found


def _check_evidence(where: str, identifier: str, claim: dict, kind: str) -> list[Finding]:
    found: list[Finding] = []
    verified = bool(claim.get("verified", False))
    evidence = claim.get("evidence", "")

    if kind == "unobservable":
        if verified:
            found.append(
                Finding(where, identifier, "unobservable and verified cannot both be true")
            )
        return found

    if verified and not evidence:
        found.append(Finding(where, identifier, "verified with nothing behind it"))
        return found

    if kind not in FILE_KINDS or not evidence:
        return found

    artefact = Path(evidence)
    if not artefact.exists():
        found.append(Finding(where, identifier, f"evidence {evidence} does not exist"))
        return found

    is_evidence = artefact_is_evidence(artefact)
    if is_evidence is None:
        found.append(
            Finding(where, identifier, f"{evidence} has no .meta.toml saying where it came from")
        )
    elif verified and not is_evidence:
        found.append(
            Finding(
                where,
                identifier,
                f"{evidence} is marked evidence = false, so it cannot verify anything",
            )
        )
    return found


def find_lessons(roots: Iterable[str]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        base = Path(root)
        if (base / "claims.toml").exists() or (base / "meta.toml").exists():
            found.append(base)
        elif base.is_dir():
            found.extend(sorted(p for p in base.iterdir() if (p / "meta.toml").exists()))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="claimledger", description="Check the claim ledger.")
    ap.add_argument("paths", nargs="*", default=[LESSONS], help="Lesson directories")
    ap.add_argument("--list-kinds", action="store_true", help="Print the evidence kinds and exit")
    args = ap.parse_args(argv)

    if args.list_kinds:
        for kind, meaning in EVIDENCE_KINDS.items():
            print(f"{kind:14} {meaning}")
        return 0

    lessons = find_lessons(args.paths or [LESSONS])
    if not lessons:
        print("claimledger: no lessons yet")
        return 0

    findings = [f for lesson in lessons for f in check_lesson(lesson)]
    for finding in findings:
        print(finding)

    if findings:
        print(f"\n{len(findings)} problem(s) in {len(lessons)} lesson(s)", file=sys.stderr)
        return 1

    print(f"claimledger: {len(lessons)} lesson(s) clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
