"""Two threads that never ran at the same time, and a report anyway.

This is the picture that makes the lesson land. The two threads are separated by a wait, so there
is no instant at which both of them hold a lock, so nothing could possibly have blocked. Run this
module a million times on a hundred machines and it never hangs.

Lockdep reports it on the first run, because the first thread taught it an edge and the second
thread asked for the edge that closes the loop. The timing never has to happen for the ordering to
be wrong.
"""

from kxdraw import Scene

ALT = (
    "A timeline running left to right, with an arrow across the top labelled time, and two rows "
    "under it. The top row is the first thread: it takes "
    "lock_a, then takes lock_b, then releases both and exits. The bottom row is the second thread, "
    "and it starts only after the top row has finished, with a labelled gap between them saying "
    "the first thread has already exited. The second thread takes lock_b, then reaches for lock_a, "
    "and at that point a marker on the timeline says lockdep reports a cycle. A note underneath "
    "says the two rows never overlap, so no thread ever waited for another one, and that the "
    "report is about the order the locks were taken in rather than about anything that happened "
    "at the same time."
)

LEFT = 150
TICK = 92


def at(step: int) -> float:
    return LEFT + step * TICK


def scene() -> Scene:
    s = Scene("Nothing overlapped", width=1140, height=560)

    s.note(40, 44, "Nothing overlapped, and it is still a bug", font_size=20)
    s.note(
        40,
        70,
        "A deadlock needs the timing. A lock ordering bug does not.",
        font_size=13,
        muted=True,
    )

    s.arrow((120, 108), (1100, 108), label="time")

    s.note(40, 150, "abba_first", font_size=14)
    s.note(40, 300, "abba_second", font_size=14)

    s.box(at(0), 130, 170, 56, "lock(lock_a)", style="muted", mono=True, font_size=12)
    s.box(at(2), 130, 170, 56, "lock(lock_b)", style="muted", mono=True, font_size=12)
    s.box(at(4), 130, 190, 56, "unlock both, exit", style="muted", mono=True, font_size=12)

    s.box(at(6), 280, 170, 56, "lock(lock_b)", style="muted", mono=True, font_size=12)
    trap = s.box(at(8), 280, 190, 56, "lock(lock_a)", style="warn", mono=True, font_size=12)

    gone = "the first thread is gone before the second starts"
    s.note(at(4) + 10, 210, gone, font_size=12, muted=True)

    report = s.box(at(6) - 20, 400, 420, 66, "lockdep prints the splat here", style="warn")
    s.arrow(trap, report)

    s.note(
        40,
        496,
        "The two rows do not overlap, so nothing ever waited for anything.",
        font_size=14,
    )
    s.note(
        40,
        520,
        "The report is about the order the locks were taken in, not about when.",
        font_size=14,
    )
    return s
