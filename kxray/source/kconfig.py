"""Kconfig files, which are where a config symbol says what it is and what it drags in with it.

    from kxray.source import kconfig, tree

    file = kconfig.load(tree.find(), "kernel/Kconfig.preempt")
    print(file["PREEMPT"].selects)
    print(kconfig.why(file, "PREEMPT_BUILD"))

`tools/kconfig.py` checks that the config fragments in this repository still say what the lessons
need. This reads the kernel's own Kconfig files, which is the other half: not what we asked for but
what the kernel does about it.

The pinned kernel is built with `CONFIG_PREEMPT=y`, and a reader who looks at the resulting
`.config` finds `CONFIG_PREEMPT_BUILD=y` and `CONFIG_PREEMPTION=y` in there as well without having
asked for either. `kernel/Kconfig.preempt` is the whole explanation and it is 194 lines long.
`PREEMPT` carries `select PREEMPT_BUILD if !PREEMPT_DYNAMIC`, and `PREEMPT_BUILD` carries
`select PREEMPTION`. One answer pulls in two more.

The thing to notice in that file is `PREEMPT_BUILD` itself. It is declared `bool` with nothing
after it, and a type with no string after it means no prompt, and no prompt means the symbol never
appears in `menuconfig` and nobody can turn it on by hand. Its value is decided entirely by who
selects it. That is a common shape and it is invisible if you only ever read `.config`, because in
`.config` it looks exactly like something a person chose.

What this does not do is evaluate anything. `depends on EXPERT && ARCH_SUPPORTS_RT && !COMPILE_TEST`
is kept as the text it is. Working out whether that is true needs every Kconfig file in the tree,
the architecture, and the rest of the config, which is what `scripts/kconfig` is for and is a
program rather than a parser. Reading the condition is enough to answer the question a lesson
actually asks, which is why a symbol is on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from kxray.models import READ, SKIPPED, UNPARSED, Lines, grid
from kxray.source.tree import File, Tree

# A type line, optionally followed by the prompt in quotes. No prompt means no menu entry.
TYPES = ("bool", "tristate", "int", "hex", "string", "def_bool", "def_tristate")

CONFIG_RE = re.compile(r"^(config|menuconfig)\s+(\w+)\s*$")
TYPE_RE = re.compile(
    r"^(" + "|".join(TYPES) + r')(?:\s+"(?P<prompt>(?:[^"\\]|\\.)*)")?\s*(?P<tail>.*)$'
)
DEPENDS_RE = re.compile(r"^depends on\s+(.*)$")
SELECT_RE = re.compile(r"^(select|imply)\s+(\w+)\s*(?:if\s+(.*))?$")
DEFAULT_RE = re.compile(r"^default\s+(.*)$")
PROMPT_RE = re.compile(r'^prompt\s+"(?P<prompt>(?:[^"\\]|\\.)*)"\s*(?P<tail>.*)$')
CHOICE_RE = re.compile(r"^(choice|endchoice)\b")
HELP_RE = re.compile(r"^(help|---help---)\s*$")
RANGE_RE = re.compile(r"^range\s+(.+)$")

# `if COND` around a run of symbols, and the `endif` that closes it. This is a condition and not a
# menu, which is why it is read here and `menu` is not: every symbol between the two carries the
# condition whether or not it says so itself, and a reader asking why a symbol is on needs it. In
# `lib/Kconfig.kfence` the entire body sits inside `if KFENCE`, so not one of the seven symbols in
# there has a `depends on` line and every one of them depends on KFENCE.
IF_RE = re.compile(r"^if\s+(.+)$")
ENDIF_RE = re.compile(r"^endif\b")


@dataclass(frozen=True)
class Select:
    symbol: str
    condition: str = ""

    def __str__(self) -> str:
        return f"{self.symbol} if {self.condition}" if self.condition else self.symbol


@dataclass
class Symbol:
    """One `config` or `menuconfig` entry, kept as written."""

    name: str
    kind: str = "config"
    type: str = ""
    prompt: str = ""
    depends: tuple[str, ...] = ()
    selects: tuple[Select, ...] = ()
    implies: tuple[Select, ...] = ()
    defaults: tuple[str, ...] = ()
    ranges: tuple[str, ...] = ()
    within: tuple[str, ...] = ()
    help: str = ""
    choice: str = ""
    line: int = 0
    source: str = ""

    @property
    def visible(self) -> bool:
        """Whether a person can find this in `menuconfig` and set it.

        A symbol with a type and no prompt cannot be set directly at all. It is on because
        something selected it, and the only way to find out what is to read the files.
        """
        return bool(self.prompt)

    @property
    def config(self) -> str:
        return f"CONFIG_{self.name}"

    @property
    def conditions(self) -> tuple[str, ...]:
        """Everything this symbol depends on, whether it said so itself or an `if` said it.

        `KFENCE_SAMPLE_INTERVAL` has no `depends on` line of its own and cannot be set unless
        KFENCE is on, because the whole block is inside `if KFENCE`. Reading the symbol without
        reading the block it sits in gives the wrong answer.
        """
        return self.within + self.depends

    def __str__(self) -> str:
        shown = self.prompt or "no prompt, so it cannot be set by hand"
        return f"{self.config} ({self.type or 'no type'}): {shown}"


@dataclass
class Choice:
    """A `choice` block: a prompt, and the symbols under it, of which exactly one gets set.

    The block carries lines of its own before any `config` in it. `kernel/Kconfig.preempt` opens
    with a prompt and two `default` lines that belong to the choice rather than to any symbol, and
    a parser that only knows about symbols drops them on the floor.
    """

    prompt: str = ""
    defaults: tuple[str, ...] = ()
    depends: tuple[str, ...] = ()
    members: tuple[str, ...] = ()
    line: int = 0


@dataclass
class KconfigFile:
    """One Kconfig file, read. Not a tree of them, and not an evaluator."""

    source: str = "<text>"
    symbols: tuple[Symbol, ...] = ()
    sourced: tuple[str, ...] = ()
    choices: tuple[Choice, ...] = ()
    lines: Lines = field(default_factory=Lines)
    unparsed: tuple[tuple[int, str], ...] = ()

    def get(self, name: str) -> Symbol | None:
        wanted = name.removeprefix("CONFIG_")
        return next((s for s in self.symbols if s.name == wanted), None)

    def __getitem__(self, name: str) -> Symbol:
        found = self.get(name)
        if found is None:
            raise KeyError(f"{name} is not declared in {self.source}")
        return found

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.symbols)

    @property
    def hidden(self) -> tuple[Symbol, ...]:
        return tuple(s for s in self.symbols if s.type and not s.visible)

    def selected_by(self, name: str) -> tuple[Symbol, ...]:
        """Every symbol in this file that would turn the named one on.

        This is the lookup that makes a `.config` readable. `PREEMPT_BUILD` is on because `PREEMPT`
        selects it, and nothing in `.config` says so.
        """
        wanted = name.removeprefix("CONFIG_")
        return tuple(s for s in self.symbols if any(x.symbol == wanted for x in s.selects))

    def table(self) -> str:
        rows = [("symbol", "type", "prompt", "selects")]
        for symbol in self.symbols:
            rows.append(
                (
                    symbol.name,
                    symbol.type or "none",
                    symbol.prompt or "none, so it is not in the menu",
                    ", ".join(str(s) for s in symbol.selects) or "nothing",
                )
            )
        return grid(rows)


def parse(text: str, source: str = "<text>") -> KconfigFile:
    """Read one Kconfig file into its symbols.

    Help text is taken by indentation, which is what the format actually uses. Everything from the
    `help` line until a line at the same indentation as the entry belongs to the help.
    """
    symbols: list[Symbol] = []
    sourced: list[str] = []
    unparsed: list[tuple[int, str]] = []
    counted = Lines()
    current: Symbol | None = None
    within: list[str] = []
    choices: list[Choice] = []
    choice: Choice | None = None
    in_help = False
    help_lines: list[str] = []

    def close() -> None:
        nonlocal current, in_help, help_lines
        if current is not None:
            current.help = "\n".join(help_lines).strip("\n")
            symbols.append(current)
            if choice is not None:
                choice.members = choice.members + (current.name,)
        current, in_help, help_lines = None, False, []

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        body = line.strip()

        if in_help:
            if not body:
                help_lines.append("")
                counted.count(SKIPPED)
                continue
            if raw.startswith((" ", "\t")):
                help_lines.append(body)
                counted.count(SKIPPED)
                continue
            in_help = False

        if not body or body.startswith("#"):
            counted.count(SKIPPED)
            continue

        opened = IF_RE.match(body)
        if opened is not None:
            close()
            within.append(opened.group(1).strip())
            counted.count(READ)
            continue

        if ENDIF_RE.match(body):
            close()
            if within:
                within.pop()
            counted.count(READ)
            continue

        found = CONFIG_RE.match(body)
        if found is not None:
            close()
            current = Symbol(
                name=found.group(2),
                kind=found.group(1),
                choice=choice.prompt if choice is not None else "",
                within=tuple(within),
                line=number,
                source=source,
            )
            counted.count(READ)
            continue

        chosen = CHOICE_RE.match(body)
        if chosen is not None:
            close()
            if chosen.group(1) == "choice":
                choice = Choice(line=number)
                choices.append(choice)
            else:
                choice = None
            counted.count(READ)
            continue

        if body.startswith("source "):
            sourced.append(body.removeprefix("source ").strip().strip('"'))
            counted.count(READ)
            continue

        if current is None:
            # Inside a `choice` block, before any `config`, these lines belong to the choice
            # itself. The prompt is the menu entry the four preemption models sit under, and the
            # defaults say which one is picked when nobody picks.
            if choice is not None:
                prompt = PROMPT_RE.match(body)
                if prompt is not None:
                    choice.prompt = prompt.group("prompt")
                    counted.count(READ)
                    continue
                default = DEFAULT_RE.match(body)
                if default is not None:
                    choice.defaults = choice.defaults + (default.group(1).strip(),)
                    counted.count(READ)
                    continue
                depends = DEPENDS_RE.match(body)
                if depends is not None:
                    choice.depends = choice.depends + (depends.group(1).strip(),)
                    counted.count(READ)
                    continue
            # Outside any `config` and outside any `choice`. `menu`, `endmenu` and `comment` land
            # here. Those are presentation, this parser answers questions about symbols and does
            # not model menus, so they are counted as unread rather than quietly passed over.
            unparsed.append((number, line))
            counted.count(UNPARSED)
            continue

        typed = TYPE_RE.match(body)
        if typed is not None:
            current.type = typed.group(1)
            current.prompt = typed.group("prompt") or ""
            counted.count(READ)
            continue

        depends = DEPENDS_RE.match(body)
        if depends is not None:
            current.depends = current.depends + (depends.group(1).strip(),)
            counted.count(READ)
            continue

        select = SELECT_RE.match(body)
        if select is not None:
            entry = Select(symbol=select.group(2), condition=(select.group(3) or "").strip())
            if select.group(1) == "select":
                current.selects = current.selects + (entry,)
            else:
                current.implies = current.implies + (entry,)
            counted.count(READ)
            continue

        default = DEFAULT_RE.match(body)
        if default is not None:
            current.defaults = current.defaults + (default.group(1).strip(),)
            counted.count(READ)
            continue

        ranged = RANGE_RE.match(body)
        if ranged is not None:
            # `range 1 65535` on an int. It is the only place the kernel says out loud what a
            # number symbol is allowed to be, and a config fragment setting one outside its range
            # is a mistake nothing else would report.
            current.ranges = current.ranges + (ranged.group(1).strip(),)
            counted.count(READ)
            continue

        prompt = PROMPT_RE.match(body)
        if prompt is not None:
            current.prompt = prompt.group("prompt")
            counted.count(READ)
            continue

        if HELP_RE.match(body):
            in_help = True
            help_lines = []
            counted.count(READ)
            continue

        unparsed.append((number, line))
        counted.count(UNPARSED)

    close()
    return KconfigFile(
        source=source,
        symbols=tuple(symbols),
        sourced=tuple(sourced),
        choices=tuple(choices),
        lines=counted,
        unparsed=tuple(unparsed),
    )


def parse_file(file: File) -> KconfigFile:
    return parse(file.text, source=f"{file.root}/{file.path}")


def load(found: Tree, path: str) -> KconfigFile:
    return parse_file(found.read(path))


def why(file: KconfigFile, name: str) -> str:
    """One sentence saying how a symbol could be on, out of this file alone.

    Out of this file alone is the caveat that matters and it is in the answer, because a symbol
    can be selected from anywhere in the tree and reading one file can only ever rule things in.
    """
    symbol = file.get(name)
    if symbol is None:
        return f"{name} is not declared in {file.source}"
    if symbol.visible:
        chose = f"{symbol.config} has a prompt, so somebody could have chosen it"
    else:
        chose = f"{symbol.config} has no prompt, so nobody chose it by hand"
    by = file.selected_by(name)
    if not by:
        return f"{chose}, and nothing in {file.source} selects it"
    names = ", ".join(s.config for s in by)
    return f"{chose}, and in {file.source} it is selected by {names}"


def report(file: KconfigFile) -> str:
    lines = [
        file.source,
        f"symbols: {len(file.symbols)}",
        f"hidden:  {len(file.hidden)} with a type and no prompt, so they can only be selected",
        f"sourced: {len(file.sourced)} other files",
    ]
    text = "\n".join(lines)
    print(text)
    return text
