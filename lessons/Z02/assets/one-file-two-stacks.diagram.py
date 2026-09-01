"""One trace file, two call stacks, and why the indentation lies to you.

This is the still that carries the same point as the `cpu-interleave` animation. The animation
shows the lines arriving in the order the file has them and then splitting into lanes, which is
the part motion is genuinely good at. This one picture has to work on its own for a reader who
printed the page, and it is the version most people will see.
"""

from kxdraw import Scene

ALT = (
    "On the left, one file called slash sys slash kernel slash tracing slash trace, holding six "
    "lines in the order they appear. The lines alternate between two CPUs: CPU 0 enters "
    "vfs_write, CPU 1 enters handle_mm_fault, CPU 0 enters generic_perform_write, CPU 1 returns, "
    "CPU 0 returns, CPU 0 returns. An arrow labelled split by the CPU column leads right to two "
    "stacked boxes. The top box is CPU 0 and holds a call stack three deep: vfs_write, then "
    "generic_perform_write, then copy_page_from_iter_atomic. The bottom box is CPU 1 and holds a "
    "call stack one deep: handle_mm_fault. A note underneath says the indentation belongs to a "
    "CPU and not to the file."
)

FILE_LINES = [
    "0)               |  vfs_write() {",
    "1)               |    handle_mm_fault() {",
    "0)               |    generic_perform_write() {",
    "1)   2.104 us    |    }",
    "0)   0.318 us    |    }",
    "0) + 12.771 us   |  }",
]


def scene() -> Scene:
    s = Scene("One file, two call stacks", width=1000, height=560)

    s.note(40, 44, "One file, two call stacks", font_size=20)
    s.note(
        40,
        70,
        "The first column is the CPU. It is the only thing holding this apart.",
        font_size=13,
        muted=True,
    )

    trace = s.box(40, 110, 380, 210, "\n".join(FILE_LINES), style="muted", mono=True, font_size=13)
    s.note(40, 336, "/sys/kernel/tracing/trace", font_size=13, mono=True, muted=True)

    lane0 = s.box(
        560,
        110,
        400,
        94,
        "vfs_write\n  generic_perform_write\n    copy_page_from_iter_atomic",
        style="accent",
        mono=True,
        font_size=13,
    )
    s.note(560, 96, "CPU 0", font_size=13, muted=True)

    lane1 = s.box(560, 246, 400, 60, "handle_mm_fault", style="accent", mono=True, font_size=13)
    s.note(560, 232, "CPU 1", font_size=13, muted=True)

    s.arrow(trace, lane0, label="split by the CPU column")
    s.arrow(trace, lane1)

    s.note(
        40,
        400,
        "Read the file top to bottom and vfs_write looks like it called handle_mm_fault.",
        font_size=14,
    )
    s.note(
        40,
        424,
        "It did not. They ran at the same time on two CPUs, and the file interleaved them.",
        font_size=14,
    )
    s.note(
        40,
        470,
        "The indentation belongs to a CPU, not to the file. One stack per CPU, always.",
        font_size=13,
        muted=True,
    )
    s.note(
        40,
        494,
        "Tier 0 cannot show you this. v86 is uniprocessor, so every line in it says 0.",
        font_size=13,
        muted=True,
    )
    return s
