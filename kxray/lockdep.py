"""What lockdep says, and how to read it without guessing.

Lockdep is the kernel's lock order checker. It does not watch for a deadlock and report one after
the fact. It builds a graph of which lock class has ever been taken while which other lock class
was held, and it complains the moment adding an edge would close a cycle. That is why a report can
arrive on a machine that has never hung, and why the report is still real: the cycle is a property
of the code, and the hang is a property of the timing.

Three things are worth parsing, and this file does all three.

A splat is the report itself, the block that starts with `possible circular locking dependency
detected`. The important part is not the pretty scenario the kernel draws at the bottom, it is the
numbered dependency chain in the middle, because that is the graph. The chain is printed in reverse
order, highest number first, and the number matters: `#0` is the lock being acquired right now and
the highest number is the lock already held. Read the numbers upward and you have the path that
already existed. Add the edge from the held lock back to the acquired one and the path is a cycle.

`/proc/lockdep_stats` is the health of the checker itself. One line in it decides whether anything
else you read that boot means a thing: `debug_locks`. Lockdep switches itself off after the first
report, so a second bug in the same boot is not reported at all, and a clean run after a splat is
not evidence of anything.

`/proc/lockdep` is every lock class the kernel has seen, with the size of its forward and backward
dependency sets. Both files need `CONFIG_PROVE_LOCKING` and `CONFIG_LOCK_STAT` to be interesting,
and most distribution kernels ship with them off, which is a fact this file reports rather than
works around.
"""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from pathlib import Path

STATS = Path("/proc/lockdep_stats")
CLASSES = Path("/proc/lockdep")

BANNER = "possible circular locking dependency detected"

# The checker's own frames, plus the locking primitives. Every stack in a splat starts with some
# of these and none of them is a place a person can go and change anything.
PLUMBING = (
    "check_noncircular",
    "check_prev_add",
    "validate_chain",
    "__lock_acquire",
    "lock_acquire",
    "__mutex_lock",
    "mutex_lock",
    "_raw_spin_lock",
    "_raw_read_lock",
    "_raw_write_lock",
    "down_read",
    "down_write",
    "dump_stack",
)

# The other headline lockdep prints. Recognised so that a reader who pastes one in gets told what
# it is rather than told it is not a splat at all.
OTHER_BANNERS = (
    "possible recursive locking detected",
    "inconsistent lock state",
    "possible irq lock inversion dependency detected",
    "suspicious RCU usage",
)

# Everything the kernel log puts in front of a line before the line starts. A timestamp from
# printk, a facility marker from the raw device, or both.
NOISE = re.compile(r"^(?:<\d+>)?(?:\[\s*\d+\.\d+\]\s?)?")

# `(lock_a){+.+.}-{4:4}, at: thread_b+0x5a/0xd0 [abba]`, with the address sometimes in front of it.
LOCK = re.compile(
    r"^(?P<address>[0-9a-f]{8,16})?\s*"
    r"\((?P<name>[^)]+)\)"
    r"\{(?P<usage>[^}]*)\}"
    r"(?:-\{(?P<wait>[^}]*)\})?"
    r"(?:\s*,\s*at:\s*(?P<where>.+?))?$"
)

# `-> #1 (lock_b){+.+.}-{4:4}:`
LINK = re.compile(r"^->\s*#(?P<index>\d+)\s*\((?P<name>[^)]+)\)\{(?P<usage>[^}]*)\}")

# `kworker/1:2/153 is trying to acquire lock:`
WHO = re.compile(r"^(?P<task>\S+)/(?P<pid>\d+) is trying to acquire lock:")

# `ffffffff8a1b2c40 FD:   14 BD:    1 +.+.: &sb->s_type->i_mutex_key`
CLASS_LINE = re.compile(
    r"^(?P<address>[0-9a-f]{8,16})\s+FD:\s*(?P<fd>\d+)\s+BD:\s*(?P<bd>\d+)\s+"
    r"(?P<usage>\S+):\s+(?P<name>.+?)\s*$"
)

