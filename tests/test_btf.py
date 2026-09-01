"""Tests for the BTF reader.

Two halves. The first builds small blobs with the writer and reads them back, which is where the
format details get pinned down one at a time. The second reads the committed fixture and checks
the numbers its `.meta.toml` promises, which is what catches a change to the writer that quietly
changes the file everybody else is testing against.
"""

from __future__ import annotations

import importlib.util
import struct
import tomllib
from pathlib import Path

import pytest

from kxray import btf
from kxray.btf import writer
from kxray.btf.format import BtfError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "corpora" / "btf" / "handwritten" / "tiny.btf"
META = FIXTURE.with_suffix(".meta.toml")
MAKE = FIXTURE.parent / "make.py"


@pytest.fixture(scope="module")
def tiny():
    return btf.parse_file(FIXTURE)


@pytest.fixture(scope="module")
def meta():
    return tomllib.loads(META.read_text(encoding="utf-8"))


def small() -> tuple[bytes, dict[str, int]]:
    """A blob with the handful of types most of these tests need."""
    b = writer.Builder()
    ids = {}
    ids["u32"] = b.int_("unsigned int", 4, signed=False)
    ids["i32"] = b.int_("int", 4)
    ids["char"] = b.int_("char", 1, char=True)
    ids["pid_t"] = b.typedef("pid_t", ids["i32"])
    ids["name"] = b.array(ids["char"], 16)
    ids["point"] = b.struct("point", 8, [("x", ids["u32"], 0), ("y", ids["u32"], 32)])
    ids["ptr"] = b.ptr(ids["point"])
    return b.build(), ids


# -- the format ------------------------------------------------------------------------------


def test_a_blob_that_is_not_btf_says_so():
    with pytest.raises(BtfError, match="magic"):
        btf.parse(b"\x7fELF" + bytes(64))


def test_a_blob_too_short_to_have_a_header_says_so():
    with pytest.raises(BtfError, match="not long enough"):
        btf.parse(b"\x9f\xeb\x01\x00")


def test_a_version_we_do_not_know_says_so():
    blob = bytearray(small()[0])
    blob[2] = 9
    with pytest.raises(BtfError, match="version 9"):
        btf.parse(bytes(blob))


def test_a_header_pointing_past_the_end_says_truncated():
    blob = bytearray(small()[0])
    struct.pack_into("<I", blob, 12, 1 << 20)  # type_length
    with pytest.raises(BtfError, match="truncated"):
        btf.parse(bytes(blob))


def test_endianness_comes_from_the_magic_number():
    """The magic is the only signal there is, and reading it backwards gives nonsense not an error.

    This checks the decision, not a whole big endian parse. The writer only writes little endian,
    so there is nothing here to read the other way round yet, and pretending otherwise would be a
    test that passes without testing anything.
    """
    blob, _ = small()
    header = btf.read_header(blob)
    assert header.little_endian is True
    swapped = bytearray(blob)
    swapped[0:2] = blob[1::-1]
    assert btf.read_header(bytes(swapped)).little_endian is False


def test_type_zero_is_void():
    parsed = btf.parse(small()[0])
    assert parsed.get(0).kind == "void"
    assert parsed.size_of(0) == 0


def test_a_reference_that_points_nowhere_is_void_and_not_a_crash():
    parsed = btf.parse(small()[0])
    assert parsed.get(9999).kind == "void"
    assert parsed.get(None).kind == "void"


# -- reading types ---------------------------------------------------------------------------


def test_an_int_records_what_it_is():
    blob, ids = small()
    parsed = btf.parse(blob)
    assert "unsigned" in parsed.int_description(ids["u32"])
    assert "signed" in parsed.int_description(ids["i32"])
    assert "char" in parsed.int_description(ids["char"])


def test_resolve_walks_through_a_typedef():
    blob, ids = small()
    parsed = btf.parse(blob)
    assert parsed.get(ids["pid_t"]).kind == "typedef"
    assert parsed.resolve(ids["pid_t"]).name == "int"
    assert parsed.size_of(ids["pid_t"]) == 4


def test_resolve_walks_through_const_and_volatile():
    b = writer.Builder()
    i32 = b.int_("int", 4)
    wrapped = b.volatile(b.const(b.typedef("counter", i32)))
    parsed = btf.parse(b.build())
    assert parsed.resolve(wrapped).name == "int"
    assert parsed.size_of(wrapped) == 4


def test_a_typedef_that_refers_to_itself_is_an_error_and_not_a_hang():
    b = writer.Builder()
    b.typedef("loop", 1)  # type 1 is itself
    parsed = btf.parse(b.build())
    with pytest.raises(BtfError, match="itself"):
        parsed.resolve(1)


