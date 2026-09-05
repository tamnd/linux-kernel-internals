"""One line, fifty two fields, and the oldest parsing trap in /proc.

    from kxray.proc import pidstat

    stat = pidstat.parse_file("corpora/proc/tier0/odd-comm-stat.txt", "/proc/self/stat")
    print(stat.state, stat.naive_state)

`/proc/<pid>/stat` is the file behind `ps`, behind `top`, and behind most of the process metrics
anything has ever collected. It is one line of space separated values, so the obvious way to read
it is `line.split()`, and that is wrong.

The second field is the command name and the kernel prints it in brackets without escaping it.
Command names come from the filename of whatever was executed, so they can contain spaces, and
they can contain a closing bracket. Here is a real line off the pinned box, from a process whose
executable is named `od) d ma`:

    37 (od) d ma) R 1 0 0 0 -1 4194304 37 0 0 0 0 1 0 0 20 0 1 0 265 ...

`line.split()` on that gives `37`, `(od)`, `d`, `ma)`, `R`, and everything after has slid two
places along. The state, which every reader of this file wants and which is meant to be field
three, is now `d`. Nothing raises. The numbers are all still numbers. A monitor reading this
would report a running process as being in a state that does not exist and carry on.

The fix is not clever and has been in `procps` for decades: the command is everything between the
first opening bracket and the last closing bracket, and the fields are what is left. `parse` does
that, and it also keeps what the naive split would have said, in `naive`, so a lesson can print
the two answers side by side instead of asking anybody to take this on trust.

`corpora/proc/tier0/odd-comm-stat.txt` is that capture. Making it needed a process with a name
like that, which on a busybox rootfs means a shell script, because busybox dispatches on its own
argv[0] and refuses to run under a name that is not an applet. The kernel takes `comm` from the
script's filename, so the script gets the name and the trap fires.

The field names come from Table 1-4 of `Documentation/filesystems/proc.rst`. That table is headed
"as of 2.6.30-rc7" and it still describes 7.2.2 correctly, all fifty two fields in the same order,
which is a good thing to sit with for a moment. This file has no entry under `Documentation/ABI`.
Nothing promises its shape. It has not moved a field in fifteen years regardless, because too much
depends on it, and that is what the rule about not breaking userspace looks like from the outside.
"""

from __future__ import annotations

from pathlib import Path

from kxray.models import READ, SKIPPED, STAT_FIELDS, UNPARSED, Lines, PidStat
from kxray.proc.stability import classify


def split_comm(text: str) -> tuple[str, str, str] | None:
    """The line in three parts: before the command, the command, after it.

    First opening bracket, last closing bracket. Not a regex, because the regex that gets this
    right is harder to read than the two index calls, and the one that is pleasant to read is the
    greedy one that gets it wrong.
    """
    opened = text.find("(")
    closed = text.rfind(")")
    if opened < 0 or closed < opened:
        return None
    return text[:opened], text[opened + 1 : closed], text[closed + 1 :]


def parse(text: str, path: str = "", source: str = "<text>") -> PidStat:
    """The one line, with the command lifted out before anything is split.

    Extra fields beyond the fifty two the documentation names go into `extra` rather than being
    dropped. The kernel has only ever appended to this line, so a newer kernel adding one is the
    expected way for this to change, and finding them in `extra` is how anybody would notice.
    """
    lines = Lines()
    body = text.strip()
    if not body:
        lines.count(SKIPPED)
        return PidStat(source=source, path=path, promise=classify(path), lines=lines)

    for _ in text.splitlines()[1:]:
        lines.count(SKIPPED)

    parts = split_comm(body)
    if parts is None:
        lines.count(UNPARSED)
        return PidStat(source=source, path=path, promise=classify(path), lines=lines)

    head, comm, tail = parts
    try:
        pid = int(head.strip())
    except ValueError:
        lines.count(UNPARSED)
        return PidStat(source=source, path=path, promise=classify(path), lines=lines)

    rest = tail.split()
    names = STAT_FIELDS[2:]
    values = dict(zip(names, rest, strict=False))
    extra = tuple(rest[len(names) :])
    lines.count(READ)
    return PidStat(
        source=source,
        path=path,
        promise=classify(path) if path else classify(""),
        lines=lines,
        pid=pid,
        comm=comm,
        values=values,
        extra=extra,
        naive=tuple(body.split()),
    )


def parse_file(path: Path | str, kernel_path: str = "") -> PidStat:
    found = Path(path)
    return parse(found.read_text(encoding="utf-8"), kernel_path, found.as_posix())


def account(text: str) -> Lines:
    return parse(text).lines


def trapped(stat: PidStat) -> bool:
    """Whether the naive split would have got this line wrong.

    True when the command name contains a space or a closing bracket, which is the whole of the
    trap. On almost every process on almost every machine this is False, and that is the reason
    the wrong parse keeps shipping.
    """
    return " " in stat.comm or ")" in stat.comm


def report(stat: PidStat) -> str:
    lines = [
        stat.banner(),
        f"pid:     {stat.pid}",
        f"comm:    {stat.comm!r}",
        f"state:   {stat.state}",
        f"fields:  {len(stat.values)} named, {len(stat.extra)} beyond what proc.rst lists",
    ]
    if trapped(stat):
        lines.append(f"naive:   a whitespace split would call the state {stat.naive_state!r}")
    else:
        lines.append("naive:   a whitespace split would have got this line right")
    text = "\n".join(lines)
    print(text)
    return text