# ` lock-classes:      1024 [max: 8192]`
STAT_LINE = re.compile(
    r"^\s*(?P<name>[a-z0-9 _,+/()#-]+?):\s+(?P<value>\d+)"
    r"(?:\s+\[max:\s*(?P<max>\d+)\])?\s*$"
)


class Truncated(ValueError):
    """The text has a splat in it and the splat is not all there.

    This is a separate error because a half copied splat is the normal failure. People select from
    the banner to somewhere in the middle of the stack traces and paste that. Filling in the
    missing half from what the rest of the text implies would be inventing a lock ordering, and an
    invented lock ordering is worse than no answer at all.
    """


class NotASplat(ValueError):
    """The text is not a circular locking report."""


def unprefix(line: str) -> str:
    """One log line without the printk timestamp in front of it."""
    return NOISE.sub("", line).rstrip()


@dataclass(frozen=True)
class LockRef:
    """One lock as the header of a splat names it."""

    name: str
    usage: str = ""
    wait: str = ""
    where: str = ""
    address: str = ""

    @property
    def function(self) -> str:
        """The function the lock was taken in, with the offset and the module dropped."""
        return self.where.split("+")[0].strip() if self.where else ""

    def __str__(self) -> str:
        at = f", at: {self.where}" if self.where else ""
        return f"{self.name}{{{self.usage}}}{at}"


@dataclass(frozen=True)
class Link:
    """One numbered entry of the dependency chain, with the stack that recorded it.

    The stack is the useful half. It is not where the deadlock would happen, it is where the kernel
    learned this edge, which is usually a completely different code path in a completely different
    subsystem written by somebody who has never heard of the other one.
    """

    index: int
    name: str
    usage: str
    stack: tuple[str, ...] = ()

    @property
    def taken_in(self) -> str:
        """The first frame that is not lockdep's own machinery, which is the real caller.

        The top of one of these stacks is always the checker and the lock primitive, and neither
        of those is a place anybody can go and fix something. The frame worth printing is the
        first one below them.
        """
        for frame in self.stack:
            if not frame.startswith(PLUMBING):
                return frame
        return self.stack[-1] if self.stack else ""


@dataclass(frozen=True)
class Scenario:
    """The picture the kernel draws under `Possible unsafe locking scenario`.

    This is a rendering, not evidence. The kernel produces it from the same chain that produced the
    cycle, so it can never disagree with the chain, and reading it instead of the chain is how
    people end up believing lockdep watched two CPUs do this. It did not. Nothing here happened.
    """

    columns: tuple[str, ...] = ()
    steps: tuple[tuple[int, str], ...] = ()

    def column(self, index: int) -> list[str]:
        return [text for where, text in self.steps if where == index]

    def __str__(self) -> str:
        if not self.columns:
            return ""
        width = 26
        lines = ["".join(name.ljust(width) for name in self.columns)]
        lines.append("".join("----".ljust(width) for _ in self.columns))
        for where, text in self.steps:
            lines.append(" " * (width * where) + text)
        return "\n".join(lines)


