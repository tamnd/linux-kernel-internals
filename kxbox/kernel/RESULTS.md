# Kill criterion results

**Nothing has been measured yet.** The tables below are empty on purpose, with the columns already decided, so that the first person to run a build has nowhere to put a vague answer.

The bar is in `README.md`. A profile passes when it boots to a shell in under thirty seconds on a mid range laptop with `/proc`, `/sys/kernel/tracing`, `dmesg` and `insmod` all working.

## Build

Filled in by `build.sh`. The compressed image is the number that matters, because it is what a reader downloads, and the vmlinux is here to show where the weight is.

| Profile | Kernel | bzImage | vmlinux | Build time | Built on | Date |
| --- | --- | --- | --- | --- | --- | --- |
| `A-full` | 7.2.2 | not measured | not measured | not measured | | |
| `A-gzip` | 7.2.2 | not measured | not measured | not measured | | |
| `B-btf-external` | 7.2.2 | not measured | not measured | not measured | | |
| `C-longterm` | 6.18.48 | not measured | not measured | not measured | | |
| `D-lockdep` | 7.2.2 | not measured | not measured | not measured | | |

## Boot

Measured in a browser tab, from the moment the page asks v86 to start to the moment a shell prompt is readable.

Every row names the machine and the browser, because thirty seconds on a developer's laptop and thirty seconds on a five year old Chromebook are different claims, and only one of them is the claim this project needs.

| Profile | Machine | Browser | Download | Decompress | To shell | Pass | Date |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `A-full` | | | | | | not measured | |
| `A-gzip` | | | | | | not measured | |
| `B-btf-external` | | | | | | not measured | |
| `C-longterm` | | | | | | not measured | |

## What worked once it booted

A boot that reaches a shell and cannot trace is a failure for this project even though it is a successful boot, so these are recorded separately rather than folded into a pass.

| Profile | `/proc` | `/sys/kernel/tracing` | `function_graph` | `dmesg` | `insmod` | BTF present |
| --- | --- | --- | --- | --- | --- | --- |
| `A-full` | not measured | not measured | not measured | not measured | not measured | not measured |
| `B-btf-external` | not measured | not measured | not measured | not measured | not measured | not measured |
| `C-longterm` | not measured | not measured | not measured | not measured | not measured | not measured |

## The decision

Not made. It gets made here, in this file, with the numbers above filled in and a sentence saying which profile the project ships on.

If every profile in the boot table fails, this section says so, and says that Tier 0 became a recorded replay, and the pedagogy spec gets rewritten in the same pull request.
