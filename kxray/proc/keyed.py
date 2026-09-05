"""The `Key: value` files, which is most of what people mean when they say they read /proc.

    from kxray.proc import keyed

    mem = keyed.parse_file("corpora/proc/tier0/meminfo.txt", "/proc/meminfo")
    print(mem.number("MemTotal"), mem["MemTotal"].unit)

`/proc/meminfo` and `/proc/<pid>/status` are the same file shape with different separators, so
they are read by the same code. One key per line, a colon, then the value.

Three things make this less simple than it sounds, and all three are visible in the two captures
in `corpora/proc/tier0/`.

The value is not always one number. `Uid:` in a status file is four numbers, the real, effective,
saved and filesystem user IDs, all on one line. `State:` is a letter and then the same state
spelled out in brackets. `Groups:` on a process in no supplementary groups is empty, and the
kernel still prints the key and a separator. So the model keeps a tuple of words and offers a
number only when there is exactly one word and it is one.

The unit is a lie that everybody has agreed to. The kernel writes `kB` and means KiB: the pinned
box reports `MemTotal: 102308 kB` for a machine given 100 MiB, and 102308 times 1024 is a hair
under 100 MiB while 102308 times 1000 is not. `unit` keeps the kernel's spelling, because
changing it here would mean this file disagreeing with every other tool on the machine, and
`bytes()` does the multiplication with the right factor.

The set of keys is per config and per version. This box has `untag_mask` and `THP_enabled` in a
status file and no `HugePages_Total` in meminfo, and another machine will differ in both
directions. So nothing here has a required key list, and a missing key raises a KeyError naming
the kernel rather than returning zero.
"""

from __future__ import annotations

from pathlib import Path

from kxray.models import READ, SKIPPED, UNPARSED, KeyedFile, KeyValue, Lines
from kxray.proc.stability import classify

# The only unit the kernel ever writes in these files. It means 1024 bytes.
UNITS = ("kB",)

KIB = 1024


def _read_line(line: str, number: int) -> KeyValue | None:
    """One line, or None when there is no key on it."""
    key, sep, rest = line.partition(":")
    if not sep or not key.strip() or ":" in key:
        return None
    words = rest.split()
    unit = ""
    if words and words[-1] in UNITS:
        unit = words[-1]
        words = words[:-1]
    return KeyValue(key=key.strip(), values=tuple(words), unit=unit, line=number)


def parse(text: str, path: str = "", source: str = "<text>") -> KeyedFile:
    """Every `Key: value` line in the file, in the order the kernel wrote them.

    Order is kept because it carries meaning. The status file groups memory keys together and the
    meminfo file puts the totals first, and a dict would throw that away for no gain.
    """
    entries = []
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
        entries.append(found)
    return KeyedFile(
        source=source,
        path=path,
        promise=classify(path) if path else classify(""),
        lines=lines,
        entries=tuple(entries),
    )


def parse_file(path: Path | str, kernel_path: str = "") -> KeyedFile:
    found = Path(path)
    return parse(found.read_text(encoding="utf-8"), kernel_path, found.as_posix())


def account(text: str) -> Lines:
    return parse(text).lines


def bytes_of(found: KeyedFile, key: str) -> int | None:
    """One key as a count of bytes, doing the KiB multiplication the kernel's spelling hides.

    None when the key is not there or has no single number, which is the same answer `number`
    gives and for the same reason.
    """
    entry = found.get(key)
    if entry is None or entry.number is None:
        return None
    return entry.number * KIB if entry.unit == "kB" else entry.number


def report(found: KeyedFile) -> str:
    """What was read and what it is worth, for the top of a lesson."""
    lines = [found.banner(), f"keys:    {len(found.entries)}", f"lines:   {found.lines}"]
    text = "\n".join(lines)
    print(text)
    return text
