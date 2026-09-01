"""The path from a system call to a line of text you can read.

Drawn for Z02, where the reader has not seen any of this before. It leaves out almost everything,
including the tracepoint layer, the buffer sizing and the reader side locking, because the job of
the first diagram in a book is to make the next paragraph readable.
"""

from kxdraw import Scene

ALT = (
    "A flow diagram running down the page. On the left, a box holding three file names: "
    "current_tracer, set_graph_function and tracing_on, described as three files written with "
    "echo, with an arrow into the middle of the flow labelled you set these first. Down the "
    "middle, five stages joined by arrows: your program calls write, the kernel runs ksys_write "
    "and vfs_write, ftrace records every call and every return, a dashed group holding one ring "
    "buffer for CPU 0 and one for CPU 1, and finally the file at slash sys slash kernel slash "
    "tracing slash trace, reached by an arrow labelled cat."
)


def scene() -> Scene:
    s = Scene("How one line of trace output gets made", width=980, height=660)

    s.note(40, 46, "How one line of trace output gets made", font_size=20)

    controls = s.box(
        40,
        180,
        250,
        120,
        "current_tracer\nset_graph_function\ntracing_on",
        style="muted",
        mono=True,
        font_size=15,
    )
    s.note(40, 326, "three files, written with echo", font_size=13, muted=True)

    program = s.box(360, 90, 280, 64, "your program calls write()", style="accent")
    kernel = s.box(360, 190, 280, 64, "the kernel runs\nksys_write, vfs_write, ...", font_size=15)
    ftrace = s.box(360, 290, 280, 66, "ftrace records\nevery call and every return", font_size=15)

    buffers = s.box(330, 396, 340, 90, style="muted", dashed=True)
    s.box(346, 412, 150, 58, "CPU 0\nring buffer", font_size=13)
    s.box(504, 412, 150, 58, "CPU 1\nring buffer", font_size=13)

    trace_file = s.box(
        360, 530, 280, 64, "/sys/kernel/tracing/trace", style="muted", mono=True, font_size=14
    )

    s.arrow(program, kernel)
    s.arrow(kernel, ftrace, label="patched call sites")
    s.arrow(controls, ftrace, label="you set these first")
    s.arrow(ftrace, buffers)
    s.arrow(buffers, trace_file, label="cat")

    s.note(700, 424, "one buffer per CPU,", font_size=13, muted=True)
    s.note(700, 444, "so the trace interleaves", font_size=13, muted=True)

    s.note(
        40,
        624,
        "The buffer is a ring. Fill it and the oldest lines go, without a word to anybody.",
        font_size=13,
        muted=True,
    )
    return s
