"""Read BTF, and answer what a struct looks like in memory.

The question this exists for is the one every memory lesson opens with. What is in this struct,
in what order, at what offset, and how much of it is padding the compiler added. On a real machine
you would run pahole. In a browser tab there is no pahole, so this reads the same bytes pahole
reads and answers the same question.

    from kxray import btf

    vmlinux = btf.parse_file("/sys/kernel/btf/vmlinux")
    print(vmlinux.layout("task_struct").table())

Pure Python and standard library only, because this has to run under Pyodide and in Colab. It
reads a 5 MB vmlinux BTF in a couple of seconds, which is slow next to pahole and fast enough for
a lesson.

One thing BTF does not tell you is the size of a pointer. The file describes types, not a machine,
and the same blob means one layout on 32-bit and another on 64-bit. So the pointer size is
something you pass in, it defaults to 8, and every layout prints which one it used. A lesson
looking at the Tier 0 kernel passes 4.
"""

from __future__ import annotations

import struct
from pathlib import Path

from kxray.btf.format import (
    FIXED_TAIL,
    FUNC_LINKAGE,
    FWD_KINDS,
    HEADER_SIZE,
    INT_BOOL,
    INT_CHAR,
    INT_SIGNED,
    KINDS,
    MAGIC,
    REPEATED_TAIL,
    SIZED,
    VERSION,
    WRAPPERS,
    BtfError,
    Header,
)
from kxray.models import EnumValue, Field, Hole, Layout, Member, Param, SecInfo, Type

VOID = Type(id=0, kind="void", name="void", size=0)


def read_header(blob: bytes) -> Header:
    """Read the header, and work out the endianness from the magic number.

    A BTF blob written on a big endian machine has the magic the other way round, and that is the
    only signal there is. Reading it the wrong way round gives you a header full of enormous
    offsets rather than an error, so this checks the magic first and decides from it.
    """
    if len(blob) < HEADER_SIZE:
        raise BtfError(f"only {len(blob)} bytes, which is not long enough to be BTF")

    little = struct.unpack_from("<H", blob, 0)[0] == MAGIC
    if not little and struct.unpack_from(">H", blob, 0)[0] != MAGIC:
        got = blob[:2].hex()
        raise BtfError(f"does not start with the BTF magic number, it starts with {got}")

    order = "<" if little else ">"
    _, version, flags, header_length = struct.unpack_from(order + "HBBI", blob, 0)
    if version != VERSION:
        raise BtfError(f"BTF version {version}, and this reader only knows version {VERSION}")

    offsets = struct.unpack_from(order + "IIII", blob, 8)
    return Header(little, version, flags, header_length, *offsets)