def test_an_array_knows_how_big_it_is():
    blob, ids = small()
    parsed = btf.parse(blob)
    assert parsed.size_of(ids["name"]) == 16
    assert parsed.type_name(ids["name"]) == "char[16]"


def test_a_pointer_has_no_size_in_the_file_so_the_reader_is_told_one():
    """The one thing BTF does not record. The same blob is two layouts on two architectures."""
    blob, ids = small()
    assert btf.parse(blob).size_of(ids["ptr"]) == 8
    assert btf.parse(blob, pointer_size=4).size_of(ids["ptr"]) == 4


def test_an_enum_keeps_its_values():
    b = writer.Builder()
    b.enum("state", [("RUNNING", 0), ("DEAD", -1)])
    parsed = btf.parse(b.build())
    assert [(v.name, v.value) for v in parsed.named("enum", "state").values] == [
        ("RUNNING", 0),
        ("DEAD", -1),
    ]


def test_an_enum64_keeps_a_value_that_does_not_fit_in_32_bits():
    b = writer.Builder()
    b.enum64("wide", [("BIG", 1 << 40)])
    parsed = btf.parse(b.build())
    assert parsed.named("enum64", "wide").values[0].value == 1 << 40


def test_a_forward_declaration_says_which_kind_it_is():
    b = writer.Builder()
    a_struct = b.fwd("thing")
    a_union = b.fwd("other", union=True)
    parsed = btf.parse(b.build())
    assert parsed.type_name(a_struct) == "struct thing"
    assert parsed.type_name(a_union) == "union other"


def test_a_type_tag_changes_the_name_and_not_the_layout():
    b = writer.Builder()
    char = b.int_("char", 1, char=True)
    tagged = b.ptr(b.type_tag("user", char))
    parsed = btf.parse(b.build())
    assert parsed.type_name(tagged) == "char __user *"
    assert parsed.size_of(tagged) == 8


def test_find_returns_every_type_with_a_name_because_there_can_be_two():
    b = writer.Builder()
    b.struct("thing", 4, [])
    b.struct("thing", 8, [])
    parsed = btf.parse(b.build())
    assert [t.size for t in parsed.find("thing")] == [4, 8]


def test_asking_for_a_type_that_is_not_there_names_what_was_asked_for():
    parsed = btf.parse(small()[0])
    with pytest.raises(KeyError, match="nothing_like_this"):
        parsed.struct("nothing_like_this")


# -- what a struct looks like ---------------------------------------------------------------


def test_a_layout_gives_the_offset_of_every_field():
    parsed = btf.parse(small()[0])
    layout = parsed.layout("point")
    assert [(f.path, f.byte_offset) for f in layout.fields] == [("x", 0), ("y", 4)]
    assert layout.offset_of("y") == 4


def test_asking_for_a_field_that_is_not_there_names_the_struct():
    parsed = btf.parse(small()[0])
    with pytest.raises(KeyError, match="point"):
        parsed.layout("point").offset_of("z")


def test_a_hole_is_found_and_named_after_the_field_before_it():
    b = writer.Builder()
    u8 = b.int_("unsigned char", 1, signed=False)
    i64 = b.int_("long long", 8)
    b.struct("gappy", 16, [("small", u8, 0), ("big", i64, 8 * 8)])
    layout = btf.parse(b.build()).layout("gappy")
    assert layout.padding == 7
    assert layout.holes[0].after == "small"
    assert layout.holes[0].byte_offset == 1


def test_padding_at_the_end_counts_as_a_hole():
    b = writer.Builder()
    u32 = b.int_("unsigned int", 4, signed=False)
    u8 = b.int_("unsigned char", 1, signed=False)
    b.struct("tail", 8, [("a", u32, 0), ("b", u8, 4 * 8)])
    assert btf.parse(b.build()).layout("tail").padding == 3


def test_a_union_has_no_holes_because_everything_is_at_zero():
    b = writer.Builder()
    u8 = b.int_("unsigned char", 1, signed=False)
    i64 = b.int_("long long", 8)
    b.union("either", 8, [("small", u8, 0), ("big", i64, 0)])
    layout = btf.parse(b.build()).layout("either")
    assert layout.holes == []
    assert [f.byte_offset for f in layout.fields] == [0, 0]


