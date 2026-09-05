"""Record a real terminal session to a file another machine can play back.

    python3 -m kxray.replay.record out.cast -- make ARCH=um tinyconfig -- make ARCH=um -j4

Each `--` starts another command. They run one after another in one shell, under a pseudo terminal,
and the output is written down with the time it arrived.

The reason for the pseudo terminal is that a program behaves differently when it is talking to one.
`make` prints its progress by writing a line, then a carriage return, then a longer line over the
top of it, and it only does that when it thinks a person is watching. A recording taken through a
pipe is a recording of the program's other personality, and the whole point of shipping a Tier 1
session to a Tier 0 reader is that they see what actually happened.

The file is asciinema v2, which is a documented format rather than one invented here. A header
object on the first line, then one JSON array per chunk of output, holding the seconds since the
recording started, the letter `o`, and the bytes. Anybody with `asciinema play` can watch the same
file this repository parses, and that is worth more than a format that fits our parser better.

## The marks

A recording of a terminal is one long stream of bytes. Nothing in it says where one command ended
and the next began, and a transcript you cannot step through is a wall of text with a scrollbar.

So the shell is asked to mark it up. There is a real convention for this, OSC 133, which iTerm2,
kitty, WezTerm and a few others already speak, and it works by having the shell print four escape
sequences a terminal knows to act on and a person never sees:

    OSC 133 ; A     a prompt is about to be drawn
    OSC 133 ; B     the prompt is finished, what follows is being typed
    OSC 133 ; C     the command has been read, what follows is its output
    OSC 133 ; D ; n the command finished, and its exit status was n

`kxray.replay.session` reads those four and nothing else, which is why it can also be pointed at a
cast somebody recorded with plain asciinema. Without the marks a whole session is one step, which
is the truth about that file rather than a failure to parse it.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

# Eighty is too narrow for a kernel build line and a hundred and twenty is wider than a phone will
# ever show. A hundred is a compromise that both survive.
WIDTH = 100
HEIGHT = 30

# How long to wait for a command to finish before giving up on it. A kernel build is the reason
# this is measured in hours rather than minutes.
TIMEOUT = 4 * 3600

# Read at most this much in one go. Small enough that the timestamps stay meaningful on a program
# that produces output steadily, large enough that a build does not produce a hundred thousand
# events.
CHUNK = 8192

# The shell startup file the recorder writes. Everything in here is setup that a reader should not
# see typed, which is exactly why it goes in a file rather than being sent through the terminal:
# anything sent through the terminal is echoed back and lands in the recording.
RCFILE = r"""
bind 'set enable-bracketed-paste off' 2>/dev/null
PS1='\[\e]133;A\a\]$ \[\e]133;B\a\]'
PS0='\e]133;C\a'
PROMPT_COMMAND='printf "\033]133;D;%s\007" "$?"'
unset PROMPT_DIRTRIM
export TERM=xterm-256color
export LC_ALL=C
"""


def _winsize(fd: int, rows: int, columns: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))


def _prompt(chunk: bytes) -> bool:
    """Whether a prompt has been drawn and the shell is ready to be typed at.

    This waits for B, the end of the prompt, rather than for D, the end of the last command. D is
    printed a moment earlier, before the new prompt is drawn, and a command written into the
    terminal during that moment gets echoed before the prompt instead of after it. The recording
    then shows the command above the prompt that is meant to be running it.
    """
    return b"\x1b]133;B" in chunk


def record(
    commands: list[str],
    out: str | Path,
    *,
    shell: str = "/bin/bash",
    width: int = WIDTH,
    height: int = HEIGHT,
    timeout: float = TIMEOUT,
    title: str = "",
) -> Path:
    """Run each command in one shell under a pseudo terminal and write the cast.

    Commands are fed one at a time, and the next one is not sent until the shell says the last one
    finished. Sending them all at once would be simpler and would be wrong: the terminal echoes
    what it is given the moment it arrives, so every command in the session would appear at the top
    of the recording before any of them had run.
    """
    out = Path(out)
    master, slave = os.openpty()
    _winsize(slave, height, width)

    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    env["LC_ALL"] = "C"
    env.pop("BASH_ENV", None)

    rc = out.with_suffix(".rc")
    rc.write_text(RCFILE, encoding="utf-8")
    started = time.time()
    events: list[tuple[float, str]] = []
    try:
        child = subprocess.Popen(  # noqa: S603
            [shell, "--noprofile", "--rcfile", str(rc), "-i"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave)
        _drain(master, events, started, until=_prompt, timeout=30)
        for one in commands:
            os.write(master, one.encode("utf-8") + b"\n")
            _drain(master, events, started, until=_prompt, timeout=timeout)
        # Shutting the shell down is housekeeping and not part of the session, so the recording
        # stops here and the `exit` goes into a list that is thrown away. Leaving it in put an
        # extra step on the end of every session, and that step could never report a status,
        # because nothing runs after `exit` to print one. A walkthrough whose last step is marked
        # as never having finished reads like the recording broke.
        ending: list[tuple[float, str]] = []
        os.write(master, b"exit\n")
        _drain(master, ending, started, until=None, timeout=60)
        child.wait(timeout=30)
    finally:
        os.close(master)
        rc.unlink(missing_ok=True)
        _kill(child)

    header = {
        "version": 2,
        "width": width,
        "height": height,
        "timestamp": int(started),
        "env": {"SHELL": shell, "TERM": "xterm-256color"},
    }
    if title:
        header["title"] = title
    lines = [json.dumps(header, sort_keys=True)]
    lines += [json.dumps([round(when, 6), "o", text]) for when, text in events]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _drain(master: int, events: list, started: float, *, until, timeout: float) -> None:
    """Read until the shell says it is done, or until the far end closes, or until we give up.

    Every chunk is written down with the moment it arrived rather than the moment it was produced,
    because the moment it was produced is not knowable from this side. On anything that prints
    steadily the difference is a few milliseconds. On a program that buffers its output the
    difference is the whole point of the buffer, and the recording will show a long pause and then
    a burst, which is what a person sitting in front of it would have seen too.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _, _ = select.select([master], [], [], 1.0)
        if not ready:
            continue
        try:
            chunk = os.read(master, CHUNK)
        except OSError:  # the child closed its end, which is the shell exiting
            return
        if not chunk:
            return
        events.append((time.time() - started, chunk.decode("utf-8", errors="replace")))
        if until is not None and until(chunk):
            return


def _kill(child) -> None:
    if child.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(child.pid), signal.SIGKILL)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="record a terminal session as an asciinema cast")
    parser.add_argument("out", help="where to write the .cast file")
    parser.add_argument("--title", default="", help="one line saying what the session is")
    parser.add_argument("--shell", default="/bin/bash")
    parser.add_argument("--width", type=int, default=WIDTH)
    parser.add_argument("--height", type=int, default=HEIGHT)
    args, rest = parser.parse_known_args(argv)

    commands = [" ".join(one) for one in _split(rest)]
    if not commands:
        print("nothing to record: put each command after its own --", file=sys.stderr)
        return 2
    path = record(
        commands,
        args.out,
        shell=args.shell,
        width=args.width,
        height=args.height,
        title=args.title,
    )
    print(f"wrote {path}, {len(commands)} command(s)")
    return 0


def _split(argv: list[str]) -> list[list[str]]:
    """Everything after each `--` is one command, so a command may contain anything it likes."""
    out: list[list[str]] = []
    for one in argv:
        if one == "--":
            out.append([])
        elif out:
            out[-1].append(one)
    return [one for one in out if one]


if __name__ == "__main__":
    sys.exit(main())
