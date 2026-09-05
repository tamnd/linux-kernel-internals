"""A parser for the flat function tracer.

    from kxray.trace import function

    log = function.parse_file("corpora/traces/tier0/flat-write.txt")
    print(log.table())
    print(log.contexts())

This is what `/sys/kernel/tracing/trace` looks like when `current_tracer` is `function` rather
than `function_graph`. One line per call, no nesting, no duration, and one column function_graph
does not print at all: the state of the machine when the call happened.

    # tracer: function
    #
    # entries-in-buffer/entries-written: 8/8   #P:1
    ...
               sleep-37      [000] d.h2.     7.712200: handle_irq_event <-handle_level_irq
               sleep-37      [000] .Ns1.     7.712426: rcu_core <-rcu_core_si

The trade against function_graph is worth stating, because a reader will ask which one to use.
function_graph gives you the shape of the call tree and how long each call took, and it costs
enough that the timings on Tier 0 are the emulator's rather than the kernel's. The flat tracer
gives you neither shape nor cost, and in exchange it gives you every call in order across every
task with the context of each one, at a fraction of the overhead. So the flat tracer answers what
ran and under what rules, and function_graph answers what called what and how long it took.

Same tolerance as the other parsers. A line this does not understand becomes an `UnparsedLine`
and the parse carries on, because ftrace output moves between releases and options change it
further. `corpora/BASELINE.toml` is what stops that tolerance from turning into silence.
"""

from __future__ import annotations

import re
from pathlib import Path

from kxray.models import READ, SKIPPED, UNPARSED, Call, FunctionLog, UnparsedLine
from kxray.trace import common

# `vfs_write <-ksys_write`, or `vfs_write` on its own when the print-parent option is off.
BODY_RE = re.compile(r"^(?P<name>\S+)(?:\s+<-(?P<caller>\S+))?$")


def parse(text: str, source: str = "<text>") -> FunctionLog:
    """Turn flat function tracer output into a FunctionLog."""
    log = FunctionLog(source=source)
    for number, raw in enumerate(text.splitlines(), start=1):
        log.lines.count(_read_line(log, number, raw.rstrip("\n")))
    return log


def parse_file(path: Path | str) -> FunctionLog:
    p = Path(path)
    return parse(p.read_text(encoding="utf-8"), source=str(p))


def _read_line(log: FunctionLog, number: int, line: str) -> str:
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

    body = BODY_RE.match(head.rest)
    if body is None:
        log.unparsed.append(UnparsedLine(number, line, f"unrecognised body {head.rest!r}"))
        return UNPARSED

    log.calls.append(
        Call(
            name=body.group("name"),
            caller=body.group("caller"),
            task=head.task,
            pid=head.pid,
            cpu=head.cpu,
            flags=head.flags,
            timestamp=head.timestamp,
            line=number,
        )
    )
    return READ
