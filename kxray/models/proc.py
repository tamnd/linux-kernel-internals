"""What comes out of `/proc` and `/sys`, and what the kernel promises about it.

Every one of these carries the promise the kernel tree makes about the file it was read from,
because most of these files are not promised anything at all and a reader should be told that
before they lean on one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kxray.models.lines import Lines, grid

# The four levels Documentation/ABI/README defines, one directory each.
STABLE = "stable"
TESTING = "testing"
OBSOLETE = "obsolete"
REMOVED = "removed"

# The two levels that are not in that README as directories but are the honest answer for most of
# what this project reads.
#
# UNDOCUMENTED means no file under Documentation/ABI describes this path. That is not the same as
# being unstable. Almost all of /proc is here, including every file in this corpus, and the rule
# that userspace does not get broken still applies to them in practice. What is missing is the
# written promise, which means nobody has said what part of the file you may depend on.
#
# NOT_ABI is stronger and rarer. Documentation/ABI/README has a closing section that names two
# things as "notable bits of non-ABI, which should not under any circumstances be considered
# stable", and this project reads both of them.
UNDOCUMENTED = "undocumented"
NOT_ABI = "not-abi"

LEVELS = (STABLE, TESTING, OBSOLETE, REMOVED, UNDOCUMENTED, NOT_ABI)


@dataclass(frozen=True)
class Promise:
    """What the kernel tree says about one path, and where it says it.

    This exists so that a parser cannot report a value without also reporting what kind of value
    it is. A number off `/sys/kernel/btf/vmlinux` and a number off `/proc/kallsyms` look the same
    coming out of Python and they are not the same kind of fact: one has a documented interface
    behind it and the other is explicitly named as something you must not depend on.

    `entry` is the file in the kernel source that carries the claim, so any of this can be
    checked rather than believed.
    """

    kind: str
    entry: str = ""
    note: str = ""
    pattern: str = ""

    @property
    def documented(self) -> bool:
        """Whether anything under Documentation/ABI describes this path at all."""
        return self.kind in (STABLE, TESTING, OBSOLETE, REMOVED)

    @property
    def dependable(self) -> bool:
        """Whether a tool may rest on the shape of this file across kernels.

        True only for `stable` and `testing`, which are the two levels whose README text says
        userspace may rely on them. Everything else is a maybe, and a maybe dressed up as a yes is
        how a tool ends up quietly wrong on somebody else's machine.
        """
        return self.kind in (STABLE, TESTING)

    def __str__(self) -> str:
        where = f" ({self.entry})" if self.entry else ""
        return f"{self.kind}{where}"


@dataclass
class ProcFile:
    """One file out of /proc or /sys, read.

    Every reader in `kxray.proc` returns something built on this, so `path` and `promise` are
    always there to be printed next to whatever was found.
    """

    source: str = "<text>"
    path: str = ""
    promise: Promise = field(default_factory=lambda: Promise(UNDOCUMENTED))
    lines: Lines = field(default_factory=Lines)

    def banner(self) -> str:
        """One line saying where this came from and what it is worth."""
        return f"{self.path or self.source}: {self.promise}"


@dataclass(frozen=True)
class KeyValue:
    """One `Key: value` line, with the value left as the words the kernel wrote.

    `values` is a tuple rather than a string because the kernel does not stick to one value per
    key. `Uid:` in `/proc/self/status` has four of them, `State:` has a letter and a word in
    brackets, and `MemTotal:` has a number and a unit. A model with a single `value: int` on it
    would have to throw two of those three away.
    """

    key: str
    values: tuple[str, ...]
    unit: str = ""
    line: int = 0

    @property
    def text(self) -> str:
        return " ".join(self.values)

    @property
    def number(self) -> int | None:
        """The value as an integer, when there is exactly one and it is one.

        None for `State: R (running)` and for `Uid: 0 0 0 0`, on purpose. A caller that wants a
        number out of those has to say which part it means.
        """
        if len(self.values) != 1:
            return None
        try:
            return int(self.values[0], 0)
        except ValueError:
            return None

    def __str__(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        return f"{self.key}: {self.text}{unit}"


@dataclass
class KeyedFile(ProcFile):
    """A whole file of `Key: value` lines, in the order the kernel printed them."""

    entries: tuple[KeyValue, ...] = ()

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(one.key for one in self.entries)

    def get(self, key: str) -> KeyValue | None:
        return next((one for one in self.entries if one.key == key), None)

    def number(self, key: str) -> int | None:
        found = self.get(key)
        return found.number if found is not None else None

    def __getitem__(self, key: str) -> KeyValue:
        found = self.get(key)
        if found is None:
            raise KeyError(f"{self.path} has no {key} line on this kernel")
        return found

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def table(self, *keys: str) -> str:
        wanted = [one for one in self.entries if not keys or one.key in keys]
        rows = [("key", "value", "unit")]
        rows += [(one.key, one.text, one.unit) for one in wanted]
        return grid(rows)


@dataclass(frozen=True)
class Counter:
    """One row of a file that counts something once per CPU.

    `/proc/interrupts` and `/proc/softirqs` are the same shape: a label, then one number for each
    CPU, then in the interrupts case some text saying what the line is about.
    """

    label: str
    counts: tuple[int, ...] = ()
    detail: str = ""
    line: int = 0

    @property
    def total(self) -> int:
        return sum(self.counts)

    @property
    def fired(self) -> bool:
        return self.total > 0

    def on(self, cpu: int) -> int:
        return self.counts[cpu]

    def __str__(self) -> str:
        detail = f"  {self.detail}" if self.detail else ""
        return f"{self.label}: {self.total}{detail}"


@dataclass
class CounterFile(ProcFile):
    """A whole per CPU counter file.

    `cpus` comes off the header row rather than from anywhere else, because the number of columns
    is the number of CPUs the kernel is willing to print and nothing else knows that number. A
    reader that assumed one column would misread every desktop and a reader that assumed the
    machine's CPU count would misread a kernel that prints only the online ones.
    """

    cpus: tuple[str, ...] = ()
    counters: tuple[Counter, ...] = ()

    @property
    def cpu_count(self) -> int:
        return len(self.cpus)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(one.label for one in self.counters)

    def get(self, label: str) -> Counter | None:
        return next((one for one in self.counters if one.label == label), None)

    def total(self, label: str) -> int:
        found = self.get(label)
        return found.total if found is not None else 0

    def busiest(self, limit: int = 5) -> list[Counter]:
        return sorted(self.counters, key=lambda one: -one.total)[:limit]

    def quiet(self) -> list[Counter]:
        """The rows that never fired, which on a small machine is most of them."""
        return [one for one in self.counters if not one.fired]

    def table(self, limit: int = 0) -> str:
        wanted = self.busiest(limit) if limit else list(self.counters)
        rows = [("label", *self.cpus, "detail")]
        for one in wanted:
            rows.append((one.label, *[str(count) for count in one.counts], one.detail))
        return grid(rows)


@dataclass(frozen=True)
class Region:
    """One mapping in an address space, as `/proc/<pid>/maps` prints it."""

    start: int
    end: int
    perms: str
    offset: int
    dev: str
    inode: int
    path: str = ""
    line: int = 0

    @property
    def size(self) -> int:
        return self.end - self.start

    @property
    def pages(self) -> int:
        """How many 4 KiB pages this covers, which is the unit the fault handler works in."""
        return self.size // 4096

    @property
    def readable(self) -> bool:
        return self.perms[0] == "r"

    @property
    def writable(self) -> bool:
        return self.perms[1] == "w"

    @property
    def executable(self) -> bool:
        return self.perms[2] == "x"

    @property
    def private(self) -> bool:
        return self.perms[3] == "p"

    @property
    def special(self) -> bool:
        """Whether the kernel named this rather than a file, so `[stack]` or `[vdso]`."""
        return self.path.startswith("[") and self.path.endswith("]")

    @property
    def anonymous(self) -> bool:
        """No file behind it. This is the memory a first write has to go and find a page for."""
        return not self.path

    @property
    def label(self) -> str:
        return self.path or "anonymous"

    def holds(self, address: int) -> bool:
        return self.start <= address < self.end

    def __str__(self) -> str:
        return f"{self.start:08x}-{self.end:08x} {self.perms} {self.label}"


@dataclass
class AddressSpace(ProcFile):
    """Every mapping one process has, in the order the kernel walked them, which is by address."""

    pid: int = 0
    regions: tuple[Region, ...] = ()

    @property
    def total_size(self) -> int:
        return sum(one.size for one in self.regions)

    def find(self, needle: str) -> list[Region]:
        return [one for one in self.regions if needle in one.label]

    def at(self, address: int) -> Region | None:
        """Which mapping an address is in, or None for a hole.

        A fault on an address with no mapping is the segmentation fault case, so None here is a
        real answer rather than a lookup failure.
        """
        return next((one for one in self.regions if one.holds(address)), None)

    def executable(self) -> list[Region]:
        return [one for one in self.regions if one.executable]

    def named(self) -> list[Region]:
        return [one for one in self.regions if one.special]

    def gaps(self) -> list[tuple[int, int]]:
        """The unmapped stretches between mappings, as (start, size).

        Most of a 32-bit address space is gap, and seeing that written down as numbers is the
        quickest way to stop thinking of an address space as a block of memory.
        """
        found = []
        for before, after in zip(self.regions, self.regions[1:], strict=False):
            if after.start > before.end:
                found.append((before.end, after.start - before.end))
        return found

    def table(self) -> str:
        rows = [("start", "end", "perms", "size", "pages", "what")]
        for one in self.regions:
            rows.append(
                (
                    f"{one.start:08x}",
                    f"{one.end:08x}",
                    one.perms,
                    str(one.size),
                    str(one.pages),
                    one.label,
                )
            )
        return grid(rows)


# The names of the fields in `/proc/<pid>/stat`, in order, from Table 1-4 of
# Documentation/filesystems/proc.rst. The table is headed "as of 2.6.30-rc7" and it still
# describes 7.2.2 exactly, all 52 of them, which is worth noticing: the file has no entry under
# Documentation/ABI at all and has not moved a field in fifteen years anyway.
#
# The three placeholders are printed as a literal 0 by the kernel. The first used to be the wchan
# address and proc.rst says to read `/proc/<pid>/wchan` instead.
STAT_FIELDS = (
    "pid",
    "tcomm",
    "state",
    "ppid",
    "pgrp",
    "sid",
    "tty_nr",
    "tty_pgrp",
    "flags",
    "min_flt",
    "cmin_flt",
    "maj_flt",
    "cmaj_flt",
    "utime",
    "stime",
    "cutime",
    "cstime",
    "priority",
    "nice",
    "num_threads",
    "it_real_value",
    "start_time",
    "vsize",
    "rss",
    "rsslim",
    "start_code",
    "end_code",
    "start_stack",
    "esp",
    "eip",
    "pending",
    "blocked",
    "sigign",
    "sigcatch",
    "placeholder_wchan",
    "placeholder_2",
    "placeholder_3",
    "exit_signal",
    "task_cpu",
    "rt_priority",
    "policy",
    "blkio_ticks",
    "gtime",
    "cgtime",
    "start_data",
    "end_data",
    "start_brk",
    "arg_start",
    "arg_end",
    "env_start",
    "env_end",
    "exit_code",
)


@dataclass
class PidStat(ProcFile):
    """The one line file, read the only way it can be read correctly.

    The second field is the command name in brackets and the kernel does not escape it, so a
    process called `od) d ma` prints as `37 (od) d ma) R 1 0 ...` and a whitespace split lands on
    the wrong field from there on. `naive` keeps what that split would have said so a lesson can
    show the two side by side instead of asserting that the trap is real.
    """

    pid: int = 0
    comm: str = ""
    values: dict[str, str] = field(default_factory=dict)
    extra: tuple[str, ...] = ()
    naive: tuple[str, ...] = ()

    @property
    def state(self) -> str:
        return self.values.get("state", "")

    @property
    def ppid(self) -> int:
        return int(self.values.get("ppid", 0))

    @property
    def threads(self) -> int:
        return int(self.values.get("num_threads", 0))

    @property
    def faults(self) -> tuple[int, int]:
        """Minor and major faults, which is the pair `blueprints/page-fault.md` counts."""
        return int(self.values.get("min_flt", 0)), int(self.values.get("maj_flt", 0))

    def number(self, name: str) -> int | None:
        raw = self.values.get(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    @property
    def naive_state(self) -> str:
        """What `line.split()[2]` would have said the state was.

        Equal to `state` on almost every process on almost every machine, which is exactly why the
        wrong parse survives so long in so much code.
        """
        return self.naive[2] if len(self.naive) > 2 else ""

    def table(self, *names: str) -> str:
        wanted = names or STAT_FIELDS
        rows = [("field", "value")]
        for name in wanted:
            if name == "tcomm":
                rows.append((name, f"({self.comm})"))
            elif name in self.values:
                rows.append((name, self.values[name]))
        return grid(rows)


@dataclass
class Version(ProcFile):
    """`/proc/version`, taken apart as far as it can honestly be taken apart.

    The release and the build number are worth pulling out and the rest is not. What sits between
    them is the user and host that built it and the whole compiler and linker banner, in
    parentheses, with parentheses inside it, and there is no promise anywhere about its shape.
    `rest` keeps it as text rather than pretending otherwise.
    """

    release: str = ""
    build: str = ""
    rest: str = ""
    text: str = ""

    @property
    def parts(self) -> tuple[int, ...]:
        """The release as numbers, for comparing kernels. Trailing junk is dropped."""
        found = []
        for piece in self.release.split("."):
            digits = ""
            for char in piece:
                if not char.isdigit():
                    break
                digits += char
            if not digits:
                break
            found.append(int(digits))
        return tuple(found)

    def at_least(self, *wanted: int) -> bool:
        return self.parts[: len(wanted)] >= tuple(wanted)

    @property
    def tags(self) -> tuple[str, ...]:
        """The shouted words the build appended after the build number.

        On the pinned kernel `rest` ends `#1 PREEMPT @0` and this is `("PREEMPT",)`. They are the
        kernel's own summary of how it was configured, they are the only part of `rest` with any
        shape at all, and they are worth having because two kernels with the same release can
        differ here in ways that change what every trace in this book means.

        Uppercase words only, and only after the build number, which keeps the compiler banner out.
        `GNU` and `ld` sit in front of the hash and a rule that swept the whole line would collect
        them. Anything with a digit in it goes as well, because `@0` is a timestamp the build put
        there and not a thing the kernel is.
        """
        after = self.rest.partition(self.build)[2] if self.build else ""
        return tuple(
            word for word in after.split() if word.isupper() and word.replace("_", "").isalpha()
        )

    @property
    def smp(self) -> bool:
        """Whether this kernel was built for more than one processor.

        Absence is the answer here, which is worth saying out loud, because a kernel with no `SMP`
        in its banner is a uniprocessor build and there is nothing that says so positively.
        """
        return "SMP" in self.tags

    @property
    def preemption(self) -> str:
        """Which preemption model this kernel was built with, in the kernel's own word.

        Four models, and which one is running decides whether a lesson about a race can be believed
        at all. On a `PREEMPT_RT` kernel most spinlocks sleep. On a `PREEMPT_NONE` kernel a task in
        the kernel runs until it gives way, so a whole class of race cannot be reproduced and a
        reader who tries will conclude the book is wrong.

        A kernel built without preemption says nothing here rather than saying `PREEMPT_NONE`, so
        silence is the answer and it is reported as such instead of being guessed at.
        """
        for tag in self.tags:
            if tag.startswith("PREEMPT"):
                return tag
        return ""
