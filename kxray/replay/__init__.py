"""Play back a recorded session from a real Linux machine, one step at a time.

    from kxray import replay

    one = replay.load("corpora/replays/tier1/build-and-boot-uml.cast")
    print(one.table())
    print(one.step(4).rows[-5:])

Most of this book is written against Tier 0, the kernel running in the browser, because that is the
tier every reader has. A few things cannot happen there at all. You cannot build a kernel in a
32-bit emulator in a tab, and you cannot boot the kernel you built. Those lessons are Tier 1, and a
reader without a Linux machine would otherwise get a paragraph describing what they missed.

They get this instead. The session is recorded on a real machine, committed like any other
artefact, and stepped through in the notebook: the command, the output, how long it took, and
whether it worked. It is a recording rather than a claim, so nothing here says what would happen on
the reader's machine, only what happened on this one.

    record    run commands under a pseudo terminal and write an asciinema v2 cast
    cast      read that file back, counting what happened to every line of it
    terminal  turn the bytes into what the screen would have shown
    session   cut the stream into steps using the marks the shell printed
    notes     the sentences a person wrote about the session, kept in a file beside it

`kxwidgets.replay` draws a session as a player. `kxray.replay.session.Session.transcript` writes the
same thing as text for a reader with no browser, which is the rule everywhere in this project: no
picture is load-bearing.
"""

from __future__ import annotations

from kxray.replay import cast, notes, record, session, terminal
from kxray.replay.cast import Cast, Moment
from kxray.replay.session import Session, Step, load, of, steps_of

__all__ = [
    "Cast",
    "Moment",
    "Session",
    "Step",
    "cast",
    "load",
    "notes",
    "of",
    "record",
    "session",
    "steps_of",
    "terminal",
]
