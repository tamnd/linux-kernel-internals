"""How a full trace buffer loses events, and why the trace file does not say so.

The picture people carry around is a queue that fills up and then refuses more work. This one does
not refuse anything. When the next page is the oldest page, the writer throws that page away, adds
its event count to a counter, moves the tail onto the space and carries on. Nothing waits, nothing
fails, and the caller is handed a perfectly good pointer.

The right hand side is the part that costs a debugging session. The same buffer read two ways
answers differently about whether it is complete, and the way most people read it is the way that
cannot tell them.
"""

from kxdraw import Scene

ALT = (
    "A picture in four parts, about how a full trace buffer loses events without saying so. "
    "Across the top, a ring of four boxes labelled sub buffer 0 to sub buffer 3, joined left to "
    "right by arrows with a dashed arrow wrapping from the last one back to the first. The first "
    "box is also labelled head, the oldest, the third is labelled tail, writing here now, and a "
    "separate box sits outside the ring labelled reader page, off the ring, with a note that the "
    "writer will never touch it. Underneath on the left, a column headed what one writer does, "
    "with three boxes reading down: read the tail page, read the two timestamps, and add my "
    "length to the write index with one atomic add. That last box forks. The left branch is "
    "labelled it fits and holds one box reading write the data and commit. The right branch is "
    "labelled it does not fit and holds three boxes in a red style reading the next page is the "
    "head, throw that whole page away and add its events to overrun, and move the tail onto it. A "
    "note beside the red branch says nothing waits, nothing fails, and no caller is told. On the "
    "lower left, a small table of the counters as the capture read them, with entries 273, "
    "overrun 44002, commit overrun 0 and dropped events 0, and a line under it reading 44275 "
    "events written, 99.4% of them thrown away, in 0.007 seconds. On the right, two columns "
    "headed the two ways to read a trace. The left column, trace_pipe, has boxes reading "
    "consuming read, take overrun minus last overrun, and print CPU:0 LOST 44002 EVENTS. The "
    "right column, the trace file, has boxes reading iterator read, ask for the iterator's missed "
    "events flag, and a red box reading the writer never sets that bit on an ordinary buffer, so "
    "nothing marks the body. An arrow leads from that red box to a wide box holding the header "
    "line of the trace file, entries-in-buffer slash entries-written 273 slash 44275. Across the "
    "bottom is a red band reading each way of reading a trace tells you half of what was lost, "
    "and under it a line saying trace_pipe says where and prints no header, while the trace file "
    "says how many, once, in a header a reader skips, and marks nothing in the body."
)


