"""An address space, one line per mapping, from `/proc/<pid>/maps`.

    from kxray.proc import maps

    space = maps.parse_file("corpora/proc/tier0/self-maps.txt", "/proc/self/maps")
    print(space.table())
    print(space.at(0x08048100))

This is the file that turns an address space from an idea into a list you can count. Seven lines
on the pinned box, for a process running `cat`:

    08048000-08149000 r-xp 00000000 00:03 11         /bin/busybox
    08149000-0814c000 rw-p 00100000 00:03 11         /bin/busybox
    b7f8f000-b7f9f000 rw-p 00000000 00:00 0
    b7f9f000-b7fa3000 r--p 00000000 00:00 0          [vvar]
    b7fa3000-b7fa5000 r--p 00000000 00:00 0          [vvar_vclock]
    b7fa5000-b7fa7000 r-xp 00000000 00:00 0          [vdso]
    bfa7b000-bfa9c000 rw-p 00000000 00:00 0          [stack]

Everything a page fault lesson needs is in there. The same file appears twice with different
permissions, once executable and once writable, because a program's text and its data are one
file mapped two ways. The third line has no name at all, which is the anonymous memory a first
write has to go and find a page for. Three of them are the kernel handing the process pieces of
itself. And between `0814c000` and `b7f8f000` there is nothing, which is most of the address
space and is the point.

The parse has one trap in it and it is in the file above, invisible in a browser. An anonymous
mapping has no path, and the kernel pads the line out to a fixed column before printing the path
it does not have, so the line ends in a space and has five fields on it rather than six. Code
that says `line.split()[5]` works on every line of every maps file until it meets one, and then
raises IndexError from inside something that was doing fine a moment ago. The regex below has the
path as optional, which is the shape the file actually has.

The bracketed names are not a fixed list. This kernel prints `[vvar]`, `[vvar_vclock]`, `[vdso]`
and `[stack]`, and other kernels print `[heap]`, `[vsyscall]` and names this one has never heard
of. So nothing here matches on them. `special` asks whether the kernel named the mapping instead
of a file, which stays true whatever the name turns out to be.
"""

from __future__ import annotations

import re
from pathlib import Path

from kxray.models import READ, SKIPPED, UNPARSED, AddressSpace, Lines, Region
from kxray.proc.stability import classify

# Two addresses, four permission characters, a file offset, a device, an inode, and then a path
# that is often not there. The trailing group is deliberately loose: it holds a filename with
# spaces in it as happily as it holds `[stack]`, and both are things the kernel prints.
LINE_RE = re.compile(
    r"^(?P<start>[0-9a-fA-F]+)-(?P<end>[0-9a-fA-F]+)\s+"
    r"(?P<perms>[rwxsp-]{4})\s+"
    r"(?P<offset>[0-9a-fA-F]+)\s+"
    r"(?P<dev>[0-9a-fA-F]+:[0-9a-fA-F]+)\s+"
    r"(?P<inode>\d+)"
    r"(?:\s+(?P<path>.*))?$"
)

PAGE = 4096


def _read_line(line: str, number: int) -> Region | None:
    match = LINE_RE.match(line)
    if match is None:
        return None
    return Region(
        start=int(match["start"], 16),
        end=int(match["end"], 16),
        perms=match["perms"],
        offset=int(match["offset"], 16),
        dev=match["dev"],
        inode=int(match["inode"]),
        path=(match["path"] or "").strip(),
        line=number,
    )


def parse(text: str, path: str = "", source: str = "<text>", pid: int = 0) -> AddressSpace:
    """Every mapping, in the order the kernel walked them, which is by address.

    The order is not incidental. The kernel keeps mappings in a tree sorted by address and walks
    it, so the file comes out sorted, which is what makes `gaps` meaningful and what lets `at` be
    a plain scan rather than a lookup.
    """
    regions = []
    lines = Lines()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            lines.count(SKIPPED)
            continue
        found = _read_line(line, number)
        if found is None:
            lines.count(UNPARSED)
            continue
        lines.count(READ)
        regions.append(found)
    return AddressSpace(
        source=source,
        path=path,
        promise=classify(path) if path else classify(""),
        lines=lines,
        pid=pid,
        regions=tuple(regions),
    )


def parse_file(path: Path | str, kernel_path: str = "", pid: int = 0) -> AddressSpace:
    found = Path(path)
    return parse(found.read_text(encoding="utf-8"), kernel_path, found.as_posix(), pid)


def account(text: str) -> Lines:
    return parse(text).lines


def naive_fields(line: str) -> list[str]:
    """What a whitespace split gives for one line, which is the wrong parse worth showing.

    Six fields for a mapping with a path and five for one without, from a file where the two look
    identical unless you count the trailing spaces. This is here so a lesson can print the two
    counts next to each other rather than asserting that the difference exists.
    """
    return line.split()


def report(space: AddressSpace) -> str:
    anonymous = [one for one in space.regions if one.anonymous]
    lines = [
        space.banner(),
        f"regions: {len(space.regions)}",
        f"mapped:  {space.total_size // PAGE} pages",
        f"anon:    {len(anonymous)} with no file behind them",
        f"named:   {', '.join(one.path for one in space.named()) or 'none'}",
        f"gaps:    {len(space.gaps())} unmapped stretches between them",
    ]
    text = "\n".join(lines)
    print(text)
    return text
