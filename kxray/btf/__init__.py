"""What the kernel knows about its own types.

`parse_file("/sys/kernel/btf/vmlinux")` on a live machine, or a blob out of `corpora/`, and then
ask it what is in a struct and where.
"""

from kxray.btf.format import KINDS, BtfError, Header
from kxray.btf.reader import Btf, parse, parse_file, read_header

__all__ = ["KINDS", "Btf", "BtfError", "Header", "parse", "parse_file", "read_header"]
