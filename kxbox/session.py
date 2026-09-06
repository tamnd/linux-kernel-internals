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

from kxbox import bridge, profiles
from kxbox.corpus import Corpus
from kxray.models import Version
from kxray.proc import version

DISABLE = "KXBOX_DISABLE"

# The one file the banner reads, and the recipe a recording answers it with. Every lesson's first
# cell goes through here, so it is a name rather than a string in the middle of a method.
VERSION = "/proc/version"
BANNER_RECIPE = "banner"

# The one thing about Tier 0 that no file in the guest will tell you. The processor count and the
# architecture used to be spelled out here too, and they are read now, from `/proc/version` and
# from the fragments. This is what is left: a number of seconds measured inside an emulator is a
# number about the emulator, and a reader who forgets that draws the wrong conclusion from a
# perfectly good trace.
LIMITS = "timing is emulated, so no performance claim can be made from this machine"


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
    profile: str = profiles.DEFAULT
    why: str = ""
    root: Path | None = None

    def built(self) -> dict:
        """The `pin.toml` row for the kernel behind this profile, empty if there is no checkout.

        The boot profile is a name a lesson asks for and the build profile is a thing somebody
        compiled, and this is how a lesson gets from one to the other without knowing which is
        which.
        """
        return profiles.built(self.profile, self.root)

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
        """Load a module, or hand back the recording of it having been loaded.

        This used to branch on `self.live` and turn a recorded load into a shell line named
        `insmod abba.ko`, a recipe naming convention that was invented here and written down
        nowhere. Both backends have an `insmod` now, so this is a delegation like the other four
        and the difference between them lives in the backend that has it.
        """
        return self.backend.insmod(path)

    def trace(
        self,
        recipe: str,
        do=None,
        *,
        functions: tuple[str, ...] | list[str] = (),
        owns_window: bool = False,
        max_depth: int = 0,
    ):
        """Run something with the function graph tracer on, and hand back a `kxray.models.Tape`.

        On a recording the callable is not run, because there is nothing to run it on. The name
        is what both sides agree about.

        `owns_window` says the thing being run opens and closes the tracer window itself, which
        every compiled program in the rootfs does. It means nothing to a recording and everything
        to a live kernel.

        `max_depth` limits how far under the named functions the tracer follows, and 0 means no
        limit, which is what every committed capture used. It is worth reaching for when the thing
        being traced does not own its window, because a busy window fills the ring buffer faster
        than a serial line drains it and that failure looks like the guest hanging rather than like
        too much output. The live backend has had this knob since it was written and there was no
        way to reach it from here, which is the sort of gap a signature test finds and a person
        does not.
        """
        return self.backend.tape(
            recipe, do, tuple(functions), owns_window=owns_window, max_depth=max_depth
        )

    def running(self) -> Version | None:
        """What the kernel says about itself, or None when nothing can be read.

        `/proc/version` is one line and it carries two things the banner needs: the release, and
        the words the build shouted after the build number, which is where the preemption model is
        written. It is read rather than taken from `pin.toml` on purpose. The pin is what somebody
        asked to be built, and this project has already had one case of a build quietly not being
        that, which is the whole of the KASAN story in `kernel/README.md`.

        It never raises. This is called from the banner, the banner is the first cell of every
        lesson, and a session that cannot say what it is running is still a session worth having.
        A profile with no recording of this file is the ordinary case rather than a broken one.
        """
        try:
            text = self.read(VERSION, recipe=BANNER_RECIPE)
        except Exception:  # noqa: BLE001 - any failure here means one fewer line, not a stop
            return None
        found = version.parse(text, VERSION, source=f"{self.backend.name}:{BANNER_RECIPE}")
        return found if found.release else None

    def banner(self) -> str:
        """What is behind this session, printed before a reader believes anything it says.

        This is the first cell of every lesson. Somebody reading a trace needs to know whether it
        came off a kernel or out of a file before they read a single line of it.

        Every line says where it came from, and that is the part worth keeping. Two of these facts
        are read off the kernel and two are copied out of a config file, and a banner that printed
        all four in the same voice would let a reader believe the config file had been checked
        against something. It has not. `kernel/RESULTS.md` has the case where that mattered.
        """
        lines = [
            f"kxbox: {self.backend.name} backend, {self.profile} profile",
            f"       {self.backend.describe()}",
        ]
        # The release and the preemption model, in the kernel's own words, or a line saying that
        # nothing could be read. Never a line quietly filled in from the pin.
        now = self.running()
        said = "the kernel says" if self.live else "the recorded kernel said"
        if now is None:
            lines.append("       nothing read off a kernel, so no release and no preemption model")
        else:
            model = now.preemption or "no preemption model in its banner, so PREEMPT_NONE"
            lines.append(f"       {said}: Linux {now.release} {now.build}, {model}")
            lines.append(
                "       and SMP, so more than one processor"
                if now.smp
                else "       and no SMP, so one processor and no true concurrency"
            )
            wanted = profiles.pinned_version(self.profile, self.root)
            if wanted and wanted != now.release:
                lines.append(f"       which is NOT the {wanted} the pin asks for, so nothing here")
                lines.append("       backs a claim about the pinned kernel")
        # Architecture is not in `/proc/version` and there is nowhere else in the guest that says
        # it plainly, so this one comes off the fragments and says so.
        lines.append(
            f"       built for {profiles.arch(self.profile, self.root)}, per its fragments"
        )
        # What the profile turns on, and what it takes for it. A reader timing something on the
        # lockdep kernel and reporting the number is the mistake this line is here to stop.
        one = profiles.get(self.profile)
        lines.append(f"       {one.name} gives you {one.gives}")
        lines.append(f"       and costs {one.costs}")
        if self.live:
            lines.append(f"       {LIMITS}")
        else:
            lines.append(f"       not a running kernel: {self.why}")
            lines.append(
                "       nothing here is evidence"
                if not self.evidence
                else "       these are real captures, replayed"
            )
        return "\n".join(lines)


def boot(profile: str = profiles.DEFAULT, *, root: Path | None = None) -> Box:
    """Get a session, live if there is one and a recording if there is not.

    The fallback is never silent. It is picked when the reader asked for it, or when there is no
    emulator in the page, and either way the banner says which happened and why.

    A profile name nothing builds raises here rather than being carried. This used to be a free
    string, so `boot("lockdpe")` came up saying it had booted a lockdep kernel while running the
    teaching one, and a lesson about lock ordering would then find no lock ordering problems for
    the least interesting reason there is.
    """
    profiles.get(profile)
    root = root or repo_root()
    if disabled():
        return Box(Corpus(root, profile), profile, f"{DISABLE} is set", root)

    live = bridge.V86.find(profile)
    if live is not None:
        return Box(live, profile, "", root)
    return Box(Corpus(root, profile), profile, bridge.explain(), root)
