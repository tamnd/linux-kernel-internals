"""The three kernels a lesson is allowed to ask for, and what each one costs.

    from kxbox import profiles

    print(profiles.table())
    print(profiles.get("memcheck").costs)

There are two different things in this repository called a profile and keeping them apart is most
of the reason this file exists.

A **build profile** is a row in `kxbox/kernel/pin.toml`. There are six, they are named `A-full`
through `E-memcheck`, and they exist so that the kill criterion can be settled: A is what the book
wants, B and C each give something up, and if none of them boots in a browser then Tier 0 does not
work and the pedagogy has to change. That is a question for whoever is building kernels.

A **boot profile** is what a lesson writes. There are three, they are named after what they are
for rather than after where they came in the ordering, and a lesson author should never have to
know that the teaching kernel is currently built as `A-full` or that it might be built as
`C-longterm` next month if the first one turns out to be too big for a tab.

So a boot profile names a build profile, and this is the one place the two are joined.

## Why a wrong name has to raise

`boot(profile="lockdpe")` used to work. The string was carried around, printed in the banner, and
nothing ever compared it to anything, so a lesson would come up saying it had booted a lockdep
kernel and then quietly not report a single lock ordering problem, because it was running the
teaching kernel and lockdep was not compiled in. A reader concludes the code they are looking at
has no lock ordering problem in it. That is the worst kind of wrong: a clean result that means
nothing, from a session that said it was doing something else.

## What each one costs, and why that is written down

Nothing here is free. lockdep watches every lock the kernel takes, the memory checkers unmap freed
pages and poison them, and both are slow enough that a reader who boots the wrong one and times
something will get a number that is about the debugging and not about the kernel. The cost is part
of the profile rather than a footnote, and the banner prints it.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

PIN = Path("kxbox/kernel/pin.toml")

# The same file as it sits after `pip install`, which is how most readers of this book get it. The
# Colab badge runs `pip install git+https://...` and there is no checkout on that machine at all, so
# a pin looked up by the path above finds nothing and every question about the kernel behind a
# profile comes back as a shrug. The wheel carries `pin.toml` and the config fragments next to this
# file, so there is a real answer sitting right there and it only needed asking for.
PACKAGED = Path(__file__).resolve().parent / "kernel" / "pin.toml"


def pin_file(root: Path | None = None) -> Path:
    """The `pin.toml` to read, and the directory every fragment path in it hangs off.

    A checkout wins when there is one, because that is the copy somebody might be editing, and the
    packaged copy is the fallback rather than the other way round. The two are the same file in
    every normal case: the wheel is built from the checkout.
    """
    inside = (root / PIN) if root is not None else PIN
    return inside if inside.exists() else PACKAGED


@dataclass(frozen=True)
class Profile:
    """One kernel a lesson can ask for."""

    name: str
    builds: str
    fragment: str
    gives: str
    costs: str
    wanted_by: str

    @property
    def default(self) -> bool:
        return self.name == DEFAULT


DEFAULT = "teaching"

PROFILES = {
    "teaching": Profile(
        name="teaching",
        builds="A-full",
        fragment="config/teaching.config",
        gives="ftrace, kprobes, BTF, every /proc file the book reads, and modules",
        costs="nothing beyond its size, which is what makes it the default",
        wanted_by="every lesson that does not say otherwise",
    ),
    "lockdep": Profile(
        name="lockdep",
        builds="D-lockdep",
        fragment="config/lockdep.config",
        gives="lockdep, lock statistics, and the sleeping in atomic context checks",
        costs="every lock the kernel takes is recorded and checked, so timings mean nothing",
        wanted_by="C09, and anything that has to show a deadlock before it happens",
    ),
    "memcheck": Profile(
        name="memcheck",
        builds="E-memcheck",
        fragment="config/memcheck.config",
        gives="KFENCE, page poisoning, unmapped freed pages, and the slab debugger",
        costs="freed pages are unmapped and rewritten, so allocation timings mean nothing",
        # The milestone asked for a profile called kasan. It cannot be built on the pinned kernel:
        # arch/x86/Kconfig selects HAVE_ARCH_KASAN only if X86_64 and Tier 0 is 32 bit, so KASAN is
        # not a symbol that exists here. The name is `memcheck` rather than `kasan` because calling
        # it kasan would be the same lie in a different file.
        wanted_by="the driver capstone, and any lesson about a use after free",
    ),
}


class Unknown(LookupError):
    """A profile name nothing builds.

    Raised rather than carried, and the message says what the three names are.
    """


def names() -> tuple[str, ...]:
    return tuple(PROFILES)


def get(name: str) -> Profile:
    """One profile by name, or an error saying what the three are.

    This is what stops a typo booting the wrong kernel and saying it booted the right one.
    """
    found = PROFILES.get(name)
    if found is None:
        raise Unknown(f"no profile called {name!r}, there is {', '.join(names())}")
    return found


def for_build(name: str) -> Profile | None:
    """The boot profile that uses a given build, or None when nothing uses it.

    The other direction, and it is needed because the harness and the capture metadata name a
    build, not a boot profile. `KXBOX_PROFILE=D-lockdep` picks which compiled image the headless
    runner boots, and whatever is standing on top of it has to say `lockdep`. Three of the six
    builds have nobody on top of them, which is why this can answer None: `A-gzip`,
    `B-btf-external` and `C-longterm` exist to be measured against `A-full` rather than to be
    booted by a lesson.
    """
    for one in PROFILES.values():
        if one.builds == name:
            return one
    return None


def built(name: str, root: Path | None = None) -> dict:
    """What `pin.toml` says about the build behind this boot profile.

    Empty only when there is no pin anywhere, which now means the package itself is broken. It used
    to be the ordinary answer for anybody without a checkout, and the banner went quiet for exactly
    the readers it was written for.
    """
    one = get(name)
    pin = pin_file(root)
    if not pin.exists():
        return {}
    document = tomllib.loads(pin.read_text(encoding="utf-8"))
    for profile in document.get("profiles", []):
        if profile.get("name") == one.builds:
            return profile
    return {}


# Which architecture a config was built for, in the two symbols that settle it. `CONFIG_X86_32`
# is set by the 32 bit choice and `CONFIG_64BIT` is the choice itself, so a fragment that turns one
# on and leaves the other alone is still readable. These are not like the symbols in the KASAN
# story: an architecture is a choice Kconfig either honours or refuses to configure at all, so what
# the fragment asked for here is what the kernel is.
ARCH_SYMBOLS = {
    "CONFIG_X86_32=y": "32 bit x86 (i386)",
    "CONFIG_64BIT=y": "64 bit x86 (x86_64)",
}
UNKNOWN_ARCH = "an architecture nothing in the fragments names"


def arch(name: str, root: Path | None = None) -> str:
    """The architecture the kernel behind this profile was compiled for.

    Read out of the config fragments the profile is built from, which is where the answer lives.
    There is nothing in `/proc/version` that says it, so unlike the release and the preemption
    model this cannot be asked of the running kernel, and the banner says so rather than printing
    it next to the two facts that were read off a kernel as if all three came from the same place.
    """
    where = built(name, root)
    base = pin_file(root).parent
    for fragment in where.get("fragments", []):
        path = base / fragment
        if not path.exists():
            continue
        lines = {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
        for symbol, said in ARCH_SYMBOLS.items():
            if symbol in lines:
                return said
    return UNKNOWN_ARCH


def pinned_version(name: str, root: Path | None = None) -> str:
    """The kernel release `pin.toml` says this profile is built from, or an empty string.

    A build profile does not name a version, it names a tree, and there are two of them. Five
    profiles say `kernel = "kernel"` and mean 7.2.2, and `C-longterm` says `kernel = "fallback"`
    and means 6.18.48. Following that pointer is the difference between checking a running kernel
    against the version it was meant to be and checking it against whichever version is written
    highest in the file.
    """
    where = built(name, root)
    pin = pin_file(root)
    if not where or not pin.exists():
        return ""
    document = tomllib.loads(pin.read_text(encoding="utf-8"))
    tree = document.get(where.get("kernel", "kernel"), {})
    return str(tree.get("version", ""))


def describe(name: str, root: Path | None = None) -> list[str]:
    """Two or three lines about a profile, for the banner."""
    one = get(name)
    lines = [f"gives you {one.gives}", f"costs {one.costs}"]
    summary = built(name, root).get("summary")
    if summary:
        lines.append(f"built as {one.builds}: {summary}")
    else:
        lines.append(f"built as {one.builds}")
    return lines


def table() -> str:
    """The three, side by side, which is what a lesson author wants to see once."""
    rows = [("profile", "built as", "gives you", "costs")]
    rows += [(one.name, one.builds, one.gives, one.costs) for one in PROFILES.values()]
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    return "\n".join(
        f"{row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  {row[2]:<{widths[2]}}  {row[3]}"
        for row in rows
    )