def scene() -> Scene:
    s = Scene("How a full ring buffer loses events", width=1240, height=1180)

    s.note(40, 44, "How a full ring buffer loses events", font_size=20)
    s.note(
        40,
        70,
        "The writer never blocks and never fails, so a full buffer is not an error. It is a "
        "silent deletion.",
        font_size=13,
        muted=True,
    )

    # -- the ring, across the top ----------------------------------------------------------------
    s.note(40, 118, "one buffer per processor, four sub buffers in this drawing", font_size=14)

    zero = s.box(
        40, 148, 200, 64, "sub buffer 0\nhead, the oldest", style="accent", font_size=13, mono=True
    )
    one = s.box(300, 148, 200, 64, "sub buffer 1", font_size=13, mono=True)
    two = s.box(
        560,
        148,
        200,
        64,
        "sub buffer 2\ntail, writing here now",
        style="accent",
        font_size=13,
        mono=True,
    )
    three = s.box(820, 148, 200, 64, "sub buffer 3", font_size=13, mono=True)
    s.box(1040, 148, 160, 64, "reader page\noff the ring", style="muted", font_size=13, mono=True)

    s.arrow(zero, one)
    s.arrow(one, two)
    s.arrow(two, three)
    s.arrow(three, zero, label="the ring wraps", dashed=True, sides=("bottom", "bottom"))

    s.note(1040, 226, "the writer will never\ntouch this one", font_size=12, muted=True)

    # -- what one writer does, on the left --------------------------------------------------------
    s.note(40, 300, "what one writer does, on any processor, in any context", font_size=14)

    tail = s.box(40, 330, 300, 44, "read the tail page", font_size=13)
    stamps = s.box(40, 386, 300, 44, "read the two timestamps", font_size=13)
    claim = s.box(
        40,
        442,
        300,
        60,
        "add my length to the write index\nwith one atomic add",
        style="accent",
        font_size=13,
    )

    s.arrow(tail, stamps)
    s.arrow(stamps, claim)

    fits = s.box(40, 552, 300, 60, "write the data\nand commit", font_size=13)
    s.arrow(claim, fits, label="it fits")

    full = s.box(400, 442, 320, 44, "the next page is the head", style="warn", font_size=13)
    discard = s.box(
        400,
        498,
        320,
        60,
        "throw that whole page away\nand add its events to overrun",
        style="warn",
        font_size=13,
    )
    move = s.box(400, 570, 320, 44, "move the tail onto it", style="warn", font_size=13)

    s.arrow(claim, full, label="it does not fit", sides=("right", "left"))
    s.arrow(full, discard)
    s.arrow(discard, move)

    s.note(
        400,
        634,
        "Nothing waits, nothing fails, and no caller is told.\n"
        "The reserve returns a good pointer on this path too.",
        font_size=13,
        muted=True,
    )

    # -- what the capture read, on the lower left -------------------------------------------------
    s.note(40, 700, "what the capture read, per_cpu/cpu0/stats", font_size=14)

    counters = s.box(
        40,
        730,
        300,
        108,
        "entries          273\noverrun        44002\ncommit overrun     0\ndropped events     0",
        font_size=13,
        mono=True,
    )
    s.arrow(discard, counters, label="this one", dashed=True)

    s.note(
        40,
        862,
        "44275 events written, 273 of them still here,\n"
        "99.4% thrown away, in 0.007 seconds on an idle\n"
        "machine running two small commands.",
        font_size=13,
    )

    # -- the two ways to read a trace, on the right -----------------------------------------------
    s.note(760, 700, "the two ways to read a trace", font_size=14)
    s.note(760, 730, "trace_pipe", font_size=13, muted=True)
    s.note(990, 730, "the trace file", font_size=13, muted=True)

    p1 = s.box(760, 754, 200, 44, "consuming read", font_size=13)
    p2 = s.box(760, 810, 200, 60, "take overrun minus\nlast overrun", font_size=13)
    p3 = s.box(
        760,
        882,
        200,
        60,
        "print CPU:0\n[LOST 44002 EVENTS]",
        style="accent",
        font_size=12,
        mono=True,
    )

    t1 = s.box(990, 754, 210, 44, "iterator read", font_size=13)
    t2 = s.box(990, 810, 210, 60, "ask for the iterator's\nmissed events flag", font_size=13)
    t3 = s.box(
        990,
        882,
        210,
        60,
        "the writer never sets that bit,\nso nothing marks the body",
        style="warn",
        font_size=12,
    )

    s.arrow(p1, p2)
    s.arrow(p2, p3)
    s.arrow(t1, t2)
    s.arrow(t2, t3)

    header = s.box(
        760,
        954,
        440,
        56,
        "the header of the trace file: entries-in-buffer/entries-written 273/44275",
        style="accent",
        font_size=12,
        mono=True,
    )
    s.arrow(t3, header, sides=("bottom", "top"))

    # -- the part that costs a debugging session --------------------------------------------------
    band = s.box(
        40,
        1056,
        1160,
        56,
        "each way of reading a trace tells you half of what was lost",
        style="warn",
        font_size=17,
    )
    s.arrow(header, band)

    s.note(
        40,
        1136,
        "trace_pipe says where and prints no header. The trace file says how many, once, in a "
        "header a reader skips, and marks nothing in the body.",
        font_size=13,
        muted=True,
    )
    return s
