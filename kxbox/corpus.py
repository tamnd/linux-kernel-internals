"""The backend that replays a recording instead of running a kernel.

This is what a lesson cell falls back to when there is no emulator: in CI, on a machine with no
browser, and whenever `KXBOX_DISABLE=1` is set. It reads `corpora/tier0/recipes.toml`, which is
the list of things a Tier 0 session knows how to do, and hands back a recording of each one.

The rule the whole design turns on is that this returns the same types as the live backend. Same
`Command`, same `kxray.models.Tape`. A lesson that took a different code path when the emulator
was missing would be a lesson whose fallback nobody ever really tested, and the fallback is the
path most readers are on.

What it does not do is pretend. A recording says where it came from, and the handwritten ones say
they are not evidence, so a claim cannot rest on one.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CORPORA = "corpora"
RECIPES = Path("tier0") / "recipes.toml"


class NotRecorded(LookupError):
    """Asked for something no recording covers, and said what would have to be recorded."""


@dataclass(frozen=True)
class Recipe:
    """One thing a Tier 0 session can do, and the recording of it.

    A recipe has a name because a replayable action has to be nameable. The live backend runs a
    callable and this one cannot, so the name is the part both backends agree on.
    """

    name: str
    profile: str
    describes: str
    command: str
    # The module this recipe loads, if it loads one. `box.insmod("/lib/modules/abba.ko")` finds a
    # recipe by the file name at the end of that path, because the path a lesson writes and the
    # path the capture was taken with are the same string on a live guest and need not be here.
    module: str = ""
    functions: tuple[str, ...] = ()
    trace: str = ""
    stdout: str = ""
    status: int = 0
    files: dict[str, str] = field(default_factory=dict)
    # Whether the command turns the tracer on and off itself, from inside, around the one system
    # call it exists to show. The programs in the rootfs all do, and it is what keeps a first
    # trace down to three frames. The live backend has to know, because if it opened the window
    # as well then everything the shell did on the way to starting the program would be in the
    # capture too. The recording backend does not care, which is exactly why nobody noticed this
    # was missing until the two were run against each other.
    owns_window: bool = False
    # Whether running it a second time in the same boot gives the same trace as the first time.
    # Most do not, and the reason is the interesting part rather than an inconvenience: a first
    # write to a file has to find a page for the data and set the file up, and a second write to
    # the same file finds both done already. So the recording of a file recipe is a recording of
    # the first run of a boot and only matches the first run of a boot. A recipe that maps fresh
    # memory every time has nothing to reuse and so gives the same answer forever.
    repeatable: bool = False

    @classmethod
    def from_toml(cls, raw: dict[str, object]) -> Recipe:
        return cls(
            name=str(raw.get("name", "")),
            profile=str(raw.get("profile", "teaching")),
            describes=str(raw.get("describes", "")),
            command=str(raw.get("command", "")),
            module=str(raw.get("module", "")),
            functions=tuple(str(one) for one in raw.get("functions", []) or []),
            trace=str(raw.get("trace", "")),
            stdout=str(raw.get("stdout", "")),
            status=int(raw.get("status", 0) or 0),
            files={str(k): str(v) for k, v in (raw.get("files", {}) or {}).items()},
            owns_window=bool(raw.get("owns_window", False)),
            repeatable=bool(raw.get("repeatable", False)),
        )


def load_recipes(root: Path) -> list[Recipe]:
    """Read the recipe list, or hand back nothing when there is not one yet."""
    path = root / CORPORA / RECIPES
    if not path.exists():
        return []
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return [Recipe.from_toml(one) for one in raw.get("recipes", [])]


def captures(one: Recipe) -> list[str]:
    """Every committed file this recipe points at, trace and snapshots together.

    A recipe's evidence is not only its tape. Both lockdep recipes have no trace at all and two
    real `/proc` readings between them, and anything that asked about the trace alone would call
    them handwritten.
    """
    return ([one.trace] if one.trace else []) + sorted(one.files.values())


def evidence_of(root: Path, relative: str) -> bool:
    """Whether the metadata beside a corpus file says it counts as evidence."""
    path = (root / CORPORA / relative).with_suffix(".meta.toml")
    if not path.exists():
        return False
    return bool(tomllib.loads(path.read_text(encoding="utf-8")).get("evidence", False))


class Corpus:
    """Replays recorded Tier 0 sessions. Same interface as the live backend."""

    name = "corpus"
    live = False

    def __init__(self, root: Path, profile: str = "teaching") -> None:
        self.root = root
        self.profile = profile
        self.recipes = {one.name: one for one in load_recipes(root) if one.profile == profile}

    @property
    def evidence(self) -> bool:
        """True only when every recording this backend could hand out is real.

        Every file a recipe points at counts, not only its trace. That used to look at traces
        alone, so a recipe whose evidence is a `/proc` snapshot rather than a tape came out
        marked handwritten no matter what its metadata said, and both of the lockdep recipes are
        that shape.
        """
        paths = [path for one in self.recipes.values() for path in captures(one)]
        return bool(paths) and all(evidence_of(self.root, path) for path in paths)

    def describe(self) -> str:
        if not self.recipes:
            return "no recordings for this profile yet"
        return f"{len(self.recipes)} recording(s), " + ("real" if self.evidence else "handwritten")

    def recipe(self, name: str) -> Recipe:
        found = self.recipes.get(name)
        if found is not None:
            return found
        known = ", ".join(sorted(self.recipes)) or "nothing"
        raise NotRecorded(
            f"no recording of `{name}` for the {self.profile} profile, and this machine has no "
            f"emulator to make one. Recorded so far: {known}. Adding it means capturing it on a "
            f"Tier 0 session and listing it in corpora/tier0/recipes.toml."
        )

    def repeatable(self) -> list[Recipe]:
        """The recipes that give the same trace however many times they have already run.

        Worth being able to ask for. Anything that wants a live tape on a guest that has already
        been used for something else has to pick from this list, because every other recording is
        a recording of the first run of a boot.
        """
        return [one for one in self.recipes.values() if one.repeatable]

    def sh(self, line: str, *, recipe: str = ""):
        from kxbox.session import Command

        one = self.recipe(recipe or line)
        return Command(one.command, one.status, one.stdout, "", backend=self.name)

    def insmod(self, path: str):
        """The recorded reply to loading a module.

        Named by the module rather than by the path it was loaded from. On a live guest the two are
        the same string, so a lesson writes the path either way, and here the path is a detail of
        where the rootfs build happened to put the file.
        """
        from kxbox.session import Command

        wanted = Path(path).name
        for one in self.recipes.values():
            if one.module == wanted:
                return Command(one.command, one.status, one.stdout, "", backend=self.name)

        loads = ", ".join(sorted(one.module for one in self.recipes.values() if one.module))
        raise NotRecorded(
            f"no recording of loading `{wanted}` for the {self.profile} profile. Recorded so far: "
            f"{loads or 'nothing'}. Adding it means loading the module on a Tier 0 session and "
            "listing the recipe in corpora/tier0/recipes.toml with a `module` field."
        )

    def read(self, path: str, *, recipe: str = "") -> str:
        if recipe:
            one = self.recipe(recipe)
            if path not in one.files:
                raise NotRecorded(
                    f"the `{one.name}` recipe has no snapshot of `{path}`. It has "
                    f"{', '.join(sorted(one.files)) or 'no files'} recorded against it."
                )
            return (self.root / CORPORA / one.files[path]).read_text(encoding="utf-8")

        # No recipe named, so the path has to pick one on its own, and it can only do that if
        # exactly one recipe recorded it. This used to take the first match in file order. Two
        # recipes reading `/proc/lockdep_stats` either side of an insmod is the ordinary case
        # rather than a strange one, and a lesson asking for it without saying which would have
        # been handed the before or the after depending on nothing it could see.
        found = [one for one in self.recipes.values() if path in one.files]
        if len(found) == 1:
            return (self.root / CORPORA / found[0].files[path]).read_text(encoding="utf-8")
        if len(found) > 1:
            names = ", ".join(sorted(one.name for one in found))
            raise NotRecorded(
                f"`{path}` is recorded against more than one recipe ({names}), so this has to say "
                "which: box.read(path, recipe=...). They are different readings of the same file "
                "and picking one for you would pick the wrong one about half the time."
            )
        raise NotRecorded(
            f"no recorded snapshot of `{path}`. A file read has to be recorded like anything "
            "else, in the `files` table of a recipe in corpora/tier0/recipes.toml."
        )

    def tape(
        self,
        recipe: str,
        do=None,
        functions: tuple[str, ...] = (),
        *,
        owns_window: bool = False,
        max_depth: int = 0,
    ):
        """Hand back the recording. The callable, the filter and the depth belong to the live one.

        They are still in the signature so that the two backends are called the same way, which
        is the only reason a lesson cell can be written once and run either side. A test compares
        the two signatures, because an argument one backend has and the other does not is a lesson
        that works in a browser and raises TypeError everywhere else.
        """
        from kxray import trace

        one = self.recipe(recipe)
        if not one.trace:
            raise NotRecorded(f"the `{one.name}` recipe has no trace recorded against it")
        return trace.parse_file(self.root / CORPORA / one.trace)
