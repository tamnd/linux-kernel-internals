# Kill criterion results

The bar is in `README.md`. A profile passes when it boots to a shell in under thirty seconds on a mid range laptop with `/proc`, `/sys/kernel/tracing`, `dmesg` and `insmod` all working.

**The kernel builds, it boots, and it boots in a browser.** That was the open question for the whole of M0. The browser numbers and the node numbers are kept in separate tables below, because they turned out to differ by more than anybody expected and averaging them away would hide the useful part.

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

**The kernel boots in a browser tab and the whole stack works in one.** That is the kill criterion answered, and it is answered with a lot of room to spare.

Filled in by `just web-measure PROFILE`, which starts the server, starts Chrome on a profile it throws away afterwards, opens the harness page and reads the numbers back off it. Every row names the machine and the browser, because thirty seconds on a developer's laptop and thirty seconds on a five year old Chromebook are different claims, and only one of them is the claim this project needs.

`To shell` is from the emulator starting to the guest printing its ready marker. `Python up` is Pyodide downloading, starting and installing this project as a wheel, which happens while the checks run. `Both ways` is every recipe in the corpus run against the live kernel and against its recording, which is the M0 criterion that cannot be checked anywhere but here. `One trace` is a whole round trip through the bridge: Python asks for a trace, the tracer goes on inside the guest, one page fault happens, and a parsed tape comes back and is drawn.

Every row says whether the laptop was busy, because that turned out to matter more than which build was booted. Busy here means several rustc builds and a compiler running on the same machine, which is not a stress test, it is what a laptop looks like on an ordinary afternoon.

| Profile | Machine | Browser | Window | To shell | Python up | Both ways | One trace | Checks | Date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `A-full` | M4 laptop, 10 cores, idle | Chrome 152 | visible | 2.6s | 1.8s | 16.7s, 3 of 3 agree | 7.2s | 10 of 10 | 2026-09-02 |
| `A-full` | M4 laptop, 10 cores, busy | Chrome 152 | visible | 6.4s to 9.1s | 3.2s to 4.1s | 35.9s to 44.6s, 3 of 3 agree | 12.5s to 15.3s | 10 of 10 | 2026-09-02 |
| `A-full` | M4 laptop, 10 cores, busy | Chrome 152 | headless | 2.2s to 2.8s | 1.4s to 2.0s | 12.3s to 18.8s, 3 of 3 agree | 4.8s to 6.2s | 10 of 10 | 2026-09-02 |
| `A-gzip` | M4 laptop, 10 cores, busy | Chrome 152 | headless | 2.2s to 2.3s | 2.1s to 2.2s | 22.2s to 22.5s, 3 of 3 agree | 7.3s to 9.1s | 10 of 10 | 2026-09-02 |
| `B-btf-external` | M4 laptop, 10 cores, busy | Chrome 152 | headless | 3.3s to 3.7s | 2.4s to 2.5s | 22.8s, 3 of 3 agree | 8.0s to 9.1s | 10 of 10 | 2026-09-02 |
| `C-longterm` | | | | | | | | not measured | |

Every number in this table was taken after the console bug described below was fixed. The rows that were here before it are gone rather than kept for comparison, because they were measuring the page and not the kernel and leaving them in would invite somebody to average them in.

Five things came out of this, and the first two replace claims an earlier version of this file made.

**A visible window is about three times slower than a headless one, and almost all of that is sensitivity to what else the machine is doing.** Headless barely moves between an idle laptop and a busy one, 2.2 seconds against maybe 2.0. Visible goes from 2.6 seconds to between 6.4 and 9.1. So the honest way to say it is not that a window costs three times, it is that a window makes the emulator share a thread with a compositor and then compete with everything else for it. The headless and visible rows above were taken in alternating pairs on purpose, so the comparison between them is not a comparison of two afternoons.

**The gap on guest work was mostly this page's own rendering, not the emulator.** An earlier version of this file said a traced write took 7 seconds headless and 38 seconds in a window, and called that v86 pacing against the compositor. It was not. It was `harness.js` appending to the console element once per byte and reading `scrollHeight` once per byte, which is cheap once and quadratic a hundred thousand times, and which costs far more in a window that really lays out than in a headless one that mostly does not. After the fix the same trace takes 7.2 seconds in a visible window on an idle laptop. The 38 was a measurement of a bug.

**`A-gzip` does not boot fastest after all, and an earlier version of this file said it did.** That claim rested on one run at 1.3 seconds against one run at 2.2. Measured again, several runs each and all under the same load, `A-gzip` reaches a shell in 2.2 to 2.3 seconds and `A-full` in 2.2 to 2.8. They are the same within the spread, and `B-btf-external` is the slow one at 3.3 to 3.7. Faster decompression is worth something and it is not worth a third more download on this evidence.

**This cannot price the download, and the download is half the question.** Everything here is served from `127.0.0.1`, so a 3.25 MiB image and a 4.36 MiB image cost the same nothing to fetch. The choice between `A-full` and `A-gzip` is a real trade and this measurement does not settle it. What it does settle is that decompression is not the reason to prefer either.

**Python beside the kernel works, and that was never certain.** `kxbox/bridge.py` finds the bridge object, `micropip` installs this project into Pyodide, and `kxray` parses a trace that came out of a kernel running a few metres away in the same tab. Every one of those was written against a test double until now.

Not in this table and worth saying: Firefox. The measurement script drives Chrome over the DevTools protocol and Firefox does not speak it, so a Firefox row has to be taken by hand off the same page. Nobody has.

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

`A-full` stays the default, and the kill criterion is answered.

The worry was that a 7.2 kernel with BTF and full tracing would be too large or too slow to run under v86 at all, and that Tier 0 would have to become a recorded replay with rule 3 of the pedagogy rewritten around it. That has not happened. A 3.25 MiB image reaches a shell in a real Chrome window on this laptop in 2.6 seconds when nothing else is running and in 6.4 to 9.1 seconds when the machine is busy, with tracing, `dmesg`, modules and BTF all working, and with Python running beside it and reading a trace back out.

The number to hold against the thirty second bar is the busy one, because that is the machine a reader has. Nine seconds against thirty is enough room that the answer is unlikely to flip on slower hardware, but that is an argument and not a measurement, and the busy number moved by a factor of three when the laptop got busy while the headless number barely moved at all. So the thing most likely to cost a reader thirty seconds is not a slow CPU, it is a slow CPU with a lot already on it.

Two rows in the table above are still empty and both matter more than another row from this laptop. Somebody has to run it on an ordinary machine rather than an M4, and somebody has to run it in Firefox, which the script cannot drive.

`A-gzip` and `B-btf-external` were the fallbacks if this failed. They are not needed and they stay built and measured anyway, because the numbers they give are the price list for two decisions this project may want to revisit, and because a fallback that has never been run is not a fallback.
