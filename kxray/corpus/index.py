"""Which reader opens which artefact, and one way to ask for any of them.

    from kxray.corpus import index

    one = index.get("traces/tier0/write-1byte")
    print(one.kind, one.meta["describes"])
    print(index.read(one).found, "frames")

`corpora/` holds forty odd files that came off real kernels, and no two kinds of them are read the
same way. A trace goes through `kxray.trace`, a splat through `kxray.lockdep`, a recorded session
through `kxray.replay`, and the `/proc` files each need to be told which file in `/proc` they are a
copy of before they mean anything. Anybody who wants to open one has to know all of that.

This module knows it once. Give it an id and it hands back the artefact with its metadata attached
and the name of the reader that opens it, and `read` will run that reader for you.

## Why the id is the path

An artefact's id is its path under `corpora/` with the suffix dropped, so `traces/tier0/write-1byte`
is `corpora/traces/tier0/write-1byte.txt`. That is not the shortest name it could have had. It is
the name every lesson, blueprint and test in this repository already uses, because they all name
these files by path, and a shorter id would have meant a migration and a period where two names for
the same file were both correct.

## Routing by name, and why that is not as fragile as it sounds

`ROUTES` matches on the path. That looks like the sort of thing that breaks the first time somebody
names a file badly, and it would be, except that an artefact with no route is an error rather than
an omission: `survey` raises, the baseline fails, and CI goes red. A file cannot quietly land in
`corpora/` and be read by nothing. The naming convention is enforced by the thing that depends on
it, which is the only kind of convention that holds.

Two orderings in that table are load bearing and both have a comment on them.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from kxray import kallsyms, lockdep, tracefs
from kxray.btf import reader as btf
from kxray.models import Lines
from kxray.proc import keyed as proc_keyed
from kxray.proc import maps as proc_maps
from kxray.proc import percpu as proc_percpu
from kxray.proc import pidstat as proc_pidstat
from kxray.proc import version as proc_version
from kxray.replay import cast as replay_cast
from kxray.replay import session as replay_session
from kxray.source import kconfig as source_kconfig
from kxray.source import maintainers as source_maintainers
from kxray.source import syscalls as source_syscalls
from kxray.trace import events, formats, parse_file
from kxray.trace import function as trace_function

CORPORA = Path("corpora")

# Which reader opens which artefact, first match winning. This table is the answer to "what reads
# this file", and it is here rather than in each artefact's metadata so that the whole mapping can
# be read at once.
ROUTES = (
    # Both tracers write `.txt` into the same directory and the file name is the only thing that
    # tells them apart, so the narrower pattern has to come first. `flat-` on the front of a
    # capture means the flat function tracer took it.
    ("traces/*/flat-*.txt", "function"),
    ("traces/*/events-*.txt", "events"),
    ("traces/*/*.txt", "function_graph"),
    ("events/*/*.format", "event-format"),
    ("proc/*/kallsyms.txt", "kallsyms"),
    ("proc/*/kallsyms-*.txt", "kallsyms"),
    ("proc/*/lockdep.txt", "lockdep-classes"),
    ("proc/*/lockdep_stats.txt", "lockdep-stats"),
    ("proc/*/lockdep-stats-*.txt", "lockdep-stats"),
    ("proc/*/ring-overrun.txt", "tracefs-stats"),
    # The rest of /proc, routed by what the file is rather than by what it is called, which is why
    # `self-status.txt` and `meminfo.txt` land on the same reader and `self-stat.txt` does not. The
    # lockdep patterns above have to stay in front of the `*-stat.txt` one.
    ("proc/*/version.txt", "proc-version"),
    ("proc/*/meminfo.txt", "proc-keyed"),
    ("proc/*/self-status.txt", "proc-keyed"),
    ("proc/*/interrupts.txt", "proc-percpu"),
    ("proc/*/softirqs.txt", "proc-percpu"),
    ("proc/*/self-maps.txt", "proc-maps"),
    ("proc/*/*-stat.txt", "proc-pidstat"),
    # Files out of the pinned tarball rather than off a running kernel. `read_write.c` has no
    # reader here on purpose: kxray.source.symbols opens it with a name to look for, so there is no
    # whole file count to take, and saying so is better than inventing one.
    ("source/*/MAINTAINERS*", "maintainers"),
    ("source/*/*.tbl", "syscall-table"),
    ("source/*/Kconfig*", "kconfig-source"),
    ("source/*/*.c", "none"),
    ("oops/*/*.txt", "lockdep-splat"),
    ("btf/*/*.btf", "btf"),
    ("experiments/*/*.txt", "none"),
    ("replays/*/*.cast", "cast"),
)


@dataclass(frozen=True)
class Artefact:
    """One committed capture, with its metadata already loaded."""

    id: str
    path: Path
    kind: str
    meta: dict

    @property
    def tier(self) -> int | None:
        """0 if a browser produced it, 1 if a real machine did, None if the file does not say."""
        value = self.meta.get("tier")
        return int(value) if isinstance(value, int) else None

    @property
    def kernel(self) -> str:
        return str(self.meta.get("kernel", ""))

    @property
    def describes(self) -> str:
        return str(self.meta.get("describes", ""))

    @property
    def kernel_path(self) -> str:
        """Which file in /proc this is a copy of, empty for everything that is not a copy of one.

        The `/proc` readers need it, because what a file is called on disk does not decide how it
        is read or what it is worth. `self-maps.txt` is `/proc/self/maps`, and only the second of
        those two names reaches the stability ledger.
        """
        return str(self.meta.get("path", ""))

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class Reading:
    """What one reader got out of one artefact.

    `found` is whatever that reader counts: frames from a trace, symbols from kallsyms, steps from
    a recorded session. `lines` is the file's own line count, and `accounted` is where those lines
    went, for the readers that account for lines at all. The two are separate on purpose. A reader
    can go on finding the same number of things while quietly reading fewer of the lines it was
    given, and that is the drift `tools.baseline` exists to catch.
    """

    artefact: Artefact
    found: int
    lines: int
    accounted: Lines | None

    @property
    def path(self) -> str:
        return self.artefact.path.as_posix()

    @property
    def reader(self) -> str:
        return self.artefact.kind

    def adds_up(self) -> bool:
        return self.accounted is None or self.accounted.total == self.lines


def _function_graph(one: Artefact) -> tuple[int, Lines | None]:
    tape = parse_file(one.path)
    return tape.frame_count, tape.lines


def _function_flat(one: Artefact) -> tuple[int, Lines | None]:
    log = trace_function.parse_file(one.path)
    return len(log.calls), log.lines


def _events(one: Artefact) -> tuple[int, Lines | None]:
    # Read through every format in the corpus rather than through none, because an event that
    # stops binding to its format is exactly the drift this file exists to catch, and a reader
    # given no formats would not notice.
    log = events.parse_file(one.path, formats.load(CORPORA / "events" / "tier0"))
    return len(log.events), log.lines


def _event_format(one: Artefact) -> tuple[int, Lines | None]:
    return len(formats.parse_file(one.path).fields), formats.account(one.text())


def _proc_keyed(one: Artefact) -> tuple[int, Lines | None]:
    found = proc_keyed.parse_file(one.path, one.kernel_path)
    return len(found.entries), found.lines


def _proc_percpu(one: Artefact) -> tuple[int, Lines | None]:
    found = proc_percpu.parse_file(one.path, one.kernel_path)
    return len(found.counters), found.lines


def _proc_maps(one: Artefact) -> tuple[int, Lines | None]:
    found = proc_maps.parse_file(one.path, one.kernel_path)
    return len(found.regions), found.lines


def _proc_pidstat(one: Artefact) -> tuple[int, Lines | None]:
    found = proc_pidstat.parse_file(one.path, one.kernel_path)
    # The named fields rather than one, because one line that read is not the number that would
    # move. A kernel that appends a field puts it in `extra`, and counting the named ones plus the
    # extras is how that shows up here at all.
    return len(found.values) + len(found.extra), found.lines


def _proc_version(one: Artefact) -> tuple[int, Lines | None]:
    found = proc_version.parse_file(one.path, one.kernel_path)
    return len(found.parts), found.lines


def _maintainers(one: Artefact) -> tuple[int, Lines | None]:
    found = source_maintainers.parse(one.text(), source=one.path.as_posix())
    return len(found.sections), found.lines


def _syscall_table(one: Artefact) -> tuple[int, Lines | None]:
    found = source_syscalls.parse(one.text(), source=one.path.as_posix())
    return len(found.calls), found.lines


def _kconfig_source(one: Artefact) -> tuple[int, Lines | None]:
    found = source_kconfig.parse(one.text(), source=one.path.as_posix())
    return len(found.symbols), found.lines


def _kallsyms(one: Artefact) -> tuple[int, Lines | None]:
    text = one.text()
    return len(kallsyms.parse(text)), kallsyms.account(text)


def _lockdep_classes(one: Artefact) -> tuple[int, Lines | None]:
    text = one.text()
    return len(lockdep.parse_classes(text)), lockdep.account_classes(text)


def _lockdep_stats(one: Artefact) -> tuple[int, Lines | None]:
    text = one.text()
    return len(lockdep.parse_stats(text).values), lockdep.account_stats(text)


def _tracefs_stats(one: Artefact) -> tuple[int, Lines | None]:
    text = one.text()
    return len(tracefs.parse_stats(text)), tracefs.account_stats(text)


def _lockdep_splat(one: Artefact) -> tuple[int, Lines | None]:
    # A splat is a report spread over many lines rather than a file of rows, so there is no line
    # accounting to do. What is worth pinning is how many complete ones come out, because the
    # incomplete ones are dropped on purpose and a change there would be silent too.
    return len(lockdep.splats(one.text())), None


def _btf(one: Artefact) -> tuple[int, Lines | None]:
    # BTF is bytes, so it has no lines. The type count is the thing that would move. Index zero is
    # the void every BTF blob starts with rather than a type anybody declared, so it is not counted,
    # which is also how the artefact's own metadata counts them.
    return len(btf.parse_file(one.path).types) - 1, None


def _cast(one: Artefact) -> tuple[int, Lines | None]:
    # A recorded session. The number worth pinning is how many steps come out of it, because the
    # steps are found from marks in the middle of the byte stream rather than from the shape of a
    # line, and a change to that walk would leave the line counts alone and quietly halve the
    # walkthrough.
    found = replay_cast.parse_file(one.path)
    return len(replay_session.steps_of(found)), found.lines


def _unread(one: Artefact) -> tuple[int, Lines | None]:
    # An artefact a person reads and no parser does. Its line count is still pinned, so a truncated
    # file is caught even here.
    return 0, None


READERS = {
    "function_graph": _function_graph,
    "function": _function_flat,
    "events": _events,
    "event-format": _event_format,
    "proc-keyed": _proc_keyed,
    "proc-percpu": _proc_percpu,
    "proc-maps": _proc_maps,
    "proc-pidstat": _proc_pidstat,
    "proc-version": _proc_version,
    "maintainers": _maintainers,
    "syscall-table": _syscall_table,
    "kconfig-source": _kconfig_source,
    "kallsyms": _kallsyms,
    "lockdep-classes": _lockdep_classes,
    "lockdep-stats": _lockdep_stats,
    "tracefs-stats": _tracefs_stats,
    "lockdep-splat": _lockdep_splat,
    "btf": _btf,
    "cast": _cast,
    "none": _unread,
}

# Readers that are handed bytes rather than text, so there is no line count to take.
BINARY = ("btf",)


def identify(path: Path, root: Path = CORPORA) -> str:
    """The id of an artefact at this path, which is its path under `corpora/` with no suffix."""
    return path.relative_to(root).with_suffix("").as_posix()


def route(path: Path, root: Path = CORPORA) -> str | None:
    """Which reader opens this artefact, or None when nothing claims it."""
    name = path.relative_to(root).as_posix()
    return next((reader for pattern, reader in ROUTES if fnmatch(name, pattern)), None)


def _meta(path: Path) -> dict:
    meta = path.with_suffix(".meta.toml")
    if not meta.exists():
        return {}
    return tomllib.loads(meta.read_text(encoding="utf-8"))


def at(path: Path, root: Path = CORPORA) -> Artefact:
    """The artefact at this path. Raises if nothing in `ROUTES` claims it."""
    kind = route(path, root)
    if kind is None:
        raise LookupError(f"{path} has no reader in kxray/corpus/index.py")
    return Artefact(identify(path, root), path, kind, _meta(path))


def find(root: Path = CORPORA) -> list[Artefact]:
    """Every committed artefact, which means every file with a `.meta.toml` beside it.

    A capture with no metadata beside it is a file somebody dropped in and has not said anything
    about yet, and this deliberately does not find it. The metadata file is how an artefact becomes
    part of the corpus rather than a file in the same directory as one.
    """
    return [
        at(one, root)
        for one in sorted(root.rglob("*"))
        if one.is_file() and one.suffix != ".toml" and one.with_suffix(".meta.toml").exists()
    ]


def get(id: str, root: Path = CORPORA) -> Artefact:
    """One artefact by id. Raises with the near misses listed, because ids are typed by hand."""
    found = {one.id: one for one in find(root)}
    if id in found:
        return found[id]
    near = [one for one in sorted(found) if id.split("/")[-1] in one]
    ending = f", did you mean {' or '.join(near)}" if near else ""
    raise LookupError(f"no artefact called {id!r} in {root}{ending}")


def read(one: Artefact) -> Reading:
    """Run this artefact's own reader over it."""
    found, accounted = READERS[one.kind](one)
    lines = 0 if one.kind in BINARY else len(one.text().splitlines())
    return Reading(one, found, lines, accounted)


def survey(root: Path = CORPORA) -> list[Reading]:
    """Read the whole corpus. Raises if anything in it has no reader."""
    return [read(one) for one in find(root)]