class Btf:
    """A parsed BTF blob, and the questions you can ask it.

    Types are held in a list indexed by identifier, so `btf.types[7]` is type 7 and there is no
    lookup to get there. Index 0 is void, which the file does not store and every reference to a
    missing type uses.
    """

    def __init__(
        self,
        types: list[Type],
        strings: bytes,
        *,
        pointer_size: int = 8,
        source: str = "<bytes>",
    ) -> None:
        self.types = types
        self.strings = strings
        self.pointer_size = pointer_size
        self.source = source
        self._by_name: dict[tuple[str, str], Type] = {}
        for one in types:
            if one.name:
                self._by_name.setdefault((one.kind, one.name), one)

    def __len__(self) -> int:
        return len(self.types)

    def __repr__(self) -> str:
        return f"<Btf {self.source} {len(self.types) - 1} types>"

    # -- looking things up ------------------------------------------------------------------

    def get(self, type_id: int | None) -> Type:
        """Type by identifier. Out of range or None gives you void rather than an exception.

        Being forgiving here is deliberate. A type reference that points nowhere is what a
        truncated blob looks like, and a lesson should see `void` in a table rather than a
        traceback halfway through printing one.
        """
        if type_id is None or type_id < 0 or type_id >= len(self.types):
            return VOID
        return self.types[type_id]

    def find(self, name: str, kind: str | None = None) -> list[Type]:
        """Every type with this name. There is usually one, and sometimes there are several.

        A kernel really does contain two different structs with the same name, from two different
        compilation units, and BTF keeps both. Returning a list rather than picking one is how
        that stays visible instead of turning into a wrong offset.
        """
        return [t for t in self.types if t.name == name and (kind is None or t.kind == kind)]

    def named(self, kind: str, name: str) -> Type:
        """The first type of this kind with this name, or a KeyError naming what was asked for."""
        found = self._by_name.get((kind, name))
        if found is None:
            raise KeyError(f"{self.source} has no {kind} called {name!r}")
        return found

    def struct(self, name: str) -> Type:
        """A struct by name, falling back to a union, because lessons ask for both this way."""
        try:
            return self.named("struct", name)
        except KeyError:
            return self.named("union", name)

    # -- reading a type ---------------------------------------------------------------------

    def resolve(self, type_id: int | None) -> Type:
        """Strip typedefs, const, volatile, restrict and type tags until something real is left.

        This is the step people forget. `pid_t pid` is a typedef of an int, and asking a typedef
        for its size gets you nothing, because the size is on the int behind it.
        """
        seen = set()
        one = self.get(type_id)
        while one.kind in WRAPPERS:
            if one.id in seen:
                raise BtfError(f"type {one.id} refers to itself through typedefs")
            seen.add(one.id)
            one = self.get(one.type_id)
        return one

    def size_of(self, type_id: int | None) -> int | None:
        """Size in bytes, or None when the file does not say.

        A pointer has no size in BTF, so it gets the pointer size this reader was given. A
        function prototype and a forward declaration have no size at all, and None is the honest
        answer rather than zero.
        """
        one = self.resolve(type_id)
        if one.kind == "ptr":
            return self.pointer_size
        if one.kind == "array":
            element = self.size_of(one.element_type)
            return None if element is None else element * (one.nelems or 0)
        if one.kind in SIZED:
            return one.size
        if one.kind == "void":
            return 0
        return None

    def type_name(self, type_id: int | None) -> str:
        """The type as you would write it in C, near enough to read in a table.

        Not a C declarator generator. An array of pointers comes out as `char *[8]` rather than in
        the spiral order C actually uses, because the point is a reader recognising the type in a
        table, not compiling it.
        """
        one = self.get(type_id)
        if one.kind == "void":
            return "void"
        if one.kind == "ptr":
            inner = self.type_name(one.type_id)
            return inner + ("*" if inner.endswith("*") else " *")
        if one.kind == "array":
            return f"{self.type_name(one.element_type)}[{one.nelems}]"
        if one.kind in ("struct", "union", "enum"):
            return f"{one.kind} {one.name}" if one.name else f"anonymous {one.kind}"
        if one.kind == "enum64":
            return f"enum {one.name}" if one.name else "anonymous enum"
        if one.kind == "fwd":
            return f"{FWD_KINDS[one.kind_flag]} {one.name}"
        if one.kind in ("const", "volatile", "restrict"):
            return f"{one.kind} {self.type_name(one.type_id)}"
        if one.kind == "type_tag":
            # Written the way the kernel source writes it. The tags that exist are `user`,
            # `percpu`, `rcu` and `kptr`, and every one of them is spelled with two leading
            # underscores in the tree, so `char __user *` is what a reader will recognise.
            return f"{self.type_name(one.type_id)} __{one.name}"
        if one.kind == "func_proto":
            args = ", ".join(self.type_name(p.type_id) for p in one.params) or "void"
            return f"{self.type_name(one.type_id)} ({args})"
        return one.name or one.kind

    def int_description(self, type_id: int | None) -> str:
        """What an int record says about itself: signedness, and whether it is a char or a bool."""
        one = self.resolve(type_id)
        if one.kind != "int":
            return ""
        parts = []
        if one.encoding & INT_BOOL:
            parts.append("bool")
        if one.encoding & INT_CHAR:
            parts.append("char")
        parts.append("signed" if one.encoding & INT_SIGNED else "unsigned")
        return " ".join(parts) + f", {one.bits} bits"

    # -- what a struct looks like -----------------------------------------------------------

    def layout(self, name: str, *, flatten: bool = True) -> Layout:
        """What this struct looks like in memory, with the holes in it.

        Anonymous members get flattened into the enclosing struct, which is what C does, so an
        anonymous union's fields appear at the offsets you would actually use them at. Pass
        `flatten=False` to see only what the struct itself declares.
        """
        one = self.struct(name)
        fields: list[Field] = []
        self._collect(one, prefix="", base=0, into=fields, flatten=flatten)
        fields.sort(key=lambda f: (f.byte_offset, f.bit_offset))
        return Layout(
            name=f"{one.kind} {name}",
            size=one.size,
            pointer_size=self.pointer_size,
            fields=fields,
            holes=self._holes(fields, one.size, is_union=one.kind == "union"),
        )

    def _collect(self, one: Type, prefix: str, base: int, into: list[Field], flatten: bool) -> None:
        for member in one.members:
            bit = base + member.bit_offset
            inner = self.resolve(member.type_id)
            anonymous = not member.name

            if flatten and anonymous and inner.is_composite:
                self._collect(inner, prefix, bit, into, flatten)
                continue

            path = f"{prefix}{member.name}" if member.name else f"{prefix}<anonymous>"
            into.append(
                Field(
                    path=path,
                    type_name=self.type_name(member.type_id),
                    byte_offset=bit // 8,
                    bit_offset=bit,
                    size=self.size_of(member.type_id),
                    bitfield_size=self._bitfield_size(member, inner),
                )
            )

            if flatten and inner.is_composite and member.name:
                self._collect(inner, f"{path}.", bit, into, flatten)

    def _bitfield_size(self, member: Member, resolved: Type) -> int:
        """How many bits this field really uses, from whichever of the two encodings was used.

        There are two, and both are still in the wild. The modern one puts the width in the
        member record and sets kind_flag on the struct. The older one leaves the member alone and
        narrows the int type behind it instead. Reading only the first quietly reports a one bit
        flag as a four byte field.
        """
        if member.bitfield_size:
            return member.bitfield_size
        narrowed = resolved.kind == "int" and resolved.bits is not None and resolved.size
        if narrowed and resolved.bits != resolved.size * 8:
            return resolved.bits
        return 0

    def _holes(self, fields: list[Field], size: int | None, *, is_union: bool) -> list[Hole]:
        """Padding between fields, and at the end.

        A union is every field at offset zero, so gaps between them are not holes and the
        arithmetic below would report the whole thing as padding. So it does not run for unions.
        """
        if is_union:
            return []
        holes: list[Hole] = []
        cursor = 0
        previous = "the start of the struct"
        for one in fields:
            if one.byte_offset > cursor:
                holes.append(Hole(previous, cursor, one.byte_offset - cursor))
            if one.end is not None:
                cursor = max(cursor, one.end)
            previous = one.path
        if size is not None and size > cursor:
            holes.append(Hole(previous, cursor, size - cursor))
        return holes

    def offset_of(self, path: str) -> int:
        """The byte offset of a field, written as `task_struct.mm` or `task_struct.se.on_rq`."""
        name, _, rest = path.partition(".")
        if not rest:
            raise KeyError(f"{path!r} names a struct and no field in it")
        return self.layout(name).offset_of(rest)

    # -- what is in here at all -------------------------------------------------------------

    def kinds(self) -> dict[str, int]:
        """How many of each kind, which is the first thing to print about an unfamiliar blob."""
        counts: dict[str, int] = {}
        for one in self.types[1:]:
            counts[one.kind] = counts.get(one.kind, 0) + 1
        return dict(sorted(counts.items(), key=lambda pair: -pair[1]))

    def functions(self) -> list[Type]:
        return [one for one in self.types if one.kind == "func"]

    def signature(self, name: str) -> str:
        """A function's signature, as far as BTF records it, which is names and types.

        BTF has no parameter names for most kernel functions, so an unnamed parameter comes out
        as its type alone. That is a limit of the file and not of this reader.
        """
        one = self.named("func", name)
        proto = self.get(one.type_id)
        args = []
        for param in proto.params:
            rendered = self.type_name(param.type_id)
            if not param.name:
                args.append(rendered)
            else:
                joiner = "" if rendered.endswith("*") else " "
                args.append(f"{rendered}{joiner}{param.name}")
        linkage = FUNC_LINKAGE.get(one.linkage or 0, "")
        prefix = "static " if linkage == "static" else ""
        return f"{prefix}{self.type_name(proto.type_id)} {name}({', '.join(args) or 'void'})"


