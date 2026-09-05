"""A handle on a kernel tree, including the honest absence of one.

    from kxray.source import tree

    found = tree.find()
    print(found.describe())
    print(found.read("MAINTAINERS").partial)

Everything else in `kxray.source` reads files out of a kernel tree, so every one of them needs an
answer to the same question first: is there a tree here, and how much of one. There are three
answers on a machine somebody might be sitting at, and the difference between them changes what a
lookup is worth.

The full tree is what `./kxbox/kernel/tree.sh` unpacks, about 1.6 GB of pristine kernel checked
against the sha256 in `pin.toml`. Anything asked of that gets a real answer.

The partial tree is `corpora/source/pinned/`, which is five files committed to this repository so
that the parsers have something to run against in CI and in a notebook that has downloaded nothing.
It is a kernel tree in shape and almost none of one in content, and a lookup for anything not in it
has to come back as "not here" rather than as "not in the kernel". Those are different sentences
and only one of them is true.

No tree at all is the state of a fresh checkout before anybody runs the script. That is normal, and
the thing to do about it is say so with the command that fixes it, rather than raise something the
reader has to go and decode.

One file in the partial tree is an excerpt, `MAINTAINERS.excerpt`, because the real one is 916 KB
and 29847 lines. The `.excerpt` suffix is the whole mechanism: `read("MAINTAINERS")` finds it,
returns it, and sets `partial` on what it hands back, so the fact that this is a slice travels with
the content instead of living in a comment somebody has to remember.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

# Where a full tree lands, relative to the repository root, and what the committed partial one is
# called. Both are looked for in that order, because a reader who has unpacked the real thing wants
# answers from the real thing.
UNPACKED = Path("kxbox/kernel/build/tree")
PINNED = Path("corpora/source/pinned")
PIN = Path("kxbox/kernel/pin.toml")

# A stand-in for a file too large to commit whole. See the module docstring.
EXCERPT = ".excerpt"

UNPACK = "./kxbox/kernel/tree.sh"


@dataclass(frozen=True)
class File:
    """One file out of a tree, knowing where it came from and whether it is all of itself."""

    path: str
    text: str
    root: str = ""
    partial: bool = False

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    def banner(self) -> str:
        kind = "an excerpt" if self.partial else "whole"
        return f"{self.path} ({kind}, from {self.root or 'nowhere'})"


@dataclass(frozen=True)
class Tree:
    """A directory that holds kernel source, or claims to.

    `complete` is the one field worth reading before anything else. False means this is the
    committed corpus, so a missing file means nobody committed it, and a lookup that comes back
    empty says nothing at all about the kernel.
    """

    root: Path
    version: str = ""
    complete: bool = False

    @property
    def present(self) -> bool:
        return self.root.is_dir()

    def _candidates(self, path: str) -> tuple[Path, Path]:
        target = self.root / path
        return target, target.with_name(target.name + EXCERPT)

    def has(self, path: str) -> bool:
        whole, excerpt = self._candidates(path)
        return whole.is_file() or excerpt.is_file()

    def open(self, path: str) -> File | None:
        """The file, or None when this tree does not have it.

        None rather than an exception, because "not in this tree" is the ordinary state of most
        paths in the partial tree and callers here want to say so in a sentence.
        """
        whole, excerpt = self._candidates(path)
        for candidate, partial in ((whole, False), (excerpt, True)):
            if candidate.is_file():
                return File(
                    path=path,
                    text=candidate.read_text(encoding="utf-8", errors="replace"),
                    root=self.root.as_posix(),
                    partial=partial,
                )
        return None

    def read(self, path: str) -> File:
        """The file, or a FileNotFoundError that says what to do about it."""
        found = self.open(path)
        if found is not None:
            return found
        if not self.present:
            raise FileNotFoundError(f"no kernel tree at {self.root}, run {UNPACK} to unpack one")
        if not self.complete:
            raise FileNotFoundError(
                f"{path} is not in the committed corpus at {self.root}, "
                f"run {UNPACK} for a full tree"
            )
        raise FileNotFoundError(f"{path} is not in {self.root}")

    def missing(self, paths: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(path for path in paths if not self.has(path))

    def files(self) -> tuple[str, ...]:
        """Every path this tree holds, with the excerpt suffix taken back off.

        Usable on the corpus and a bad idea on a full tree, which has ninety thousand files in it.
        """
        found = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            name = path.relative_to(self.root).as_posix()
            found.append(name[: -len(EXCERPT)] if name.endswith(EXCERPT) else name)
        return tuple(found)

    def describe(self) -> str:
        if not self.present:
            return f"no kernel tree at {self.root}, run {UNPACK}"
        kind = "full" if self.complete else "the committed corpus, a handful of files"
        return f"linux {self.version or 'unknown'} at {self.root} ({kind})"


def pinned_version(root: Path | str = ".") -> str:
    """The version out of `pin.toml`, or an empty string when there is no pin file to read."""
    path = Path(root) / PIN
    if not path.is_file():
        return ""
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    kernel = document.get("kernel")
    return str(kernel.get("version", "")) if isinstance(kernel, dict) else ""


def find(root: Path | str = ".") -> Tree:
    """The best tree this checkout has, full one first.

    The full tree is preferred without asking, because a reader who has spent the 1.6 GB wants
    their answers from it, and a partial answer that quietly wins over a complete one is the kind
    of thing nobody notices until a lookup disagrees with the source in front of them.
    """
    base = Path(root)
    version = pinned_version(base)
    if version:
        unpacked = base / UNPACKED / f"linux-{version}"
        if unpacked.is_dir():
            return Tree(root=unpacked, version=version, complete=True)
    return Tree(root=base / PINNED, version=version, complete=False)
