"""The coverage ledger.

    python3 -m tools.coverage           check the ledger against what the documents cite
    python3 -m tools.coverage --show    print the ledger, grouped by status
    python3 -m tools.coverage --cited   print every kernel path this project cites and who owns it

This project will never cover the Linux kernel. Nothing does. The kernel is about forty million
lines and `drivers/` alone is around two thirds of it, so any book about it is a book about a
chosen slice, and the only question is whether the author says which slice or lets the reader find
out over six months.

`coverage.toml` is that declaration, and this checks it. Every top-level directory of the kernel
tree gets exactly one status, and so does every subsystem inside the ones in scope:

* `taught` has a lesson and at least one blueprint marked complete
* `partial` has something written about it, and no complete blueprint yet
* `mentioned` is reached into with a pointer outward, and no blueprint is owed
* `out-of-scope` is declared, with a reason, and nothing may cite into it

The `lessons` and `blueprints` on an entry are every document that cites into it, which is not the
same as every document about it. The page-fault blueprint is about memory management and it cites
one tracepoint definition under `include/trace/`, so it is listed on tracing too. That is on
purpose. The list answers "who reaches in here", because that is the question you need answered
when a file moves or a subsystem is rewritten.

The rule that does the work is the first one below. A lesson citing a file in a subsystem with no
entry fails the build. That is the mechanism that stops scope from expanding one citation at a
time, which is the way a project like this dies: nobody ever decides to cover the network stack,
somebody just cites `net/core/dev.c` in a lesson about something else, and a year later there are
eleven half taught subsystems and no finished ones.

The other rules keep the ledger honest in both directions, which matters more than it sounds.

* every kernel path cited by a lesson or a blueprint has an owner here
* the owner is the entry with the longest matching prefix, so `mm/shmem.c` can belong to tmpfs
  while the rest of `mm/` belongs to memory management
* every lesson and blueprint an entry names really does cite into it, so an entry cannot keep
  claiming credit for a lesson that moved on
* every lesson and blueprint that cites into an entry is named on it, so coverage cannot grow
  without the ledger saying so
* a status has to be earned: `taught` needs a complete blueprint, `partial` needs something
  written, `mentioned` owes no blueprint and may not have one

The last of those is why nothing is `taught` today. Both blueprints are `partial`, so the best any
subsystem can honestly claim is `partial`, and the ledger says that rather than rounding up.

What this does not do yet is draw the treemap over the tree sized by lines of code. That is on the
milestone that publishes the ledger on the site, and it needs the pinned tree unpacked to count
lines, which CI does not do. The declaration and the enforcement come first, because a picture of
a ledger nobody checks is worse than no picture.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from tools.bpc import parse_front_matter

LEDGER = Path("coverage.toml")
LESSONS = Path("lessons")
BLUEPRINTS = Path("blueprints")
SCHEMA = 1

STATUSES = ("taught", "partial", "mentioned", "out-of-scope")

# What a status has to have behind it before an entry may claim it.
NEEDS_LESSON = ("taught",)
NEEDS_SOMETHING = ("taught", "partial")
NEEDS_COMPLETE_BLUEPRINT = ("taught",)
FORBIDS_BLUEPRINT = ("mentioned", "out-of-scope")

# Every top-level directory of the kernel tree. All of them need an owner, because a ledger that
# only lists the parts somebody thought about is a ledger with holes exactly where the thinking
# stopped. This list is written down rather than read off the tree because CI does not unpack a
# hundred and sixty megabytes of tarball to check a declaration.
TOP_LEVEL = (
    "Documentation",
    "LICENSES",
    "arch",
    "block",
    "certs",
    "crypto",
    "drivers",
    "fs",
    "include",
    "init",
    "io_uring",
    "ipc",
    "kernel",
    "lib",
    "mm",
    "net",
    "rust",
    "samples",
    "scripts",
    "security",
    "sound",
    "tools",
    "usr",
    "virt",
)

# How long a reason has to be before it counts as one. Same number as the claim ledger uses, for
# the same reason: long enough that "not needed" does not clear it.
MIN_REASON = 40


@dataclass(frozen=True)
class Finding:
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


@dataclass(frozen=True)
class Citation:
    """One kernel path, and the document that cites it."""

    path: str
    document: str


@dataclass
class Subsystem:
    name: str
    status: str
    paths: list[str] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)
    blueprints: list[str] = field(default_factory=list)
    reason: str = ""
    note: str = ""

    def owns(self, path: str) -> str | None:
        """The longest of this entry's prefixes that matches, or None."""
        matching = [one for one in self.paths if path == one or path.startswith(one)]
        return max(matching, key=len) if matching else None


