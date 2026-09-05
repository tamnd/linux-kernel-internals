"""Asking the kernel source a question, from a notebook with almost none of it on disk.

    from kxray import source

    tree = source.tree.find()
    print(tree.describe())
    print(source.maintainers.load(tree).table("mm/memory.c"))
    print(source.syscalls.load(tree, "i386").by_number(4))

Every other package in `kxray` reads something a running kernel produced. This one reads the kernel
itself, which is a different problem, because the thing being read is 1.6 GB and a reader opening a
lesson in Colab has none of it.

So everything here goes through `tree.find()`, which returns the full unpacked source when
`./kxbox/kernel/tree.sh` has been run and the five files in `corpora/source/pinned/` when it has
not. The object says which it is, and a lookup that misses in the partial tree says "not in the
corpus" rather than "not in the kernel". Those are different sentences and only one of them is true.

Five modules, and each one exists because a name means something different depending on which of
them you asked.

`maintainers` reads MAINTAINERS, which is a glob engine wearing an address book. `syscalls` reads
the `.tbl` files, where write is 4 on i386 and 1 on x86-64. `kconfig` reads the kernel's own Kconfig
files, which is where a symbol with no prompt turns out to be on because something else selected it.
`symbols` bridges a name in a stack trace to the line that defines it, which for a system call means
going through a macro. `citations` is the anchor and the context hash that `tools/refcheck` uses, so
that a citation whose text still matches but whose surroundings have been rewritten gets noticed.

The models live in the modules rather than in `kxray/models/`, which is the opposite of what
`kxray.proc` does. The difference is real: the `/proc` readers hand their results to widgets, to the
baseline and to each other, so those types are shared and belong in the shared file. A syscall table
row is only ever a syscall table row, the same way a BTF header is only ever a BTF header, and
`kxray/btf/format.py` has kept its own dataclasses for that reason since the beginning.
"""

from __future__ import annotations

from kxray.source import citations, kconfig, maintainers, symbols, syscalls, tree

__all__ = [
    "citations",
    "kconfig",
    "maintainers",
    "symbols",
    "syscalls",
    "tree",
]