def test_a_bitfield_written_the_modern_way_keeps_its_width():
    b = writer.Builder()
    u8 = b.int_("unsigned char", 1, signed=False)
    b.struct("bits", 1, [("on", u8, 0, 1), ("rest", u8, 1, 7)])
    layout = btf.parse(b.build()).layout("bits")
    assert [(f.path, f.bit_offset, f.bitfield_size) for f in layout.fields] == [
        ("on", 0, 1),
        ("rest", 1, 7),
    ]


def test_a_bitfield_written_the_old_way_is_still_a_bitfield():
    """The older encoding narrows the int type instead of marking the member.

    Reading only the modern encoding reports a one bit flag as a four byte field, which is a
    wrong answer that looks entirely reasonable in a table.
    """
    b = writer.Builder()
    narrow = b.int_("unsigned int", 4, bits=1, signed=False)
    b.struct("old", 4, [("on", narrow, 0)])
    layout = btf.parse(b.build()).layout("old")
    assert layout.fields[0].bitfield_size == 1
    assert layout.fields[0].is_bitfield


def test_an_anonymous_union_is_flattened_the_way_c_flattens_it():
    b = writer.Builder()
    u32 = b.int_("unsigned int", 4, signed=False)
    i64 = b.int_("long long", 8)
    inner = b.union("", 8, [("as_int", i64, 0), ("as_pair", u32, 0)])
    b.struct("outer", 16, [("tag", u32, 0), ("", inner, 8 * 8)])
    layout = btf.parse(b.build()).layout("outer")
    assert [f.path for f in layout.fields] == ["tag", "as_int", "as_pair"]
    assert layout.offset_of("as_int") == 8


def test_flatten_off_shows_only_what_the_struct_declares():
    b = writer.Builder()
    u32 = b.int_("unsigned int", 4, signed=False)
    inner = b.struct("inner", 4, [("value", u32, 0)])
    b.struct("outer", 8, [("head", u32, 0), ("body", inner, 32)])
    parsed = btf.parse(b.build())
    assert [f.path for f in parsed.layout("outer", flatten=False).fields] == ["head", "body"]
    assert [f.path for f in parsed.layout("outer").fields] == ["head", "body", "body.value"]


def test_offset_of_takes_a_dotted_path():
    b = writer.Builder()
    u32 = b.int_("unsigned int", 4, signed=False)
    inner = b.struct("inner", 8, [("first", u32, 0), ("second", u32, 32)])
    b.struct("outer", 16, [("head", u32, 0), ("body", inner, 8 * 8)])
    parsed = btf.parse(b.build())
    assert parsed.offset_of("outer.body.second") == 12
    with pytest.raises(KeyError, match="names a struct"):
        parsed.offset_of("outer")


def test_a_layout_table_says_which_pointer_size_it_used():
    blob, _ = small()
    assert btf.parse(blob, pointer_size=4).layout("point").pointer_size == 4


# -- functions -------------------------------------------------------------------------------


def test_a_function_signature_reads_like_c():
    b = writer.Builder()
    i32 = b.int_("int", 4)
    u32 = b.int_("unsigned int", 4, signed=False)
    b.func("count", b.func_proto(i32, [("how_many", u32)]))
    assert btf.parse(b.build()).signature("count") == "int count(unsigned int how_many)"


def test_a_function_with_no_parameters_says_void():
    b = writer.Builder()
    b.func("nothing", b.func_proto(0, []))
    assert btf.parse(b.build()).signature("nothing") == "void nothing(void)"


def test_a_static_function_says_static():
    b = writer.Builder()
    i32 = b.int_("int", 4)
    b.func("hidden", b.func_proto(i32, []), linkage=0)
    assert btf.parse(b.build()).signature("hidden").startswith("static ")


def test_a_parameter_with_no_name_comes_out_as_its_type_alone():
    """Most kernel functions have no parameter names in BTF. That is the file, not the reader."""
    b = writer.Builder()
    i32 = b.int_("int", 4)
    b.func("unnamed", b.func_proto(i32, [("", i32)]))
    assert btf.parse(b.build()).signature("unnamed") == "int unnamed(int)"


# -- ops tables ------------------------------------------------------------------------------


def ops_blob() -> bytes:
    """A struct with two function pointers and one field that is not one."""
    b = writer.Builder()
    i32 = b.int_("int", 4)
    u64 = b.int_("unsigned long long", 8)
    void_ptr = b.ptr(0)
    read = b.ptr(b.func_proto(i32, [("how_many", i32)]))
    write = b.ptr(b.func_proto(0, [("", i32)]))
    b.struct(
        "demo",
        32,
        [("owner", void_ptr, 0), ("read", read, 64), ("write", write, 128), ("flags", u64, 192)],
    )
    return b.build()


