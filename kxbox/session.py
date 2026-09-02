"""One Tier 0 session, whichever machine is actually behind it.

    import kxbox

    box = kxbox.boot(profile="teaching")
    print(box.banner())

    tape = box.trace("write-1byte", lambda: box.sh("dd if=/dev/zero of=/tmp/one bs=1 count=1"))
    tape.tree()

The same three lines run against a kernel in the page and against a recording, and they hand back
the same objects either way. That is the whole point of this file. A lesson with two code paths
has one path that is tested and one that is not, and the untested one is the one most readers get,
because most readers do not have an emulator running.

Every traced action has a name. `write-1byte` is not decoration: it is the thing the recording is
filed under, and it is what lets the fallback answer the same question. The callable beside it is
what the live backend runs. A backend that cannot run it ignores it, which is the one asymmetry in
the design and it is in one place rather than sprinkled through the lessons.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from kxbox import bridge
from kxbox.corpus import Corpus

DISABLE = "KXBOX_DISABLE"

# What Tier 0 is, stated in every banner, because a reader who forgets it draws the wrong
# conclusion from a perfectly good trace.
LIMITS = "uniprocessor, 32 bit x86, emulated timing"


@dataclass(frozen=True)
class Command:
    """What a shell line did. The same shape from either backend."""

    line: str
    status: int
    stdout: str = ""
    stderr: str = ""
    backend: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 0

    def __str__(self) -> str:
        return self.stdout


def repo_root(start: Path | None = None) -> Path:
    """The checkout this is running inside, found by looking for the corpus."""
    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents]:
        if (parent / "corpora").is_dir():
            return parent
    return Path.cwd()


def disabled() -> bool:
    """Whether the reader has asked for the fallback on purpose."""
    return os.environ.get(DISABLE, "") not in ("", "0", "false")


@dataclass
class Box:
    """A booted Tier 0 session, or the recording of one."""

    backend: object
    profile: str = "teaching"
    why: str = ""

    @property
    def live(self) -> bool:
        return bool(getattr(self.backend, "live", False))

    @property
    def evidence(self) -> bool:
        """Whether anything this session hands back is allowed to back a claim."""
        return bool(getattr(self.backend, "evidence", False))

    def sh(self, line: str, *, recipe: str = "") -> Command:
        return self.backend.sh(line, recipe=recipe)

    def read(self, path: str, *, recipe: str = "") -> str:
        return self.backend.read(path, recipe=recipe)

    def insmod(self, path: str) -> Command:
        if not self.live:
            return self.sh(f"insmod {path}", recipe=f"insmod {Path(path).name}")
        return self.backend.insmod(path)

    def trace(
        self,
        recipe: str,
        do=None,
        *,
        functions: tuple[str, ...] | list[str] = (),
        owns_window: bool = False,
    ):
        """Run something with the function graph tracer on, and hand back a `kxray.models.Tape`.

        On a recording the callable is not run, because there is nothing to run it on. The name
        is what both sides agree about.

        `owns_window` says the thing being run opens and closes the tracer window itself, which
        every compiled program in the rootfs does. It means nothing to a recording and everything
        to a live kernel.
        """
        return self.backend.tape(recipe, do, tuple(functions), owns_window=owns_window)

    def banner(self) -> str:
        """What is behind this session, printed before a reader believes anything it says.

        This is the first cell of every lesson. Somebody reading a trace needs to know whether it
        came off a kernel or out of a file before they read a single line of it.
        """
        lines = [
            f"kxbox: {self.backend.name} backend, {self.profile} profile",
            f"       {self.backend.describe()}",
        ]
        if self.live:
            lines.append(f"       {LIMITS}")
            lines.append("       no performance claim can be made from this machine")
        else:
            lines.append(f"       not a running kernel: {self.why}")
            lines.append(
                "       nothing here is evidence"
                if not self.evidence
                else "       these are real captures, replayed"
            )
        return "\n".join(lines)


def boot(profile: str = "teaching", *, root: Path | None = None) -> Box:
    """Get a session, live if there is one and a recording if there is not.

    The fallback is never silent. It is picked when the reader asked for it, or when there is no
    emulator in the page, and either way the banner says which happened and why.
    """
    root = root or repo_root()
    if disabled():
        return Box(Corpus(root, profile), profile, f"{DISABLE} is set")

    live = bridge.V86.find(profile)
    if live is not None:
        return Box(live, profile, "")
    return Box(Corpus(root, profile), profile, bridge.explain())
