"""Parsers for what the kernel's tracing interface prints."""

from kxray.trace.function_graph import parse, parse_file

__all__ = ["parse", "parse_file"]
