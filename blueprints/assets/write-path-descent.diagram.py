"""Where one byte goes when a program writes it, and where it stops.

The thing most people get wrong about `write` is not any single step. It is the ending. The system
call returns as soon as the byte is sitting in a folio in the page cache with a dirty flag on it,
and nothing has gone near a disk. Everything after that is somebody else's mechanism running later.

So the picture is a descent with a hard line across it. Above the line is what the system call
does. Below it is what happens afterwards, on a different thread, at a time nothing in the write
path chooses.

This is the picture for the blueprint's section 3. The numbered steps there are the same descent in
words, with the citations attached.
"""

from kxdraw import Scene

ALT = (
    "A descent down the left side of the picture, from the write system call to a dirty folio in "
    "the page cache, with a note on the right of each step saying what it decides. From the top: "
    "the write system call looks up the file descriptor; vfs_write checks the file is open for "
    "writing and asks the security modules; the file operations table is consulted, and a box off "
    "to the side notes that a file with a write_iter but no write is wrapped in a kiocb and an "
    "iov_iter, which is nearly every file; the filesystem's write_iter takes the inode lock, "
    "checks the size limits, drops setuid bits and updates the modification time; then "
    "generic_perform_write, whose three steps are drawn below it and repeat once per folio, which "
    "are write_begin to find or allocate the folio, an atomic copy of the bytes in from "
    "userspace, and write_end to mark it dirty and unlock it. Underneath is a red band across the "
    "whole width reading that the system call returns here and the byte is in memory with a dirty "
    "flag on it. Below that band, in grey, are the three things that happen later and on another "
    "thread: writeback finds the dirty folio, the filesystem builds block requests, and the device "
    "stores it. Notes at the bottom say that a write returning 1 has promised one byte is in the "
    "page cache and nothing more, and that fsync is what turns that into a promise about storage."
)


def scene() -> Scene:
    s = Scene("Where one byte goes", width=1140, height=940)

    s.note(40, 44, "Where one byte goes", font_size=20)
    s.note(
        40,
        70,
        "One write() of one byte, from the system call down to where it stops.",
        font_size=13,
        muted=True,
    )

    down = {"sides": ("bottom", "top")}

    syscall = s.box(40, 104, 480, 48, "write(fd, buf, 1)", style="accent", font_size=14)
    s.note(
        560,
        118,
        "the descriptor is looked up, and its position is the one thing locked here",
        font_size=13,
        muted=True,
    )

    vfs = s.box(
        40,
        176,
        480,
        56,
        "vfs_write\nopen for writing? address readable? security modules happy?",
        font_size=13,
    )
    s.note(
        560,
        190,
        "every refusal that does not need the filesystem happens here",
        font_size=13,
        muted=True,
    )

    dispatch = s.box(
        40, 256, 480, 48, "f_op->write, or wrap it and call f_op->write_iter", font_size=13
    )
    wrap = s.box(
        560,
        250,
        540,
        60,
        "nearly every file takes the second branch: a kiocb and an\niov_iter are built on the "
        "stack, and the byte is described\nrather than passed",
        style="muted",
        font_size=12,
    )

    fs = s.box(
        40,
        328,
        480,
        72,
        "the filesystem's write_iter\ntake the inode lock, check the limits,\ndrop setuid, update "
        "the modification time",
        font_size=13,
    )
    s.note(
        560,
        346,
        "the inode lock is why two writes to one file do not interleave",
        font_size=13,
        muted=True,
    )

    perform = s.box(40, 424, 480, 48, "generic_perform_write", style="accent", font_size=14)
    s.note(
        560,
        438,
        "the three steps below run once per folio, so a one byte write runs them once",
        font_size=13,
        muted=True,
    )

    begin = s.box(40, 496, 480, 40, "write_begin: find the folio, or allocate one", font_size=13)
    copy = s.box(40, 560, 480, 40, "copy the bytes in, without ever sleeping", font_size=13)
    s.note(
        560,
        574,
        "this copy cannot sleep, because a fault here could reach back into this filesystem",
        font_size=13,
        muted=True,
    )
    end = s.box(40, 624, 480, 40, "write_end: mark it dirty, unlock it", font_size=13)

    returned = s.box(
        40,
        700,
        1060,
        44,
        "the system call returns here, and the byte is in memory with a dirty flag on it",
        style="warn",
        font_size=14,
    )

    writeback = s.box(
        40, 776, 320, 44, "writeback finds the dirty folio", style="muted", font_size=12
    )
    blocks = s.box(
        410, 776, 320, 44, "the filesystem builds block requests", style="muted", font_size=12
    )
    device = s.box(780, 776, 320, 44, "the device stores it", style="muted", font_size=12)

    s.arrow(syscall, vfs, **down)
    s.arrow(vfs, dispatch, **down)
    s.arrow(dispatch, wrap, dashed=True)
    s.arrow(dispatch, fs, **down)
    s.arrow(fs, perform, **down)
    s.arrow(perform, begin, **down)
    s.arrow(begin, copy, **down)
    s.arrow(copy, end, **down)
    s.arrow(end, returned, **down)
    s.arrow(returned, writeback, dashed=True, sides=("bottom", "top"))
    s.arrow(writeback, blocks, dashed=True)
    s.arrow(blocks, device, dashed=True)

    s.note(
        40,
        856,
        "Everything in grey happens later, on another thread, at a time the write did not choose.",
        font_size=14,
    )
    s.note(
        40,
        880,
        "A write that returns 1 has promised that one byte is in the page cache. Nothing more.",
        font_size=14,
    )
    s.note(
        40,
        912,
        "fsync is what turns that into a promise about storage, and it is a separate mechanism "
        "with its own blueprint.",
        font_size=13,
        muted=True,
    )
    return s