def parse(blob: bytes, *, pointer_size: int = 8, source: str = "<bytes>") -> Btf:
    """Parse a whole BTF blob.

    Everything is read up front rather than lazily. Lazy parsing would be faster to open and
    would put the cost of a mistake at the point where a lesson prints a table, which is the worst
    place for it. A vmlinux blob takes a couple of seconds here and then every question is fast.
    """
    header = read_header(blob)
    order = "<" if header.little_endian else ">"

    start = header.types_at
    end = start + header.type_length
    strings_at = header.strings_at
    if end > len(blob) or strings_at + header.string_length > len(blob):
        raise BtfError("the header points past the end of the file, so this blob is truncated")

    strings = blob[strings_at : strings_at + header.string_length]
    types = [VOID]
    cursor = start
    while cursor < end:
        one, cursor = _read_type(blob, cursor, order, strings, len(types))
        types.append(one)

    return Btf(types, strings, pointer_size=pointer_size, source=source)


def parse_file(path: str | Path, *, pointer_size: int = 8) -> Btf:
    """Parse a file. `/sys/kernel/btf/vmlinux` on a live machine, or a blob from `corpora/`."""
    path = Path(path)
    return parse(path.read_bytes(), pointer_size=pointer_size, source=str(path))


def _string(strings: bytes, offset: int) -> str:
    """One name out of the string table. Offset 0 is the empty string, which means unnamed."""
    if offset == 0 or offset >= len(strings):
        return ""
    end = strings.find(b"\0", offset)
    raw = strings[offset:] if end < 0 else strings[offset:end]
    return raw.decode("utf-8", "replace")


