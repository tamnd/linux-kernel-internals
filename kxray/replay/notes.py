"""The sentences a person wrote about a recorded session, kept next to it.

    corpora/replays/tier1/build-and-boot-uml.cast
    corpora/replays/tier1/build-and-boot-uml.notes.toml

The recording is evidence and nothing in it may be edited. The notes are the other half: what step
four is actually doing, why step six takes twenty minutes, which line of its output is the one to
look at. Keeping them in a second file is what lets the first one stay untouched.

## Why a note names its command

A note keyed only by step number is a note that silently moves. Insert one command near the top of
a session, record it again, and every note below is now attached to the wrong step, pointing a
reader at the wrong output with total confidence. Nothing raises and nothing looks wrong.

So every note carries the command it belongs to as well as the number, and loading a notes file
whose numbers no longer match its commands is an error rather than a warning. It is an error at
authoring time, on a machine with the recording in front of it, which is the only time anybody can
do anything about it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

SCHEMA = 1

# What the notes file for a recording is called. The recording keeps its own suffix so that
# `asciinema play` still opens it.
SUFFIX = ".notes.toml"


def path_for(cast: str | Path) -> Path:
    """Where the notes for a recording live, which is beside it under a second suffix."""
    cast = Path(cast)
    return cast.with_name(cast.stem + SUFFIX)


def read(path: str | Path) -> list[dict]:
    """The raw entries, in file order, without checking them against anything."""
    path = Path(path)
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    schema = raw.get("schema")
    if schema != SCHEMA:
        raise ValueError(f"{path} is schema {schema}, and this reads schema {SCHEMA}")
    return list(raw.get("step", []))


def problems(entries: list[dict], steps) -> list[str]:
    """Every way a notes file and a recording can disagree, in the order a person would fix them."""
    out = []
    by_number = {one.number: one for one in steps}
    for entry in entries:
        number = entry.get("number")
        wanted = str(entry.get("command", ""))
        if number not in by_number:
            out.append(
                f"a note is written for step {number}, and the recording has no step {number}"
            )
            continue
        if not wanted:
            out.append(f"the note on step {number} does not say which command it belongs to")
            continue
        got = by_number[number].command
        if got != wanted:
            out.append(
                f"the note on step {number} says it belongs to {wanted!r}, and step {number} of "
                f"the recording is {got!r}"
            )
        if not str(entry.get("note", "")).strip():
            out.append(f"the note on step {number} is empty")
    return out


def for_steps(path: str | Path, steps) -> dict[int, str]:
    """The notes as a mapping from step number to sentence, refusing any that have drifted."""
    entries = read(path)
    wrong = problems(entries, steps)
    if wrong:
        joined = "\n  ".join(wrong)
        raise ValueError(f"{path} does not match the recording it annotates:\n  {joined}")
    return {one["number"]: str(one["note"]).strip() for one in entries}
