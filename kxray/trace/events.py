"""A reader for event lines, bound to each event's own format rather than to a hard coded layout.

    from kxray.trace import events, formats

    layouts = formats.load("corpora/events/tier0")
    log = events.parse_file("corpora/traces/tier0/events-exec.txt", layouts)
    print(log.table("prev_comm", "prev_pid", "next_comm", "next_pid"))

An event line is the shared six column header, then the event's name, then whatever its
`print fmt` decided to say:

           sleep-38      [000] d..2.     3.049350: sched_switch: prev_comm=sh prev_pid=38 ...

Reading the key and value pairs out of that is the small half and is not the job. The job is
knowing what the keys mean, and the kernel publishes exactly that, per event, at
`/sys/kernel/tracing/events/<group>/<event>/format`. So a format is loaded, the line is read
through it, and three things come out that a plain split cannot give you.

Values arrive as numbers where the format declares numbers. `pid=38` is the integer 38 and
`comm=sh` is the string, and nothing downstream has to guess which by looking at the characters.

Fields the line printed that the format does not declare are named rather than kept quietly, and
so are fields the format declares that the line did not print. Neither is a fault. A `print fmt`
is free to leave a field out, and this is how you find out it did.

And a field the format calls a number that arrived as text is recorded as symbolic. That is not a
parse failure either, it is `__print_flags` having already run. `sched_switch` stores `prev_state`
as an integer and prints it as `S`, `R+` or `X`, and the record and the line are both correct.

There are two things this deliberately does not do. It does not read the ring buffer in binary,
which is what `trace_pipe_raw` gives you and what the offsets and sizes in a format are actually
for, and it does not evaluate `print fmt`. Both are real work and neither is needed to read the
text output, which is what a lesson reads.
"""

from __future__ import annotations

import re
from pathlib import Path

from kxray.models import READ, SKIPPED, UNPARSED, EventFormat, EventLog, TraceEvent, UnparsedLine
from kxray.trace import common

# `sched_switch: prev_comm=sh prev_pid=1 ...`, once the shared header is off the front.
EVENT_RE = re.compile(r"^(?P<name>[A-Za-z_][\w.]*):\s*(?P<body>.*)$")

# One `key=value` pair. The value runs to the next key rather than to the next space, because a
# comm can contain a space and ftrace does not quote it, so `prev_comm=my prog prev_pid=7` has to
# come apart in the one way that is right.
PAIR_RE = re.compile(r"(?P<key>\w+)=(?P<value>.*?)(?=\s+\w+=|\s*$)")

# A run of punctuation on the end of a value, which is a literal out of the print fmt rather than
# part of the value. `prev_state=S ==> next_comm=sh` puts `==>` on the end of the state. Anything
# joined to the value with no space, such as the `+` in `R+`, is left alone, because that came
# out of a __print_flags call and is part of what the field printed as.
LITERAL_RE = re.compile(r"\s+[^\w\s]+$")


def parse(
    text: str,
    formats: dict[str, EventFormat] | None = None,
    source: str = "<text>",
) -> EventLog:
    """Turn event trace output into an EventLog, reading each line through its format.

    `formats` is what `kxray.trace.formats.load` returns. Leaving it out is allowed and means
    every value stays a string, which `EventLog.unbound()` will tell you about.
    """
    log = EventLog(source=source, formats=dict(formats or {}))
    for number, raw in enumerate(text.splitlines(), start=1):
        log.lines.count(_read_line(log, number, raw.rstrip("\n")))
    return log


def parse_file(path: Path | str, formats: dict[str, EventFormat] | None = None) -> EventLog:
    p = Path(path)
    return parse(p.read_text(encoding="utf-8"), formats, source=str(p))


def pairs(body: str) -> dict[str, str]:
    """The key and value pairs in what an event printed, as text, in the order they appeared."""
    found: dict[str, str] = {}
    for one in PAIR_RE.finditer(body):
        found[one.group("key")] = LITERAL_RE.sub("", one.group("value").strip())
    return found


def bind(name: str, said: dict[str, str], layout: EventFormat | None) -> dict:
    """Read what a line printed through what its format declares.

    Returns the keyword arguments a `TraceEvent` wants: the values, and the three ways a line and a
    format can differ. With no format the values come back as strings and nothing is claimed.
    """
    if layout is None:
        return {"values": dict(said), "layout": None}

    values: dict[str, object] = {}
    symbolic: list[str] = []
    unknown: list[str] = []
    for key, text in said.items():
        one = layout.field(key)
        if one is None:
            unknown.append(key)
            values[key] = text
            continue
        if one.is_text:
            values[key] = text
            continue
        number = _number(text)
        if number is None:
            symbolic.append(key)
            values[key] = text
        else:
            values[key] = number

    missing = [one.name for one in layout.own if one.name not in said]
    return {
        "values": values,
        "layout": layout,
        "unknown": tuple(unknown),
        "missing": tuple(missing),
        "symbolic": tuple(symbolic),
    }


def _number(text: str) -> int | None:
    """The value as an integer, or None when it did not print as one."""
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return int(text, 16) if text.lower().startswith("0x") else None
    except ValueError:
        return None


def _read_line(log: EventLog, number: int, line: str) -> str:
    """What this line was: READ, SKIPPED or UNPARSED. Exactly one of the three, every time."""
    stripped = line.strip()
    if not stripped:
        return SKIPPED

    if stripped.startswith("#"):
        for key, value in common.banner(stripped).items():
            setattr(log, key, value)
        return SKIPPED

    head = common.header(line)
    if head is None:
        log.unparsed.append(UnparsedLine(number, line, "no task, cpu, flags and timestamp header"))
        return UNPARSED

    body = EVENT_RE.match(head.rest)
    if body is None:
        log.unparsed.append(
            UnparsedLine(number, line, f"no `event: ...` after the header, got {head.rest!r}")
        )
        return UNPARSED

    name = body.group("name")
    log.events.append(
        TraceEvent(
            name=name,
            task=head.task,
            pid=head.pid,
            cpu=head.cpu,
            flags=head.flags,
            timestamp=head.timestamp,
            line=number,
            **bind(name, pairs(body.group("body")), log.formats.get(name)),
        )
    )
    return READ
