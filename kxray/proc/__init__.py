"""The /proc and /sys files the lessons read, each one knowing what it is worth.

    from kxray import proc

    print(proc.read("corpora/proc/tier0/meminfo.txt", "/proc/meminfo").table())
    print(proc.stability.table())

Five readers for four file shapes, because /proc has fewer shapes in it than it has files.
`keyed` handles `Key: value`, which is meminfo and a process status file. `percpu` handles a
label and one count per CPU, which is interrupts and softirqs. `maps` handles one record per line
with positional columns. `pidstat` handles the single line with the command name in it, which is
its own shape because of what the command name is allowed to contain. `version` is one line of
free text with two useful things in it.

Every one of them returns something carrying a `promise`, from `kxray.proc.stability`, saying
what the kernel tree says about the file it read. That is not decoration. On Linux 7.2.2 there
are 685 files under `Documentation/ABI` and six of them describe a path in /proc, and not one of
those six is a file in this corpus. Everything here is read on custom rather than on a promise,
and the object says so when you print it.
"""

from __future__ import annotations

from pathlib import Path

from kxray.models import ProcFile
from kxray.proc import keyed, maps, percpu, pidstat, stability, version

__all__ = [
    "READERS",
    "keyed",
    "maps",
    "percpu",
    "pidstat",
    "read",
    "reader_for",
    "stability",
    "version",
]

# Which reader opens which kernel path. Patterns rather than names, because a per process file is
# read under a pid and under `self` and under `thread-self` and it is the same file either way.
READERS = (
    ("/proc/version", version),
    ("/proc/meminfo", keyed),
    ("/proc/interrupts", percpu),
    ("/proc/softirqs", percpu),
    ("/proc/*/stat", pidstat),
    ("/proc/*/maps", maps),
    ("/proc/*/status", keyed),
)


def reader_for(kernel_path: str):
    """The module that reads this path, or None when nothing here does.

    None rather than a guess. A file shape that has not been looked at is not a `Key: value` file
    merely because most of them are, and returning `keyed` for anything unrecognised would turn a
    missing reader into a quiet half correct one.
    """
    from fnmatch import fnmatch

    return next((module for pattern, module in READERS if fnmatch(kernel_path, pattern)), None)


def read(path: Path | str, kernel_path: str) -> ProcFile:
    """Read a captured file with whatever reader its kernel path calls for.

    `kernel_path` is passed separately because a capture on disk is called something else. The
    file in the corpus is `self-maps.txt` and what it is, is `/proc/self/maps`, and only the
    second of those decides how to read it or what it is worth.
    """
    module = reader_for(kernel_path)
    if module is None:
        raise LookupError(f"nothing in kxray.proc reads {kernel_path}")
    return module.parse_file(path, kernel_path)