def test_the_slots_are_the_members_that_are_pointers_to_a_function():
    table = btf.parse(ops_blob()).ops("demo")
    assert [one.name for one in table.slots] == ["read", "write"]


def test_everything_that_is_not_a_slot_comes_back_as_data():
    """An ops table with a flags word in it is normal, and the flags word is not an operation."""
    table = btf.parse(ops_blob()).ops("demo")
    assert [one.path for one in table.data_fields] == ["owner", "flags"]


def test_a_pointer_to_something_that_is_not_a_function_is_not_a_slot():
    table = btf.parse(ops_blob()).ops("demo")
    assert "owner" not in [one.name for one in table.slots]


def test_a_slot_knows_its_offset_and_its_signature():
    table = btf.parse(ops_blob()).ops("demo")
    read = table.slot("read")
    assert read.byte_offset == 8
    assert read.signature == "int (*read)(int how_many)"


def test_a_slot_with_nothing_in_it_says_so():
    table = btf.parse(ops_blob()).ops("demo")
    assert table.filled == []
    assert all(not one.filled for one in table.slots)


def test_filling_a_slot_leaves_the_original_alone():
    """The interface and one implementation of it have to be able to sit side by side."""
    table = btf.parse(ops_blob()).ops("demo")
    filled = table.with_implementations({"read": "demo_read"})
    assert filled.slot("read").filled_by == "demo_read"
    assert table.slot("read").filled_by is None


def test_filling_a_slot_that_does_not_exist_says_which_one():
    table = btf.parse(ops_blob()).ops("demo")
    with pytest.raises(KeyError, match="nonsense"):
        table.with_implementations({"nonsense": "whatever"})


def test_asking_for_a_slot_that_does_not_exist_says_which_one():
    table = btf.parse(ops_blob()).ops("demo")
    with pytest.raises(KeyError, match="nonsense"):
        table.slot("nonsense")


def test_an_ops_table_prints_its_slots_and_its_signatures():
    printed = btf.parse(ops_blob()).ops("demo").table()
    assert "read" in printed
    assert "nothing yet" in printed
    assert "int (*read)(int how_many)" in printed


def test_a_struct_with_no_function_pointers_has_no_slots():
    blob, _ = small()
    assert btf.parse(blob).ops("point").slots == []


# -- the committed fixture -------------------------------------------------------------------


def test_the_fixture_is_what_make_py_produces():
    """An edit to the writer that changes the fixture fails here, with the file name."""
    spec = importlib.util.spec_from_file_location("btf_fixture_make", MAKE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.build() == FIXTURE.read_bytes(), "run python3 corpora/btf/handwritten/make.py"


def test_the_fixture_is_not_evidence(meta):
    """The rule the whole project rests on. Nothing handwritten is allowed to verify a claim."""
    assert meta["evidence"] is False


def test_the_fixture_has_the_types_its_metadata_promises(tiny, meta):
    assert len(tiny.types) - 1 == meta["types"]
    assert tiny.kinds()["struct"] == meta["struct_count"]


def test_the_fixture_has_one_of_every_kind_that_matters(tiny):
    present = tiny.kinds()
    for kind in ("enum64", "type_tag", "decl_tag", "datasec", "var", "fwd", "float", "union"):
        assert kind in present, kind


def test_the_fixture_struct_is_the_size_and_the_shape_its_metadata_promises(tiny, meta):
    layout = tiny.layout("demo_task")
    assert layout.size == meta["demo_task_size"]
    assert layout.padding == meta["demo_task_padding"]
    assert tiny.layout("demo_arg").padding == meta["demo_arg_padding"]


def test_the_fixture_reads_the_same_on_a_32_bit_machine_except_for_the_pointers():
    """Same bytes, different layout, because the pointer size is not in the file."""
    wide = btf.parse_file(FIXTURE).layout("demo_arg")
    narrow = btf.parse_file(FIXTURE, pointer_size=4).layout("demo_arg")
    assert wide.fields[0].size == 8
    assert narrow.fields[0].size == 4


def test_the_fixture_has_an_ops_table_with_three_slots_and_one_field(tiny):
    """`demo_ops` is in the fixture so the ops reader has something shaped like a real one."""
    table = tiny.ops("demo_ops")
    assert [one.name for one in table.slots] == ["open", "write", "release"]
    assert [one.path for one in table.data_fields] == ["owner"]


def test_the_fixture_table_prints_offsets_and_holes(tiny):
    printed = tiny.layout("demo_task").table()
    assert "comm" in printed
    assert "char[16]" in printed
    assert "6 byte hole" in printed
