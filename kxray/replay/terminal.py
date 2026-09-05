"""What a terminal would have shown, from the bytes a program wrote at it.

A recording is not text. It is the input to a machine that draws text, and the difference shows up
the first time you print a build log with `cat`. Two hundred lines of `Building...` come out where
one line was on the screen, because each one was drawn over the last with a carriage return and no
newline, and nothing in a text file remembers that.

This is small on purpose. It does not implement a terminal. There is no cursor addressing, no
scrollback, no alternate screen, and no colour. It handles the five things that actually appear
in a recorded build or boot:

    escape sequences  removed, because a lesson shows text and not colour
    carriage return   the rest of the line is drawn over what was there
    backspace         one character back
    tab               to the next multiple of eight
    the right edge    a line longer than the screen carries on underneath itself

Anything more than that and the honest answer is to stop and use a real terminal emulator, which is
a dependency this project is not taking on for the sake of prettier build output. If a recording
turns up that needs cursor addressing, the fix is to record something simpler.

## Why the right edge is in that list

It looks like presentation and it is not. When you type a command longer than the screen is wide,
the shell writes the character in the last column and then a carriage return, and it does that
because the terminal has already moved the cursor down a line on its own. Read those bytes without
knowing where the right edge is and the carriage return sends you back to the start of the same
line, so the tail of the command lands on top of its own head. `apt-get install ... libssl-dev` is
what was typed and `libssl-ddev libelf-dev` is what you get, which is a command that does not exist
being shown to a reader as though somebody ran it.

So the width is passed in from the recording, which wrote it down, and a line that fills the screen
carries on the row below. `typed()` is the other half: it puts a wrapped line back together, because
a command that took two rows to draw is still one command.
"""

from __future__ import annotations

import re

TAB = 8

# The escape sequences to take out. CSI is the common one, `\e[` and then a final letter, and it
# covers colour, cursor movement and clearing. OSC is `\e]` up to a bell or a string terminator,
# and it is how a program sets the window title and how the shell prints the marks this project
# steps on. The last alternative catches the two character sequences like `\e(B` and `\e=`.
ESCAPE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC, ended by a bell or a string terminator
    r"|\x1b[@-Z\\-_]"  # a single character escape
    r"|\x1b[ -/]*[0-~]"  # anything else two or three bytes long
)

# Control characters that survive as themselves, sort of. Everything else in the C0 range is
# dropped rather than drawn, because a terminal does not draw them either.
KEEP = "\n\r\t\b"


def strip(text: str) -> str:
    """The bytes with the escape sequences taken out and the control characters left alone."""
    out = ESCAPE.sub("", text)
    return "".join(one for one in out if one >= " " or one in KEEP)


def render(text: str, width: int = 0) -> str:
    """What the screen would have said, one line at a time.

    Lines are independent of each other here, which is the simplification that makes this a page
    instead of a terminal emulator. It is true for everything that scrolls, which is every build and
    every boot. It is false for anything that moves the cursor up, and this returns nonsense for
    those rather than pretending otherwise. `kxray.replay.session` is the only caller and it is only
    ever handed output that scrolled.

    A width of zero means no right edge, so nothing wraps and a long line stays long.
    """
    out = []
    for line in strip(text).split("\n"):
        out.extend(_rows(line, width))
    return "\n".join(one.rstrip() for one in out)


def _rows(text: str, width: int = 0, start: int = 0) -> list[str]:
    """One written line as the rows it took up, carriage returns and tabs acted on.

    Every row but the last is exactly `width` long, because that is what made it end. Keeping the
    padding is what lets `typed()` put the rows back together and get the spaces right.

    `start` is the column the cursor was already in, which is not zero when something was drawn
    before this. The shell's prompt is the case that matters: two characters of prompt means the
    command wraps two characters earlier, and getting that wrong puts the break in the wrong place.
    """
    out: list[str] = []
    row: list[str] = [" "] * start
    at = start
    for one in text:
        if one == "\r":
            at = 0
        elif one == "\b":
            at = max(0, at - 1)
        elif one == "\t":
            at += TAB - (at % TAB)
        else:
            # The padding is done here rather than when the tab was seen, because a tab that
            # nothing is written after moves the cursor and leaves no spaces behind it.
            while len(row) < at:
                row.append(" ")
            if at < len(row):
                row[at] = one
            else:
                row.append(one)
            at += 1
            if width and at >= width:
                out.append("".join(row).ljust(width))
                row, at = [], 0
    out.append("".join(row))
    return out


def lines(text: str, width: int = 0) -> list[str]:
    """The rendered screen as a list, with the trailing blank lines taken off.

    Trailing blanks and not leading ones. A blank line at the end of a command's output is the
    newline the shell printed before the next prompt and says nothing. A blank line at the start is
    usually the program leaving room above itself and is part of what it looks like.
    """
    out = render(text, width).split("\n")
    while out and not out[-1].strip():
        out.pop()
    return out


def typed(text: str, width: int = 0, start: int = 0) -> str:
    """One logical line, with the wrapping undone, for reading a command back off the screen.

    The shell echoes what you type, and if it did not fit it echoed it over two rows. Those two rows
    are one command, so they are joined rather than kept apart. Everything before the first newline
    is taken, because what comes after it is the command running rather than the command being read.
    """
    first = strip(text).split("\n")[0]
    return "".join(_rows(first, width, start)).strip()


def column(text: str, width: int = 0) -> int:
    """Which column the cursor is left in after drawing this, which is where typing starts."""
    return len(_rows(strip(text).split("\n")[-1], width)[-1])
