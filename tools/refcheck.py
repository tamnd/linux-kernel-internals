"""Check the references, ours and the kernel's.

    python3 -m tools.refcheck                       check everything that can be checked here
    python3 -m tools.refcheck --tree ~/src/linux    also resolve every kernel citation
    python3 -m tools.refcheck --tree ~/src/linux --confirm    write the line numbers back
    python3 -m tools.refcheck --list-planned        paths we talk about that do not exist yet

There are two kinds of reference in this repository and both of them rot.

The first is a path into this repository, written in prose, in backticks. A file gets moved and
forty documents keep pointing at where it used to be. Nobody notices, because prose does not fail
to compile. This is not hypothetical. The first run of this checker found a lesson pointing at a
teaching config that had moved into a subdirectory when the kernel got pinned. The exception is a
path a build makes, such as the vmlinux a generated blueprint section says it read its types out
of. That file is absent in a fresh checkout by design, and naming it is the whole point.

The second is a citation into the kernel tree. This is the one the project cannot afford to get
wrong, because a lesson that says "see mm/memory.c:5310" is worthless the moment somebody adds ten
lines above it, and worse than worthless, because it now points confidently at something else.

So a citation here never rests on a line number. It names a file and a piece of text to find in
it. The line number is output, not input: `--confirm` against a real tree writes down where the
text was, and the next check finds it again wherever it has moved to. A citation that cannot be
found is a failure with the file and the anchor in it, which is the moment to go and read the
code rather than six months later.

`./kxbox/kernel/tree.sh` unpacks the pinned source, and `--tree` against it is what turns an
unconfirmed citation into a confirmed one. An unconfirmed citation still cannot verify a claim, and
the checker says how many are waiting so that nobody has to go looking.

The first real run of `--tree` had twenty one problems in it, out of thirty six citations. Three
were files that had moved, and the rest were anchors that matched in more than one place, usually
a function name that also appears at a call site or in a forward declaration. Both kinds are the
reason this tool exists, and neither would have been caught by reading.

A confirmed citation also carries a context hash, which covers the failure the anchor cannot. An
anchor is usually a function signature, the signature is the most stable line in a function, and
the body underneath it is the part people edit. So a citation supporting a sentence about what a
function does can go stale without the anchor moving at all. `--confirm` records a hash of the
lines around the anchor, and a later `--tree` run reports "still there and the lines around it have
changed", which is a different sentence from "gone" and needs a different answer from a reader.
`kxray.source.citations` does the hashing and says what it deliberately does not notice.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from kxray.source import citations

SCHEMA = 1

LESSONS = Path("lessons")
BLUEPRINTS = Path("blueprints")
PLANNED = Path("refcheck.toml")
PIN = Path("kxbox/kernel/pin.toml")

# Things a build makes. These are not in a fresh checkout and they are not meant to be, so
# "does not exist" is the normal state rather than a stale reference. They cannot go in the
# planned list either, because that list fails when a path turns up and these turn up on any
# machine that has run a build. A blueprint generated from a kernel says which vmlinux it read,
# and that sentence has to name the real path or it is not provenance.
BUILD_OUTPUT = ("kxbox/kernel/build/", "site/_build/")

# The top level of a kernel tree. A citation whose first segment is not one of these is not a
# path into the kernel, it is a typo or a path into this repository by mistake.
KERNEL_TOPS = {
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
}

# A backticked token that has a slash in it and no shell or glob punctuation. Anything with a
# placeholder in it, like `lessons/<ID>/assets/`, is prose about a shape rather than a path.
BACKTICKED = re.compile(r"`([^`\n]+)`")
PLACEHOLDER = re.compile(r"[<>*{}|$\s]")

FENCE = re.compile(r"^\s*```")

# An anchor has to be long enough to be worth searching for. One word matches everywhere and
# tells you nothing when it moves.
MIN_ANCHOR = 12

# How a blueprint points at its evidence in the middle of a sentence: `[page-fault-R07]`.
CITATION = re.compile(r"\[([a-z0-9][a-z0-9-]*-R\d+)\]")

# What a recorded context hash looks like. The width comes from `kxray.source.citations`.
CONTEXT = re.compile(r"[0-9a-f]{" + str(citations.WIDTH) + "}")


@dataclass(frozen=True)
class Finding:
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


@dataclass(frozen=True)
class Reference:
    """One citation into the kernel tree."""

    identifier: str
    path: str
    anchor: str
    kernel: str
    confirmed: bool = False
    line: int = 0
    context: str = ""
    note: str = ""
    source: str = ""

    def __str__(self) -> str:
        state = f"line {self.line}" if self.confirmed else "unconfirmed"
        return f"{self.identifier}  {self.path}  ({state})"


def _load(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


# -- paths into this repository ----------------------------------------------------------------


def repository_tops(root: Path) -> set[str]:
    """What the top level of this repository has in it, right now.

    Read from the filesystem rather than written down, because a hardcoded list is one more thing
    that goes stale, and this is a checker for things going stale.
    """
    return {entry.name for entry in root.iterdir() if not entry.name.startswith(".")}


def planned_paths(root: Path) -> dict[str, str]:
    """Paths this repository talks about that do not exist yet, and why.

    The same shape as the Kconfig drop rule, for the same reason. Writing about a directory before
    it exists is fine and often useful, because the plan is public. Doing it silently means nobody
    can tell a plan from a broken link.
    """
    path = root / PLANNED
    if not path.exists():
        return {}
    document = _load(path)
    return {entry["path"]: entry.get("reason", "") for entry in document.get("planned", [])}


def exists(root: Path, target: str) -> bool:
    """Whether a path in prose points at something.

    `tools/kconfig` is how a person writes a module they run with `-m`, so a bare path that is a
    Python module counts as found. Being fussy about that spelling would train people to ignore
    the checker, which is the only way a checker actually fails.
    """
    candidate = root / target.rstrip("/")
    return candidate.exists() or candidate.with_suffix(".py").exists()


def prose_paths(text: str) -> list[tuple[int, str]]:
    """Every backticked repository-looking path in a document, with its line number.

    Fenced code blocks are skipped. A command line in a code block is an example, and half of
    them name files that are meant to be typed rather than files that exist.
    """
    found: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        for match in BACKTICKED.finditer(line):
            token = match.group(1)
            if "/" not in token or PLACEHOLDER.search(token):
                continue
            found.append((number, token))
    return found


def check_document(
    root: Path, path: Path, tops: set[str], planned: dict[str, str]
) -> list[Finding]:
    findings: list[Finding] = []
    generated = path.name in ("lesson.md",)
    for number, token in prose_paths(path.read_text(encoding="utf-8")):
        if token.split("/")[0] not in tops:
            continue
        if token.startswith(BUILD_OUTPUT):
            continue
        if exists(root, token) or token in planned:
            continue
        hint = ", which is generated from build.py, so fix it there" if generated else ""
        findings.append(
            Finding(f"{path}:{number}", f"points at {token}, which does not exist{hint}")
        )
    return findings


def check_planned(root: Path, planned_file: dict) -> list[Finding]:
    """A planned path has to say why, and has to stop being planned once it turns up."""
    findings: list[Finding] = []
    for entry in planned_file.get("planned", []):
        target = entry.get("path", "")
        where = f"{PLANNED}#{target or '?'}"
        if not target:
            findings.append(Finding(str(PLANNED), "an entry with no path"))
            continue
        reason = str(entry.get("reason", "")).strip()
        if len(reason.split()) < 8:
            findings.append(Finding(where, "no reason saying what it will be, in at least 8 words"))
        if exists(root, target):
            findings.append(Finding(where, "exists now, so take it out of the planned list"))
    return findings


def pinned_profiles(root: Path) -> set[str]:
    path = root / PIN
    if not path.exists():
        return set()
    return {str(p.get("name")) for p in _load(path).get("profiles", []) if p.get("name")}


def check_lesson_metadata(root: Path, directory: Path, profiles: set[str]) -> list[Finding]:
    """A lesson says which build it was written against, and it has to be one that exists.

    A kernel claim with no version, config and architecture attached is not a claim. Naming a
    profile out of `pin.toml` gets all three at once, and it means a profile that gets renamed
    fails here rather than leaving a lesson pointing at a build nobody makes any more.
    """
    meta = directory / "meta.toml"
    if not meta.exists():
        return []
    document = _load(meta)
    profile = document.get("profile")
    if not profile:
        return [Finding(str(meta), "no profile, and a kernel claim with no build is not a claim")]
    if profiles and profile not in profiles:
        listed = ", ".join(sorted(profiles))
        return [Finding(str(meta), f"profile is {profile}, and pin.toml has {listed}")]
    return []


# -- citations into the kernel -----------------------------------------------------------------


def pinned_versions(root: Path) -> set[str]:
    """The kernel versions a citation is allowed to name, out of the pin file."""
    path = root / PIN
    if not path.exists():
        return set()
    document = _load(path)
    return {
        str(document[key]["version"])
        for key in ("kernel", "fallback")
        if isinstance(document.get(key), dict) and document[key].get("version")
    }


def read_references(path: Path) -> tuple[list[Reference], list[Finding]]:
    """Read one `refs.toml`. Shape problems come back as findings rather than exceptions."""
    document = _load(path)
    findings: list[Finding] = []
    references: list[Reference] = []

    if document.get("schema") != SCHEMA:
        findings.append(
            Finding(str(path), f"schema is {document.get('schema')!r}, expected {SCHEMA}")
        )

    for entry in document.get("references", []):
        references.append(
            Reference(
                identifier=str(entry.get("id", "")),
                path=str(entry.get("path", "")),
                anchor=str(entry.get("anchor", "")),
                kernel=str(entry.get("kernel", "")),
                confirmed=bool(entry.get("confirmed", False)),
                line=int(entry.get("line", 0) or 0),
                context=str(entry.get("context", "")),
                note=str(entry.get("note", "")),
                source=str(path),
            )
        )
    return references, findings


def check_reference(reference: Reference, lesson: str, versions: set[str]) -> list[Finding]:
    where = f"{reference.source}#{reference.identifier or '?'}"
    findings: list[Finding] = []

    if not reference.identifier.startswith(f"{lesson}-R"):
        findings.append(Finding(where, f"id should start with {lesson}-R"))

    if not reference.path:
        findings.append(Finding(where, "no path, so there is nothing to cite"))
    else:
        if reference.path.startswith("/"):
            findings.append(
                Finding(where, "an absolute path, and a citation is relative to the tree")
            )
        elif reference.path.split("/")[0] not in KERNEL_TOPS:
            head = reference.path.split("/")[0]
            findings.append(Finding(where, f"starts with {head}/, which is not in a kernel tree"))
        if ":" in reference.path:
            findings.append(
                Finding(where, "has a line number in the path, and a line number is not an anchor")
            )

    if len(reference.anchor.strip()) < MIN_ANCHOR:
        findings.append(
            Finding(where, f"the anchor is under {MIN_ANCHOR} characters, so it matches anywhere")
        )
    if reference.anchor.strip().isdigit():
        findings.append(Finding(where, "the anchor is a number, and line numbers move"))

    if reference.kernel not in versions:
        findings.append(
            Finding(where, f"names kernel {reference.kernel!r}, which is not a pinned version")
        )

    if reference.context and not CONTEXT.fullmatch(reference.context):
        findings.append(
            Finding(where, f"context is {reference.context!r}, and a context hash is 12 hex digits")
        )

    if reference.confirmed and reference.line <= 0:
        findings.append(Finding(where, "says confirmed with no line, so nobody has resolved it"))
    if reference.line > 0 and not reference.confirmed:
        findings.append(Finding(where, "has a line but is not confirmed, so the line is a guess"))

    return findings


def check_lesson_claims(directory: Path, references: list[Reference]) -> list[Finding]:
    """A claim that rests on the source has to name a citation, and a verified one a confirmed
    citation.

    This lives here rather than in the claim ledger because the reference format is this tool's
    business. The ledger checks that evidence exists and is allowed to count. This checks that a
    source claim points at a citation somebody has actually resolved against a tree.
    """
    claims_file = directory / "claims.toml"
    if not claims_file.exists():
        return []

    by_id = {r.identifier: r for r in references}
    findings: list[Finding] = []
    for claim in _load(claims_file).get("claims", []):
        if claim.get("evidence_kind") != "source":
            continue
        identifier = claim.get("id", "?")
        where = f"{claims_file}#{identifier}"
        evidence = str(claim.get("evidence", ""))
        verified = bool(claim.get("verified", False))

        if not evidence:
            if verified:
                findings.append(Finding(where, "verified against the source with no citation"))
            continue
        if evidence not in by_id:
            findings.append(Finding(where, f"cites {evidence}, which is not in refs.toml"))
            continue
        if verified and not by_id[evidence].confirmed:
            findings.append(
                Finding(where, f"verified against {evidence}, which nobody has confirmed yet")
            )
    return findings


def check_blueprint_citations(document: Path, references: list[Reference]) -> list[Finding]:
    """Every citation marker in the prose exists, and every citation in the file is used.

    A blueprint is a normative document, so a sentence in one is a claim about the kernel and a
    claim about the kernel needs somewhere a reader can go and check it. The marker in the prose
    is `[page-fault-R07]`, and it resolves here rather than in the reader's head.

    The unused half matters as much as the missing half. A citation nothing points at is usually a
    sentence that got rewritten and lost its evidence on the way, and the file still looks
    thoroughly cited afterwards.
    """
    findings: list[Finding] = []
    text = document.read_text(encoding="utf-8")
    used = {found.group(1) for found in CITATION.finditer(text)}
    known = {r.identifier for r in references}

    for identifier in sorted(used - known):
        findings.append(Finding(str(document), f"cites {identifier}, which is not in refs.toml"))
    for identifier in sorted(known - used):
        findings.append(
            Finding(
                f"{document.stem}.refs.toml#{identifier}",
                "is not cited anywhere in the blueprint, so nothing rests on it",
            )
        )
    return findings


def resolve(reference: Reference, tree: Path) -> tuple[int | None, str, str]:
    """Find the anchor in a real kernel tree, and hash the lines around it.

    Returns the line, the context hash, and what went wrong if anything did. The first match wins,
    and a second match is reported, because an anchor that appears twice is an anchor that will
    silently point at the wrong one after the next refactor.

    The hash is the part that is new and it exists for a failure the anchor cannot catch. An anchor
    is usually a function signature, the signature is the most stable line in a function, and the
    body underneath it is the part people edit. So a citation supporting a sentence about what a
    function does can go stale without the anchor moving at all, and until this was recorded
    nothing noticed. `kxray.source.citations` does the hashing and says what it normalises away.
    """
    path = tree / reference.path
    if not path.exists():
        return None, "", f"{reference.path} is not in {tree}"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as problem:
        return None, "", f"cannot read {reference.path}: {problem}"

    hit = citations.resolve(text, reference.anchor)
    if not hit.found:
        return None, "", f"{reference.anchor!r} is not in {reference.path} any more"
    if hit.problem:
        return hit.line, hit.context, f"{reference.anchor!r} {hit.problem}"
    if citations.changed(reference.context, hit.context):
        return (
            hit.line,
            hit.context,
            (
                f"{reference.anchor!r} is still there and "
                f"{citations.compare(reference.context, hit.context)}, so go and read it"
            ),
        )
    return hit.line, hit.context, ""


# -- putting it together -------------------------------------------------------------------------


def find_documents(root: Path) -> list[Path]:
    # `build` is on this list because `./kxbox/kernel/tree.sh` unpacks ninety thousand files of
    # Linux into `kxbox/kernel/build/tree`, and several thousand of them are markdown. None of it
    # is ours, none of it is checkable by these rules, and walking it takes long enough to notice.
    skip = {".git", "__pycache__", "node_modules", "vendor", "build"}
    found = []
    for path in sorted(root.rglob("*.md")):
        if any(part in skip for part in path.parts):
            continue
        found.append(path)
    return found


def find_lessons(root: Path) -> list[Path]:
    lessons = root / LESSONS
    if not lessons.is_dir():
        return []
    return sorted(p for p in lessons.iterdir() if (p / "meta.toml").exists())


def find_blueprints(root: Path) -> list[tuple[Path, Path]]:
    """Every blueprint that has citations, as the document and its `refs.toml` beside it.

    A blueprint keeps its references in `<name>.refs.toml` rather than in a directory of its own,
    because a blueprint is one file and giving each one a directory to hold a single sidecar buys
    nothing. A blueprint with no citations does not appear here at all, which is allowed while one
    is a stub and is what the status field is for.
    """
    directory = root / BLUEPRINTS
    if not directory.is_dir():
        return []
    found = []
    for refs in sorted(directory.rglob("*.refs.toml")):
        document = refs.with_name(refs.name[: -len(".refs.toml")] + ".md")
        if document.exists():
            found.append((document, refs))
    return found


def check(root: Path) -> tuple[list[Finding], list[Reference]]:
    tops = repository_tops(root)
    planned_file = _load(root / PLANNED) if (root / PLANNED).exists() else {}
    planned = planned_paths(root)
    versions = pinned_versions(root)
    profiles = pinned_profiles(root)

    findings = check_planned(root, planned_file)
    for document in find_documents(root):
        findings.extend(check_document(root, document, tops, planned))

    references: list[Reference] = []
    for lesson in find_lessons(root):
        findings.extend(check_lesson_metadata(root, lesson, profiles))
        refs_file = lesson / "refs.toml"
        mine: list[Reference] = []
        if refs_file.exists():
            mine, problems = read_references(refs_file)
            findings.extend(problems)
            for reference in mine:
                findings.extend(check_reference(reference, lesson.name, versions))
            references.extend(mine)
        # A lesson may only cite its own references, so this gets that lesson's list and not the
        # pile from every lesson before it.
        findings.extend(check_lesson_claims(lesson, mine))

    for document, refs_file in find_blueprints(root):
        mine, problems = read_references(refs_file)
        findings.extend(problems)
        for reference in mine:
            findings.extend(check_reference(reference, document.stem, versions))
        findings.extend(check_blueprint_citations(document, mine))
        references.extend(mine)

    return findings, references


def confirm(root: Path, tree: Path, *, write: bool) -> tuple[list[Finding], int]:
    """Resolve every citation against a real tree, and optionally write the line numbers back."""
    findings: list[Finding] = []
    resolved = 0
    files = [lesson / "refs.toml" for lesson in find_lessons(root)]
    files += [refs for _, refs in find_blueprints(root)]

    for refs_file in files:
        if not refs_file.exists():
            continue
        references, problems = read_references(refs_file)
        findings.extend(problems)

        text = refs_file.read_text(encoding="utf-8")
        for reference in references:
            line, context, problem = resolve(reference, tree)
            where = f"{refs_file}#{reference.identifier}"
            if problem:
                findings.append(Finding(where, problem))
            if line is None:
                continue
            resolved += 1
            state = citations.compare(reference.context, context)
            print(f"{reference.identifier}  {reference.path}:{line}  {context}  {state}")
            if write and not problem:
                text = _rewrite(text, reference.identifier, line, context)
        if write:
            refs_file.write_text(text, encoding="utf-8")
    return findings, resolved


def _rewrite(text: str, identifier: str, line: int, context: str = "") -> str:
    """Put the resolved line, the confirmation and the context hash into one entry.

    A rewrite rather than a dump of parsed TOML, because the comments in these files are the part
    a person wrote and a round trip through tomllib would throw all of them away.

    An entry with no `context =` line yet gets one written directly under its `line =`, so that a
    citation written before context hashes existed picks one up the first time anybody confirms it
    against a tree, without anybody having to go and edit seventy three entries by hand. Any
    `context =` already in the entry is dropped and reissued in that same place, which keeps the
    field where a reader expects it and makes running this twice give the same file.
    """
    out: list[str] = []
    inside = False
    for row in text.splitlines():
        stripped = row.strip()
        if stripped.startswith("id ="):
            inside = f'"{identifier}"' in stripped
        if not inside:
            out.append(row)
            continue
        if stripped.startswith("context ="):
            continue
        if stripped.startswith("line ="):
            out.append(f"line = {line}")
            if context:
                out.append(f'context = "{context}"')
            continue
        if stripped.startswith("confirmed ="):
            out.append("confirmed = true")
            continue
        out.append(row)
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="refcheck", description="Check every reference.")
    ap.add_argument("--root", default=".", help="Repository root")
    ap.add_argument("--tree", help="A kernel tree to resolve citations against")
    ap.add_argument("--confirm", action="store_true", help="With --tree, write the lines back")
    ap.add_argument("--list-planned", action="store_true", help="Paths that do not exist yet")
    args = ap.parse_args(argv)

    root = Path(args.root)

    if args.list_planned:
        for target, reason in planned_paths(root).items():
            print(f"{target}\n    {reason}")
        return 0

    findings, references = check(root)
    for finding in findings:
        print(finding)

    if args.tree:
        problems, resolved = confirm(root, Path(args.tree), write=args.confirm)
        findings.extend(problems)
        for problem in problems:
            print(problem)
        print(f"refcheck: resolved {resolved} citation(s) against {args.tree}")

    if findings:
        print(f"\n{len(findings)} problem(s)", file=sys.stderr)
        return 1

    waiting = sum(1 for r in references if not r.confirmed)
    # Counted rather than failed. Every citation written before context hashes existed has none,
    # and a rule that turns those into errors on the day it lands gives a wall of red and gets
    # switched off. The number goes down on its own, one `--confirm` run at a time.
    bare = sum(1 for r in references if r.confirmed and not r.context)
    tail = f", {waiting} waiting on a kernel tree" if waiting else ""
    tail += f", {bare} confirmed with no context hash yet" if bare else ""
    print(f"refcheck: paths clean, {len(references)} citation(s){tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
