"""Take the run out of a capture, so that two captures of the same thing look the same.

    from kxray.corpus import normalize

    one = normalize.of(open("corpora/traces/tier0/write-1byte.txt").read())
    print(one.text)
    print(one.legend.table())

Kernel output is full of numbers that are true and mean nothing. The process happened to be pid 41
this time and pid 2792 last time. The trace happened to start 3.04 seconds after boot. The mutex
happened to live at `c78250b8`. Run the same experiment again and every one of those changes, and a
comparison of the two files reports several hundred differences, none of which is the difference
anybody wanted to know about.

So they are replaced, consistently, with names. The same pid always becomes the same `pid#1` inside
one capture, and a second capture of the same work gets the same names in the same places. What is
left when the run specific numbers are gone is the part that is about the kernel, which is the part
a lesson is allowed to make a claim about.

## Two properties this holds itself to, and a test for each

**It never changes the number of lines.** Normalising is a substitution and not an edit. A rule that
dropped a line, or wrapped one, would make the result unreadable next to the original, and reading
the two next to each other is how anybody checks that a rule is doing what it says.

**Running it twice is the same as running it once.** A rule that matched its own output would keep
renaming things every pass, and a file that changes every time you look at it is not a baseline.

## What it deliberately does not do

It does not reorder anything by default. Rule seven in the specification is that concurrent events
get sorted by a stable key, and that is right for a trace where every line stands alone and wrong
for a `function_graph` trace where the lines are a call tree and their order is the shape of it.
So `order` exists, it is off unless asked for, and asking for it on a call graph is a mistake this
cannot make on your behalf.

It does not guess at what might vary. Every pattern in here was written against a line that is in
`corpora/`, with one exception that says so in its own comment. A list of things to ignore is
exactly where a check quietly stops being a check.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

# The rules, in the order the specification puts them, which is also the order they have to run in.
# Pointers before offsets, because `lock_acquire+0x8c/0x230` has hex in it that is not an address.
# Identity before cpu, because a task column holds a pid and a cpu column holds a cpu and telling
# them apart is done by where they are rather than by what they look like.
RULES = ("time", "pointer", "identity", "cpu", "offset", "counter")

# Not in RULES, and the docstring says why. Ask for it by name or do not get it.
ORDER = "order"

ALL = (*RULES, ORDER)

# How long a run of hex digits has to be before it is treated as an address. Eight is a pointer on
# the 32-bit kernel this project pins and sixteen is one on x86-64. Shorter runs are the offsets
# inside `symbol+0x8c/0x230`, the lock class keys in a lockdep splat, and every other small hex
# number the kernel prints, and eating those would make a splat unreadable.
POINTER_DIGITS = (8, 16)


@dataclass
class Legend:
    """Which name stands for which original value, in the order the values were first seen.

    This is half the output and it is not optional. A normalised trace that says `pid#2` and cannot
    say which process that was is a trace nobody can take back to the machine it came off.
    """

    families: dict[str, dict[str, str]] = field(default_factory=dict)

    def name(self, family: str, original: str) -> str:
        """The name for this value, allocating one in first appearance order if it is new."""
        seen = self.families.setdefault(family, {})
        if original not in seen:
            seen[original] = f"{family}#{len(seen) + 1}"
        return seen[original]

    def rows(self) -> list[tuple[str, str, str]]:
        return [
            (family, name, original)
            for family, seen in self.families.items()
            for original, name in seen.items()
        ]

    def table(self) -> str:
        rows = self.rows()
        if not rows:
            return "nothing was renamed"
        width = max(len(one[1]) for one in rows)
        return "\n".join(f"{name:<{width}}  was  {original}" for _, name, original in rows)

    def original(self, name: str) -> str | None:
        """The value a name stands for, for a reader going the other way."""
        for seen in self.families.values():
            for was, is_now in seen.items():
                if is_now == name:
                    return was
        return None


@dataclass(frozen=True)
class Normalised:
    """A capture with the run taken out of it, and the key to what was taken."""

    text: str
    legend: Legend
    rules: tuple[str, ...]
    source: str = ""

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")


# -- rule one, time --------------------------------------------------------------------------------

# `[    3.700589] ` on the front of every printk line.
PRINTK_TIME = re.compile(r"\[\s*\d+\.\d{6}\]")

# ` 3.040809: ` in the timestamp column of an event trace, always followed by the event name.
EVENT_TIME = re.compile(r"(?<=\s)\d+\.\d{6}(?=:)")

# ` + 21.875 us ` in the duration column of a function_graph trace. The marker in front is `+` for
# over ten microseconds and `!` for over a hundred, so it is the duration said a second way and it
# goes at the same time as the duration itself.
GRAPH_DURATION = re.compile(r"([+!#*@$]\s)?(\d+\.\d+) us")

# The buckets for `mode="bucket"`. Powers of ten, because the honest resolution of a duration in a
# trace is its order of magnitude: the same call on the same machine varies by a factor of two run
# to run, and by rather more than that between a warm cache and a cold one.
BUCKETS = ((1, "under 1us"), (10, "1 to 10us"), (100, "10 to 100us"), (1000, "100us to 1ms"))


def _bucket(microseconds: float) -> str:
    for edge, name in BUCKETS:
        if microseconds < edge:
            return name
    return "over 1ms"


def _time(text: str, legend: Legend, *, mode: str = "elide") -> str:
    text = PRINTK_TIME.sub("[TIME]", text)
    text = EVENT_TIME.sub("TIME", text)

    def duration(match: re.Match) -> str:
        if mode == "bucket":
            return f"[{_bucket(float(match.group(2)))}]"
        return "DUR us"

    return GRAPH_DURATION.sub(duration, text)


# -- rule two, pointers ----------------------------------------------------------------------------

_WIDE = "|".join(f"[0-9a-f]{{{one}}}" for one in POINTER_DIGITS)

# `08048000-08149000` at the start of a line of /proc/self/maps. A range of two addresses is a
# range of two addresses whatever digits are in it, so this goes first and the rule below does not
# have to decide.
POINTER_RANGE = re.compile(rf"(?<![\w+.])({_WIDE})-({_WIDE})\b")

POINTER = re.compile(rf"(?<![\w+.])(0x)?({_WIDE})\b")

HAS_LETTER = re.compile(r"[a-f]")


def _pointer(text: str, legend: Legend, *, symbols=None) -> str:
    def name(digits: str, whole: str) -> str:
        # A null pointer is a fact rather than a nonce, and it is the same fact in every run. The
        # same goes for a zero file offset in /proc/self/maps, which is what this mostly catches.
        if int(digits, 16) == 0:
            return whole
        if symbols is not None:
            found = symbols.lookup(int(digits, 16))
            if found is not None:
                return f"&{found.name}"
        return legend.name("ptr", digits)

    def one(match: re.Match) -> str:
        prefix, digits = match.group(1), match.group(2)
        # Eight hex digits and eight decimal digits look identical when none of the digits happen
        # to be a letter, and the kernel prints plenty of eight digit decimal numbers that are not
        # addresses. So a bare run has to have a hex letter in it to count. Written `0x` it counts
        # either way, and a range is handled above. What this gives up is the occasional real
        # address whose digits are all decimal and which is not in a range or written `0x`, and
        # leaving one of those alone is the safe direction: a number that was not renamed is
        # visible, and a size that was renamed to `ptr#4` is a difference nobody will ever see.
        if not prefix and not HAS_LETTER.search(digits):
            return match.group(0)
        return (prefix or "") + name(digits, digits)

    text = POINTER_RANGE.sub(
        lambda m: f"{name(m.group(1), m.group(1))}-{name(m.group(2), m.group(2))}", text
    )
    return POINTER.sub(one, text)


# -- rule three, identity --------------------------------------------------------------------------

# The task column of a function_graph trace, which is `comm-pid` after the CPU number: ` 4)
# sh-83082    |`. Anchored to the start of the line and to the closing bracket of the CPU column so
# that a function name with a hyphen and digits in it cannot be mistaken for a task.
GRAPH_TASK = re.compile(r"^(\s*\d+\)\s+\S+?-)(\d+)(?=\s)", re.MULTILINE)

# The task column of an event trace, which comes first on the line and is followed by the CPU in
# square brackets: `              sh-1       [000]`.
EVENT_TASK = re.compile(r"^(\s*\S+?-)(\d+)(?=\s+\[\d+\])", re.MULTILINE)

# Every `pid=` shaped field a tracepoint prints. `prev_pid`, `next_pid`, `old_pid`, `tgid` and a
# bare `pid` are all in the committed event captures.
PID_FIELD = re.compile(r"\b((?:\w+_)?(?:pid|tgid))=(\d+)")

# What an oops says about who was running: `CPU: 0 UID: 0 PID: 40 Comm: abba_second` and
# `1 lock held by abba_second/40:`.
OOPS_PID = re.compile(r"\bPID:\s*(\d+)")
HELD_BY = re.compile(r"(\block(?:s)? held by \S+?/)(\d+)")

# The other place a splat names a task, at the top: `abba_second/40 is trying to acquire lock:`.
TRYING = re.compile(r"(?<=[\w.])/(\d+)(?= is trying to acquire)")

# The device and inode columns of /proc/self/maps: `00000000 00:03 11         /bin/busybox`.
MAPS_DEVICE_INODE = re.compile(r"(?<=\s)([0-9a-f]{2}:[0-9a-f]{2}) (\d+)(?=\s|$)")


def _identity(text: str, legend: Legend) -> str:
    text = GRAPH_TASK.sub(lambda m: m.group(1) + legend.name("pid", m.group(2)), text)
    text = EVENT_TASK.sub(lambda m: m.group(1) + legend.name("pid", m.group(2)), text)
    text = PID_FIELD.sub(lambda m: f"{m.group(1)}={legend.name('pid', m.group(2))}", text)
    text = OOPS_PID.sub(lambda m: f"PID: {legend.name('pid', m.group(1))}", text)
    text = HELD_BY.sub(lambda m: m.group(1) + legend.name("pid", m.group(2)), text)
    text = TRYING.sub(lambda m: "/" + legend.name("pid", m.group(1)), text)

    def device_inode(match: re.Match) -> str:
        device, inode = match.group(1), match.group(2)
        # Inode zero means the mapping is not a file, which is a fact about the mapping rather than
        # a number that changes run to run.
        named = inode if inode == "0" else legend.name("inode", inode)
        return f"{legend.name('dev', device)} {named}"

    return MAPS_DEVICE_INODE.sub(device_inode, text)


# -- rule four, cpu --------------------------------------------------------------------------------

# The CPU column of a function_graph trace, ` 4)` at the very start of the line.
GRAPH_CPU = re.compile(r"^(\s*)(\d+)\)", re.MULTILINE)

# The CPU column of an event trace, `[000]` after the task.
EVENT_CPU = re.compile(r"(?<=\s)\[(\d{3})\](?=\s)")

# What a tracepoint says about where it is sending something, and what an oops says about where it
# was running.
TARGET_CPU = re.compile(r"\btarget_cpu=(\d+)")
OOPS_CPU = re.compile(r"\bCPU:\s*(\d+)")


def _cpu(text: str, legend: Legend) -> str:
    text = GRAPH_CPU.sub(lambda m: f"{m.group(1)}{legend.name('lane', m.group(2))})", text)
    text = EVENT_CPU.sub(lambda m: f"[{legend.name('lane', m.group(1).lstrip('0') or '0')}]", text)
    text = TARGET_CPU.sub(
        lambda m: f"target_cpu={legend.name('lane', m.group(1).lstrip('0') or '0')}", text
    )
    return OOPS_CPU.sub(lambda m: f"CPU: {legend.name('lane', m.group(1))}", text)


# -- rule five, offsets ----------------------------------------------------------------------------

# `lock_acquire+0x8c/0x230` in a backtrace. The offset into the function and the size of the
# function both move when anything in front of them in the object file moves, which is to say on
# every build, so neither survives a comparison between two kernels.
SYMBOL_OFFSET = re.compile(r"(?<=[\w.])\+0x[0-9a-f]+(/0x[0-9a-f]+)?")


def _offset(text: str, legend: Legend) -> str:
    return SYMBOL_OFFSET.sub("", text)


# -- rule six, counters ----------------------------------------------------------------------------

# The counters that count from boot rather than from the thing being watched. Each becomes its
# distance from the first value seen, so a capture taken an hour later reads the same.
#
# This is the one rule in the file with no line behind it in `corpora/`. Nothing committed here
# prints a jiffies or a grace period number yet, so it is written from the shapes the kernel uses
# and tested against constructed input. That is worth less than the rest of this file and saying so
# is the point. When a real capture with one in it lands, this list should be checked against it.
COUNTERS = ("jiffies", "gp_seq", "seq", "sequence", "nr_grace")

COUNTER = re.compile(r"\b(" + "|".join(COUNTERS) + r")=(\d+)")


def _counter(text: str, legend: Legend) -> str:
    base: dict[str, int] = {}

    def one(match: re.Match) -> str:
        name, value = match.group(1), int(match.group(2))
        first = base.setdefault(name, value)
        return f"{name}=+{value - first}"

    return COUNTER.sub(one, text)


# -- rule seven, order -----------------------------------------------------------------------------


def _order(text: str, legend: Legend) -> str:
    """Sort runs of lines that share a timestamp, so two interleavings read the same.

    Off by default, and the module docstring says why. This is right for an event trace, where each
    line is a whole event and the order two CPUs landed in the ring buffer is not a fact about the
    kernel. It is wrong for a `function_graph` trace, where the lines are a call tree drawn with
    indentation and sorting them destroys the thing being taught.
    """
    out: list[str] = []
    run: list[str] = []
    at: str | None = None

    def flush() -> None:
        # A run of lines with no timestamp is left exactly as it was. Only lines the time rule
        # already collapsed onto the same moment are candidates for sorting, because those are the
        # ones whose order the kernel did not decide.
        out.extend(sorted(run) if at is not None and len(run) > 1 else run)

    for line in text.split("\n"):
        stamp = _stamp(line)
        if stamp != at:
            flush()
            run, at = [], stamp
        run.append(line)
    flush()
    return "\n".join(out)


STAMPED = re.compile(r"\[TIME\]|(?<=\s)TIME(?=:)")


def _stamp(line: str) -> str | None:
    """What a line is timestamped with, or None for one that is not part of a run.

    This runs after the time rule, so every line that had a moment on it now says the same thing.
    That is what makes a run of lines findable at all: before normalising, two events a microsecond
    apart have different timestamps and there is no run to sort.
    """
    found = STAMPED.search(line)
    return None if found is None else found.group(0)


# -- putting them together -------------------------------------------------------------------------

APPLY = {
    "time": _time,
    "pointer": _pointer,
    "identity": _identity,
    "cpu": _cpu,
    "offset": _offset,
    "counter": _counter,
    ORDER: _order,
}


def of(
    text: str,
    *,
    rules: Iterable[str] = RULES,
    time: str = "elide",
    symbols=None,
    source: str = "",
) -> Normalised:
    """Normalise a capture, keeping the key to what was replaced.

    `rules` is which of the seven to run and defaults to the six that are safe on anything.
    `time` is `elide` or `bucket`: elide takes durations out entirely, bucket keeps their order of
    magnitude, which is what a lesson wants when the point is that one call is slow.
    `symbols` is an optional `kxray.kallsyms` table. Given one, an address that resolves becomes
    `&symbol` instead of `ptr#3`, which is the difference between a diff you can read and one you
    can only compare.
    """
    wanted = tuple(rules)
    unknown = [one for one in wanted if one not in APPLY]
    if unknown:
        raise ValueError(f"no such rule: {', '.join(unknown)}, and there are {', '.join(ALL)}")

    legend = Legend()
    out = text
    for name in ALL:
        if name not in wanted:
            continue
        if name == "time":
            out = _time(out, legend, mode=time)
        elif name == "pointer":
            out = _pointer(out, legend, symbols=symbols)
        else:
            out = APPLY[name](out, legend)
    return Normalised(text=out, legend=legend, rules=wanted, source=source)


def same(one: str, other: str, **kwargs) -> bool:
    """Whether two captures are the same once the run is taken out of both."""
    return of(one, **kwargs).text == of(other, **kwargs).text
