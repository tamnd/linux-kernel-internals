"""Parsers for what the kernel's tracing interface prints.

`function_graph` for the call tree with its durations, `function` for the flat one line per call
trace that says which context every call ran in, and `events` for trace events, read through each
event's own `format` file rather than through a layout written down here. They are imported by
module rather than by name, because `parse` means three different things here and a lesson should
have to say which.
"""

from kxray.trace import events, formats, function, function_graph
from kxray.trace.function_graph import parse, parse_file

__all__ = ["events", "formats", "function", "function_graph", "parse", "parse_file"]
