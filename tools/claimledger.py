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
* a lesson has to say which kernel, which architecture, which profile and which tier it is written
  against, and the profile has to be one `kxbox/kernel/pin.toml` actually builds
* evidence has to come off the machine the lesson says it does, or the claim has to say why not
* a lesson can have at most two claims nobody can observe
* a published lesson has to have every claim verified, so drafts are allowed to be honest about
  what is still missing and published lessons are not

The rule about handwritten artefacts is the important one. `corpora/traces/handwritten/` holds
traces nobody captured, written so the parser had something to test against. They are useful and
they are not evidence, their metadata says so, and this checker is what makes that stick.

The rule about the declaration is the one that will annoy people, so here is the argument for it.
A kernel claim with no version, config and architecture attached is not a claim, because the same
sentence is true on one build and false on another, and a reader cannot tell which they have. Every
lesson already declares those four things in its `meta.toml` and every artefact already declares
them in its `.meta.toml`. Until now nothing compared the two, so a lesson pinned to 7.2.2 on i386
could cite a capture off 6.8 on aarch64 and nothing would say a word.

Some of those citations are right, and there are two kinds. A Tier 0 lesson has to reach for Tier 1
when the thing it is about needs more than one CPU or a real clock, because v86 has neither and no
amount of work changes that. And a lesson about lockdep has to cite captures taken under the
lockdep profile rather than the default one, because the default build does not have lockdep in it.

So the rule is not that evidence has to match. It is that evidence that does not match has to say
why, in the claim, in a sentence, in `why_not_pinned`. A reason that goes stale is also caught: a
claim carrying `why_not_pinned` whose evidence does match the declaration is an excuse for a
problem that no longer exists, and a wrong explanation is worse than none.
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

# Where the profiles are defined, so that a profile a lesson names has to be one somebody builds.
PIN = Path("kxbox/kernel/pin.toml")

# What a lesson has to say about the machine its claims are about, and what an artefact says about
# the machine it came off. The same four names in both files, on purpose.
DECLARED = ("kernel", "arch", "profile", "tier")

# The same architecture under the names different tools give it. This is a small table on purpose.
# It exists because `uname -m` says `i686`, the kernel build says `i386` and everybody says `x86`
# for the same thing, and comparing those as strings would fail on a difference that is not one.
# Anything not in here is compared as written, which is the safe direction: an unknown name fails
# to match rather than matching something it should not.
ARCH_FAMILIES = {
    "x86": "x86-32",
    "i386": "x86-32",
    "i486": "x86-32",
    "i586": "x86-32",
    "i686": "x86-32",
    "x86_64": "x86-64",
    "amd64": "x86-64",
    "aarch64": "arm64",
    "arm64": "arm64",
}

# How long a reason has to be before it counts as one. Short enough that a real sentence clears it
# easily, long enough that "n/a" and "see above" do not.
MIN_REASON = 40


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


def profiles(pin: Path = PIN) -> dict[str, str]:
    """Every profile `pin.toml` builds, and which kernel version each one is on.

    A profile names a tree rather than a version, so `C-longterm` follows the fallback and the
    others follow the pinned one. Reading it this way means bumping the pin moves every lesson at
    once, and renaming a profile fails a check rather than leaving a lesson pointing at a build
    nobody makes any more.
    """
    if not pin.exists():
        return {}
    document = _load(pin)
    trees = {name: document.get(name, {}).get("version", "") for name in ("kernel", "fallback")}
    return {
        one.get("name", ""): trees.get(one.get("kernel", "kernel"), "")
        for one in document.get("profiles", [])
    }


def _same_arch(one: str, other: str) -> bool:
    return ARCH_FAMILIES.get(one, one) == ARCH_FAMILIES.get(other, other)


def check_declaration(where: str, meta: dict, built: dict[str, str]) -> list[Finding]:
    """That the lesson says which machine it is about, and that the machine is one that exists."""
    found: list[Finding] = []
    for name in DECLARED:
        if meta.get(name) in (None, ""):
            found.append(Finding(where, "", f"no {name}, so its claims are about no machine"))
    if meta.get("tier") not in (None, 0, 1):
        found.append(Finding(where, "", f"tier {meta.get('tier')!r} is not 0 or 1"))

    profile = meta.get("profile")
    if not profile or not built:
        return found
    if profile not in built:
        found.append(
            Finding(where, "", f"profile {profile!r} is not one of {sorted(built)} in {PIN}")
        )
    elif built[profile] and meta.get("kernel") != built[profile]:
        found.append(
            Finding(
                where,
                "",
                f"says kernel {meta.get('kernel')!r} but profile {profile!r} builds "
                f"{built[profile]!r}",
            )
        )
    return found


def _differences(meta: dict, artefact: dict) -> list[str]:
    """Every way an artefact disagrees with the lesson about which machine it came off."""
    out = []
    for name in DECLARED:
        theirs, ours = artefact.get(name), meta.get(name)
        if theirs in (None, "") or ours in (None, ""):
            continue
        same = _same_arch(str(ours), str(theirs)) if name == "arch" else ours == theirs
        if not same:
            out.append(f"{name} {theirs!r} rather than {ours!r}")
    return out


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

    found.extend(check_declaration(str(meta_file), meta, profiles()))

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

        found.extend(_check_evidence(where, identifier, claim, kind, meta))

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


def _check_evidence(
    where: str, identifier: str, claim: dict, kind: str, meta: dict
) -> list[Finding]:
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

    if not evidence:
        return found

    artefact = Path(evidence)
    if kind in FILE_KINDS and not artefact.exists():
        found.append(Finding(where, identifier, f"evidence {evidence} does not exist"))
        return found

    if kind in FILE_KINDS:
        is_evidence = artefact_is_evidence(artefact)
        if is_evidence is None:
            found.append(
                Finding(
                    where, identifier, f"{evidence} has no .meta.toml saying where it came from"
                )
            )
        elif verified and not is_evidence:
            found.append(
                Finding(
                    where,
                    identifier,
                    f"{evidence} is marked evidence = false, so it cannot verify anything",
                )
            )

    found.extend(_check_machine(where, identifier, claim, meta, artefact))
    return found


def _check_machine(
    where: str, identifier: str, claim: dict, meta: dict, artefact: Path
) -> list[Finding]:
    """That evidence came off the machine the lesson says it did, or the claim says why not.

    This runs on any evidence that turns out to be a file with metadata beside it, rather than only
    on the kinds in `FILE_KINDS`, because an `experiment` kind pointing at a committed run is the
    same situation and deserves the same question.
    """
    beside = artefact.with_suffix(".meta.toml")
    if not artefact.is_file() or not beside.exists():
        return []

    differs = _differences(meta, _load(beside))
    reason = claim.get("why_not_pinned", "")

    if differs and not reason:
        return [
            Finding(
                where,
                identifier,
                f"{artefact} was taken on {', '.join(differs)}, so the claim needs a "
                "why_not_pinned saying why that is the right machine for it",
            )
        ]
    if differs and len(reason.strip()) < MIN_REASON:
        return [
            Finding(
                where,
                identifier,
                f"why_not_pinned is {len(reason.strip())} characters, which is not a reason. "
                f"Say why {artefact} is on {', '.join(differs)} in a sentence.",
            )
        ]
    if reason and not differs:
        return [
            Finding(
                where,
                identifier,
                f"why_not_pinned explains a difference that is not there, because {artefact} "
                "matches what the lesson declares",
            )
        ]
    return []


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
