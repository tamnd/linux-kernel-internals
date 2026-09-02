"""One write system call, three destinations, three different pieces of kernel code.

The point of the picture is the fork in the middle. Everything above it is identical for all three
destinations, everything below it is different, and the thing that chose which way to go is a
pointer that was written into the file when it was opened.
"""

from kxdraw import Scene

ALT = (
    "At the top, one box labelled your program calling write of fd, one byte. An arrow leads down "
    "to a box labelled vfs_write in fs slash read_write dot c, with a line underneath reading it "
    "calls file arrow f underscore op arrow write underscore iter. Three arrows fan out from it, "
    "each labelled with the file that was opened. The left arrow, for a file on ext4, leads to a "
    "box holding ext4_file_operations and under it ext4_file_write_iter. The middle arrow, for a "
    "file on tmpfs, leads to a box holding shmem_file_operations and under it "
    "shmem_file_write_iter. The right arrow, for a pipe, leads to a box holding pipefifo_fops and "
    "under it pipe_write. A note at the bottom says the VFS chose the slot and the filesystem "
    "chose the code, and that nothing above the fork knows which of the three it is talking to."
)


def scene() -> Scene:
    s = Scene("One write, three tables", width=1040, height=600)

    s.note(40, 44, "One write, three tables", font_size=20)
    s.note(
        40,
        70,
        "The same system call, the same VFS code, three different implementations underneath.",
        font_size=13,
        muted=True,
    )

    call = 'write(fd, "x", 1)'
    program = s.box(400, 104, 260, 54, call, style="plain", mono=True, font_size=14)

    vfs = s.box(360, 200, 340, 76, "vfs_write()", style="accent", mono=True, font_size=15)
    s.note(
        360,
        292,
        "it calls file->f_op->write_iter, whatever that is",
        font_size=13,
        mono=True,
        muted=True,
    )

    s.arrow(program, vfs)

    ext4 = s.box(
        60,
        380,
        280,
        90,
        "ext4_file_operations\n\next4_file_write_iter",
        style="muted",
        mono=True,
        font_size=13,
    )
    tmpfs = s.box(
        380,
        380,
        280,
        90,
        "shmem_file_operations\n\nshmem_file_write_iter",
        style="muted",
        mono=True,
        font_size=13,
    )
    pipe = s.box(
        700,
        380,
        280,
        90,
        "pipefifo_fops\n\npipe_write",
        style="muted",
        mono=True,
        font_size=13,
    )

    s.arrow(vfs, ext4, label="opened on ext4")
    s.arrow(vfs, tmpfs, label="opened on tmpfs")
    s.arrow(vfs, pipe, label="a pipe")

    s.note(
        40,
        506,
        "The VFS picked the slot. The filesystem picked the code that is in it.",
        font_size=14,
    )
    s.note(
        40,
        530,
        "Nothing above the fork knows or cares which of the three it is talking to.",
        font_size=14,
    )
    s.note(
        40,
        566,
        "That is the whole mechanism. There is no switch on the file type anywhere in the VFS.",
        font_size=13,
        muted=True,
    )
    return s
