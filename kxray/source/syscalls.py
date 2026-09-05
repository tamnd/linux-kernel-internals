"""The syscall tables, which are where a number stops being a number and becomes a name.

    from kxray.source import syscalls, tree

    table = syscalls.load(tree.find(), "i386")
    print(table.by_number(4).name, table.by_number(4).entry)

`arch/x86/entry/syscalls/syscall_32.tbl` and `syscall_64.tbl` are tab separated text with a header
comment that gives the format in one line:

    <number> <abi> <name> <entry point> [<compat entry point> [noreturn]]

The single fact worth putting at the top of anything that reads these files is that write is 4 on
i386 and 1 on x86-64, and read is 3 and 0. A syscall number with no architecture attached is not
an identifier, it is a number somebody wrote down while looking at one machine. This project pins
a 32 bit kernel, so every number a lesson prints comes out of the i386 table, and a reader on their
own x86-64 laptop who compares against the numbers they know will find they do not line up. Loading
both tables and printing them side by side is cheaper than explaining that.

Three shapes in these files catch a reader who assumes four fields per line.

Nineteen rows in the 32 bit table have a name and no entry point at all: `break`, `stty`, `gtty`,
`ftime`, `prof` and the rest of the calls that were removed decades ago. The number stays reserved
forever because somebody's binary from 1994 might still make the call and has to get ENOSYS rather
than somebody else's syscall.

Two rows carry a literal `-` where the compat entry point goes, followed by `noreturn`. That dash
is not an entry point named minus, it is a placeholder holding the column open so the word after it
lands in the right place.

The 64 bit table has three abis in it, `common`, `64` and `x32`, and the same name appears under
more than one of them with different numbers. `rt_sigaction` is one of them. So a lookup by name in
that file has to say which abi it means, and `by_name` returns a tuple rather than pretending
there is one answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kxray.models import READ, SKIPPED, UNPARSED, Lines, grid
from kxray.source.tree import File, Tree

TABLES = {
    "i386": "arch/x86/entry/syscalls/syscall_32.tbl",
    "x86_64": "arch/x86/entry/syscalls/syscall_64.tbl",
}

# The placeholder in the compat column. See the module docstring.
NONE = "-"

NORETURN = "noreturn"


@dataclass(frozen=True)
class Syscall:
    """One row: what the number means and what the kernel runs when it arrives."""

    number: int
    abi: str
    name: str
    entry: str = ""
    compat: str = ""
    noreturn: bool = False
    line: int = 0

    @property
    def implemented(self) -> bool:
        """Whether anything runs for this number.

        A row with no entry point is a number the kernel keeps reserved and answers with ENOSYS.
        Removing the row instead would let a later call take the number, and then a very old binary
        gets a wrong answer rather than an error.
        """
        return bool(self.entry)

    def __str__(self) -> str:
        where = self.entry or "nothing, the number is reserved"
        return f"{self.abi} {self.number} {self.name} -> {where}"


@dataclass
class Table:
    """One `.tbl` file, read."""

    source: str = "<text>"
    arch: str = ""
    calls: tuple[Syscall, ...] = ()
    unparsed: tuple[tuple[int, str], ...] = ()
    lines: Lines = field(default_factory=Lines)

    @property
    def abis(self) -> tuple[str, ...]:
        seen: list[str] = []
        for call in self.calls:
            if call.abi not in seen:
                seen.append(call.abi)
        return tuple(seen)

    def by_number(self, number: int, abi: str = "") -> Syscall | None:
        return next(
            (c for c in self.calls if c.number == number and (not abi or c.abi == abi)),
            None,
        )

    def by_name(self, name: str) -> tuple[Syscall, ...]:
        """Every row with this name, because in the 64 bit table there can be more than one."""
        return tuple(c for c in self.calls if c.name == name)

    def number_of(self, name: str, abi: str = "") -> int | None:
        """The number for a name, or None when the name is absent or the answer is ambiguous.

        None on ambiguity rather than the first hit. A name that exists under `64` and under `x32`
        has two numbers, and returning one of them silently is how a tool ends up making the wrong
        call on the machine where it matters.
        """
        found = [c for c in self.by_name(name) if not abi or c.abi == abi]
        return found[0].number if len(found) == 1 else None

    def entry_of(self, name: str, abi: str = "") -> str:
        found = [c for c in self.by_name(name) if not abi or c.abi == abi]
        return found[0].entry if len(found) == 1 else ""

    @property
    def reserved(self) -> tuple[Syscall, ...]:
        return tuple(c for c in self.calls if not c.implemented)

    def holes(self) -> tuple[int, ...]:
        """Numbers inside the range that no row claims.

        Different from a reserved row. A hole is a number nobody has written down at all, and the
        64 bit table has a hundred and twenty seven of them because the x32 calls start at 512 and
        everything between the end of the common numbers and there is empty.
        """
        numbers = {c.number for c in self.calls}
        if not numbers:
            return ()
        return tuple(n for n in range(min(numbers), max(numbers)) if n not in numbers)

    def table(self, names: tuple[str, ...]) -> str:
        rows = [("name", "number", "abi", "entry point")]
        for name in names:
            found = self.by_name(name)
            if not found:
                rows.append((name, "not here", "", ""))
                continue
            for call in found:
                rows.append(
                    (call.name, str(call.number), call.abi, call.entry or "reserved, no entry")
                )
        return grid(rows)


def parse(text: str, arch: str = "", source: str = "<text>") -> Table:
    """Read a `.tbl` file. Comments and blank lines are skipped, everything else has to fit."""
    calls: list[Syscall] = []
    unparsed: list[tuple[int, str]] = []
    counted = Lines()

    for number, line in enumerate(text.splitlines(), start=1):
        body = line.strip()
        if not body or body.startswith("#"):
            counted.count(SKIPPED)
            continue
        fields = body.split()
        if len(fields) < 3 or not fields[0].isdigit():
            unparsed.append((number, line))
            counted.count(UNPARSED)
            continue
        counted.count(READ)
        entry = fields[3] if len(fields) > 3 else ""
        compat = fields[4] if len(fields) > 4 else ""
        calls.append(
            Syscall(
                number=int(fields[0]),
                abi=fields[1],
                name=fields[2],
                entry="" if entry == NONE else entry,
                compat="" if compat == NONE else compat,
                noreturn=NORETURN in fields[3:],
                line=number,
            )
        )

    return Table(
        source=source,
        arch=arch,
        calls=tuple(calls),
        unparsed=tuple(unparsed),
        lines=counted,
    )


def parse_file(file: File, arch: str = "") -> Table:
    return parse(file.text, arch=arch, source=f"{file.root}/{file.path}")


def load(found: Tree, arch: str = "i386") -> Table:
    if arch not in TABLES:
        known = ", ".join(sorted(TABLES))
        raise LookupError(f"no table here for {arch}, this reads {known}")
    return parse_file(found.read(TABLES[arch]), arch=arch)


def compare(left: Table, right: Table, names: tuple[str, ...]) -> str:
    """The same calls in two tables, side by side.

    This is the whole argument for keeping both files in the corpus. Nobody argues with
    `write 4 1` once they have seen it.
    """
    rows = [("name", left.arch or "left", right.arch or "right", "same number")]
    for name in names:
        here = _one(left, name)
        there = _one(right, name)
        rows.append((name, here, there, "yes" if here == there and here.isdigit() else "no"))
    return grid(rows)


def _one(table: Table, name: str) -> str:
    """A name's number as a word, saying which of the three ways it can fail to be one number."""
    found = table.by_name(name)
    if not found:
        return "not in this table"
    if len(found) > 1:
        return ", ".join(f"{c.number} under {c.abi}" for c in found)
    return str(found[0].number)


def report(table: Table) -> str:
    lines = [
        f"{table.source}",
        f"arch:     {table.arch or 'not said'}",
        f"calls:    {len(table.calls)} rows, abis {', '.join(table.abis)}",
        f"reserved: {len(table.reserved)} numbers with no entry point",
        f"holes:    {len(table.holes())} numbers nothing claims",
    ]
    text = "\n".join(lines)
    print(text)
    return text
