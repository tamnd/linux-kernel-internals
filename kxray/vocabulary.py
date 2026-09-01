"""The words, colours and glyphs that mean the same thing in every drawing.

A reader learns a visual language once and then reuses it for a hundred lessons, so teal has to
mean a filesystem on page 3 and on page 300, and a filled circle has to mean hardware interrupt
context everywhere it appears. That only holds if there is one list and every renderer reads it.

This lives in `kxray` rather than in a renderer because these are facts about the kernel, not
facts about HTML or about video. `kxray.models` says what a struct is. This says what a struct
looks like when you draw it. Both are upstream of every drawing.

Two rules are baked in rather than written down and hoped for.

Colour is never the only channel. Every coloured thing here also has a name, and a renderer is
expected to print the name, because about one reader in twelve cannot tell the teal from the
green and because a printed page is often black and white anyway.

Order is fixed. The eight layers always run in the same direction, top to bottom, whether the
drawing is a diagram, a widget or an animation. A reader who has learnt that a page cache sits
above a block layer should never have to check which way up this particular picture is.
"""

from __future__ import annotations

from dataclasses import dataclass

# -- subsystems -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Subsystem:
    """One area of the tree, its name in prose, and the colour it is always drawn in."""

    key: str
    prefix: str
    name: str
    stroke: str
    fill: str

    def describe(self) -> str:
        return f"{self.name} ({self.prefix})"


# Ordered longest prefix first, so `kernel/sched/` wins over `kernel/` if a shorter one is ever
# added. The set is deliberately small. A palette of twenty colours is a palette nobody learns.
SUBSYSTEMS: tuple[Subsystem, ...] = (
    Subsystem("sched", "kernel/sched/", "the scheduler", "#6d28d9", "#ede9fe"),
    Subsystem("fs", "fs/", "the filesystem layer", "#0f766e", "#ccfbf1"),
    Subsystem("mm", "mm/", "memory management", "#b45309", "#fef3c7"),
    Subsystem("block", "block/", "the block layer", "#475569", "#e2e8f0"),
    Subsystem("net", "net/", "networking", "#15803d", "#dcfce7"),
    Subsystem("drivers", "drivers/", "a driver", "#57534e", "#e7e5e4"),
    Subsystem("arch", "arch/", "architecture specific code", "#be123c", "#ffe4e6"),
    Subsystem("lib", "lib/", "a library helper", "#525252", "#f5f5f5"),
)

# What a thing is drawn as when nothing is known about where it came from. This is not a colour
# for "other". It is a colour for "we did not look it up", and it is meant to be visibly dull so
# that a drawing full of it looks unfinished, which it is.
UNKNOWN = Subsystem("unknown", "", "not attributed to a subsystem", "#94a3b8", "#f8fafc")


def subsystem_for(path: str | None) -> Subsystem:
    """Which subsystem a source path belongs to, or `UNKNOWN` when there is no path.

    A function_graph trace prints names and not paths, so most frames arrive here with nothing
    and come back `UNKNOWN`. That is the honest answer rather than a failure. Guessing that
    anything starting with `ext4_` lives in `fs/ext4/` is right often enough to be dangerous.
    """
    if not path:
        return UNKNOWN
    clean = path.lstrip("./")
    for one in SUBSYSTEMS:
        if clean.startswith(one.prefix):
            return one
    return UNKNOWN


# -- layers ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Layer:
    """One horizontal band, in the order it is always drawn."""

    key: str
    name: str
    blurb: str


# Top to bottom, always. A write starts at the top of this list and falls down it.
LAYERS: tuple[Layer, ...] = (
    Layer("userspace", "userspace", "your program, which cannot touch any of the rest directly"),
    Layer("entry", "syscall entry", "the doorway, where a register becomes a function call"),
    Layer("vfs", "VFS", "the layer that knows about files without knowing about disks"),
    Layer("fs", "filesystem", "ext4, xfs, tmpfs, the code that knows what a file is made of"),
    Layer("pagecache", "page cache", "file content held in memory, where most writes stop"),
    Layer("block", "block layer", "requests, queues and the scheduler that reorders them"),
    Layer("driver", "driver", "the code that talks to one particular piece of hardware"),
    Layer("hardware", "hardware", "the disk, the card, the thing that finally does the work"),
)

LAYER_KEYS: tuple[str, ...] = tuple(one.key for one in LAYERS)


def layer(key: str) -> Layer:
    for one in LAYERS:
        if one.key == key:
            return one
    raise KeyError(f"no layer called {key!r}, the eight are {', '.join(LAYER_KEYS)}")


def layer_depth(key: str) -> int:
    """How far down the stack a layer sits, counting from 0 at userspace."""
    return LAYER_KEYS.index(layer(key).key)


