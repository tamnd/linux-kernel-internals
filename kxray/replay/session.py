"""Cut a recorded session into steps a reader can walk through one at a time.

    from kxray.replay import session

    one = session.load("corpora/replays/tier1/build-and-boot-uml.cast")
    print(one.table())
    print(one.step(3).output)

A recording is a stream of bytes with no structure in it. The structure comes from four escape
sequences the shell was asked to print, OSC 133, described in `kxray.replay.record`. A prompt is
drawn, the command is typed, the command starts, the command finishes with a status. Between two
of those marks is one step.

## What a step is worth

A step knows what was typed, what came back, how long it took and whether it worked. That is enough
to build the thing this module exists for: a Tier 0 reader, on a machine that cannot build a kernel,
stepping through a real build on a machine that did. They see the command, they see the output, and
they see that step four took eleven minutes, which is the fact a description of the session always
leaves out.

## What a step is not

It is not a claim about anything. The recording is evidence that these commands ran on that machine
on that day and produced this output. It is not evidence that they will do the same on any other
machine, and a lesson that needs that has to say so and be checked by `claimledger` like everything
else.

## Casts with no marks in them

A recording made with plain `asciinema rec` has no marks, and this returns one step holding the
whole session, with no command and no exit status. That is the truth about the file. Guessing at
where the prompts were by looking for a dollar sign is how you get a transcript that is subtly
wrong in the middle of a build log that prints dollar signs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from kxray.models import grid
from kxray.replay import notes as notesfile
from kxray.replay import terminal
from kxray.replay.cast import Cast, parse_file

# The four marks, as the shell prints them. The final byte is a bell or a string terminator, and
# both are allowed because different shells and different frameworks pick different ones.
MARK = re.compile(r"\x1b\]133;([ABCD])(;([^\x07\x1b]*))?(?:\x07|\x1b\\)")

PROMPT_START = "A"
PROMPT_END = "B"
OUTPUT_START = "C"
COMMAND_DONE = "D"


@dataclass(frozen=True)
class Step:
    """One command in a recorded session, with everything that came back from it."""

    number: int
    command: str
    output: str
    started_at: float
    seconds: float
    exit_code: int | None = None
    complete: bool = True
    note: str = ""
    width: int = 0

    @property
    def worked(self) -> bool:
        """Whether the command reported success. An unknown status is not a success."""
        return self.exit_code == 0

    @property
    def rows(self) -> list[str]:
        """The output as the screen had it, which is not the same as the bytes."""
        return terminal.lines(self.output, self.width)

    @property
    def took(self) -> str:
        """The duration in the largest unit that leaves a number a person can hold."""
        if self.seconds >= 60:
            return f"{int(self.seconds) // 60}m {int(self.seconds) % 60}s"
        if self.seconds >= 1:
            return f"{self.seconds:.1f}s"
        return f"{self.seconds * 1000:.0f}ms"

    @property
    def status(self) -> str:
        if not self.complete:
            return "never finished"
        if self.exit_code is None:
            return "status not recorded"
        return "ok" if self.exit_code == 0 else f"failed, exit {self.exit_code}"

    def alt(self) -> str:
        """The step in one sentence, for a screen reader and for the transcript."""
        what = f"step {self.number}, {self.command or 'the whole session'}"
        return f"{what}, took {self.took}, {self.status}, {len(self.rows)} lines of output."


@dataclass(frozen=True)
class Session:
    """A recorded session, cut into steps."""

    steps: tuple[Step, ...]
    cast: Cast
    title: str = ""
    source: str = ""

    @property
    def seconds(self) -> float:
        return self.cast.seconds

    @property
    def marked(self) -> bool:
        """Whether the shell marked this recording up, or whether it is one lump.

        Worth asking before drawing it. A player that offers a step control over a session with one
        step in it is a player promising something it cannot do.
        """
        return any(one.command for one in self.steps)

    @property
    def failures(self) -> tuple[Step, ...]:
        return tuple(one for one in self.steps if not one.worked)

    def step(self, number: int) -> Step:
        return self.steps[number]

    def slowest(self) -> Step | None:
        return max(self.steps, key=lambda one: one.seconds, default=None)

    def table(self) -> str:
        rows = [("#", "took", "status", "out", "command")]
        for one in self.steps:
            rows.append(
                (
                    str(one.number),
                    one.took,
                    one.status,
                    str(len(one.rows)),
                    one.command or "(the whole recording)",
                )
            )
        return grid(rows)

    def alt(self) -> str:
        if not self.marked:
            return (
                f"{self.title or self.source or 'a recorded session'}, {self.seconds:.0f} seconds, "
                "recorded without the shell marks, so it is one step rather than a walkthrough."
            )
        slow = self.slowest()
        out = (
            f"{self.title or self.source or 'a recorded session'}: {len(self.steps)} steps over "
            f"{self.seconds:.0f} seconds"
        )
        if slow is not None:
            out += f", the longest being {slow.command!r} at {slow.took}"
        bad = self.failures
        out += f", and {len(bad)} of them did not report success." if bad else ", all successful."
        return out

    def transcript(self) -> str:
        """The whole session as text, for a reader who has no browser and no player."""
        out = [f"# {self.title or self.source or 'a recorded session'}", "", self.alt(), ""]
        for one in self.steps:
            out.append(f"## {one.number}. {one.command or 'the whole recording'}")
            out.append("")
            if one.note:
                out += [one.note, ""]
            out.append(f"{one.took}, {one.status}")
            out += ["", "```", *one.rows, "```", ""]
        return "\n".join(out).rstrip() + "\n"


def steps_of(cast: Cast) -> tuple[Step, ...]:
    """Walk the marks and cut the stream between them."""
    text = cast.text
    marks = [
        (one.start(), one.end(), one.group(1), one.group(3) or "") for one in MARK.finditer(text)
    ]
    if not any(one[2] == PROMPT_END for one in marks):
        return (_whole(cast, text),)

    out: list[Step] = []
    prompt_at = 0
    typed_at: int | None = None
    ran_at: int | None = None
    for start, end, letter, argument in marks:
        if letter == PROMPT_START:
            prompt_at = end
        elif letter == PROMPT_END:
            typed_at, ran_at = end, None
        elif letter == OUTPUT_START and typed_at is not None:
            ran_at = end
        elif letter == COMMAND_DONE and typed_at is not None:
            out.append(_step(cast, text, len(out), prompt_at, typed_at, ran_at, start, argument))
            typed_at, ran_at = None, None
    # A recording that stops after the last prompt was drawn has an opening B mark and nothing
    # after it. That is not a step that was cut off, it is a shell sitting there waiting, and every
    # recording ends that way. A step is only reported here if something was actually typed.
    if typed_at is not None:
        last = _step(
            cast, text, len(out), prompt_at, typed_at, ran_at, len(text), "", complete=False
        )
        if last.command:
            out.append(last)
    return tuple(out)


def _step(cast, text, number, prompt_at, typed_at, ran_at, done_at, argument, *, complete=True):
    """One step, from where the prompt ended to where the shell said the command was over.

    `ran_at` is where the shell said the command started, and it is allowed to be missing. Bash has
    only printed that mark since 4.4, and a recording from an older shell, or from a shell that is
    not bash, has the prompt and the finish and nothing in between. In that case the command is
    everything up to the first newline after it was typed, which is the same thing the terminal
    echoed, and the output is everything after that newline.
    """
    if ran_at is None:
        newline = text.find("\n", typed_at)
        ran_at = len(text) if newline < 0 else newline + 1
    # Where on the screen the typing began, which is after the prompt. It is needed because a
    # command wraps at the right edge of the terminal and not at its own hundredth character, so a
    # two character prompt moves the wrap two characters earlier.
    at = terminal.column(text[prompt_at:typed_at], cast.width)
    command = terminal.typed(text[typed_at:ran_at], cast.width, at)
    # The clock starts one character earlier than the output does, and it has to. `ran_at` is the
    # first byte of the output, and the first byte of the output can arrive minutes after the
    # command started. The byte before it is the end of the mark, or the newline that sent the
    # command, and both of those arrived at the moment the command began. Timing from `ran_at`
    # instead makes every command that prints nothing take zero seconds, including `sleep 10`.
    began = cast.at(max(0, ran_at - 1))
    return Step(
        number=number,
        command=command,
        output=text[ran_at:done_at],
        started_at=began,
        seconds=max(0.0, cast.at(done_at) - began),
        exit_code=_code(argument),
        complete=complete,
        width=cast.width,
    )


def _whole(cast: Cast, text: str) -> Step:
    return Step(
        number=0,
        command="",
        output=text,
        started_at=0.0,
        seconds=cast.seconds,
        exit_code=None,
        width=cast.width,
    )


def _code(argument: str) -> int | None:
    """The exit status out of the D mark, which carries it as `D;0` and sometimes as bare `D`."""
    head = argument.split(";")[0].strip()
    try:
        return int(head)
    except ValueError:
        return None


def of(cast: Cast, *, notes: dict[int, str] | None = None, title: str = "") -> Session:
    """A session from a cast, with the notes attached to the steps they belong to."""
    steps = steps_of(cast)
    if notes:
        steps = tuple(
            Step(**{**one.__dict__, "note": notes.get(one.number, one.note)}) for one in steps
        )
    return Session(
        steps=steps,
        cast=cast,
        title=title or cast.title,
        source=cast.source,
    )


def load(path: str | Path, *, notes: dict[int, str] | None = None) -> Session:
    """A session from a recording, with the notes file beside it picked up if there is one.

    A notes file that no longer lines up with the recording raises here rather than being applied
    with a warning. `kxray.replay.notes` says why: a note attached to the wrong step is a sentence
    confidently pointing a reader at the wrong output, and there is nothing quiet about that
    failure worth preserving.
    """
    cast = parse_file(path)
    if notes is None:
        beside = notesfile.path_for(path)
        if beside.exists():
            notes = notesfile.for_steps(beside, steps_of(cast))
    return of(cast, notes=notes)
