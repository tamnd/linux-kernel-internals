# The userland inside the box

The kernel is the subject of this book. The rootfs is the smallest thing that lets you talk to it.

One statically linked busybox, three nine kilobyte programs, and one init script. That is the whole image, and it comes to 649 KiB compressed, next to a 3.25 MiB kernel.

## Building it

```sh
sh kxbox/rootfs/build.sh
```

No root. It downloads busybox, checks it against the sha256 in `pin.toml`, asks the binary which applets it has and stops if one the bridge needs is missing, compiles the three programs, then makes a cpio archive with `cpio -R 0:0` so every file is owned by root without anybody having to be root to say so.

The compiled programs need the container, because they are 32-bit x86 and the machine building them usually is not. That is the same container the kernel is built in, so it adds no toolchain that was not already needed. A machine with no docker gets an image without it and a warning saying what that costs.

The output is `build/initrd.gz` and it is not committed.

## The three programs

They exist for one reason each and it is the same reason. No busybox applet does one thing and stops, so every trace taken by running an applet has the interesting call somewhere in the middle of thirty others, and a beginner should not have to be told which one is theirs.

All three share `tiny.h`, which is the syscall wrappers and the entry point a C library would have provided. Adding a fourth means one line in `pin.toml` and one file beside it.

### touchpage

There is no way to trace one page fault with busybox. Running any applet faults about thirty times before it reaches your code, because a fork copies on write and an exec pages a binary in, and a trace with thirty faults in it is a trace where somebody has to tell the reader which one is theirs.

`touchpage` maps one anonymous page, turns the tracer on, writes one byte to it, and turns the tracer off. Nothing else may fault inside that window, which is why it has no C library in it at all and why it runs the whole sequence once against `/dev/null` first. It goes straight to the syscalls, which costs thirty lines of assembly and saves seven hundred kilobytes, because a static glibc with one `printf` in it is bigger than everything else in this image put together.

`corpora/traces/tier0/page-fault.txt` is what it produces.

### writebyte

`dd if=/dev/zero of=/tmp/one bs=1 count=1` is not one write. The shell writes its prompt, dd writes two lines of summary, busybox writes more on the way past, and filtering to `vfs_write` does not help because every one of those is a `vfs_write` too.

`writebyte` opens its file first, turns the tracer on, writes one byte, and turns it off, so the window has one write in it. The file it writes to is one nothing has written to before, which is the choice that makes the trace worth reading: a first write has to go and find a page and a second one is over in four frames.

`corpora/traces/tier0/write-1byte.txt` is what it produces.

### twowrites

The same thing done twice with the second destination swapped for a pipe. Both writes are the same system call with the same count, both go through the same `vfs_write`, and underneath that they run completely different kernel code, which is the whole of what S05 is about.

Both writes are in one tracer window rather than in two. Two captures taken a second apart could differ because something else on the machine changed, and nothing in the two files would let anybody rule it out.

`corpora/traces/tier0/two-writes.txt` is what it produces.

## Why an upstream binary

The busybox here is somebody else's build, downloaded from busybox.net. Building it from source would need a second cross toolchain and a second container, and would make the fast half of Tier 0 as slow as the kernel half.

The checksum is what makes that safe rather than a shrug. `pin.toml` records the version, the URL, the size and the sha256, and the build refuses a binary that does not match. If this ever needs to become a real build, it happens in this directory and nothing above it changes.

## What init does, and what it deliberately does not

It mounts `/proc`, `/sys`, a tmpfs on `/tmp` and tracefs on `/sys/kernel/tracing`, prints `__kx:READY`, and execs a shell. Thirty lines.

Everything else a lesson needs is a command the bridge sends over the serial port. That is not minimalism for its own sake. An init script that turns a tracer on, or sets a sysctl, or mounts something a lesson is about to claim it mounted, is an init script that makes the lessons lie: the reader runs a cell, sees the result, and the result was already true before they ran anything.

The ready line is the one thing here the page depends on. It waits for that exact string rather than for a shell prompt, because a prompt is whatever busybox decided this week and this marker is a fact we control.

## When tracefs is missing

The mount is allowed to fail and says `__kx:NOTRACEFS` on the console when it does. A box without tracefs still boots and is still no use, and a reader deserves to be told that on the first line rather than five cells later when a trace comes back empty.
