"""A symbol to the file and line that defines it, and the gap between the two names.

    from kxray.source import symbols, tree

    found = tree.find()
    for hit in symbols.find(found, "vfs_write", ("fs/read_write.c",)):
        print(hit)

    print(symbols.unwrap("__ia32_sys_write"))

Two halves. The first is text search with C shaped patterns, which is what `grep` in a kernel tree
is and what `cscope` does properly. The second is the part that is actually worth writing down.

A name off a running kernel and a name in the source are not the same name. There are three names
for the write system call in the pinned build and no two of them are equal.

`arch/x86/entry/syscalls/syscall_32.tbl` calls the entry point `sys_write`. `fs/read_write.c` has
no line defining anything by that name. What it has, on line 747, is:

    SYSCALL_DEFINE3(write, unsigned int, fd, const char __user *, buf,

And `/proc/kallsyms` off the running box, in `corpora/proc/tier0/kallsyms-write.txt`, calls it
`__ia32_sys_write`. Macros stand between each pair.

Grepping that file for `sys_write` is worse than finding nothing. It finds two lines, 728 and 750,
and both of them are `ksys_write`, which is a different function with a different signature that
the real entry point calls on line 750. So the reader lands three lines away from what they wanted,
on something that looks close enough to be believed.

`unwrap` strips the wrappers a syscall picks up on the way to being a symbol, and `find` knows that
a syscall called `write` is defined by a `SYSCALL_DEFINE` line whose first argument is `write`.

The wrappers depend on the architecture, which is why they are a list rather than a rule.
`__ia32_` is the 32 bit entry stub, `__x64_` the 64 bit one, `__se_` the sign extending wrapper and
`__do_` the body the other two call. So the same call is `__ia32_sys_write` on the box this project
pins and `__x64_sys_write` on the laptop the reader is sitting at, and a lesson that hardcoded
either one would be wrong for half its readers.

What this is not is an index. It reads the files it is given and no others, and `find` takes the
paths from the caller for that reason: searching a full kernel tree for a common name means reading
seventy thousand files, and the answer to "where is `write` defined" is not improved by also
finding the eleven hundred other places that word appears.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from kxray.models import grid
from kxray.source.tree import Tree

# The wrappers a syscall name picks up between the source and the symbol table, longest first so
# that stripping is not order dependent.
WRAPPERS = (
    "__ia32_compat_sys_",
    "__x64_compat_sys_",
    "__ia32_sys_",
    "__x64_sys_",
    "__se_sys_",
    "__do_sys_",
    "compat_sys_",
    "sys_",
)

# What a definition looks like. Each entry is a kind and a template with `{name}` in it, tried in
# order, and the first kind that matches a line names the line.
PATTERNS = (
    ("syscall", r"^(COMPAT_)?SYSCALL_DEFINE\d\(\s*{name}\s*[,)]"),
    ("macro", r"^#\s*define\s+{name}\b"),
    ("struct", r"^(struct|union|enum)\s+{name}\s*\{{"),
    ("typedef", r"^typedef\b.*\b{name}\s*[;(]"),
    ("function", r"^[A-Za-z_].*\b{name}\s*\("),
    ("variable", r"^[A-Za-z_][\w \t*]*\b{name}\s*(\[[^\]]*\])?\s*="),
)

# The export macros, which say a symbol is available to modules. Not a definition, and worth
# reporting beside one, because a symbol that is defined and not exported is a symbol a module
# cannot call however visible it looks in the source.
EXPORT_RE = r"^EXPORT_SYMBOL[A-Z_]*\(\s*{name}\s*[,)]"


@dataclass(frozen=True)
class Definition:
    """Where a symbol is written down, and what kind of thing was written."""

    name: str
    kind: str
    path: str
    line: int
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.kind}  {self.text.strip()[:60]}"


def unwrap(symbol: str) -> str:
    """A symbol table name reduced to the name the source would use.

    `__ia32_sys_write` comes back as `write`, and so does `sys_write`. A name with no wrapper on it
    comes back unchanged, because most symbols are not syscalls and guessing at them would be worse
    than doing nothing.
    """
    for prefix in WRAPPERS:
        if symbol.startswith(prefix):
            return symbol[len(prefix) :]
    return symbol


def wrapped(symbol: str) -> bool:
    """Whether this name is a syscall entry point rather than a function somebody wrote."""
    return symbol != unwrap(symbol)


def _compiled(name: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    quoted = re.escape(name)
    return tuple((kind, re.compile(template.format(name=quoted))) for kind, template in PATTERNS)


def search(text: str, name: str, path: str = "<text>") -> tuple[Definition, ...]:
    """Every line in one file that looks like a definition of this name."""
    patterns = _compiled(name)
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if name not in line:
            continue
        if line.rstrip().endswith(";"):
            # A declaration in a header, or a call. Neither is where the thing lives, and headers
            # are full of both.
            continue
        for kind, pattern in patterns:
            if pattern.search(line):
                found.append(Definition(name=name, kind=kind, path=path, line=number, text=line))
                break
    return tuple(found)


def find(tree: Tree, name: str, paths: tuple[str, ...]) -> tuple[Definition, ...]:
    """Look for a symbol in a named set of files.

    A syscall is looked for twice, once under the name as given and once with the wrappers off,
    because `sys_write` and `write` are the same call and only one of them is in the source.
    """
    wanted = [name]
    bare = unwrap(name)
    if bare != name:
        wanted.append(bare)

    found: list[Definition] = []
    for path in paths:
        file = tree.open(path)
        if file is None:
            continue
        for candidate in wanted:
            found.extend(search(file.text, candidate, path))
    return tuple(found)


def exported(tree: Tree, name: str, paths: tuple[str, ...]) -> tuple[Definition, ...]:
    """Where a symbol is handed to modules, if it is."""
    pattern = re.compile(EXPORT_RE.format(name=re.escape(name)))
    found = []
    for path in paths:
        file = tree.open(path)
        if file is None:
            continue
        for number, line in enumerate(file.lines, start=1):
            if pattern.search(line):
                found.append(
                    Definition(name=name, kind="export", path=path, line=number, text=line)
                )
    return tuple(found)


def table(definitions: tuple[Definition, ...]) -> str:
    rows = [("symbol", "kind", "where", "line")]
    for found in definitions:
        rows.append((found.name, found.kind, found.path, str(found.line)))
    return grid(rows)


def report(tree: Tree, name: str, paths: tuple[str, ...]) -> str:
    definitions = find(tree, name, paths)
    lines = [f"{name} in {tree.describe()}"]
    if wrapped(name):
        lines.append(f"name:    a syscall wrapper, the source calls it {unwrap(name)}")
    if not definitions:
        looked = ", ".join(paths) or "nothing"
        lines.append(f"found:   nothing, having looked in {looked}")
    else:
        lines.append("")
        lines.append(table(definitions))
    text = "\n".join(lines)
    print(text)
    return text