@dataclass(frozen=True)
class Splat:
    """One circular locking dependency report."""

    task: str = ""
    pid: int = 0
    kernel: str = ""
    tainted: str = ""
    acquiring: LockRef | None = None
    holding: LockRef | None = None
    chain: tuple[Link, ...] = ()
    scenario: Scenario | None = None
    source: str = "<text>"

    @property
    def cycle(self) -> tuple[str, ...]:
        """The lock classes in the order the edges run, closing back on the first one.

        Taken from the numbered chain and from nothing else. The chain prints highest number first
        and the edges run the other way, so this walks the numbers upward and then adds the edge
        the kernel was about to record, which is the one that closes the loop.
        """
        names = [link.name for link in sorted(self.chain, key=lambda one: one.index)]
        return tuple(names + names[:1])

    @property
    def classes(self) -> tuple[str, ...]:
        """Each lock class once, in cycle order."""
        return self.cycle[:-1]

    @property
    def length(self) -> int:
        """How many locks are in the cycle.

        Two is the AB-BA everybody draws, and it is not the limit. Longer ones are common.
        """
        return len(self.classes)

    def link(self, name: str) -> Link:
        for one in self.chain:
            if one.name == name:
                return one
        raise KeyError(f"no lock called {name!r} in this chain")

    def edges(self) -> list[tuple[str, str]]:
        """The cycle as pairs, so it can be drawn or compared without reformatting text."""
        return list(zip(self.cycle[:-1], self.cycle[1:], strict=True))

    def summary(self) -> str:
        first = self.acquiring.name if self.acquiring else "?"
        held = self.holding.name if self.holding else "?"
        lines = [
            f"{self.task}/{self.pid} on kernel {self.kernel or 'unknown'}",
            f"holding {held}, acquiring {first}",
            f"cycle of {self.length}: " + " -> ".join(self.cycle),
        ]
        for one in sorted(self.chain, key=lambda link: link.index):
            lines.append(f"  #{one.index} {one.name} recorded in {one.taken_in or 'unknown'}")
        return "\n".join(lines)


def _lock(line: str) -> LockRef | None:
    found = LOCK.match(line.strip())
    if found is None:
        return None
    return LockRef(
        name=found["name"].strip(),
        usage=found["usage"] or "",
        wait=found["wait"] or "",
        where=(found["where"] or "").strip(),
        address=found["address"] or "",
    )


def _next_lock(lines: list[str], start: int, limit: int = 4) -> LockRef | None:
    """The first lock line within a few lines of a header, skipping the blanks in between."""
    for line in lines[start : start + limit]:
        found = _lock(line)
        if found is not None:
            return found
    return None


def _scenario(lines: list[str], start: int) -> Scenario | None:
    """The CPU columns under `Possible unsafe locking scenario`, if the paste got that far."""
    header = None
    for offset, line in enumerate(lines[start : start + 8]):
        if re.match(r"^\s*CPU\d", line):
            header = start + offset
            break
    if header is None:
        return None

    names = lines[header].split()
    starts = [lines[header].index(name) for name in names]
    steps: list[tuple[int, str]] = []
    for line in lines[header + 1 :]:
        text = line.strip()
        if "DEADLOCK" in text:
            break
        if not text or set(text) <= {"-"}:
            continue
        if not text.startswith(("lock(", "rlock(", "wlock(")):
            continue
        # Whichever column header this line sits closest to. The kernel indents the steps a couple
        # of characters to the left of the header they belong to, so nearest wins and a rule about
        # exact columns would not survive the first splat with three CPUs in it.
        at = line.index(text)
        column = min(range(len(starts)), key=lambda i: abs(at - starts[i]))
        steps.append((column, text))
    return Scenario(tuple(names), tuple(steps))