def _read_type(
    blob: bytes, cursor: int, order: str, strings: bytes, type_id: int
) -> tuple[Type, int]:
    """Read one type record, and say where the next one starts.

    Every record begins the same way: a name, an info word, and a third word that is either a size
    or a reference to another type depending on the kind. What comes after that is the kind's
    business, and the table in `format` says how much of it there is.
    """
    name_off, info, size_type = struct.unpack_from(order + "III", blob, cursor)
    cursor += 12

    vlen = info & 0xFFFF
    kind_number = (info >> 24) & 0x1F
    kind_flag = bool(info & (1 << 31))
    kind = KINDS.get(kind_number)
    if kind is None:
        raise BtfError(f"type {type_id} has kind {kind_number}, which this reader does not know")

    name = _string(strings, name_off)
    sized = kind in SIZED
    fields: dict = {
        "id": type_id,
        "kind": kind,
        "name": name,
        "vlen": vlen,
        "kind_flag": kind_flag,
        "size": size_type if sized else None,
        "type_id": None if sized else size_type,
    }

    if kind == "int":
        (word,) = struct.unpack_from(order + "I", blob, cursor)
        fields["encoding"] = (word >> 24) & 0x0F
        fields["bit_offset"] = (word >> 16) & 0xFF
        fields["bits"] = word & 0xFF
    elif kind == "array":
        element, index, nelems = struct.unpack_from(order + "III", blob, cursor)
        fields["element_type"] = element
        fields["index_type"] = index
        fields["nelems"] = nelems
        fields["type_id"] = element
    elif kind in ("struct", "union"):
        members = []
        for index in range(vlen):
            member_name, member_type, offset = struct.unpack_from(
                order + "III", blob, cursor + index * 12
            )
            # kind_flag on a struct means the offset word carries a bitfield width in its top
            # byte. Without the flag the whole word is a bit offset and there is no width here.
            bit_offset = offset & 0xFFFFFF if kind_flag else offset
            width = (offset >> 24) & 0xFF if kind_flag else 0
            members.append(Member(_string(strings, member_name), member_type, bit_offset, width))
        fields["members"] = tuple(members)
    elif kind == "enum":
        values = []
        for index in range(vlen):
            value_name, value = struct.unpack_from(order + "Ii", blob, cursor + index * 8)
            values.append(EnumValue(_string(strings, value_name), value))
        fields["values"] = tuple(values)
    elif kind == "enum64":
        values = []
        for index in range(vlen):
            value_name, low, high = struct.unpack_from(order + "III", blob, cursor + index * 12)
            values.append(EnumValue(_string(strings, value_name), (high << 32) | low))
        fields["values"] = tuple(values)
    elif kind == "func_proto":
        params = []
        for index in range(vlen):
            param_name, param_type = struct.unpack_from(order + "II", blob, cursor + index * 8)
            params.append(Param(_string(strings, param_name), param_type))
        fields["params"] = tuple(params)
    elif kind == "datasec":
        variables = []
        for index in range(vlen):
            var_type, offset, var_size = struct.unpack_from(
                order + "III", blob, cursor + index * 12
            )
            variables.append(SecInfo(var_type, offset, var_size))
        fields["variables"] = tuple(variables)
        fields["size"] = size_type
        fields["type_id"] = None
    elif kind == "var":
        (linkage,) = struct.unpack_from(order + "I", blob, cursor)
        fields["linkage"] = linkage
    elif kind == "decl_tag":
        (component,) = struct.unpack_from(order + "i", blob, cursor)
        fields["component_idx"] = component
    elif kind == "func":
        # A function stores its linkage in vlen, which is the one place the format reuses that
        # field for something that is not a count.
        fields["linkage"] = vlen

    return Type(**fields), cursor + _tail_length(kind, vlen)


def _tail_length(kind: str, vlen: int) -> int:
    if kind in FIXED_TAIL:
        return FIXED_TAIL[kind]
    if kind in REPEATED_TAIL:
        return REPEATED_TAIL[kind] * vlen
    return 0
