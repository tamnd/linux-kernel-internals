"""The BTF file format, as constants and small records.

BTF is what the kernel knows about its own types, written into the image at build time by pahole
and readable at runtime from `/sys/kernel/btf/vmlinux`. It is the answer to the question this book
asks over and over: what is actually in this struct, and where.

The format is documented in `Documentation/bpf/btf.rst` in the kernel tree. It is three pieces. A
header, then a type section, then a string table. Every name in the type section is an offset into
the string table, and every type reference is an index into the type section. Type 0 is void and
is not stored.

Nothing in here does any work. It is the vocabulary, kept apart from the reader so the reader can
be read as a story about parsing rather than as a wall of magic numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

MAGIC = 0xEB9F
VERSION = 1

# The header, once, at the start of the file.
HEADER_SIZE = 24

# The kinds of type BTF can describe. The number is what is in the file, the name is what we print.
KINDS = {
    0: "void",
    1: "int",
    2: "ptr",
    3: "array",
    4: "struct",
    5: "union",
    6: "enum",
    7: "fwd",
    8: "typedef",
    9: "volatile",
    10: "const",
    11: "restrict",
    12: "func",
    13: "func_proto",
    14: "var",
    15: "datasec",
    16: "float",
    17: "decl_tag",
    18: "type_tag",
    19: "enum64",
}

# Kinds whose `size_type` field is a size in bytes. Everything else stores a type reference there.
SIZED = {"int", "struct", "union", "enum", "float", "enum64"}

# Kinds that wrap another type and add nothing to its layout. Resolving a type means walking these
# until something with a size comes out. This is why `struct list_head *` and a typedef of it have
# the same offset in a struct: the wrappers are annotations, not storage.
WRAPPERS = {"typedef", "volatile", "const", "restrict", "type_tag"}

# What follows the common part of a type record, per kind, as a count of extra bytes. A kind that
# repeats a record `vlen` times has its per element size here and gets multiplied by `vlen`.
FIXED_TAIL = {
    "int": 4,
    "array": 12,
    "var": 4,
    "decl_tag": 4,
}

REPEATED_TAIL = {
    "struct": 12,
    "union": 12,
    "enum": 8,
    "enum64": 12,
    "func_proto": 8,
    "datasec": 12,
}

# The encoding bits on an int, from BTF_INT_SIGNED and friends.
INT_SIGNED = 1 << 0
INT_CHAR = 1 << 1
INT_BOOL = 1 << 2

# What a forward declaration is a forward declaration of. The bit lives in kind_flag, which is
# reused per kind, so it means something different here than it does on a struct.
FWD_KINDS = {False: "struct", True: "union"}

# What a variable's linkage number means, from BTF_VAR_STATIC and friends.
VAR_LINKAGE = {0: "static", 1: "global-allocated", 2: "global-extern"}

# What a function's linkage number means.
FUNC_LINKAGE = {0: "static", 1: "global", 2: "extern"}


class BtfError(ValueError):
    """Something in the file is not BTF, or is BTF we cannot read.

    A separate exception because a lesson that opens the wrong file should be told that, rather
    than getting a struct.error out of the middle of the standard library.
    """


@dataclass(frozen=True)
class Header:
    """The 24 bytes at the front of every BTF blob."""

    little_endian: bool
    version: int
    flags: int
    header_length: int
    type_offset: int
    type_length: int
    string_offset: int
    string_length: int

    @property
    def types_at(self) -> int:
        """Where the type section starts, counted from the start of the file.

        The offsets in the header are relative to the end of the header, not to the start of the
        file. Getting this wrong reads the string table as types and produces a blob of nonsense
        rather than an error, so it is worth naming.
        """
        return self.header_length + self.type_offset

    @property
    def strings_at(self) -> int:
        return self.header_length + self.string_offset
