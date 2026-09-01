"""A parser for ftrace's function_graph output.

This is the format behind the Syscall Tape, so it is the most important parser in the project.
It reads what comes out of `/sys/kernel/tracing/trace` when `current_tracer` is `function_graph`,
and it produces a `Tape`.

Two decisions worth knowing about before you read the code.

**Nothing raises.** A line the parser does not understand becomes an `UnparsedLine` and the parse
carries on. ftrace output changes between releases, options such as `funcgraph-proc` and
`funcgraph-args` change it further, and a book that falls over on an unfamiliar line is a book
that breaks on somebody else's kernel. The price of that tolerance is a count: every artefact in
`corpora/` records how many unparsed lines it should have, and CI fails when the number goes up.

**Depth is per CPU.** Output from every CPU is interleaved in one file, so there is one call stack
per CPU and not one for the trace. Getting this wrong produces a tree that looks fine and is
nonsense, which is the worst kind of wrong.

The format itself, for reference:

    # tracer: function_graph
    #
    # CPU  DURATION                  FUNCTION CALLS
    # |     |   |                     |   |   |   |
     0)               |  vfs_write() {
     0)   0.101 us    |    security_file_permission();
     0) + 16.157 us   |  }
"""

from __future__ import annotations

import re
from pathlib import Path

from kxray.models import (
    Comment,
    Frame,
    InterruptEntry,
    InterruptExit,
    Tape,
    TaskSwitch,
    UnparsedLine,
)

# " 0) " at the start of every data line.
CPU_RE = re.compile(r"^\s*(?P<cpu>\d+)\)\s?(?P<rest>.*)$")

# The task column, present when the funcgraph-proc option is on. Task names contain dashes and
# slashes, so the pid on the end is the only reliable anchor.
TASK_RE = re.compile(r"^\S+-\d+$")

# The duration column. The leading character is a slowness marker when there is one.
DURATION_RE = re.compile(r"^(?P<marker>[+!#*@$])?\s*(?P<value>\d+(?:\.\d+)?)\s*us$")

# A call that has a body, so its cost arrives later on the closing line.
OPEN_RE = re.compile(r"^(?P<name>[^\s(]+)\((?P<args>.*)\)\s*\{$")

# A call with no children, printed complete on one line.
LEAF_RE = re.compile(r"^(?P<name>[^\s(]+)\((?P<args>.*)\);$")

# A closing brace, with the name attached when funcgraph-tail is on.
CLOSE_RE = re.compile(r"^\}(?:\s*/\*\s*(?P<name>.*?)\s*\*/)?$")

COMMENT_RE = re.compile(r"^/\*\s*(?P<text>.*?)\s*\*/$")

# The task switch banner, which has no duration column and no pipe.
SWITCH_RE = re.compile(r"^(?P<previous>\S+)\s+=>\s+(?P<following>\S+)$")

SEPARATOR_RE = re.compile(r"^\s*-{4,}\s*$")

TRACER_RE = re.compile(r"^#\s*tracer:\s*(?P<name>\S+)")


def parse(text: str, source: str = "<text>") -> Tape:
    """Turn function_graph output into a Tape."""
    tape = Tape(source=source)
    stacks: dict[int, list[Frame]] = {}

    for number, raw in enumerate(text.splitlines(), start=1):
        _read_line(tape, stacks, number, raw)

    # Whatever is still open ran off the end of the buffer. Say so rather than hiding it.
    for stack in stacks.values():
        for frame in stack:
            frame.complete = False

    return tape


def parse_file(path: Path | str) -> Tape:
    p = Path(path)
    return parse(p.read_text(encoding="utf-8"), source=str(p))


