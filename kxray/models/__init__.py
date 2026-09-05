"""The models that everything else renders.

A parser produces these and nothing else. Rendering never reaches into a parser, which is what
lets one trace appear as a tape in a notebook, as an animation in a lesson and as a table in a
blueprint without the three of them disagreeing about what happened.

Everything is re-exported here, so `from kxray.models import Tape` keeps working and nothing
outside this package needs to know which file a model lives in. Six files, one per subject:

    lines.py    line accounting and the table printer, which every parser here uses
    tape.py     function_graph: frames, the events between them, and the whole tape
    flat.py     the flat function tracer, and the flags column that gives the context
    events.py   trace events, read through the format file the kernel publishes
    proc.py     what comes out of /proc and /sys, each carrying its stability promise
    types.py    what the kernel knows about its own types, out of BTF

Nothing here imports a renderer, and that is the rule the split is protecting. Models are the
bottom of the stack: `kxshapes` works out geometry from them, `kxwidgets` and `kxmanim` draw what
`kxshapes` returns. The single conversion from a model to pictures lives in `kxshapes.scene`, one
layer up, because a model that knows how it is drawn is a model two renderers will fight over.
"""

from __future__ import annotations

from kxray.models.events import EventField, EventFormat, EventLog, TraceEvent
from kxray.models.flat import Call, Flags, FunctionLog, TraceLog
from kxray.models.lines import READ, SKIPPED, UNPARSED, Lines, grid
from kxray.models.proc import (
    LEVELS,
    NOT_ABI,
    OBSOLETE,
    REMOVED,
    STABLE,
    STAT_FIELDS,
    TESTING,
    UNDOCUMENTED,
    AddressSpace,
    Counter,
    CounterFile,
    KeyedFile,
    KeyValue,
    PidStat,
    ProcFile,
    Promise,
    Region,
    Version,
)
from kxray.models.tape import (
    DURATION_MARKERS,
    Comment,
    Event,
    Frame,
    InterruptEntry,
    InterruptExit,
    Tape,
    TaskSwitch,
    UnparsedLine,
)
from kxray.models.types import (
    EnumValue,
    Field,
    Hole,
    Layout,
    Member,
    OpsTable,
    Param,
    SecInfo,
    Slot,
    Type,
)

__all__ = [
    "DURATION_MARKERS",
    "LEVELS",
    "NOT_ABI",
    "OBSOLETE",
    "READ",
    "REMOVED",
    "SKIPPED",
    "STABLE",
    "STAT_FIELDS",
    "TESTING",
    "UNDOCUMENTED",
    "UNPARSED",
    "AddressSpace",
    "Call",
    "Comment",
    "Counter",
    "CounterFile",
    "EnumValue",
    "Event",
    "EventField",
    "EventFormat",
    "EventLog",
    "Field",
    "Flags",
    "Frame",
    "FunctionLog",
    "Hole",
    "InterruptEntry",
    "InterruptExit",
    "KeyValue",
    "KeyedFile",
    "Layout",
    "Lines",
    "Member",
    "OpsTable",
    "Param",
    "PidStat",
    "ProcFile",
    "Promise",
    "Region",
    "SecInfo",
    "Slot",
    "Tape",
    "TaskSwitch",
    "TraceEvent",
    "TraceLog",
    "Type",
    "UnparsedLine",
    "Version",
    "grid",
]
