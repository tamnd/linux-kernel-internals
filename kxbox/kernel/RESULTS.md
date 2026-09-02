# Kill criterion results

The bar is in `README.md`. A profile passes when it boots to a shell in under thirty seconds on a mid range laptop with `/proc`, `/sys/kernel/tracing`, `dmesg` and `insmod` all working.

**The kernel builds and it boots.** That was the open question for the whole of M0 and it is now answered for the part that a script can answer. What is not answered is the browser, and the two are kept in separate tables below for exactly that reason.

## Build

Filled in by `build.sh`. The compressed image is the number that matters, because it is what a reader downloads. The vmlinux is here to show where the weight is, and it is thirty times the size of the image because it carries the full DWARF that the blueprints are generated from and that never goes near a browser.

| Profile | Kernel | bzImage | vmlinux | Build time | Built on | Date |
| --- | --- | --- | --- | --- | --- | --- |
| `A-full` | 7.2.2 | 3408384 (3.25 MiB) | 106914512 (102 MiB) | 207s | M4 laptop, docker, cross from aarch64 | 2026-09-02 |
| `A-gzip` | 7.2.2 | 4567552 (4.36 MiB) | 106914512 (102 MiB) | 326s | M4 laptop, docker, cross from aarch64 | 2026-09-02 |
| `B-btf-external` | 7.2.2 | 2896384 (2.76 MiB) | 104525968 (100 MiB) | 243s | M4 laptop, docker, cross from aarch64 | 2026-09-02 |
| `C-longterm` | 6.18.48 | not measured | not measured | not measured | | |
| `D-lockdep` | 7.2.2 | 3600896 (3.43 MiB) | 121288336 (116 MiB) | 249s | M4 laptop, docker, cross from aarch64 | 2026-09-02 |

Two of those rows are the same kernel with one symbol changed, so the difference is the price of a decision and nothing else.

`A-gzip` costs 1.1 MiB, a third more download, for `CONFIG_KERNEL_XZ` becoming `CONFIG_KERNEL_GZIP`. The vmlinux is byte for byte the same size, because compression happens after the kernel is built. Whether the faster decompression pays for the extra download is a browser measurement and is not answered here.

`B-btf-external` saves 0.49 MiB off the image, which is fifteen percent, by dropping BTF out of it. That is a smaller saving than expected, and it is worth saying so: BTF is 2.07 MiB uncompressed and it compresses well, so most of what it costs in the image is already gone. Fifteen percent is real but it is not the difference between booting and not.

The toolchain for each build is recorded next to the image in `toolchain.toml`. For the `A-full` row above it was gcc 14.2.0, binutils 2.44 and pahole v1.30, which are the versions `pin.toml` asks for, but reached through `i686-linux-gnu-gcc` because the host is aarch64. That is a real deviation from what the pin means and it is written down rather than glossed over. An image built natively on x86 with the same versions has not been compared against this one.

## Boot in a browser

Measured in a browser tab, from the moment the page asks v86 to start to the moment a shell prompt is readable.

Every row names the machine and the browser, because thirty seconds on a developer's laptop and thirty seconds on a five year old Chromebook are different claims, and only one of them is the claim this project needs.

| Profile | Machine | Browser | Download | Decompress | To shell | Pass | Date |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `A-full` | | | | | | not measured | |
| `A-gzip` | | | | | | not measured | |
| `B-btf-external` | | | | | | not measured | |
| `C-longterm` | | | | | | not measured | |

This table is still empty and that is the honest state of it. Nobody has opened the page in a browser and timed it.

## Boot without a browser

v86 runs under node as well as in a tab, so `node kxbox/web/headless.js` boots the same kernel with the same rootfs and the same protocol on a machine with no display. This is what settles whether the kernel boots at all.

It is not a substitute for the table above. Node is not a tab, there is no page to download the image over a network, and this laptop is not a reader's machine. Reading a pass here as a pass on the kill criterion would be exactly the kind of claim this project keeps a ledger to stop.

| Profile | Machine | Runtime | To `__kx:READY` | Date |
| --- | --- | --- | --- | --- |
| `A-full` | M4 laptop, 128 MiB guest | node v26.7.0 | 4.2s to 5.2s idle, 9.0s with six cores busy | 2026-09-02 |
| `B-btf-external` | M4 laptop, 128 MiB guest | node v26.7.0 | 6.2s | 2026-09-02 |
| `D-lockdep` | M4 laptop, 128 MiB guest | node v26.7.0 | boots, measured under load only | 2026-09-02 |

The spread is worth keeping rather than averaging away. The slow number was measured while a kernel build had every core busy, and a reader with a browser full of tabs is closer to that case than to the idle one.

`D-lockdep` is in this table and not in the browser one on purpose. No reader boots it by default, so how fast it starts is not part of the kill criterion. What matters about it is that lockdep is actually running, and it is: `/proc/lockdep`, `/proc/lockdep_chains` and `/proc/lockdep_stats` all exist, the boot log says RCU lockdep checking is enabled, and `debug_locks` reads 1 after boot with 392 lock classes and 290675 chain lookup hits already recorded. That last number is what C09 needs, because a `debug_locks` of 0 means lockdep has already given up and every splat after it is missing.

## What worked once it booted

A boot that reaches a shell and cannot trace is a failure for this project even though it is a successful boot, so these are recorded separately rather than folded into a pass.

| Profile | `/proc` | `/sys/kernel/tracing` | `function_graph` | `dmesg` | `insmod` | BTF present |
| --- | --- | --- | --- | --- | --- | --- |
| `A-full` | yes | yes | yes | yes | yes | yes, 2173305 bytes |
| `B-btf-external` | yes | yes | yes | yes | yes | no, and that is the point |
| `C-longterm` | not measured | not measured | not measured | not measured | not measured | not measured |

The `A-full` row is what `headless.js smoke` checks, nine checks, each one named after a lesson that stops working without it. Alongside those: 50787 symbols in `/proc/kallsyms`, 16755 functions in `available_filter_functions`, and a real filtered `function_graph` tape came back through the four call protocol in 3.2 seconds.

The `no` in the `B-btf-external` row is the profile working. `/sys/kernel/btf` is not there at all, tracing and kallsyms are untouched, and the type information a blueprint needs has to come down as a second file. What that costs a reader is one more download and one more thing that can be missing, which is exactly the trade this profile exists to price.

Two things in that row were broken on the first build and are only yes because of it. `CONFIG_PRINTK` is off in `tinyconfig` along with everything else behind `EXPERT`, which gives a kernel that boots perfectly and has no `dmesg`. `CONFIG_FUNCTION_GRAPH_TRACER` was silently dropped because on 32-bit x86 it depends on the kernel not being built for size. Neither showed up as a build error. Both were found by reading the generated config, which is what the post build `tools.kconfig --verify` step exists to do.

## The decision

Not made, and it should not be made from this page.

What can be said today is that the pessimistic outcome is off the table. The worry was that a 7.2 kernel with BTF and full tracing would be too large or too slow to run under v86 at all, and that Tier 0 would have to become a recorded replay with rule 3 of the pedagogy rewritten around it. That has not happened. A 3.25 MiB image boots in single digit seconds outside a browser with everything the book needs turned on.

What is left is a measurement, not a redesign. Somebody has to open the page in Chrome and in Firefox on ordinary hardware and fill in the browser table. If that comes back over thirty seconds, `A-gzip` and `B-btf-external` are the next two things to try, in that order, and they exist for this.