def _read_line(tape: Tape, stacks: dict[int, list[Frame]], number: int, raw: str) -> None:
    line = raw.rstrip("\n")
    stripped = line.strip()

    if not stripped or SEPARATOR_RE.match(line):
        return

    if stripped.startswith("#"):
        tracer = TRACER_RE.match(stripped)
        if tracer:
            tape.tracer = tracer.group("name")
        return

    head = CPU_RE.match(line)
    if not head:
        tape.unparsed.append(UnparsedLine(number, line, "no CPU column"))
        return

    cpu = int(head.group("cpu"))
    rest = head.group("rest")

    switch = SWITCH_RE.match(rest.strip())
    if switch:
        tape.events.append(
            TaskSwitch(cpu, number, switch.group("previous"), switch.group("following"))
        )
        return

    if "|" not in rest:
        tape.unparsed.append(UnparsedLine(number, line, "no duration column"))
        return

    task, duration_field, body = _split_columns(rest)

    marker_event = _interrupt_marker(duration_field, cpu, number)
    if marker_event is not None:
        tape.events.append(marker_event)
        return

    duration_us, marker, bad_duration = _parse_duration(duration_field)
    if bad_duration:
        tape.unparsed.append(UnparsedLine(number, line, f"duration {duration_field.strip()!r}"))
        return

    _read_body(tape, stacks, cpu, number, line, body, task, duration_us, marker)


def _split_columns(rest: str) -> tuple[str | None, str, str]:
    """Split the part after the CPU into task, duration and body.

    The task column only exists when funcgraph-proc is on, and the only way to tell it apart from
    a duration is that it ends in a pid.
    """
    parts = rest.split("|")
    if len(parts) >= 3 and TASK_RE.match(parts[0].strip()):
        return parts[0].strip(), parts[1], "|".join(parts[2:])
    return None, parts[0], "|".join(parts[1:])


def _interrupt_marker(field: str, cpu: int, number: int) -> InterruptEntry | InterruptExit | None:
    text = field.strip()
    if text.startswith("="):
        return InterruptEntry(cpu, number)
    if text.startswith("<="):
        return InterruptExit(cpu, number)
    return None


def _parse_duration(field: str) -> tuple[float | None, str | None, bool]:
    """Returns the duration, the slowness marker, and whether the field was unreadable."""
    text = field.strip()
    if not text:
        return None, None, False
    match = DURATION_RE.match(text)
    if not match:
        return None, None, True
    return float(match.group("value")), match.group("marker"), False


def _read_body(
    tape: Tape,
    stacks: dict[int, list[Frame]],
    cpu: int,
    number: int,
    line: str,
    body: str,
    task: str | None,
    duration_us: float | None,
    marker: str | None,
) -> None:
    content = body.strip()
    if not content:
        return

    stack = stacks.setdefault(cpu, [])
    # ftrace indents by two spaces per level, after two spaces of its own.
    indent = len(body) - len(body.lstrip(" "))
    depth = max(0, (indent - 2) // 2)

    comment = COMMENT_RE.match(content)
    if comment:
        tape.events.append(Comment(cpu, number, comment.group("text")))
        return

    close = CLOSE_RE.match(content)
    if close:
        if not stack:
            tape.unparsed.append(UnparsedLine(number, line, "closing brace with no matching call"))
            return
        frame = stack.pop()
        frame.duration_us = duration_us
        frame.marker = marker
        named = close.group("name")
        if named and named != frame.name:
            tape.unparsed.append(
                UnparsedLine(
                    number, line, f"closing brace names {named!r}, open frame is {frame.name!r}"
                )
            )
        return

    open_call = OPEN_RE.match(content)
    if open_call:
        frame = Frame(open_call.group("name"), cpu, depth, number, task=task)
        _attach(tape, stack, frame)
        stack.append(frame)
        return

    leaf = LEAF_RE.match(content)
    if leaf:
        frame = Frame(
            leaf.group("name"),
            cpu,
            depth,
            number,
            duration_us=duration_us,
            marker=marker,
            task=task,
        )
        _attach(tape, stack, frame)
        return

    tape.unparsed.append(UnparsedLine(number, line, "unrecognised body"))


def _attach(tape: Tape, stack: list[Frame], frame: Frame) -> None:
    if stack:
        frame.parent = stack[-1]
        stack[-1].children.append(frame)
    else:
        tape.roots.append(frame)
