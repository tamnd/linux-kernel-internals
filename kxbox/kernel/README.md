# The pinned kernel

Every trace in this book, every field offset, every line number in a citation and every `/proc` snapshot comes from one kernel. This directory is where that kernel is pinned and where the config that makes it teachable lives.

Linux 7.2.2, released 2026-08-28, built for 32-bit x86 with one processor, because that is the machine v86 gives us. The version, the tarball URL and the sha256 are in `pin.toml`, read from the signed sums file on kernel.org on 2026-09-01. `build.sh` checks the tarball against that checksum and stops if it does not match, because a tarball that does not match the pin is not our kernel.

## Nothing here has been built yet

That is the honest state of this directory, and it is worth saying at the top rather than in a footnote.

What exists is the recipe, the requirement list and the checker. What does not exist is an image, a boot, or a single measurement. The first build is what turns any of this from a plan into a fact, and until then the most likely thing to be wrong is the processor family line in `v86.config`, because it decides which instructions the compiler may emit and v86 does not implement all of them. A boot failure there looks like an instant reboot with no output at all.

## Building one

```sh
./kxbox/kernel/build.sh A-full
```

It downloads the tarball, checks it, and builds inside a `debian:trixie-slim` container with gcc, binutils and pahole pinned by version in `pin.toml`. The container is the whole reason this is reproducible: a kernel built with a different pahole has different BTF, and BTF is what the blueprints are generated from.

The output lands in `kxbox/kernel/build/<profile>/` and is not committed. The recipe is in the repository, the artefacts are not.

## The config

`config/` holds Kconfig fragments, not a `.config`. A committed `.config` would be stale after one release and wrong in a way nobody could see, so the fragments get merged over `tinyconfig` by the kernel's own `merge_config.sh`, which is the only thing that understands the dependencies between these symbols.

- `teaching.config`, everything the book needs the kernel to be able to say about itself. Tracing, kprobes, `KALLSYMS_ALL`, BTF, `/proc`, `/sys`, debugfs, modules.
- `v86.config`, the shape of the emulated machine. 32-bit, uniprocessor, serial console, initramfs, and a list of things switched off because a browser pays for every byte twice.
- `btf-external.config`, `gzip.config` and `lockdep.config`, the deltas that make the other profiles.

`just kconfig` checks all of it. The list with teeth is `REQUIRED` in `tools/kconfig.py`: every symbol the book stops working without, each with a line saying what breaks. A profile is allowed to drop one, because profile B exists to drop BTF, but it has to declare the drop in `pin.toml` and give a reason. Turning off a requirement is a decision. Turning one off quietly is how a project ends up with lessons that cannot run and nobody knowing which change did it.

There is a second check for after a build. A fragment says what was asked for, and a `.config` says what Kconfig did with it once every dependency was resolved. A symbol whose dependencies are unmet gets dropped with no error at all, so `build.sh` runs `tools.kconfig --verify` on the generated config before it believes the build.

## The kill criterion

The whole project rests on one unverified assumption: that this kernel, with this config, boots under v86 in a browser tab in under thirty seconds on an ordinary laptop.

v86 boots real Linux distributions today, so the emulator is not what is in doubt. Our kernel with our config is. BTF alone adds several megabytes, and image size is the thing a browser pays for twice, once to download and once to decompress.

Four profiles get tried, in the order they are listed in `pin.toml`, and each one gives up less than the next.

| Profile | What it gives up | Why it might be needed |
| --- | --- | --- |
| `A-full` | Nothing | This is the book as designed |
| `A-gzip` | A bigger download for a faster decompression | Which of the two wins is a measurement, not an argument |
| `B-btf-external` | BTF is a second download rather than part of the image | Several megabytes off the boot path |
| `C-longterm` | The 7.2 tree, falling back to 6.18 longterm | If 7.2 is simply too large to boot in a tab |

`D-lockdep` is not in that list. It is built for lesson C09, it is deliberately slow, and no reader boots it by default, so a failure there says nothing about whether Tier 0 works.

**Pass** is a profile that boots to a shell in under thirty seconds on a mid range laptop with `/proc`, `/sys/kernel/tracing`, `dmesg` and `insmod` all working. **Fail** is every profile missing that bar.

If all four fail, Tier 0 becomes fully recorded. Every experiment turns into a replay of a real session instead of a live kernel, rule 3 of the pedagogy has to be rewritten, and the project is materially weaker. That decision gets made in the open, at M0, with the numbers published, rather than discovered in month ten.

## Where the numbers go

`RESULTS.md`, next to this file. One row per profile per measurement, with the machine it was measured on, because thirty seconds on a developer's laptop and thirty seconds on a five year old Chromebook are different claims. It is empty today and it says so.