def load(path: Path = LEDGER) -> tuple[list[Subsystem], dict]:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = [
        Subsystem(
            name=one.get("name", ""),
            status=one.get("status", ""),
            paths=list(one.get("paths", [])),
            lessons=list(one.get("lessons", [])),
            blueprints=list(one.get("blueprints", [])),
            reason=one.get("reason", ""),
            note=one.get("note", ""),
        )
        for one in document.get("subsystem", [])
    ]
    return entries, document


def owner(entries: list[Subsystem], path: str) -> Subsystem | None:
    """Which entry owns a kernel path, by longest matching prefix.

    Longest match rather than first match, so an entry for one file inside a directory beats the
    entry for the directory. That is what lets tmpfs own `mm/shmem.c` while memory management owns
    the rest of `mm/`, without either of them having to list what the other has taken.
    """
    matched = [(one, one.owns(path)) for one in entries]
    hits = [(one, prefix) for one, prefix in matched if prefix is not None]
    return max(hits, key=lambda pair: len(pair[1]))[0] if hits else None


def citations(lessons: Path = LESSONS, blueprints: Path = BLUEPRINTS) -> list[Citation]:
    """Every kernel path this project cites, and which document cites it."""
    found: list[Citation] = []
    for refs in sorted(lessons.glob("*/refs.toml")):
        found += _read_refs(refs, refs.parent.name)
    for refs in sorted(blueprints.glob("*.refs.toml")):
        found += _read_refs(refs, refs.name.removesuffix(".refs.toml"))
    return found


def _read_refs(path: Path, document: str) -> list[Citation]:
    entries = tomllib.loads(path.read_text(encoding="utf-8")).get("references", [])
    return [Citation(one["path"], document) for one in entries if one.get("path")]


def blueprint_status(name: str, root: Path = BLUEPRINTS) -> str | None:
    """The status in a blueprint's front matter, or None when there is no such blueprint."""
    path = root / f"{name}.md"
    if not path.exists():
        return None
    header, _ = parse_front_matter(path.read_text(encoding="utf-8").splitlines())
    return str(header.get("status", ""))


def check(entries: list[Subsystem], document: dict, cited: list[Citation]) -> list[Finding]:
    """Everything wrong with the ledger, in the order somebody would want to fix it."""
    found: list[Finding] = []
    if document.get("schema") != SCHEMA:
        found.append(Finding(str(LEDGER), f"schema should be {SCHEMA}"))
    if not entries:
        found.append(Finding(str(LEDGER), "no subsystems, so nothing is declared"))
        return found

    found += _check_entries(entries)
    found += _check_top_level(entries)
    found += _check_citations(entries, cited)
    return found


def _check_entries(entries: list[Subsystem]) -> list[Finding]:
    found: list[Finding] = []
    seen: set[str] = set()
    claimed: dict[str, str] = {}

    for one in entries:
        where = f"{LEDGER} [{one.name or '?'}]"
        if not one.name:
            found.append(Finding(str(LEDGER), "an entry with no name"))
        if one.name in seen:
            found.append(Finding(where, "declared twice"))
        seen.add(one.name)

        if one.status not in STATUSES:
            found.append(Finding(where, f"status {one.status!r} is not one of {list(STATUSES)}"))
        if not one.paths:
            found.append(Finding(where, "no paths, so it owns nothing"))
        found += _check_paths(one, where, claimed)

        if one.status == "out-of-scope" and len(one.reason.strip()) < MIN_REASON:
            found.append(Finding(where, "out of scope needs a reason, in a sentence"))
        if one.status in NEEDS_LESSON and not one.lessons:
            found.append(Finding(where, f"{one.status} with no lesson behind it"))
        if one.status in NEEDS_SOMETHING and not (one.lessons or one.blueprints):
            found.append(Finding(where, f"{one.status} with nothing written about it"))
        if one.status in FORBIDS_BLUEPRINT and one.blueprints:
            found.append(
                Finding(where, f"{one.status} owes no blueprint, and names {one.blueprints}")
            )

        found += _check_named(one, where)
    return found


def _check_paths(one: Subsystem, where: str, claimed: dict[str, str]) -> list[Finding]:
    """That the prefixes are unambiguous, and that a directory is written as one.

    Ownership is by longest match, so two entries listing the same prefix have no answer and the
    winner would come down to the order of the file. A directory written without its trailing
    slash is the other quiet one: `arch/x86` matches `arch/x86_64/mm/fault.c`, and the ledger would
    look right while owning the wrong half of the tree.
    """
    found: list[Finding] = []
    for path in one.paths:
        if path in claimed:
            found.append(Finding(where, f"claims {path}, and so does {claimed[path]}"))
        claimed[path] = one.name
        if not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
            found.append(Finding(where, f"{path} looks like a directory, so write it as {path}/"))
    return found


