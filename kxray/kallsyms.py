"""Every symbol in the running kernel, by name, from `/proc/kallsyms`.

This is here for one reason: it is the cheapest way to see that the kernel really is built out of
ops tables. A `struct file_operations` is a type and BTF can describe it, but an instance of one
is a fact about a running machine, and instances are what this file finds. `ext4_file_operations`,
`pipefifo_fops`, `tty_fops` and several hundred more are all there, by name, on any Linux box, with
no root and nothing installed.

Two things about the file surprise people, and both are load bearing for S05.

Addresses come back as zeros unless you are root. That is `kptr_restrict`, and it is a security
feature rather than a broken file: a kernel pointer handed to an unprivileged process is a gift to
whoever is trying to defeat address randomisation. Names are not restricted, which is why counting
and naming work anyway.

The one letter in the middle is the symbol's section, in the same code `nm` uses. Lower case is
local and upper case is global, `r` and `R` are read only data, and `d` and `D` are writable data.
Ops tables are almost always in read only data, because they are declared `const`, which is the
observable half of "one table, shared by every open file".
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

PATH = Path("/proc/kallsyms")

# What an ops table instance is called. Not a rule the kernel enforces, just what forty years of
# convention settled on, which is why this is a list of suffixes rather than a type check.
SUFFIXES = ("_fops", "_ops", "_operations")

# The section letters that mean read only data. Anything here was declared const.
READONLY = "rR"
WRITABLE = "dDbB"


@dataclass(frozen=True)
class Symbol:
    """One line of `/proc/kallsyms`."""

    address: int
    kind: str
    name: str
    module: str = ""

    @property
    def readonly(self) -> bool:
        return self.kind in READONLY

    @property
    def writable(self) -> bool:
        return self.kind in WRITABLE

    @property
    def is_ops(self) -> bool:
        return self.name.endswith(SUFFIXES)

    @property
    def family(self) -> str:
        """Which kind of ops table this is, taken from the end of the name.

        `ext4_file_operations` and `pipefifo_fops` are both file operations, and they are spelled
        differently because different parts of the tree picked different abbreviations. The family
        is the suffix, which is the most that can honestly be worked out from a name.
        """
        for suffix in SUFFIXES:
            if self.name.endswith(suffix):
                return suffix.lstrip("_")
        return ""


def parse(text: str) -> list[Symbol]:
    """Every line that is a symbol, and nothing else.

    A line is an address, a letter, a name, and sometimes a module in brackets. Anything that does
    not fit is skipped rather than raising, because this file is read on machines nobody writing
    this has seen and a parser that dies on line four hundred thousand helps nobody.
    """
    found: list[Symbol] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3 or len(parts[1]) != 1:
            continue
        try:
            address = int(parts[0], 16)
        except ValueError:
            continue
        module = parts[3].strip("[]") if len(parts) > 3 else ""
        found.append(Symbol(address, parts[1], parts[2], module))
    return found


def find(path: Path = PATH) -> Path | None:
    return path if path.exists() else None


def available(path: Path = PATH) -> bool:
    found = find(path)
    if found is None:
        return False
    try:
        with found.open("rb") as handle:
            handle.read(1)
    except OSError:
        return False
    return True


def read(path: Path = PATH) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def symbols(path: Path = PATH) -> list[Symbol]:
    return parse(read(path))


def ops_tables(found: list[Symbol]) -> list[Symbol]:
    """Every symbol whose name says it is an ops table."""
    return [one for one in found if one.is_ops]


def families(found: list[Symbol]) -> dict[str, int]:
    """How many tables of each spelling, most common first."""
    counted: dict[str, int] = {}
    for one in ops_tables(found):
        counted[one.family] = counted.get(one.family, 0) + 1
    return dict(sorted(counted.items(), key=lambda pair: (-pair[1], pair[0])))


def named(found: list[Symbol], needle: str) -> list[Symbol]:
    """Every symbol with `needle` somewhere in its name, in the order the file had them."""
    return [one for one in found if needle in one.name]


def hidden(found: list[Symbol]) -> bool:
    """Whether the addresses have been zeroed, which is what kptr_restrict does to a non root read.

    True for an empty list as well, because a list with no addresses in it certainly has no
    addresses you can use, and saying otherwise would read as a promise.
    """
    return all(one.address == 0 for one in found)


def explain(path: Path = PATH) -> str:
    """Why this machine has no symbol table, in the order worth checking."""
    if platform.system() != "Linux":
        return f"this is {platform.system()}, and /proc/kallsyms is a Linux kernel file"
    if find(path) is None:
        return f"{path} is not there, so this runtime is sandboxed away from /proc"
    if not available(path):
        return f"{path} exists and cannot be read here"
    return "the kernel symbol table is readable"


def report(path: Path = PATH) -> str:
    """What this runtime knows about its own kernel. Printed at the top of a lesson."""
    lines = [f"system:  {platform.system()} {platform.release()}"]
    if available(path):
        found = symbols(path)
        tables = ops_tables(found)
        lines.append(f"symbols: {len(found)}")
        lines.append(f"ops:     {len(tables)} tables named like one")
        const = sum(1 for one in tables if one.readonly)
        lines.append(f"const:   {const} of them in read only data")
        lines.append(f"address: {'hidden, so you are not root' if hidden(found) else 'visible'}")
    lines.append(f"status:  {explain(path)}")
    text = "\n".join(lines)
    print(text)
    return text
