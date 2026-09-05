"""What the kernel promises about a file, before anything reads it.

    from kxray.proc import stability

    stability.classify("/proc/meminfo")        undocumented
    stability.classify("/sys/kernel/btf/vmlinux")   testing (Documentation/ABI/testing/...)
    print(stability.table())

Every reader in this package attaches one of these to what it returns. The reason is narrow and
worth stating plainly: this project teaches people to read files that mostly carry no promise at
all, and the difference between a file that is documented and a file that merely happens to work
is not visible from the file itself.

The kernel keeps its own answer in `Documentation/ABI`, with one directory per level, and
`Documentation/ABI/README` defines them. `stable` will be kept working for at least two years and
in practice forever. `testing` may gain features but will not break under you. `obsolete` is on
its way out with a date attached. `removed` is a record of things that are gone.

Then there is what is not in that tree. On Linux 7.2.2 there are 685 files under
`Documentation/ABI` and exactly six of them describe a path in `/proc`: `/proc/i8k`,
`/proc/diskstats`, `/proc/pid/smaps_rollup`, and the three `/proc/*/attr` files. Not
`/proc/meminfo`. Not `/proc/interrupts`. Not `/proc/<pid>/stat`, which is the file every process
monitor ever written reads. Not `/proc/<pid>/maps`. None of the files in this project's corpus.

That is `undocumented`, and it is not the same as unstable. Those files have been the same shape
for many years and breaking them would break userspace, which is the one rule that does not bend.
What is missing is anybody having written down which part of the shape you may lean on. So a
reader may lean on them, and a reader should be told it is leaning on custom rather than on a
promise.

One level is stronger than that, and this project reads two files that fall under it. The last
section of `Documentation/ABI/README` names, as "notable bits of non-ABI, which should not under
any circumstances be considered stable", both Kconfig, naming `/proc/config.gz` outright, and
kernel symbols, saying not to rely on "the presence, absence, location, or type of any kernel
symbol". `/proc/kallsyms` is exactly the second one. `kxray.kallsyms` reads it anyway, because
counting ops tables by name is a fine thing to do to a machine in front of you, and the ledger
now says out loud that the same code has no business inside a tool somebody deploys.

The rules below are patterns rather than exact paths, matched in order, first match wins. Each
carries the file in the kernel tree that makes the claim, so none of this has to be believed.
"""

from __future__ import annotations

from fnmatch import fnmatch

from kxray.models import (
    NOT_ABI,
    OBSOLETE,
    STABLE,
    TESTING,
    UNDOCUMENTED,
    Promise,
    grid,
)

# How many files were in `Documentation/ABI` on the pinned kernel, and how many of them described
# a path in /proc. Checked against the 7.2.2 source tree, and worth checking again after a bump.
ABI_FILES = 685
ABI_PROC_ENTRIES = 6

README = "Documentation/ABI/README"

# Pattern, level, the file in the kernel tree that says so, and why in one sentence. Order
# matters. The specific paths come before the directory wildcards, and the two catch-alls are
# last.
RULES: tuple[tuple[str, str, str, str], ...] = (
    (
        "/proc/kallsyms",
        NOT_ABI,
        README,
        "the README says not to rely on the presence, absence, location or type of any kernel "
        "symbol, and this file is nothing but those",
    ),
    (
        "/proc/config.gz",
        NOT_ABI,
        README,
        "the README names Kconfig as non-ABI and names this file while doing it",
    ),
    (
        "/proc/*/loginuid",
        STABLE,
        "Documentation/ABI/stable/procfs-audit_loginuid",
        "the one file in /proc this project could read that carries a stable promise, kept here "
        "as the counterexample",
    ),
    (
        "/proc/*/smaps_rollup",
        TESTING,
        "Documentation/ABI/testing/procfs-smaps_rollup",
        "one of the six /proc paths the ABI tree describes at all",
    ),
    (
        "/proc/diskstats",
        TESTING,
        "Documentation/ABI/testing/procfs-diskstats",
        "one of the six /proc paths the ABI tree describes at all",
    ),
    (
        "/sys/kernel/btf/*",
        TESTING,
        "Documentation/ABI/testing/sysfs-kernel-btf",
        "documented since 5.5, and the reason a BTF dump is safe to build a lesson on",
    ),
    (
        "/sys/kernel/debug/tracing/*",
        OBSOLETE,
        "Documentation/ABI/obsolete/automount-tracefs-debugfs",
        "the debugfs copy of tracefs, which that entry says should be gone by January 2030",
    ),
    (
        "/sys/kernel/tracing/*",
        UNDOCUMENTED,
        "",
        "tracefs itself has no ABI entry, only the debugfs path it replaced does, so the "
        "interface every tracing lesson here uses is described in Documentation/trace/ftrace.rst "
        "and nowhere that carries a level",
    ),
    (
        "/proc/*",
        UNDOCUMENTED,
        "",
        "no file under Documentation/ABI describes this path, which is true of nearly all of /proc",
    ),
    (
        "/sys/*",
        UNDOCUMENTED,
        "",
        "no file under Documentation/ABI describes this path",
    ),
)


def classify(path: str) -> Promise:
    """What is promised about `path`, with the pattern that decided it.

    An unrecognised path comes back as `undocumented` with no pattern rather than raising. That is
    the honest answer for a path nobody here has looked up, and it is also the safe one, because
    the levels this returns are only ever used to decide how much to lean on something.
    """
    for pattern, kind, entry, note in RULES:
        if fnmatch(path, pattern):
            return Promise(kind=kind, entry=entry, note=note, pattern=pattern)
    return Promise(kind=UNDOCUMENTED, note="not looked up")


def dependable(path: str) -> bool:
    return classify(path).dependable


def table() -> str:
    """The whole ledger, for printing at the top of a lesson."""
    rows = [("path", "level", "written down in")]
    for pattern, kind, entry, _ in RULES:
        rows.append((pattern, kind, entry or "nothing"))
    return grid(rows)


def explain(path: str) -> str:
    """One paragraph on why `path` is at the level it is."""
    found = classify(path)
    where = f", from {found.entry}" if found.entry else ""
    return f"{path} is {found.kind}{where}: {found.note}"
