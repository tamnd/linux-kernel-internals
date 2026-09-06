"""What the lock checker keeps, and the one moment it says no.

The thing readers get wrong about lockdep is that they think it watches for a deadlock. It does
not. It keeps a directed graph whose nodes are lock classes and whose edges mean this one was held
while that one was taken, and every time it is about to add an edge it asks whether the edge would
close a cycle. That question is asked at the moment of an acquire, on one processor, with nothing
waiting for anything, which is why a report can arrive on a run that finished fine.

This is the picture for the blueprint's section 3. The graph on the left is what is being kept.
The two threads on the right are what the module in the corpus does. The band across the bottom is
what happens after the report, which is the part that costs people a debugging session.
"""

from kxdraw import Scene

ALT = (
    "A picture in three parts. On the left, a small directed graph labelled the lock graph, with "
    "two round-cornered nodes, lock_a and lock_b. A solid arrow runs from lock_a down to lock_b "
    "labelled edge added by the first thread, meaning lock_a was held while lock_b was taken. A "
    "dashed red arrow runs back up from lock_b to lock_a labelled the edge about to be added, and "
    "beside it a red box reads adding this closes a cycle, so refuse it and print. In the middle, "
    "two columns headed first thread and second thread, four steps in time order reading down: "
    "first thread takes lock_a, first thread takes lock_b, first thread releases both, then "
    "second thread takes lock_b and second thread takes lock_a. A note beside them says both "
    "threads ran to completion and neither ever waited. On the right, a column of the four things "
    "the checker does on every single acquire, in order: find or register the class for this "
    "lock, push it onto this task's held lock stack, mix its class index into the chain key, and "
    "look the chain key up in the chain cache. A note says a hit means this exact sequence has "
    "been seen before and nothing else runs, which is why the checker is affordable at all. "
    "Across the bottom is a red band reading debug_locks goes to zero on the first report of the "
    "boot, and under it a line saying from that moment nothing is checked, a second bug loaded "
    "afterwards is silent, and the only place this is visible is the debug_locks line of "
    "/proc/lockdep_stats."
)


def scene() -> Scene:
    s = Scene("How a lock ordering report happens", width=1240, height=780)

    s.note(40, 44, "How a lock ordering report happens", font_size=20)
    s.note(
        40,
        70,
        "No thread has to wait. The graph is what is checked, and it is checked on the acquire.",
        font_size=13,
        muted=True,
    )

    # -- the graph, on the left ------------------------------------------------------------------
    s.note(40, 118, "the lock graph", font_size=14)
    a = s.box(96, 148, 200, 52, "lock_a", style="accent", font_size=16, mono=True)
    b = s.box(96, 308, 200, 52, "lock_b", style="accent", font_size=16, mono=True)

    s.arrow(a, b, label="held while taking")
    s.arrow(b, a, label="about to be added", dashed=True, sides=("left", "left"))

    refuse = s.box(
        40,
        400,
        312,
        68,
        "adding this edge closes a cycle\nrefuse it, print, and switch off",
        style="warn",
        font_size=14,
    )
    s.arrow((196, 360), refuse)

    s.note(
        40,
        494,
        "A node is a lock class, which is a line of source rather\n"
        "than an object. Every mutex initialised on one line is\n"
        "one node here, however many of them exist.",
        font_size=13,
        muted=True,
    )

    # -- what the two threads did, in the middle -------------------------------------------------
    s.note(408, 118, "what the module in the corpus does", font_size=14)
    s.note(408, 148, "first thread", font_size=13, muted=True)
    s.note(628, 148, "second thread", font_size=13, muted=True)

    one = s.box(408, 172, 200, 44, "lock(lock_a)", font_size=14, mono=True)
    two = s.box(408, 228, 200, 44, "lock(lock_b)", font_size=14, mono=True)
    done = s.box(408, 284, 200, 44, "release both, exit", style="muted", font_size=14)
    three = s.box(628, 340, 200, 44, "lock(lock_b)", font_size=14, mono=True)
    four = s.box(628, 396, 200, 44, "lock(lock_a)", style="warn", font_size=14, mono=True)

    s.arrow(one, two)
    s.arrow(two, done)
    s.arrow(done, three)
    s.arrow(three, four)

    s.note(
        408,
        468,
        "Both threads ran to the end. Neither ever waited for\n"
        "the other. The report came out anyway, because the\n"
        "cycle is a property of the code and a hang is a\n"
        "property of the timing.",
        font_size=13,
        muted=True,
    )

    # -- what runs on every acquire, on the right ------------------------------------------------
    s.note(880, 118, "on every acquire, always", font_size=14)
    find = s.box(880, 148, 320, 44, "find or register the lock class", font_size=13)
    push = s.box(880, 204, 320, 44, "push it on this task's held lock stack", font_size=13)
    mix = s.box(880, 260, 320, 44, "mix the class index into the chain key", font_size=13)
    look = s.box(880, 316, 320, 44, "look the chain key up in the chain cache", font_size=13)
    miss = s.box(
        880,
        380,
        320,
        60,
        "miss: walk the graph backwards\nlooking for a path home",
        style="accent",
        font_size=13,
    )

    s.arrow(find, push)
    s.arrow(push, mix)
    s.arrow(mix, look)
    s.arrow(look, miss, label="miss")

    s.note(
        880,
        468,
        "A hit means this exact sequence of held locks has\n"
        "been seen before, and nothing below runs. That is\n"
        "the whole reason the checker is affordable.",
        font_size=13,
        muted=True,
    )

    # -- the part that costs a debugging session -------------------------------------------------
    off = s.box(
        40,
        612,
        1160,
        60,
        "debug_locks goes to 0 on the first report of the boot",
        style="warn",
        font_size=17,
    )
    s.arrow(refuse, off)

    s.note(
        40,
        692,
        "From that moment nothing is checked at all. A second bug loaded afterwards is silent, and "
        "a quiet log means nothing.",
        font_size=14,
    )
    s.note(
        40,
        722,
        "The only place it shows is the debug_locks line of /proc/lockdep_stats, which is why that "
        "file is the thing to read after a report.",
        font_size=13,
        muted=True,
    )
    return s
