"""The counter files, where the number of columns is a fact about the machine.

    from kxray.proc import percpu

    irqs = percpu.parse_file("corpora/proc/tier0/interrupts.txt", "/proc/interrupts")
    print(irqs.cpu_count, irqs.total("0"))

`/proc/interrupts` and `/proc/softirqs` are one shape: a header naming the CPUs, then rows of a
label, one count for each CPU, and in the interrupts case some trailing text saying what the line
is for. Reading one takes four lines of Python. Reading one without hard coding anything is the
part worth writing down.

The column count comes off the header and nowhere else. Not from `os.cpu_count()`, not from
`/proc/cpuinfo`, and certainly not from a constant. The pinned box has one CPU and prints one
column. A sixteen thread laptop prints sixteen. A kernel that has offlined a CPU prints a column
for it anyway, because these are per possible CPU, and one that was built with a lower
`CONFIG_NR_CPUS` prints fewer than the hardware has. The header is the only place all of that is
already resolved.

The rows below the numbered interrupts are per architecture and per config. This box, being
32-bit x86 under an emulator with one CPU and no local APIC to speak of, prints two of them:
`NMI` and `TLB`. An ordinary x86-64 desktop prints somewhere around fifteen, including `LOC`,
`RES`, `CAL` and `TRM`, and an arm64 machine prints a different set again. So there is no list of
them here. A row is a row, its label is whatever the kernel wrote, and `detail` keeps the text.

What the two files are for is easier to see together than apart. `/proc/interrupts` counts the
hardware asking for attention. `/proc/softirqs` counts the deferred work that the answering did
not do itself. `corpora/traces/tier0/flat-interrupt.txt` is that gap happening, four lines apart,
with timestamps on it. These two files are the same gap counted since boot.
"""

from __future__ import annotations

from pathlib import Path

from kxray.models import READ, SKIPPED, UNPARSED, Counter, CounterFile, Lines
from kxray.proc.stability import classify


def _header(line: str) -> tuple[str, ...] | None:
    """The CPU names off the first row, or None when this is not that row.

    The kernel writes the header as leading whitespace and then `CPU0 CPU1 ...` with no label and
    no colon, which is what makes it recognisable without matching on the word CPU: it is the one
    line in the file that has no colon on it.
    """
    if ":" in line or not line.strip():
        return None
    names = tuple(line.split())
    return names or None


def _read_line(line: str, cpus: int, number: int) -> Counter | None:
    """One row, or None when the counts are not counts."""
    label, sep, rest = line.partition(":")
    if not sep or not label.strip():
        return None
    words = rest.split(None, cpus)
    if len(words) < cpus:
        return None
    counts = []
    for word in words[:cpus]:
        try:
            counts.append(int(word))
        except ValueError:
            return None
    detail = words[cpus].strip() if len(words) > cpus else ""
    return Counter(label=label.strip(), counts=tuple(counts), detail=detail, line=number)


def parse(text: str, path: str = "", source: str = "<text>") -> CounterFile:
    """The header, then every row that fits it.

    A row is only read once the header has been seen, because until then there is no way to know
    where the counts stop and the description starts. `NMI: 0 Non-maskable interrupts` splits into
    a label and four words, and only the column count says that one of them is a number and three
    of them are prose.
    """
    cpus: tuple[str, ...] = ()
    counters = []
    lines = Lines()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            lines.count(SKIPPED)
            continue
        if not cpus:
            found_cpus = _header(line)
            if found_cpus is not None:
                cpus = found_cpus
                lines.count(SKIPPED)
                continue
            # A row before the header is a row nobody can read. With no column count there is no
            # way to say where the numbers stop, so this is unparsed rather than read with an empty
            # list of counts, which is the shape that would sail through and mean nothing.
            lines.count(UNPARSED)
            continue
        found = _read_line(line, len(cpus), number)
        if found is None:
            lines.count(UNPARSED)
            continue
        lines.count(READ)
        counters.append(found)
    return CounterFile(
        source=source,
        path=path,
        promise=classify(path) if path else classify(""),
        lines=lines,
        cpus=cpus,
        counters=tuple(counters),
    )


def parse_file(path: Path | str, kernel_path: str = "") -> CounterFile:
    found = Path(path)
    return parse(found.read_text(encoding="utf-8"), kernel_path, found.as_posix())


def account(text: str) -> Lines:
    return parse(text).lines


def hardware(found: CounterFile) -> list[Counter]:
    """The rows whose label is an interrupt number rather than a name.

    Those are the lines with a device on the end of them. The named rows underneath are the
    kernel's own counters and are a different kind of thing, even though the file prints them the
    same way.
    """
    return [one for one in found.counters if one.label.isdigit()]


def named(found: CounterFile) -> list[Counter]:
    return [one for one in found.counters if not one.label.isdigit()]


def report(found: CounterFile) -> str:
    lines = [
        found.banner(),
        f"cpus:    {found.cpu_count} column(s): {', '.join(found.cpus)}",
        f"rows:    {len(found.counters)}, of which {len(found.quiet())} never fired",
        f"lines:   {found.lines}",
    ]
    text = "\n".join(lines)
    print(text)
    return text
