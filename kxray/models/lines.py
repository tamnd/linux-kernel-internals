"""Two things every parser in this project needs and nothing else does.

Counting what happened to each line of a file, and printing a table.

Neither belongs to a subsystem. `kxray.trace`, `kxray.proc`, `kxray.source`, `kxray.kallsyms` and
`kxray.lockdep` all count lines the same way and all print tables the same way, and a copy of
either in each of them is five places for the three buckets to stop adding up.
"""

from __future__ import annotations

from dataclasses import dataclass

# What a parser did with one line. Every line of every committed artefact gets exactly one of
# these, which is the point: a line the parser quietly walked past is the one that goes wrong.
READ = "read"
SKIPPED = "skipped"
UNPARSED = "unparsed"


@dataclass
class Lines:
    """How every line of a file was accounted for.

    `read` turned into something. `skipped` was never data, so a blank line, a separator or a
    header the kernel prints above the rows. `unparsed` was meant to be data and was not
    understood.

    The reason all three are counted rather than just the last one is that the interesting drift
    moves a line between the first two. A parser that starts treating a data line as a header does
    not report a failure and does not raise, it just returns fewer rows, and the only way to see
    that from outside is to have written down how many lines were in each bucket beforehand.

    `total` has to equal the number of lines in the file. `tools/baseline` checks that, and a
    reader that cannot make the three numbers add up is a reader that is guessing.
    """

    read: int = 0
    skipped: int = 0
    unparsed: int = 0

    @property
    def total(self) -> int:
        return self.read + self.skipped + self.unparsed

    def count(self, verdict: str) -> None:
        setattr(self, verdict, getattr(self, verdict) + 1)

    def __str__(self) -> str:
        return f"{self.read} read, {self.skipped} skipped, {self.unparsed} unparsed"


def grid(rows: list[tuple[str, ...]]) -> str:
    """A header row, a rule, then the rest, every column as wide as its widest cell."""
    width = max(len(row) for row in rows)
    padded = [tuple(list(row) + [""] * (width - len(row))) for row in rows]
    widths = [max(len(row[i]) for row in padded) for i in range(width)]
    out = []
    for index, row in enumerate(padded):
        out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if index == 0:
            out.append("  ".join("-" * one for one in widths))
    return "\n".join(out)
