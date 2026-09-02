"""Three open files, one table, and where the per file state actually lives.

The trap this picture exists for is the idea that each open file gets its own set of operations.
It does not. The table is one constant object in read only memory and every file that uses that
filesystem points at the same one, which is why changing a slot is not a thing you can do per file
and why the per file state has to hang off the file instead.
"""

from kxdraw import Scene

ALT = (
    "On the left, three boxes stacked, each labelled struct file and each holding two fields: "
    "f_op and private_data. The first is fd 3 with private data pointing at its own ext4 state, "
    "the second is fd 7 with its own, the third is fd 12 with its own. Three arrows leave the f_op "
    "field of each box and meet at a single box on the right labelled const struct "
    "file_operations ext4_file_operations, marked read only data. That box lists five slots: "
    "read_iter, write_iter, open, release and one slot shown as empty. A note underneath says "
    "three files, one table, and that the per file state is in private_data rather than in the "
    "table, because the table is shared and constant."
)

FILES = [
    ("fd 3", 120),
    ("fd 7", 250),
    ("fd 12", 380),
]

SLOTS = [
    "read_iter   ext4_file_read_iter",
    "write_iter  ext4_file_write_iter",
    "open        ext4_file_open",
    "release     ext4_release_file",
    "get_unmapped_area   empty",
]


def scene() -> Scene:
    s = Scene("Three files, one table", width=1040, height=580)

    s.note(40, 44, "Three files, one table", font_size=20)
    s.note(
        40,
        70,
        "How many copies of the operations does a thousand open files need? One.",
        font_size=13,
        muted=True,
    )

    table = s.box(
        560,
        150,
        440,
        200,
        "const struct file_operations\next4_file_operations\n\n" + "\n".join(SLOTS),
        style="accent",
        mono=True,
        font_size=12,
    )
    s.note(560, 136, "read only data, one instance for the whole machine", font_size=12, muted=True)

    for label, top in FILES:
        box = s.box(
            60,
            top,
            360,
            88,
            f"struct file  ({label})\n  f_op          -->\n  private_data  its own",
            style="muted",
            mono=True,
            font_size=12,
        )
        s.arrow(box, table)

    s.note(
        40,
        500,
        "The table is shared and constant, so nothing about one file can live in it.",
        font_size=14,
    )
    s.note(
        40,
        524,
        "Everything that differs between two open files is in the file, usually private_data.",
        font_size=14,
    )
    s.note(
        40,
        556,
        "An empty slot is not a crash. The caller checks it and falls back or returns an error.",
        font_size=13,
        muted=True,
    )
    return s
