# The userland inside the box

The kernel is the subject of this book. The rootfs is the smallest thing that lets you talk to it.

One statically linked busybox, one strace, three nine kilobyte programs, and one init script. That is the whole image, and it comes to 1.66 MiB compressed, next to a 3.25 MiB kernel.

## Building it

```sh
sh kxbox/rootfs/build.sh
```

No root. It downloads busybox, checks it against the sha256 in `pin.toml`, asks the binary which applets it has and stops if one the bridge needs is missing, compiles the three programs, builds strace, then makes a cpio archive with `cpio -R 0:0` so every file is owned by root without anybody having to be root to say so.

Everything compiled needs the container, because it is all 32-bit x86 and the machine building it usually is not. That is the same container the kernel is built in, so it adds no toolchain that was not already needed. A machine with no docker gets an image without any of it and a warning saying what that costs.

The output is `build/initrd.gz` and it is not committed.

## strace

The function graph tracer says what the kernel did once it was inside a call, and how long each frame took. It does not say what the program asked for. The arguments, the file descriptors, the flags and the errno on the way back are not in a tape and no amount of reading one recovers them, because the tracer records entry and exit and those values live in registers it never samples.

Those are the first questions anybody has, and until now the box could not answer them. Here is `writebyte`, which the section below describes in words:

```
execve("/bin/writebyte", ["/bin/writebyte", "/tmp/probe"], 0xbffaf98c /* 6 vars */) = 0
open("/tmp/.writebyte-warmup", O_WRONLY|O_CREAT|O_TRUNC, 0600) = 3
write(3, "x", 1)                        = 1
close(3)                                = 0
unlink("/tmp/.writebyte-warmup")        = 0
open("/tmp/one-byte", O_WRONLY|O_CREAT|O_TRUNC, 0600) = 3
open("/sys/kernel/tracing/tracing_on", O_WRONLY) = 4
write(4, "1\n", 2)                      = 2
write(3, "x", 1)                        = 1
write(4, "0\n", 2)                      = 2
close(4)                                = 0
close(3)                                = 0
write(1, "wrote 1 byte to /tmp/one-byte\n", 30) = 30
exit(0)                                 = ?
+++ exited with 0 +++
```

Everything the section below claims is on that page. The warmup runs the whole sequence once and throws it away. The file is opened before the window rather than inside it. Between the two writes to `tracing_on` there is one `write`, which is the claim all three programs are built on and which nothing was checking until this binary went in.

It is built from the release tarball rather than downloaded, because nobody publishes a static i686 strace. The build is the expensive thing here: about thirty seven minutes on an arm laptop, where almost all of it is qemu translating x86 one instruction at a time, and a couple of minutes on an x86 machine. The result is cached beside busybox and reused, so it happens once.

It costs about a megabyte compressed, which more than doubles the image. Most of that is a static glibc plus the tables that turn a syscall number and six longs into a line somebody can read, and those tables are the entire feature.

Three things it will not do here. `-k` needs libunwind and there is none, so `strace -V` reports `Optional features enabled: (none)`. The `seconds` column of `strace -c` is emulated time on Tier 0 and means nothing, the same as every other duration in the box. And attaching to a process stops it twice per system call, so a tape taken while strace is attached is a tape of ptrace doing its job, which is a real trace of something nobody asked about.

## Modules

The image also carries any `.ko` it finds beside a lesson, which today means `abba.ko` from `lessons/C09/assets`, put in at `/lib/modules` where `insmod` can reach it.

Nothing here builds one. A module needs the kernel tree, which needs the container and the volume, so `kxbox/kernel/module.sh` builds it and this copies it. That also makes it optional in a way the programs below are not: a module is compiled against one profile and refused by every other, because `vermagic` carries the preemption model along with the version, so an image that insisted on having one would only build for somebody who had run the kernel build. An image with no module boots exactly the same, and the lesson that wants one falls back to the committed capture.

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

## Why busybox is downloaded and strace is built

The busybox here is somebody else's build, downloaded from busybox.net. Building it from source would need a second cross toolchain and a second container, and would make the fast half of Tier 0 as slow as the kernel half.

strace goes the other way for a duller reason than any argument: there is no static i686 binary to download. So it is built, and the thirty seven minutes that costs is the price of the only option there was.

The checksum is what makes both safe rather than a shrug. `pin.toml` records the version, the URL, the size and the sha256 of each, and the build refuses anything that does not match. For strace the checksum is on the source tarball, which is the thing that came off the network, and `built_bytes` beside it records what the compiler then made of it, so a build that starts producing something a long way from that is a build somebody should look at.

## What init does, and what it deliberately does not

It mounts `/proc`, `/sys`, a tmpfs on `/tmp` and tracefs on `/sys/kernel/tracing`, prints `__kx:READY`, and execs a shell. Thirty lines.

Everything else a lesson needs is a command the bridge sends over the serial port. That is not minimalism for its own sake. An init script that turns a tracer on, or sets a sysctl, or mounts something a lesson is about to claim it mounted, is an init script that makes the lessons lie: the reader runs a cell, sees the result, and the result was already true before they ran anything.

The ready line is the one thing here the page depends on. It waits for that exact string rather than for a shell prompt, because a prompt is whatever busybox decided this week and this marker is a fact we control.

## When tracefs is missing

The mount is allowed to fail and says `__kx:NOTRACEFS` on the console when it does. A box without tracefs still boots and is still no use, and a reader deserves to be told that on the first line rather than five cells later when a trace comes back empty.