def _check_named(one: Subsystem, where: str) -> list[Finding]:
    """That the lessons and blueprints an entry names exist, and that its status is earned."""
    found: list[Finding] = []
    for lesson in one.lessons:
        if not (LESSONS / lesson / "meta.toml").exists():
            found.append(Finding(where, f"names lesson {lesson}, which does not exist"))

    statuses = {}
    for name in one.blueprints:
        status = blueprint_status(name)
        if status is None:
            found.append(Finding(where, f"names blueprint {name}, which does not exist"))
        else:
            statuses[name] = status

    if one.status in NEEDS_COMPLETE_BLUEPRINT and "complete" not in statuses.values():
        found.append(
            Finding(
                where,
                "taught needs a complete blueprint, and its blueprints are "
                + (f"{statuses}" if statuses else "not named"),
            )
        )
    return found


def _check_top_level(entries: list[Subsystem]) -> list[Finding]:
    """That every top-level directory of the kernel has an owner."""
    return [
        Finding(str(LEDGER), f"nothing owns {name}/, so that part of the tree is undeclared")
        for name in TOP_LEVEL
        if owner(entries, f"{name}/") is None
    ]


def _check_citations(entries: list[Subsystem], cited: list[Citation]) -> list[Finding]:
    """The rule this whole file exists for, and the two that keep it true in both directions."""
    found: list[Finding] = []
    reaches: dict[str, set[str]] = {}

    for one in sorted(set(cited), key=lambda c: (c.path, c.document)):
        holder = owner(entries, one.path)
        if holder is None:
            found.append(
                Finding(
                    one.document,
                    f"cites {one.path}, and no subsystem in {LEDGER} owns it. Add an entry, or "
                    "stop citing it.",
                )
            )
            continue
        if holder.status == "out-of-scope":
            found.append(
                Finding(
                    one.document,
                    f"cites {one.path}, which {holder.name} declares out of scope",
                )
            )
        reaches.setdefault(holder.name, set()).add(one.document)

    found += _check_both_ways(entries, reaches)
    return found


def _check_both_ways(entries: list[Subsystem], reaches: dict[str, set[str]]) -> list[Finding]:
    """That the entry and the documents agree about who touches what.

    A ledger only checked one way rots quietly. An entry keeps naming a lesson that stopped citing
    it, or a lesson starts citing a subsystem the entry has never heard of and the status stays at
    whatever it was. Both of those are the ledger describing last month.
    """
    found: list[Finding] = []
    for one in entries:
        where = f"{LEDGER} [{one.name}]"
        named = set(one.lessons) | set(one.blueprints)
        citing = reaches.get(one.name, set())

        for stale in sorted(named - citing):
            found.append(Finding(where, f"names {stale}, which cites nothing it owns"))
        for missing in sorted(citing - named):
            found.append(Finding(where, f"{missing} cites it and is not named on the entry"))
    return found


def show(entries: list[Subsystem]) -> str:
    rows = []
    for status in STATUSES:
        here = [one for one in entries if one.status == status]
        rows.append(f"{status} ({len(here)})")
        for one in here:
            behind = ", ".join(one.lessons + one.blueprints) or "nothing yet"
            rows.append(f"  {one.name:22} {', '.join(one.paths):46} {behind}")
        rows.append("")
    return "\n".join(rows).rstrip() + "\n"


def cited_table(entries: list[Subsystem], cited: list[Citation]) -> str:
    rows = []
    for path in sorted({one.path for one in cited}):
        holder = owner(entries, path)
        who = sorted({one.document for one in cited if one.path == path})
        rows.append(f"{path:46} {holder.name if holder else 'NOBODY':22} {', '.join(who)}")
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="coverage", description="Check the coverage ledger.")
    ap.add_argument("--show", action="store_true", help="Print the ledger by status and stop")
    ap.add_argument("--cited", action="store_true", help="Print every cited path and its owner")
    args = ap.parse_args(argv)

    if not LEDGER.exists():
        print(f"coverage: {LEDGER} does not exist", file=sys.stderr)
        return 1

    entries, document = load()
    cited = citations()

    if args.show:
        print(show(entries), end="")
        return 0
    if args.cited:
        print(cited_table(entries, cited), end="")
        return 0

    findings = check(entries, document, cited)
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} problem(s) in the coverage ledger", file=sys.stderr)
        return 1

    counts = {status: sum(1 for one in entries if one.status == status) for status in STATUSES}
    print(
        f"coverage: {len(entries)} subsystem(s), "
        + ", ".join(f"{count} {status}" for status, count in counts.items())
        + f", {len({one.path for one in cited})} path(s) cited"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
