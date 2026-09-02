# The userland inside the box

The kernel is the subject of this book. The rootfs is the smallest thing that lets you talk to it.

One statically linked busybox and one init script. That is the whole image, and it comes to 647 KiB compressed, next to a 3.25 MiB kernel.

## Building it

```sh
sh kxbox/rootfs/build.sh
```

No container and no root. It downloads busybox, checks it against the sha256 in `pin.toml`, asks the binary which applets it has and stops if one the bridge needs is missing, then makes a cpio archive with `cpio -R 0:0` so every file is owned by root without anybody having to be root to say so.

The output is `build/initrd.gz` and it is not committed.

## Why an upstream binary

The busybox here is somebody else's build, downloaded from busybox.net. Building it from source would need a second cross toolchain and a second container, and would make the fast half of Tier 0 as slow as the kernel half.

The checksum is what makes that safe rather than a shrug. `pin.toml` records the version, the URL, the size and the sha256, and the build refuses a binary that does not match. If this ever needs to become a real build, it happens in this directory and nothing above it changes.

## What init does, and what it deliberately does not

It mounts `/proc`, `/sys`, a tmpfs on `/tmp` and tracefs on `/sys/kernel/tracing`, prints `__kx:READY`, and execs a shell. Thirty lines.

Everything else a lesson needs is a command the bridge sends over the serial port. That is not minimalism for its own sake. An init script that turns a tracer on, or sets a sysctl, or mounts something a lesson is about to claim it mounted, is an init script that makes the lessons lie: the reader runs a cell, sees the result, and the result was already true before they ran anything.

The ready line is the one thing here the page depends on. It waits for that exact string rather than for a shell prompt, because a prompt is whatever busybox decided this week and this marker is a fact we control.

## When tracefs is missing

The mount is allowed to fail and says `__kx:NOTRACEFS` on the console when it does. A box without tracefs still boots and is still no use, and a reader deserves to be told that on the first line rather than five cells later when a trace comes back empty.
