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

    record    run commands under a pseudo terminal and write an asciinema v2 cast, on a machine
              that has a pseudo terminal, which is why it is the one module here loaded on demand
    cast      read that file back, counting what happened to every line of it
    terminal  turn the bytes into what the screen would have shown
    session   cut the stream into steps using the marks the shell printed
    notes     the sentences a person wrote about the session, kept in a file beside it

`kxwidgets.replay` draws a session as a player. `kxray.replay.session.Session.transcript` writes the
same thing as text for a reader with no browser, which is the rule everywhere in this project: no
picture is load-bearing.
"""

from __future__ import annotations

import importlib
from typing import Any

from kxray.replay import cast, notes, session, terminal
from kxray.replay.cast import Cast, Moment
from kxray.replay.session import Session, Step, load, of, steps_of

# `record` is the one module here that cannot be imported everywhere. It drives a pseudo terminal,
# so it needs `fcntl` and `termios`, and Pyodide has neither: a browser has no pty to drive. Every
# other module here is a parser and runs anywhere.
#
# Importing it at the top cost the browser the entire toolkit. `kxwidgets` imports its replay
# player, that imports `kxray.replay.session`, and this line ran on the way past and raised
# `ModuleNotFoundError: No module named 'fcntl'`, so a page that only wanted to draw a tape got
# nothing at all. Loading it when somebody asks for it by name keeps `replay.record` working for
# whoever is recording a session and stops charging a reader in a tab for it.
_LAZY = {"record"}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        found = importlib.import_module(f"kxray.replay.{name}")
        globals()[name] = found
        return found
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
