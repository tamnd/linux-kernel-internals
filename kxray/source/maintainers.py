"""MAINTAINERS, which answers who to send a patch to and is a glob engine in disguise.

    from kxray.source import maintainers, tree

    book = maintainers.load(tree.find())
    for hit in book.lookup("mm/memory.c"):
        print(hit.section.name, hit.tag, hit.pattern)

The file is a header block describing the format, then a few thousand sections. A section is a name
on its own line and then tagged lines under it: `M:` for a maintainer, `L:` for a list, `S:` for
status, `F:` for the files it covers, `X:` for files it does not, `N:` for a regex over paths and
`K:` for a regex over content. Blank line, next section.

Four things in here are worth knowing before leaning on any answer.

A path has more than one maintainer and that is the normal case, not an edge case. On 7.2.2
`mm/memory.c` matches MEMORY MANAGEMENT, MEMORY MANAGEMENT - CORE and THE REST. `lookup` returns
all of them in file order and refuses to pick, because picking is what `get_maintainer.pl` does
with more information than there is here.

THE REST is the last section in the file and it carries `F: *` and `F: */`, so it matches every
path in the tree. Any lookup that takes the first hit and stops gets Linus for every file in
Linux, which is a sentence that has been in a lot of first drafts of a lot of tools.

The globs are not fnmatch. The header block says `F: drivers/net/*` covers the files in that
directory and not the ones below it, and `F: fs/**/*foo*.c` covers subdirectories. So a single star
stops at a slash and a double star does not, which is git's rule rather than Python's. That is also
why THE REST needs two lines: `*` alone matches `MAINTAINERS` and `Makefile` and nothing deeper.

The difference is not academic. FILESYSTEMS (VFS and infrastructure) carries `F: fs/*`.
`fnmatch.fnmatch("fs/proc/base.c", "fs/*")` is True, and the answer the file gives is False, because
`fs/proc/` belongs to PROC FILESYSTEM and the VFS section said so by using one star instead of a
trailing slash. A tool built on `fnmatch` sends every patch under `fs/` to the VFS maintainers.

Exclusions are tested first. The header says so in as many words, and ABI/API is the section that
shows it: it covers `include/linux/syscalls.h` and excludes all of `include/uapi/`.

What this is not is `scripts/get_maintainer.pl`. That script reads git history, weighs how recently
somebody touched a file, and decides who actually gets the mail. This reads the file and reports
what is in it. When the two disagree the script is right, and the value of this one is that it runs
in a notebook with no git and no kernel tree beyond the corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from kxray.models import READ, SKIPPED, UNPARSED, Lines, grid
from kxray.source.tree import File, Tree

MAINTAINERS = "MAINTAINERS"

# Where the section list starts. Everything above this is the block that documents the format, and
# it has lines in it that look exactly like tagged lines because it is describing tagged lines.
HEADING = "Maintainers List"

# One tagged line: a single capital, a colon, then the value. The separator in the file is a tab,
# and there are entries that use spaces, so this does not insist.
TAG_RE = re.compile(r"^([A-Z]):\s*(.*)$")

# `FullName <address@domain>`, with the name sometimes quoted because it has a comma in it.
PERSON_RE = re.compile(r'^\s*"?(?P<name>[^"<]*?)"?\s*<(?P<address>[^>]+)>\s*$')

# The statuses the header block documents. THE REST does not use one of these, which is the point
# of keeping the list separate from the parser rather than validating against it.
STATUSES = ("Supported", "Maintained", "Odd Fixes", "Orphan", "Obsolete")

# Statuses that mean somebody is looking at it. Everything else, including the joke on the last
# section of the file, means the answer to "who fixes this" is nobody in particular.
LOOKED_AFTER = ("Supported", "Maintained")


@dataclass(frozen=True)
class Person:
    name: str
    address: str

    def __str__(self) -> str:
        return f"{self.name} <{self.address}>" if self.name else self.address


def person(text: str) -> Person:
    """A name and address line, or the whole line as an address when it is not that shape."""
    found = PERSON_RE.match(text)
    if found is None:
        return Person(name="", address=text.strip())
    return Person(name=found["name"].strip(), address=found["address"].strip())


@dataclass(frozen=True)
class Section:
    """One entry in the file: a name and its tagged lines, kept in the order they were written."""

    name: str
    tags: tuple[tuple[str, str], ...] = ()
    line: int = 0

    def values(self, tag: str) -> tuple[str, ...]:
        return tuple(value for key, value in self.tags if key == tag)

    @property
    def maintainers(self) -> tuple[Person, ...]:
        return tuple(person(value) for value in self.values("M"))

    @property
    def reviewers(self) -> tuple[Person, ...]:
        return tuple(person(value) for value in self.values("R"))

    @property
    def lists(self) -> tuple[str, ...]:
        return self.values("L")

    @property
    def status(self) -> str:
        found = self.values("S")
        return found[0] if found else ""

    @property
    def looked_after(self) -> bool:
        return self.status in LOOKED_AFTER

    @property
    def files(self) -> tuple[str, ...]:
        return self.values("F")

    @property
    def excluded(self) -> tuple[str, ...]:
        return self.values("X")

    @property
    def path_patterns(self) -> tuple[str, ...]:
        return self.values("N")

    @property
    def content_patterns(self) -> tuple[str, ...]:
        return self.values("K")

    @property
    def contacts(self) -> tuple[str, ...]:
        """Everywhere a patch could go, maintainers first and then the lists.

        A section with no `M:` line is not a bug in the file. PROC FILESYSTEM has none: it has a
        status of Maintained and two mailing lists and nobody named, and the honest answer to who
        to mail is those lists.
        """
        return tuple(str(who) for who in self.maintainers) + self.lists


@dataclass(frozen=True)
class Match:
    """One section matching one path, and which line in it did the matching."""

    section: Section
    tag: str
    pattern: str

    def __str__(self) -> str:
        return f"{self.section.name}  ({self.tag}: {self.pattern})"


@dataclass
class Maintainers:
    """The whole file, or as much of it as was in front of the parser."""

    source: str = "<text>"
    partial: bool = False
    sections: tuple[Section, ...] = ()
    unparsed: tuple[tuple[int, str], ...] = field(default_factory=tuple)
    lines: Lines = field(default_factory=Lines)

    def get(self, name: str) -> Section | None:
        return next((s for s in self.sections if s.name == name), None)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.sections)

    def lookup(self, path: str) -> tuple[Match, ...]:
        """Every section that covers this path, in the order the file lists them.

        `F:` first and then `N:`, and both kinds come back tagged, because the header block says
        `get_maintainer.pl` treats them differently and a caller that cares can see which it got.
        """
        found: list[Match] = []
        for section in self.sections:
            if any(covers(pattern, path) for pattern in section.excluded):
                continue
            hit = next((p for p in section.files if covers(p, path)), None)
            if hit is not None:
                found.append(Match(section=section, tag="F", pattern=hit))
                continue
            regex = next((p for p in section.path_patterns if _search(p, path)), None)
            if regex is not None:
                found.append(Match(section=section, tag="N", pattern=regex))
        return tuple(found)

    def specific(self, path: str) -> tuple[Match, ...]:
        """The same lookup with the catch-all taken out.

        THE REST matches everything, so it is in every answer and tells nobody anything. This is
        the list to print when the question is which subsystem a file belongs to.
        """
        return tuple(hit for hit in self.lookup(path) if hit.section.name != CATCH_ALL)

    def contacts(self, path: str) -> tuple[str, ...]:
        """Everyone the sections covering this path name, deduplicated, in file order."""
        seen: list[str] = []
        for hit in self.lookup(path):
            for who in hit.section.contacts:
                if who not in seen:
                    seen.append(who)
        return tuple(seen)

    def content(self, text: str) -> tuple[Match, ...]:
        """Sections whose `K:` regex appears in a body of text.

        This is the tag that reads a patch rather than a path, so a patch touching a subsystem's
        functions anywhere in the tree can reach that subsystem's list even though the file it
        touched belongs to somebody else.

        The flag matters. `scripts/get_maintainer.pl` applies these with perl's `/x`, which ignores
        whitespace in the pattern, and this does the same so the two agree. Worth knowing because
        the patterns in the file are hand written and not all of them do what they look like: the
        one on AUDIT SUBSYSTEM is `\\baudit_[a-z_0-9]\\+\\b`, where `\\+` means one or more in the
        basic regular expressions that `grep` speaks and a literal plus sign in the perl that
        actually runs it. So it does not match `audit_log_start`, here or in the real script.
        """
        found = []
        for section in self.sections:
            hit = next((p for p in section.content_patterns if _search(p, text, re.X)), None)
            if hit is not None:
                found.append(Match(section=section, tag="K", pattern=hit))
        return tuple(found)

    def table(self, path: str) -> str:
        rows = [("section", "matched", "status", "contacts")]
        for hit in self.lookup(path):
            rows.append(
                (
                    hit.section.name,
                    f"{hit.tag}: {hit.pattern}",
                    hit.section.status or "none given",
                    ", ".join(hit.section.contacts) or "nobody named",
                )
            )
        return grid(rows)


# The section that covers the whole tree, by name, so that `specific` can leave it out without
# hunting for a section whose patterns happen to match everything.
CATCH_ALL = "THE REST"


def _search(pattern: str, text: str, flags: int = 0) -> bool:
    """A regex out of the file, applied without letting a bad one take the process down.

    These are perl regexes written by hand in a text file. A pattern Python cannot compile is
    reported as not matching rather than raised, because a lookup for one path should not fail on a
    pattern belonging to a subsystem nobody asked about.
    """
    try:
        return re.search(pattern, text, flags) is not None
    except re.error:
        return False


def _glob(pattern: str) -> re.Pattern[str]:
    """One `F:` or `X:` pattern as a regex, with the star rule the header block describes.

    A single star stops at a slash and a double star crosses them. `fnmatch` does not make that
    distinction and lets one star cross, which turns `drivers/net/*` into every file under
    `drivers/net` and is the reason this function exists instead of a one line call.
    """
    out = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if pattern.startswith("**", index):
                out.append(".*")
                index += 2
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        index += 1
    return re.compile("^" + "".join(out) + "$")


def covers(pattern: str, path: str) -> bool:
    """Whether one pattern covers one path.

    A trailing slash means the directory and everything under it, which the file uses far more
    than it uses stars.
    """
    if not pattern:
        return False
    if pattern.endswith("/"):
        return _glob(pattern + "**").match(path) is not None
    return _glob(pattern).match(path) is not None


def parse(text: str, source: str = "<text>", partial: bool = False) -> Maintainers:
    """Read the file from the section list down.

    Everything above the `Maintainers List` heading is the block that documents the format, and it
    is skipped rather than parsed, because it contains lines like `F: drivers/net/` as examples and
    a parser that read those would invent a section covering half the network drivers.
    """
    body = text.splitlines()
    start = next((n for n, line in enumerate(body) if line.startswith(HEADING)), 0)

    sections: list[Section] = []
    unparsed: list[tuple[int, str]] = []
    counted = Lines()
    name = ""
    tags: list[tuple[str, str]] = []
    at = 0

    # Everything above the heading. Counted as skipped rather than ignored, so that the buckets in
    # `corpora/BASELINE.toml` still add up to the length of the file.
    for _ in range(start):
        counted.count(SKIPPED)

    def close() -> None:
        """End the block being read, and say what its name line turned out to be worth.

        The name line is counted here rather than where it was seen, because whether it became a
        section is not known until the block ends. `Maintainers List` and the underline under it
        are two bare lines that never get a tag, and counting those as read would mean the baseline
        recorded two sections this parser does not return.
        """
        nonlocal name, tags, at
        if name and tags:
            sections.append(Section(name=name, tags=tuple(tags), line=at))
            counted.count(READ)
        elif name:
            counted.count(SKIPPED)
        name, tags, at = "", [], 0

    for number, line in enumerate(body[start:], start=start + 1):
        if not line.strip():
            counted.count(SKIPPED)
            close()
            continue
        found = TAG_RE.match(line)
        if found is not None and name:
            tags.append((found.group(1), found.group(2).strip()))
            counted.count(READ)
            continue
        if name and tags:
            unparsed.append((number, line))
            counted.count(UNPARSED)
            continue
        if name:
            # A second bare line before any tag. The heading and its underline are the only place
            # this happens in the real file, and the second one wins.
            counted.count(SKIPPED)
        name, at = line.strip(), number
        tags = []
    close()

    return Maintainers(
        source=source,
        partial=partial,
        sections=tuple(sections),
        unparsed=tuple(unparsed),
        lines=counted,
    )


def parse_file(file: File) -> Maintainers:
    return parse(file.text, source=f"{file.root}/{file.path}", partial=file.partial)


def load(found: Tree) -> Maintainers:
    """Read MAINTAINERS out of a tree, carrying the tree's partiality into the result."""
    return parse_file(found.read(MAINTAINERS))


def report(book: Maintainers, path: str) -> str:
    lines = [
        f"{path} in {book.source}",
        f"sections: {len(book.sections)}{' (an excerpt)' if book.partial else ''}",
        "",
        book.table(path),
    ]
    text = "\n".join(lines)
    print(text)
    return text
