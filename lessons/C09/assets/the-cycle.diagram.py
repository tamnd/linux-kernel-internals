"""The lock graph, and the one edge that closes it.

The picture people carry around for a deadlock is two threads stuck facing each other. That picture
is about timing and it is the reason the bug is hard to find, because the timing almost never
happens. Lockdep does not draw that picture at all. It draws this one: lock classes as nodes, "was
held when this one was taken" as edges, and a complaint the moment a new edge would close a loop.

The closing edge is drawn dashed on purpose. It is the only edge in the picture that has not
happened yet at the moment of the report. Lockdep is refusing to add it.

This is also the still that carries the same point as the `lock-cycle` animation. The animation
adds the first edge, starts the second, and stops at the moment the loop would close. This picture
has both edges on screen at once and has to work on its own, which is what most readers get.
"""

from kxdraw import Scene

ALT = (
    "A graph with two boxes. On the left a box labelled lock_a, with the address c1a4e0a0 and the "
    "words one lock class under it, and on the right the same for lock_b at c1a4e060. A solid "
    "arrow "
    "runs from lock_a to lock_b, labelled edge one, recorded when the first thread held lock_a "
    "and took lock_b. A dashed arrow runs back from lock_b to lock_a, labelled edge two, about to "
    "be recorded because the second thread holds lock_b and is taking lock_a. A note by the "
    "dashed arrow says it has not been added and that this is the moment lockdep says no. "
    "Underneath, three notes say what an edge means, that a loop means there is an order in which "
    "two of these block forever, and that nothing here is blocked because both threads finished."
)


def scene() -> Scene:
    s = Scene("The cycle", width=1000, height=560)

    s.note(40, 44, "Two locks, two edges, one loop", font_size=20)
    s.note(
        40,
        70,
        "Lockdep works on a graph of lock classes rather than on a picture of stuck threads.",
        font_size=13,
        muted=True,
    )

    a = s.box(120, 180, 240, 110, "lock_a\n\nc1a4e0a0\none lock class", style="accent")
    b = s.box(620, 180, 240, 110, "lock_b\n\nc1a4e060\none lock class", style="accent")

    s.arrow(a, b, label="1. lock_a was held when lock_b was taken")
    s.arrow(
        (740, 300),
        (240, 300),
        label="2. lock_b is held and lock_a is being taken",
        dashed=True,
    )

    s.note(
        120,
        330,
        "The dashed edge has not been added. This is the moment lockdep says no.",
        font_size=13,
        muted=True,
    )

    s.note(40, 400, "An edge means one lock was held while the other was taken.", font_size=14)
    s.note(
        40,
        424,
        "A loop means there is an order in which two of these block forever.",
        font_size=14,
    )
    s.note(
        40,
        448,
        "Nothing is blocked here. No thread waited on anything. Both threads finished.",
        font_size=14,
    )
    s.note(
        40,
        480,
        "The bug is in the code either way, and the graph is what says so.",
        font_size=13,
        muted=True,
    )
    return s
