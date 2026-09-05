"""The line header every ftrace format shares, and the flags column inside it.

Two tracers print the same six columns before they print anything of their own:

    writebyte-37      [000] .....     7.153632: vfs_write <-ksys_write
       sleep-37      [000] d.h2.     7.712200: handle_irq_event <-handle_level_irq
         cat-41      [000] d..2.     8.114900: sched_switch: prev_comm=cat prev_pid=41 ...

Task, pid, CPU, flags, timestamp, and then whatever the tracer has to say. So the header is read
here once and the two parsers that need it, the flat function tracer and the event reader, take
the rest of the line and go their own way.

The flags column is the interesting one and it is the one people skip. It says what state the
machine was in when the line was recorded, which is what decides whether the call on that line
was allowed to do what it did. `kxray/vocabulary.py` has the six contexts, and `Flags.context`
maps the column onto them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from kxray.models import Flags

# A data line, up to and including the timestamp. The task name is greedy from the left and the
# pid is the anchor, because a comm can contain almost anything, dashes and slashes included:
# `kworker/0:1-9` is one task called `kworker/0:1` with pid 9.
HEADER_RE = re.compile(
    r"^\s*(?P<task>.+)-(?P<pid>\d+)\s+"
    r"\[(?P<cpu>\d+)\]\s+"
    r"(?P<flags>[a-zA-Z.0-9]{4,5})\s+"
    r"(?P<timestamp>\d+\.\d+):\s?"
    r"(?P<rest>.*)$"
)

# `# entries-in-buffer/entries-written: 7/7   #P:1`, the banner line that says whether the ring
# buffer kept everything. Worth reading, because a trace that dropped events looks complete.
COUNTS_RE = re.compile(r"entries-in-buffer/entries-written:\s*(?P<kept>\d+)/(?P<written>\d+)")
CPUS_RE = re.compile(r"#P:(?P<count>\d+)")
TRACER_RE = re.compile(r"^#\s*tracer:\s*(?P<name>\S+)")


def parse_flags(raw: str) -> Flags:
    """Read the four or five character flags column.

    Four characters is a kernel from before migrate-disable was a thing. Five is current. The
    preemption count is a digit or a dot, and a dot means zero rather than unknown.
    """
    depth = raw[3]
    return Flags(
        raw=raw,
        irqs_off=raw[0],
        resched=raw[1],
        interrupt=raw[2],
        preempt_depth=int(depth) if depth.isdigit() else 0,
        migrate_disable=raw[4] if len(raw) > 4 else None,
    )


@dataclass(frozen=True)
class LineHeader:
    """The six columns in front of whatever the tracer had to say, plus what is left of the line."""

    task: str
    pid: int
    cpu: int
    flags: Flags
    timestamp: float
    rest: str


def header(line: str) -> LineHeader | None:
    """The header of a data line, or None when this is not one."""
    found = HEADER_RE.match(line)
    if not found:
        return None
    return LineHeader(
        task=found.group("task").strip(),
        pid=int(found.group("pid")),
        cpu=int(found.group("cpu")),
        flags=parse_flags(found.group("flags")),
        timestamp=float(found.group("timestamp")),
        rest=found.group("rest").strip(),
    )


def banner(line: str) -> dict[str, int | str]:
    """What one comment line at the top of a trace says. An empty dict when it says nothing.

    The keys are the field names on `FunctionLog`, so a parser can update the log with whatever
    comes back and not care which of the banner lines it was looking at.
    """
    found: dict[str, int | str] = {}
    tracer = TRACER_RE.match(line)
    if tracer:
        found["tracer"] = tracer.group("name")
    counts = COUNTS_RE.search(line)
    if counts:
        found["in_buffer"] = int(counts.group("kept"))
        found["written"] = int(counts.group("written"))
    cpus = CPUS_RE.search(line)
    if cpus:
        found["cpu_count"] = int(cpus.group("count"))
    return found
