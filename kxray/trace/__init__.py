"""Parsers for what the kernel's tracing interface prints.

`function_graph` for the call tree with its durations, and `function` for the flat one line per
call trace that says which context every call ran in. Both are imported by module rather than by
name, because `parse` means two different things here and a lesson should have to say which.
"""

from kxray.trace import function, function_graph
from kxray.trace.function_graph import parse, parse_file

__all__ = ["function", "function_graph", "parse", "parse_file"]
