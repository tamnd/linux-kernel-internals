"""Build `tiny.btf`, the small BTF blob the reader is tested against.

Run it from the top of the repository:

    python3 corpora/btf/handwritten/make.py

There is no kernel here yet, so there is no real `/sys/kernel/btf/vmlinux` to read. This writes a
blob by hand instead, small enough that a reader can hold all of it in their head, and wide enough
that every kind in the format appears at least once.

The structs in it are made up and named so that nobody mistakes them for kernel structs. The
offsets are the ones a 64-bit compiler would pick for the fields as written, holes included,
because a layout with no padding in it teaches nobody anything about padding.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from kxray.btf import writer  # noqa: E402

HERE = Path(__file__).resolve().parent


def build() -> bytes:
    b = writer.Builder()

    char = b.int_("char", 1, char=True)
    u8 = b.int_("unsigned char", 1, signed=False)
    u32 = b.int_("unsigned int", 4, signed=False)
    i32 = b.int_("int", 4)
    i64 = b.int_("long long", 8)
    boolean = b.int_("_Bool", 1, signed=False, boolean=True)
    double = b.float_("double", 8)

    pid_t = b.typedef("demo_pid_t", i32)
    comm = b.array(char, 16)
    bytes8 = b.array(char, 8)

    state = b.enum("demo_state", [("DEMO_RUNNING", 0), ("DEMO_SLEEPING", 1), ("DEMO_DEAD", 2)])
    # Nothing uses this one. It is here so that a kind almost no reader has ever seen is still in
    # the fixture, because the ones nobody thinks about are the ones that break.
    b.enum64("demo_wide", [("DEMO_LOW", 1), ("DEMO_HIGH", 1 << 40)])

    # Three bitfields packed into one byte, with the width in the member record, which is the
    # encoding pahole writes today.
    flags = b.struct(
        "demo_flags",
        1,
        [("on_rq", u8, 0, 1), ("in_iowait", u8, 1, 1), ("prio", u8, 2, 6)],
    )

    forward = b.fwd("demo_mm")
    mm_ptr = b.ptr(forward)
    void_ptr = b.ptr(0)

    task = b.fwd("demo_task")
    task_ptr = b.ptr(task)

    # A pointer the kernel would annotate as user memory. The tag rides on the type and changes
    # nothing about the layout, which is the point of it.
    user_ptr = b.ptr(b.type_tag("user", char))

    value = b.union(
        "demo_value",
        8,
        [("as_int", i64, 0), ("as_ptr", void_ptr, 0), ("as_bytes", bytes8, 0)],
    )

    # Sixty four bytes, with a six byte hole in the middle of it. The hole is there on purpose,
    # because `flags` and `waiting` are one byte each and `weight` has to start on an eight byte
    # boundary. Finding it is the exercise.
    demo_task = b.struct(
        "demo_task",
        64,
        [
            ("pid", pid_t, 0 * 8),
            ("state", state, 4 * 8),
            ("comm", comm, 8 * 8),
            ("mm", mm_ptr, 24 * 8),
            ("parent", task_ptr, 32 * 8),
            ("value", value, 40 * 8),
            ("flags", flags, 48 * 8),
            ("waiting", boolean, 49 * 8),
            ("weight", double, 56 * 8),
        ],
    )

    # A struct that holds another struct by value, so flattening has something to flatten.
    b.struct("demo_pair", 128, [("first", demo_task, 0), ("second", demo_task, 64 * 8)])

    # Sixteen bytes with four of them padding at the end, because the struct has to be a multiple
    # of its widest member. A trailing hole is the one people miss.
    b.struct("demo_arg", 16, [("name", user_ptr, 0), ("len", u32, 8 * 8)])

    # An ops table: a struct of function pointers with one field in the middle that is not one.
    # Real ops tables all look like this, and the field that is not an operation is there because
    # a reader has to see that the tool picks the slots out rather than listing every member.
    b.struct(
        "demo_ops",
        32,
        [
            ("owner", void_ptr, 0 * 8),
            ("open", b.ptr(b.func_proto(i32, [("task", task_ptr)])), 8 * 8),
            (
                "write",
                b.ptr(b.func_proto(i64, [("task", task_ptr), ("buf", user_ptr), ("len", u32)])),
                16 * 8,
            ),
            ("release", b.ptr(b.func_proto(0, [("task", task_ptr)])), 24 * 8),
        ],
    )

    opened = b.func_proto(i32, [("task", task_ptr), ("", u32)])
    b.func("demo_open", opened)
    b.func("demo_close", b.func_proto(0, [("task", task_ptr)]), linkage=0)

    counter = b.var("demo_counter", b.const(u32))
    b.datasec(".data", 4, [(counter, 0, 4)])

    b.decl_tag("teaching-only", demo_task)

    return b.build()


def main() -> int:
    path = HERE / "tiny.btf"
    blob = build()
    if path.exists() and path.read_bytes() == blob:
        print(f"{path}: unchanged")
        return 0
    path.write_bytes(blob)
    print(f"wrote {path}, {len(blob)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
