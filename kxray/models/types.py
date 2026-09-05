"""What the kernel knows about its own types.

Parsed by `kxray.btf`, rendered by `kxwidgets` and by the generated sections of a blueprint.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Member:
    """One field of a struct or a union, as BTF records it.

    The offset is in bits and not in bytes, because a bitfield does not start on a byte boundary
    and the format refuses to pretend otherwise.
    """

    name: str
    type_id: int
    bit_offset: int
    bitfield_size: int = 0  # 0 means this field is not a bitfield

    @property
    def byte_offset(self) -> int:
        return self.bit_offset // 8

    @property
    def is_bitfield(self) -> bool:
        return self.bitfield_size > 0


@dataclass(frozen=True)
class EnumValue:
    name: str
    value: int


@dataclass(frozen=True)
class Param:
    """One parameter of a function prototype. An empty name is a parameter nobody named."""

    name: str
    type_id: int


@dataclass(frozen=True)
class SecInfo:
    """Where one variable sits inside a section, from a datasec record."""

    type_id: int
    offset: int
    size: int


@dataclass(frozen=True)
class Type:
    """One entry in the type section.

    One dataclass for all nineteen kinds rather than nineteen classes. A reader looking at a
    struct should not have to know a class hierarchy to ask what its fields are, and the fields
    that do not apply to a kind are simply empty.
    """

    id: int
    kind: str
    name: str = ""
    size: int | None = None  # bytes, for the kinds that have a size
    type_id: int | None = None  # what this refers to, for the kinds that refer to something
    vlen: int = 0
    kind_flag: bool = False
    members: tuple[Member, ...] = ()
    values: tuple[EnumValue, ...] = ()
    params: tuple[Param, ...] = ()
    variables: tuple[SecInfo, ...] = ()
    element_type: int | None = None  # array element
    index_type: int | None = None  # array index, which is always an int in practice
    nelems: int | None = None
    encoding: int = 0  # int only: signed, char and bool bits
    bits: int | None = None  # int only: how many bits are actually used
    bit_offset: int = 0  # int only, and only for the old way of writing a bitfield
    linkage: int | None = None  # func and var only
    component_idx: int | None = None  # decl_tag only

    @property
    def is_composite(self) -> bool:
        return self.kind in ("struct", "union")

    def __str__(self) -> str:
        named = f" {self.name}" if self.name else ""
        return f"[{self.id}] {self.kind}{named}"


@dataclass(frozen=True)
class Field:
    """One field of a struct after flattening, with the answer a lesson actually wants.

    `path` is what you would type in C to reach it, so an anonymous struct in the middle
    contributes nothing to it, which is exactly how C behaves.
    """

    path: str
    type_name: str
    byte_offset: int
    bit_offset: int
    size: int | None
    bitfield_size: int = 0
    tags: tuple[str, ...] = ()  # user, rcu, percpu: who is allowed to follow this pointer

    @property
    def is_bitfield(self) -> bool:
        return self.bitfield_size > 0

    @property
    def is_annotated(self) -> bool:
        """Whether this field carries an annotation about how it may be reached.

        An annotation changes no offset and no size, so it never shows up in the arithmetic. It
        is the difference between a pointer you may dereference and one that will corrupt memory
        or crash the machine if you do.
        """
        return bool(self.tags)

    @property
    def end(self) -> int | None:
        """The first byte after this field, or None when the size is unknown."""
        return None if self.size is None else self.byte_offset + self.size


@dataclass(frozen=True)
class Hole:
    """Padding between two fields. The reason anyone runs pahole in the first place."""

    after: str
    byte_offset: int
    size: int


@dataclass
class Layout:
    """What a struct looks like in memory, for one architecture.

    The architecture matters and is not in the file. BTF records no pointer size at all, so the
    same blob describes a different memory layout on a 32-bit machine than on a 64-bit one. That
    is why `pointer_size` is recorded here and printed with the table.
    """

    name: str
    size: int | None
    pointer_size: int
    fields: list[Field] = field(default_factory=list)
    holes: list[Hole] = field(default_factory=list)

    @property
    def padding(self) -> int:
        return sum(hole.size for hole in self.holes)

    def offset_of(self, path: str) -> int:
        for one in self.fields:
            if one.path == path:
                return one.byte_offset
        raise KeyError(f"{self.name} has no field called {path!r}")

    def table(self) -> str:
        """The layout as a table, holes included, in the order the bytes are laid out."""
        rows = [("offset", "size", "field", "type")]
        for one in self.fields:
            size = "?" if one.size is None else str(one.size)
            if one.is_bitfield:
                size = f"{one.bitfield_size} bits"
            rows.append((str(one.byte_offset), size, one.path, one.type_name))
        widths = [max(len(row[i]) for row in rows) for i in range(4)]
        out = []
        for index, row in enumerate(rows):
            out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
            if index == 0:
                out.append("  ".join("-" * width for width in widths))
        for hole in self.holes:
            out.append(f"{hole.size} byte hole at offset {hole.byte_offset}, after {hole.after}")
        return "\n".join(out)


@dataclass(frozen=True)
class Slot:
    """One function pointer in an ops table.

    `filled_by` is the name of the function that is actually in the slot. It stays None until
    somebody reads a real instance out of a real kernel, because what a function pointer holds is
    a fact about a running machine and not about a type. The type only says what shape it has to
    be.
    """

    name: str
    signature: str
    byte_offset: int
    filled_by: str | None = None

    @property
    def filled(self) -> bool:
        return self.filled_by is not None


@dataclass
class OpsTable:
    """A struct of function pointers, which is how the kernel does polymorphism.

    There is no `class` in C and no vtable the compiler makes for you, so the kernel writes one by
    hand: a struct full of function pointers, one instance per implementation, and a pointer to
    the instance hanging off the object. `file_operations`, `inode_operations` and `net_device_ops`
    are all this. Learn to read one and a large part of the kernel stops being a mystery.

    `instance` is the name of the particular one being looked at, such as `ext4_file_operations`.
    It is None when what is being looked at is the interface rather than an implementation of it.
    """

    name: str
    slots: list[Slot] = field(default_factory=list)
    data_fields: list[Field] = field(default_factory=list)
    size: int | None = None
    instance: str | None = None

    @property
    def filled(self) -> list[Slot]:
        return [one for one in self.slots if one.filled]

    def slot(self, name: str) -> Slot:
        for one in self.slots:
            if one.name == name:
                return one
        raise KeyError(f"{self.name} has no slot called {name!r}")

    def with_implementations(self, filled: dict[str, str]) -> OpsTable:
        """The same table with the slots filled in, for when you know what is in the instance.

        Returns a new table rather than changing this one, so the interface and an implementation
        of it can sit side by side without one quietly overwriting the other.
        """
        unknown = sorted(set(filled) - {one.name for one in self.slots})
        if unknown:
            raise KeyError(f"{self.name} has no slot called {unknown[0]!r}")
        slots = [
            Slot(one.name, one.signature, one.byte_offset, filled.get(one.name, one.filled_by))
            for one in self.slots
        ]
        return OpsTable(self.name, slots, self.data_fields, self.size, self.instance)

    def table(self) -> str:
        rows = [("offset", "slot", "filled by")]
        for one in self.slots:
            rows.append((str(one.byte_offset), one.name, one.filled_by or "nothing yet"))
        widths = [max(len(row[i]) for row in rows) for i in range(3)]
        out = []
        for index, row in enumerate(rows):
            out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
            if index == 0:
                out.append("  ".join("-" * width for width in widths))
        out.append("")
        out.extend(one.signature for one in self.slots)
        return "\n".join(out)
