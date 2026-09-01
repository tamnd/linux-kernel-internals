"""Write a small BTF blob.

This is here because there is no kernel to read BTF from yet, and a parser with nothing to parse
is a parser nobody can trust. It builds blobs the reader then reads, which is what the tests do,
and it builds the small teaching blob in `corpora/btf/handwritten/`.

It is worth being blunt about the limit. A blob written here is a blob we made up. It proves the
reader handles the format we believe in, and it proves nothing at all about what a real kernel
puts in `/sys/kernel/btf/vmlinux`. That is why the fixture it produces carries `evidence = false`
and no lesson is allowed to cite it. When there is a real kernel, the same tests run against the
real thing and this stays as a way of making a five type example a reader can hold in their head.

    from kxray.btf import writer

    b = writer.Builder()
    u32 = b.int_("unsigned int", 4, signed=False)
    b.struct("point", 8, [("x", u32, 0), ("y", u32, 32)])
    blob = b.build()
"""

from __future__ import annotations

import struct

from kxray.btf.format import (
    HEADER_SIZE,
    INT_BOOL,
    INT_CHAR,
    INT_SIGNED,
    KINDS,
    MAGIC,
    VERSION,
)

NUMBERS = {name: number for number, name in KINDS.items()}


class Builder:
    """Collects types, hands out identifiers, and packs the whole thing at the end.

    Every method returns the identifier of the type it added, so a nested type reads as nested
    calls rather than as a list of numbers somebody has to keep straight by hand.
    """

    def __init__(self) -> None:
        self._strings = bytearray(b"\0")
        self._offsets: dict[str, int] = {"": 0}
        self._types: list[bytes] = []

    # -- the pieces -------------------------------------------------------------------------

    def string(self, text: str) -> int:
        """Add a name to the string table, or return where it already is."""
        if text in self._offsets:
            return self._offsets[text]
        offset = len(self._strings)
        self._offsets[text] = offset
        self._strings += text.encode("utf-8") + b"\0"
        return offset

    def _add(self, kind: str, name: str, size_type: int, vlen: int, flag: bool, tail: bytes) -> int:
        info = (vlen & 0xFFFF) | (NUMBERS[kind] << 24) | ((1 << 31) if flag else 0)
        self._types.append(struct.pack("<III", self.string(name), info, size_type) + tail)
        return len(self._types)  # type 0 is void, so the first added type is 1

    # -- the kinds --------------------------------------------------------------------------

    def int_(
        self,
        name: str,
        size: int,
        *,
        bits: int | None = None,
        signed: bool = True,
        char: bool = False,
        boolean: bool = False,
        offset: int = 0,
    ) -> int:
        encoding = (INT_SIGNED if signed else 0) | (INT_CHAR if char else 0)
        encoding |= INT_BOOL if boolean else 0
        word = (encoding << 24) | ((offset & 0xFF) << 16) | ((bits if bits else size * 8) & 0xFF)
        return self._add("int", name, size, 0, False, struct.pack("<I", word))

    def ptr(self, target: int) -> int:
        return self._add("ptr", "", target, 0, False, b"")

    def array(self, element: int, nelems: int, index_type: int = 1) -> int:
        tail = struct.pack("<III", element, index_type, nelems)
        return self._add("array", "", 0, 0, False, tail)

    def struct(
        self,
        name: str,
        size: int,
        members: list[tuple[str, int, int]] | list[tuple[str, int, int, int]],
        *,
        union: bool = False,
    ) -> int:
        """Members are `(name, type, bit_offset)`, or `(name, type, bit_offset, bitfield_size)`.

        A member with a bitfield width turns on kind_flag for the whole record, which is what the
        format requires and what the reader keys off.
        """
        flag = any(len(member) == 4 and member[3] for member in members)
        tail = b""
        for member in members:
            member_name, member_type, bit_offset = member[0], member[1], member[2]
            width = member[3] if len(member) == 4 else 0
            offset = ((width & 0xFF) << 24) | (bit_offset & 0xFFFFFF) if flag else bit_offset
            tail += struct.pack("<III", self.string(member_name), member_type, offset)
        kind = "union" if union else "struct"
        return self._add(kind, name, size, len(members), flag, tail)

    def union(self, name: str, size: int, members: list[tuple[str, int, int]]) -> int:
        return self.struct(name, size, members, union=True)

    def enum(self, name: str, values: list[tuple[str, int]], size: int = 4) -> int:
        tail = b"".join(struct.pack("<Ii", self.string(n), v) for n, v in values)
        return self._add("enum", name, size, len(values), False, tail)

    def enum64(self, name: str, values: list[tuple[str, int]], size: int = 8) -> int:
        tail = b""
        for value_name, value in values:
            tail += struct.pack("<III", self.string(value_name), value & 0xFFFFFFFF, value >> 32)
        return self._add("enum64", name, size, len(values), False, tail)

    def typedef(self, name: str, target: int) -> int:
        return self._add("typedef", name, target, 0, False, b"")

    def const(self, target: int) -> int:
        return self._add("const", "", target, 0, False, b"")

    def volatile(self, target: int) -> int:
        return self._add("volatile", "", target, 0, False, b"")

    def fwd(self, name: str, *, union: bool = False) -> int:
        return self._add("fwd", name, 0, 0, union, b"")

    def float_(self, name: str, size: int) -> int:
        return self._add("float", name, size, 0, False, b"")

    def func_proto(self, returns: int, params: list[tuple[str, int]]) -> int:
        tail = b"".join(struct.pack("<II", self.string(n), t) for n, t in params)
        return self._add("func_proto", "", returns, len(params), False, tail)

    def func(self, name: str, proto: int, linkage: int = 1) -> int:
        return self._add("func", name, proto, linkage, False, b"")

    def var(self, name: str, target: int, linkage: int = 1) -> int:
        return self._add("var", name, target, 0, False, struct.pack("<I", linkage))

    def datasec(self, name: str, size: int, variables: list[tuple[int, int, int]]) -> int:
        tail = b"".join(struct.pack("<III", t, o, s) for t, o, s in variables)
        return self._add("datasec", name, size, len(variables), False, tail)

    def type_tag(self, name: str, target: int) -> int:
        return self._add("type_tag", name, target, 0, False, b"")

    def decl_tag(self, name: str, target: int, component: int = -1) -> int:
        return self._add("decl_tag", name, target, 0, False, struct.pack("<i", component))

    # -- packing it up ----------------------------------------------------------------------

    def build(self) -> bytes:
        """Header, then types, then strings, which is the order the format puts them in."""
        types = b"".join(self._types)
        header = struct.pack(
            "<HBBIIIII",
            MAGIC,
            VERSION,
            0,
            HEADER_SIZE,
            0,  # the type section starts right after the header
            len(types),
            len(types),  # and the string table starts right after the types
            len(self._strings),
        )
        return header + types + bytes(self._strings)
