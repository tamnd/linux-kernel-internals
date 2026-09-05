"""Read an asciinema v2 recording.

    from kxray.replay import cast

    one = cast.parse_file("corpora/replays/tier1/build-and-boot-uml.cast")
    print(one.lines)          # 1 read, 0 skipped, 0 unparsed
    print(one.seconds)        # how long the session took

The format is one JSON object on the first line and one JSON array on each line after it. The
object says how wide the terminal was, how tall, when it started and what shell was in it. Each
array is a moment: seconds since the start, a letter saying which direction the bytes went, and the
bytes.

Two letters exist. `o` is output, which is everything the terminal showed. `i` is input, which is
what the keyboard sent, and this reader does not use it. That is not laziness. A terminal echoes
what is typed at it, so every keystroke is already in the output stream, and adding the input back
in would print every command in the session twice.

Nothing here understands escape sequences or commands. `kxray.replay.terminal` renders the bytes
and `kxray.replay.session` cuts them into steps. This layer only reads the file and counts what it
did with each line, which is the same contract every other reader in `kxray` signs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from kxray.models import READ, SKIPPED, UNPARSED, Lines

# The only version of the format this reads. asciinema v1 is a single JSON document with the whole
# recording inside it, which is a different file rather than an older one, and no tool this project
# uses writes it any more.
VERSION = 2

OUTPUT = "o"
INPUT = "i"


@dataclass(frozen=True)
class Moment:
    """One chunk of output, and when it arrived.

    `at` is when the recorder read the bytes, not when the program wrote them. There is no way to
    know the second one from this side of a pipe. For anything that prints as it goes the gap is a
    few milliseconds. For a program that buffers its output the gap is the whole buffer, and the
    recording shows a silence and then a burst, which is what a person watching would have seen.
    """

    at: float
    text: str


@dataclass
class Cast:
    """A recorded terminal session, as it came off the recorder."""

    width: int = 80
    height: int = 24
    version: int = VERSION
    timestamp: int = 0
    title: str = ""
    env: dict = field(default_factory=dict)
    moments: tuple[Moment, ...] = ()
    lines: Lines = field(default_factory=Lines)
    source: str = ""

    @property
    def seconds(self) -> float:
        """How long the recording ran, which is the last moment in it."""
        return self.moments[-1].at if self.moments else 0.0

    @property
    def text(self) -> str:
        """Every byte of output, in order, with nothing between the chunks.

        The chunk boundaries are an artefact of how often the recorder got to run, not of anything
        the program did, so a reader that treats them as meaningful is reading its own scheduler.
        """
        return "".join(one.text for one in self.moments)

    def at(self, offset: int) -> float:
        """When the character at this offset into `text` arrived.

        Rounded to the chunk it came in, because that is the resolution the recording has. A step
        boundary found in the middle of a chunk is timed as the whole chunk, and the error is
        bounded by how long that chunk took to arrive.
        """
        seen = 0
        for one in self.moments:
            seen += len(one.text)
            if offset < seen:
                return one.at
        return self.seconds

    def __str__(self) -> str:
        return (
            f"{self.title or self.source or 'a session'}: {len(self.moments)} moments over "
            f"{self.seconds:.1f} seconds, {self.width} by {self.height}"
        )


def parse(text: str, *, source: str = "") -> Cast:
    """Read a cast, counting what happened to every line of it.

    A file whose first line is not a version 2 header is refused rather than guessed at. Everything
    after that is counted: an output moment is read, an input moment is skipped and says why in the
    module docstring, a blank line is skipped, and a line that is neither is unparsed.
    """
    rows = text.split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    counted = Lines()
    if not rows:
        return Cast(lines=counted, source=source)

    header = _header(rows[0], source)
    counted.count(READ)
    moments: list[Moment] = []
    for row in rows[1:]:
        if not row.strip():
            counted.count(SKIPPED)
            continue
        moment = _moment(row)
        if moment is None:
            counted.count(UNPARSED)
        elif moment is False:
            counted.count(SKIPPED)
        else:
            moments.append(moment)
            counted.count(READ)

    return Cast(
        width=int(header.get("width", 80)),
        height=int(header.get("height", 24)),
        version=int(header.get("version", VERSION)),
        timestamp=int(header.get("timestamp", 0)),
        title=str(header.get("title", "")),
        env=dict(header.get("env", {})),
        moments=tuple(moments),
        lines=counted,
        source=source,
    )


def parse_file(path: str | Path) -> Cast:
    path = Path(path)
    return parse(path.read_text(encoding="utf-8"), source=str(path))


def _header(row: str, source: str) -> dict:
    try:
        header = json.loads(row)
    except json.JSONDecodeError as bad:
        raise ValueError(f"{source or 'this file'} does not start with a header: {bad}") from bad
    if not isinstance(header, dict):
        raise ValueError(
            f"{source or 'this file'} does not start with a header object, it starts with a "
            f"{type(header).__name__}"
        )
    version = header.get("version")
    if version != VERSION:
        raise ValueError(
            f"{source or 'this file'} is asciinema v{version}, and this reads v{VERSION}"
        )
    return header


def _moment(row: str):
    """A moment, or False for input we deliberately drop, or None for a line not understood."""
    try:
        one = json.loads(row)
    except json.JSONDecodeError:
        return None
    if not isinstance(one, list) or len(one) < 3:
        return None
    when, kind, text = one[0], one[1], one[2]
    if kind == INPUT:
        return False
    if kind != OUTPUT or not isinstance(text, str):
        return None
    try:
        return Moment(at=float(when), text=text)
    except (TypeError, ValueError):
        return None