def parse_splat(text: str, source: str = "<text>") -> Splat:
    """One splat, or an error saying which half is missing.

    Nothing here is inferred. If the header says a lock is being acquired and the chain has no
    entry for that lock, this raises instead of picking the closest name, because the whole value
    of a lock order report is that somebody can act on it without checking it first.
    """
    lines = [unprefix(line) for line in text.splitlines()]
    body = "\n".join(lines)

    if BANNER not in body:
        for other in OTHER_BANNERS:
            if other in body:
                raise NotASplat(f"this is a lockdep report, and it is a {other!r} one, not a cycle")
        raise NotASplat(f"no {BANNER!r} line, so this is not a circular locking report")

    banner_at = next(i for i, line in enumerate(lines) if BANNER in line)
    kernel, tainted = "", ""
    for line in lines[banner_at + 1 : banner_at + 3]:
        version = re.match(r"^(\S+)\s+#\d+\s*(.*)$", line.strip())
        if version:
            kernel, tainted = version[1], version[2].strip()
            break

    task, pid, acquiring, holding = "", 0, None, None
    chain: list[Link] = []
    scenario = None
    current: Link | None = None
    stack: list[str] = []

    def close() -> None:
        nonlocal current, stack
        if current is not None:
            chain.append(Link(current.index, current.name, current.usage, tuple(stack)))
        current, stack = None, []

    for index, line in enumerate(lines):
        who = WHO.match(line.strip())
        if who:
            task, pid = who["task"], int(who["pid"])
            acquiring = _next_lock(lines, index + 1)
            continue
        if line.strip().startswith("but task is already holding lock:"):
            holding = _next_lock(lines, index + 1)
            continue

        link = LINK.match(line.strip())
        if link:
            close()
            current = Link(int(link["index"]), link["name"].strip(), link["usage"])
            continue
        if current is not None:
            frame = line.strip()
            if not frame or frame.startswith(("other info", "->", "stack backtrace")):
                close()
            elif re.match(r"^[\w.$]+\+0x[0-9a-f]+/0x[0-9a-f]+", frame):
                stack.append(frame)
            continue

        if "unsafe locking scenario" in line:
            scenario = _scenario(lines, index + 1)
    close()

    if acquiring is None:
        raise Truncated("no `is trying to acquire lock` line with a lock under it")
    if holding is None:
        raise Truncated("no `but task is already holding lock` line with a lock under it")
    if len(chain) < 2:
        raise Truncated(f"a cycle needs at least two locks and the chain has {len(chain)}")

    ordered = sorted(chain, key=lambda one: one.index)
    if [one.index for one in ordered] != list(range(len(ordered))):
        raise Truncated("the numbered chain has a gap in it, so part of the cycle was cut off")
    if ordered[0].name != acquiring.name:
        raise Truncated(f"#0 is {ordered[0].name!r} and the header is acquiring {acquiring.name!r}")
    if ordered[-1].name != holding.name:
        raise Truncated(
            f"the top of the chain is {ordered[-1].name!r} and the task holds {holding.name!r}"
        )

    return Splat(
        task=task,
        pid=pid,
        kernel=kernel,
        tainted=tainted,
        acquiring=acquiring,
        holding=holding,
        chain=tuple(ordered),
        scenario=scenario,
        source=source,
    )