def in_layer_order(keys: list[str]) -> list[str]:
    """The same layers, sorted top to bottom, with duplicates removed.

    Callers pass layers in whatever order they thought of them. The drawing does not care what
    order they thought of them in.
    """
    return sorted(dict.fromkeys(keys), key=layer_depth)


# -- execution context ------------------------------------------------------------------------


@dataclass(frozen=True)
class Context:
    """Which of the six contexts a piece of code is running in, and what that forbids.

    Rule 7 says concurrency is never deferred, and this is the mechanism. A frame that does not
    say which context it ran in cannot be drawn, because the same function is safe in one context
    and a bug in another, and a picture that leaves that out is teaching the wrong thing.
    """

    key: str
    badge: str
    name: str
    forbids: str

    def describe(self) -> str:
        return f"{self.name}: {self.forbids}"


CONTEXTS: tuple[Context, ...] = (
    Context(
        "process",
        "▢",
        "process context, preemptible",
        "nothing much, you can sleep and allocate and take any lock",
    ),
    Context(
        "nopreempt",
        "▣",
        "process context, preemption disabled",
        "you can still sleep by accident, and that is the bug",
    ),
    Context(
        "atomic",
        "⏸",
        "atomic, a spinlock is held",
        "no sleeping, no GFP_KERNEL, no mutex, no copy_to_user",
    ),
    Context(
        "softirq",
        "◐",
        "softirq",
        "no sleeping, and you are on whichever CPU took the interrupt",
    ),
    Context(
        "hardirq",
        "●",
        "hardware interrupt",
        "no sleeping, be quick, most of the machine is waiting for you",
    ),
    Context(
        "nmi",
        "◆",
        "non maskable interrupt",
        "almost everything, including most locks and most tracing",
    ),
)

CONTEXT_KEYS: tuple[str, ...] = tuple(one.key for one in CONTEXTS)


def context(key: str) -> Context:
    for one in CONTEXTS:
        if one.key == key:
            return one
    raise KeyError(f"no context called {key!r}, the six are {', '.join(CONTEXT_KEYS)}")


# -- type tags --------------------------------------------------------------------------------


@dataclass(frozen=True)
class TypeTag:
    """A kernel annotation that changes what you are allowed to do with a pointer."""

    marker: str
    glyph: str
    name: str
    meaning: str

    def describe(self) -> str:
        return f"{self.glyph} {self.name}, {self.meaning}"


TYPE_TAGS: tuple[TypeTag, ...] = (
    TypeTag(
        "__user",
        "→U",
        "user pointer",
        "points into another address space, so dereferencing it is a bug and copy_from_user is not",
    ),
    TypeTag(
        "__rcu",
        "≈",
        "RCU protected",
        "read it inside rcu_read_lock, and never twice expecting the same answer",
    ),
    TypeTag(
        "__percpu",
        "⊞",
        "per CPU",
        "one copy per CPU, so the address means nothing until you say which CPU",
    ),
    TypeTag(
        "__iomem",
        "⌗",
        "device memory",
        "not memory, a device, so readl and writel rather than a load and a store",
    ),
)

# Two more glyphs that are not annotations in the source but are still facts about a field.
BEHIND_IFDEF = "?"
LOCK_GLYPH = "\U0001f512"


def tags_for(type_name: str) -> list[TypeTag]:
    """Every annotation present in a type as BTF spells it, in a fixed order.

    BTF keeps `__user` and friends as type tags, so they survive into the debug information and
    a drawing can show them. That is the whole reason a field can be drawn with a glyph at all.
    """
    return [one for one in TYPE_TAGS if one.marker in type_name]


# -- pointers ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Reference:
    """What one object holding a pointer to another object actually promises.

    The line style is the difference between a leak, a use after free and neither, and it is the
    single most useful thing a picture of kernel data structures can carry.
    """

    key: str
    name: str
    dash: tuple[int, ...]
    meaning: str

    def describe(self) -> str:
        return f"{self.name}, {self.meaning}"


REFERENCES: tuple[Reference, ...] = (
    Reference(
        "owning",
        "owning",
        (),
        "a reference is held, so the target cannot go away while this pointer exists",
    ),
    Reference(
        "borrowed",
        "borrowed",
        (6, 4),
        "no reference is held, so this is only valid while something else keeps the target alive",
    ),
    Reference(
        "rcu",
        "RCU",
        (1, 3),
        "valid inside rcu_read_lock and stale the moment you leave it",
    ),
)

REFERENCE_KEYS: tuple[str, ...] = tuple(one.key for one in REFERENCES)


def reference(key: str) -> Reference:
    for one in REFERENCES:
        if one.key == key:
            return one
    raise KeyError(f"no reference kind called {key!r}, the three are {', '.join(REFERENCE_KEYS)}")
