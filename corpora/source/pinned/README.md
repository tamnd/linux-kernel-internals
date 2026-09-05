# Five files out of the pinned kernel

Everything else in `corpora/` came off a running kernel. This came out of the tarball, so it is a different kind of evidence and it lives in a directory of its own rather than being filed next to the traces.

The tarball is `linux-7.2.2.tar.xz`, sha256 `7d0e7ce14f98c43efe880cffbf354a59be45928fdf7170d7333c374ae91c0d83`, which is the same checksum `kxbox/kernel/build.sh` and `kxbox/kernel/tree.sh` verify before either of them will do anything. The checksum is in every metadata file beside every capture here, so a file in this directory can be traced back to a kernel without going through anything this repository wrote.

## Why not the whole tree

The whole tree is 1.6 GB. `./kxbox/kernel/tree.sh` unpacks it and `kxray.source.tree.find()` uses it when it is there. This directory is what a reader has when it is not there, which is every reader opening a lesson in Colab and every CI run.

So this is a kernel tree in shape and almost none of one in content, and that difference has to survive being read. `Tree.complete` is False here, and a lookup that misses says the file is not in the corpus rather than saying it is not in the kernel. Those are different sentences and only one of them is true.

## What is here

```
corpora/source/pinned/
├── MAINTAINERS.excerpt                        # the format block and thirteen sections
├── arch/x86/entry/syscalls/syscall_32.tbl     # the numbers the pinned box answers to
├── arch/x86/entry/syscalls/syscall_64.tbl     # the numbers the reader's laptop answers to
├── fs/read_write.c                            # one real source file, whole
└── kernel/Kconfig.preempt                     # why a .config has symbols nobody chose
```

Four of the five are verbatim. The fifth is an excerpt, and the `.excerpt` on its name is the mechanism rather than a label: `Tree.read("MAINTAINERS")` finds it, returns it, and sets `partial` on what it hands back, so the fact that it is a slice travels with the content.

## MAINTAINERS.excerpt

The real file is 29847 lines and 916 KB, which is nine times the rest of this directory put together.

What is kept is the header block that documents the format, then the thirteen sections that cover the paths this repository cites, then three sections chosen for the tags they carry. ABI/API is the shortest section with an `X:` line on it, and exclusions are tested before matches. AUDIT SUBSYSTEM has a `K:` line, which matches on the content of a patch rather than on a path. TEGRA ARCHITECTURE SUPPORT has an `N:` line, and it is the same regex the header block uses as its own worked example.

Three things this file is here to show.

A path has more than one maintainer. `mm/memory.c` matches MEMORY MANAGEMENT, MEMORY MANAGEMENT - CORE and THE REST, and THE REST is the last section in the file with `F: *` and `F: */` on it, so it matches everything in Linux. Any lookup that takes the first hit and stops reports Linus for every file in the kernel.

The globs are not fnmatch. FILESYSTEMS (VFS and infrastructure) carries `F: fs/*`, and `fnmatch.fnmatch("fs/proc/base.c", "fs/*")` is True while the answer the file gives is False, because a single star stops at a slash. `fs/proc/` belongs to PROC FILESYSTEM, and the VFS section said so by writing one star instead of a trailing slash.

A section can name nobody. PROC FILESYSTEM has a status of Maintained, two mailing lists and no `M:` line at all, so the honest answer to who to mail is the lists.

## The two syscall tables

Write is 4 on i386 and 1 on x86-64. Read is 3 and 0. Both tables are here so that sentence can be a table rather than a claim.

The pinned box is 32 bit, so every syscall number any lesson prints comes out of `syscall_32.tbl`, and a reader comparing against the numbers they know from their own machine will find they do not line up. That is not a mistake in either place. A syscall number with no architecture attached is not an identifier.

Nineteen rows in the 32 bit table have a name and no entry point: `break`, `stty`, `gtty`, `ftime`, `prof` and the rest. Those numbers are reserved forever, because a binary from 1994 making one of those calls has to get ENOSYS rather than somebody else's system call.

The 64 bit table has three abis in it where the 32 bit one has one, and the same name appears under more than one of them. `rt_sigaction` is 13 under `64` and 512 under `x32`.

## fs/read_write.c

One real kernel source file, whole, so that symbol lookup and citation anchors have something to resolve against with nothing downloaded.

Nothing in this file is named `sys_write`, which is the name the syscall table uses. What is here is `SYSCALL_DEFINE3(write, ...)` on line 747, and the symbol the running kernel ends up with is `__ia32_sys_write`, which is in `corpora/proc/tier0/kallsyms-write.txt` off the box. Three names for one call and no two of them equal.

Grepping this file for `sys_write` is the part worth trying. It finds lines 728 and 750, and both are `ksys_write`, a different function that the real entry point calls. The reader lands three lines from what they wanted, on something close enough to be believed, and the thing they were actually looking for is spelled `write`.

`vfs_write` is defined on line 667 and is not exported, so a module cannot call it. `rw_verify_area` is exported. `__kernel_write` is exported to exactly one named module, `autofs4`. Being in `kallsyms` and being callable from a module are different questions.

## kernel/Kconfig.preempt

The pinned kernel is built with `CONFIG_PREEMPT=y`. Its `.config` also has `CONFIG_PREEMPT_BUILD=y` and `CONFIG_PREEMPTION=y` in it, which nobody asked for, and this file is the whole explanation: `PREEMPT` selects `PREEMPT_BUILD`, and `PREEMPT_BUILD` selects `PREEMPTION`.

Six of its fifteen symbols have a type and no prompt. A symbol with no prompt never appears in `menuconfig` and cannot be set by hand at all, and in a `.config` it looks exactly like something a person chose.

## Taking these again

```sh
./kxbox/kernel/tree.sh
```

That unpacks the pinned tarball into `kxbox/kernel/build/tree/linux-7.2.2/`, checksum verified. The four verbatim files are copies out of that. The excerpt is the header block plus the sections named in `MAINTAINERS.excerpt.meta.toml`, in the order the real file lists them, with the tabs left alone.

Nothing in here has been edited to match any prose. If a number in a metadata file disagrees with the file beside it, the file is right.
