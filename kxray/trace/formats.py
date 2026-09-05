"""A reader for an event's `format` file, which is the kernel telling you its own layout.

    from kxray.trace import formats

    layout = formats.parse_file("corpora/events/tier0/sched_switch.format")
    print(layout.table())
    print(layout.field("prev_state"))

Every trace event publishes one of these at `/sys/kernel/tracing/events/<group>/<event>/format`,
and it exists so that nothing has to hard code the shape of a record. That is not a nicety. The
layout is decided by the compiler that built the kernel, from a struct the kernel assembled from
a macro, on the architecture it was built for, with the config it was built with. `sched_switch`
on the 32 bit box this project pins says

    field:long prev_state;  offset:32;  size:4;  signed:1;

and the same event on the machine you are reading this on almost certainly says size 8, and every
field after it sits somewhere else. A parser that wrote those numbers down once is a parser that
is correct on one machine and quietly wrong on every other, which is the worst way to be wrong,
because nothing raises.

So this reads the file. What it does not do is read `print fmt`. That line is a C expression with
`__print_flags` and nested macro expansions in it, and evaluating it properly means being a C
compiler. It is kept as text because a person reading it learns something, and because it is the
answer to why a field the format calls an integer arrives as the letter `S`.
"""

from __future__ import annotations

import re
from pathlib import Path

from kxray.models import READ, SKIPPED, UNPARSED, EventField, EventFormat, Lines

# `	field:unsigned short common_type;	offset:0;	size:2;	signed:0;`
FIELD_RE = re.compile(
    r"^\s*field:(?P<decl>[^;]+);\s*"
    r"offset:(?P<offset>\d+);\s*"
    r"size:(?P<size>\d+);\s*"
    r"signed:(?P<signed>\d+);"
)
NAME_RE = re.compile(r"^\s*name:\s*(?P<name>\S+)\s*$")
ID_RE = re.compile(r"^\s*ID:\s*(?P<id>\d+)\s*$")
PRINT_RE = re.compile(r"^\s*print fmt:\s*(?P<fmt>.*)$")

# `prev_comm[16]`, and `args[6]`, and `filename[]` on a data_loc field with no length.
ARRAY_RE = re.compile(r"^(?P<name>\w+)\[(?P<count>\d*)\]$")

# `__data_loc char[] filename` and `__rel_loc char[] filename`. Both mean the same thing to a
# reader of the text output, which is that the record holds a reference and the string lives at
# the end of it, so the printed value is a string of whatever length it turned out to be.
INDIRECT = ("__data_loc ", "__rel_loc ")


class FormatError(ValueError):
    """A format file that did not say the things a format file says."""


def parse(text: str, source: str = "<text>") -> EventFormat:
    """Read one format file. Raises rather than guessing when the header is not there."""
    name = ""
    identity: int | None = None
    fields: list[EventField] = []
    print_fmt = ""

    for line in text.splitlines():
        found = NAME_RE.match(line)
        if found:
            name = found.group("name")
            continue
        found = ID_RE.match(line)
        if found:
            identity = int(found.group("id"))
            continue
        found = PRINT_RE.match(line)
        if found:
            print_fmt = found.group("fmt").strip()
            continue
        found = FIELD_RE.match(line)
        if found:
            fields.append(_field(found))

    if not name or identity is None:
        raise FormatError(f"{source} has no `name:` and `ID:` header, so it is not a format file")
    if not fields:
        raise FormatError(f"{source} declares no fields")

    return EventFormat(name=name, id=identity, fields=tuple(fields), print_fmt=print_fmt)


def parse_file(path: Path | str) -> EventFormat:
    p = Path(path)
    return parse(p.read_text(encoding="utf-8"), source=str(p))


def load(directory: Path | str, pattern: str = "*.format") -> dict[str, EventFormat]:
    """Every format in a directory, keyed by event name.

    Keyed by the event's own name rather than by the file name, because the trace prints the
    event name and that is what a lookup has to match. A file called `switch.format` holding
    `sched_switch` is still found under `sched_switch`.
    """
    found: dict[str, EventFormat] = {}
    for path in sorted(Path(directory).glob(pattern)):
        layout = parse_file(path)
        found[layout.name] = layout
    return found


def account(text: str) -> Lines:
    """How every line of a format file was accounted for, for `tools/baseline`.

    A `field:` line, the name, the ID and the print fmt are read. A blank line and the bare
    `format:` separator are skipped. Anything else is a line this reader would have thrown away
    without saying so, which is the thing the baseline exists to notice.
    """
    counted = Lines()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "format:":
            counted.count(SKIPPED)
        elif any(one.match(line) for one in (NAME_RE, ID_RE, PRINT_RE, FIELD_RE)):
            counted.count(READ)
        else:
            counted.count(UNPARSED)
    return counted


def _field(found: re.Match[str]) -> EventField:
    declaration = found.group("decl").strip()
    data_loc = declaration.startswith(INDIRECT)
    if data_loc:
        declaration = declaration.split(" ", 1)[1].strip()

    kind, _, name = declaration.rpartition(" ")
    kind, name = kind.strip(), name.strip()
    # `void *ptr` rather than `void * ptr`. The star belongs to the type either way.
    while name.startswith("*"):
        kind, name = f"{kind} *", name[1:]

    count: int | None = None
    array = ARRAY_RE.match(name)
    if array:
        name = array.group("name")
        count = int(array.group("count")) if array.group("count") else None
        # An array with no length written is a data_loc reference, and its length is whatever the
        # string turned out to be. Saying `count = 0` would read as an empty array.
        if count is None and not data_loc:
            count = 0

    return EventField(
        name=name,
        type=kind or "unknown",
        offset=int(found.group("offset")),
        size=int(found.group("size")),
        signed=found.group("signed") == "1",
        count=count,
        data_loc=data_loc,
    )
