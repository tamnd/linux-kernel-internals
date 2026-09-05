"""Anchors into the kernel source, and a hash of what was around them.

    from kxray.source import citations

    hit = citations.resolve(text, "ssize_t vfs_write(struct file *file")
    print(hit.line, hit.context)

Every citation in this repository names a file and a piece of text to find in it, never a line
number, because a line number is wrong the moment somebody adds a line above it. `tools/refcheck`
resolves those anchors against a real tree and writes the line it found, and the next run finds the
same text wherever it has moved to. That much already worked before this module existed.

What did not work is the case where the anchor still matches and the answer has changed anyway. An
anchor is usually a function signature. The signature is the most stable line in a function and the
body underneath it is the part people edit, so a citation supporting a sentence about what a
function does can go stale without the anchor moving at all. Nothing notices. The checker is green
and the lesson is wrong.

So a confirmed citation also records a hash of the lines around the anchor. When the anchor
resolves and the hash still matches, nothing near it has changed. When the anchor resolves and the
hash does not, the citation is still valid as a pointer and the text it points at has been edited,
which is the moment to go and read it rather than six months later.

The hash is over normalised lines: leading and trailing space removed, runs of whitespace collapsed
to one. That is a deliberate choice about what counts as a change. Reindenting a block, or the tab
to space churn that happens when a file gets reformatted, does not fire. Renaming a variable,
adding a branch, or changing an argument does. The alternative, hashing the bytes, gives a checker
that cries every release and gets ignored, which is worse than not having one.

`RADIUS` is three lines either side, so seven lines in all. Wide enough to cover the signature and
the top of a body, narrow enough that an unrelated edit forty lines away does not drag it in.

Twelve hex characters of sha256. This detects change, it does not defend against anybody. Nobody is
trying to forge a kernel source file that collides with a hash in a TOML file in this repository,
and a full digest in every citation would be sixty four characters of noise in a file people read.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# Lines either side of the anchor that go into the hash.
RADIUS = 3

# Characters of the digest kept. See the module docstring.
WIDTH = 12

SPACE_RE = re.compile(r"\s+")


def normalise(line: str) -> str:
    """One line reduced to what a change to it would have to survive."""
    return SPACE_RE.sub(" ", line).strip()


def window(lines: list[str], index: int, radius: int = RADIUS) -> list[str]:
    """The lines around a hit, clipped at both ends of the file.

    Clipped rather than padded. A citation three lines from the top of a file gets a shorter window
    and a hash over it, which is correct, where padding would make two different short windows at
    two different ends of a file hash the same.
    """
    start = max(0, index - radius)
    return lines[start : index + radius + 1]


def context_hash(lines: list[str], index: int, radius: int = RADIUS) -> str:
    """The digest of the normalised window around one line."""
    body = "\n".join(normalise(line) for line in window(lines, index, radius))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:WIDTH]


def hash_text(text: str, anchor: str, radius: int = RADIUS) -> str:
    """The context hash for the first place an anchor appears, or empty when it does not."""
    lines = text.splitlines()
    index = next((n for n, line in enumerate(lines) if anchor in line), None)
    return "" if index is None else context_hash(lines, index, radius)


@dataclass(frozen=True)
class Hit:
    """What resolving one anchor against one file found."""

    anchor: str
    line: int = 0
    context: str = ""
    count: int = 0
    problem: str = ""

    @property
    def found(self) -> bool:
        return self.line > 0

    @property
    def unique(self) -> bool:
        return self.count == 1

    def __str__(self) -> str:
        if not self.found:
            return f"{self.anchor!r}: {self.problem or 'not found'}"
        return f"line {self.line}, context {self.context}"


def resolve(text: str, anchor: str, radius: int = RADIUS) -> Hit:
    """Find an anchor in a file and hash what is around it.

    An anchor that matches more than once still returns the first hit, with the count and a
    sentence saying to pick a longer one. Returning nothing would hide a citation that is nearly
    right, and returning the first quietly is how a citation ends up pointing at a call site rather
    than at the function it thought it named.
    """
    lines = text.splitlines()
    hits = [number for number, line in enumerate(lines) if anchor in line]
    if not hits:
        return Hit(anchor=anchor, problem="not in the file any more")
    problem = ""
    if len(hits) > 1:
        problem = f"appears {len(hits)} times, so pick a longer anchor"
    return Hit(
        anchor=anchor,
        line=hits[0] + 1,
        context=context_hash(lines, hits[0], radius),
        count=len(hits),
        problem=problem,
    )


def compare(recorded: str, found: str) -> str:
    """What to say about two context hashes.

    An empty recorded hash is not a failure. Every citation written before this existed has one,
    and turning those into errors on the day the checker landed would have meant either a wall of
    red or a rule nobody could turn on.
    """
    if not recorded:
        return "no context recorded yet"
    if not found:
        return "nothing to compare against, the anchor did not resolve"
    if recorded == found:
        return "unchanged"
    return f"the lines around it have changed, recorded {recorded} and found {found}"


def changed(recorded: str, found: str) -> bool:
    """True only when both hashes exist and they differ."""
    return bool(recorded) and bool(found) and recorded != found