def splats(text: str, source: str = "<text>") -> list[Splat]:
    """Every complete splat in a log, with the incomplete ones left out.

    A dmesg buffer is a ring, so the first splat in it is usually missing its top. That one is
    dropped rather than repaired. Everything that parses cleanly comes back.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if BANNER in line]
    found = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        chunk = "\n".join(lines[max(start - 2, 0) : end])
        try:
            found.append(parse_splat(chunk, source))
        except (Truncated, NotASplat):
            continue
    return found


@dataclass(frozen=True)
class Stats:
    """`/proc/lockdep_stats`, as numbers rather than as a wall of text."""

    values: dict[str, int]
    maxima: dict[str, int]
    source: str = "<text>"

    @property
    def debug_locks(self) -> int | None:
        return self.values.get("debug_locks")

    @property
    def off(self) -> bool:
        """Whether lockdep has switched itself off.

        It does that after the first report of the boot, and after that it checks nothing. A run
        with no splat in it, on a machine where this is true, is not evidence that the code is
        clean. It is evidence that nobody was looking.
        """
        return self.debug_locks == 0

    def headroom(self, name: str) -> float | None:
        """How much of a limit is used, from 0 to 1, or None when the line has no limit."""
        if name not in self.values or name not in self.maxima or not self.maxima[name]:
            return None
        return self.values[name] / self.maxima[name]

    def near_limits(self, threshold: float = 0.9) -> list[tuple[str, float]]:
        """Every table that is close to full, worst first.

        Running one of these out is not a warning, it turns lockdep off for the rest of the boot,
        which is the same silence as a splat having already fired.
        """
        close = []
        for name in self.maxima:
            used = self.headroom(name)
            if used is not None and used >= threshold:
                close.append((name, used))
        return sorted(close, key=lambda pair: -pair[1])

    def __str__(self) -> str:
        lines = []
        for name, value in self.values.items():
            limit = f" of {self.maxima[name]}" if name in self.maxima else ""
            lines.append(f"{name}: {value}{limit}")
        return "\n".join(lines)


def parse_stats(text: str, source: str = "<text>") -> Stats:
    values: dict[str, int] = {}
    maxima: dict[str, int] = {}
    for line in text.splitlines():
        found = STAT_LINE.match(unprefix(line))
        if found is None:
            continue
        # One spelling for a key. The file writes some names with spaces and some with hyphens,
        # and a reader should not have to remember which is which to ask for a number.
        name = found["name"].strip().replace(" ", "_").replace("-", "_")
        values[name] = int(found["value"])
        if found["max"]:
            maxima[name] = int(found["max"])
    return Stats(values, maxima, source)


@dataclass(frozen=True)
class LockClass:
    """One line of `/proc/lockdep`.

    A class is not a lock. Every mutex initialised by the same line of source shares one class, and
    the whole checker works on classes, which is why a report about `&inode->i_mutex` is about
    every inode in the machine at once and not about the one you were holding.
    """

    address: str
    forward: int
    backward: int
    usage: str
    name: str

    @property
    def subclass(self) -> str:
        """The `#3` suffix lockdep adds when a class was split by nesting, or an empty string."""
        return self.name.split("#")[1] if "#" in self.name else ""


def parse_classes(text: str, limit: int | None = None) -> list[LockClass]:
    found = []
    for line in text.splitlines():
        one = CLASS_LINE.match(unprefix(line))
        if one is None:
            continue
        found.append(
            LockClass(one["address"], int(one["fd"]), int(one["bd"]), one["usage"], one["name"])
        )
        if limit is not None and len(found) >= limit:
            break
    return found


def busiest(classes: list[LockClass], count: int = 10) -> list[LockClass]:
    """The classes with the most locks reachable from them, which are the ones worth reading."""
    return sorted(classes, key=lambda one: -one.forward)[:count]


def available(path: Path = STATS) -> bool:
    try:
        with path.open("rb") as handle:
            handle.read(1)
    except OSError:
        return False
    return True


def explain(path: Path = STATS) -> str:
    """Why this machine has no lockdep, in the order worth checking."""
    if platform.system() != "Linux":
        return f"this is {platform.system()}, and lockdep is a Linux kernel feature"
    if not path.exists():
        return f"{path} is not there, so this kernel was built without CONFIG_PROVE_LOCKING"
    if not available(path):
        return f"{path} exists and cannot be read here"
    return "lockdep is built in and its statistics are readable"


def read_stats(path: Path = STATS) -> Stats | None:
    if not available(path):
        return None
    return parse_stats(path.read_text(errors="replace"), str(path))


def report(path: Path = STATS) -> str:
    """Whether the checker on this machine is on, off, or absent. Printed at the top of a lesson."""
    lines = [f"system:  {platform.system()} {platform.release()}"]
    stats = read_stats(path)
    if stats is not None:
        lines.append(f"classes: {stats.values.get('lock_classes', 0)} lock classes seen so far")
        lines.append(f"edges:   {stats.values.get('direct_dependencies', 0)} direct dependencies")
        state = "off, so nothing is being checked" if stats.off else "on"
        lines.append(f"checker: {state}")
        for name, used in stats.near_limits():
            lines.append(f"warning: {name} is {used:.0%} full")
    lines.append(f"status:  {explain(path)}")
    text = "\n".join(lines)
    print(text)
    return text
