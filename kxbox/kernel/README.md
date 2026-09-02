# The pinned kernel

Every trace in this book, every field offset, every line number in a citation and every `/proc` snapshot comes from one kernel. This directory is where that kernel is pinned and where the config that makes it teachable lives.

Linux 7.2.2, released 2026-08-28, built for 32-bit x86 with one processor, because that is the machine v86 gives us. The version, the tarball URL and the sha256 are in `pin.toml`, read from the signed sums file on kernel.org on 2026-09-01. `build.sh` checks the tarball against that checksum and stops if it does not match, because a tarball that does not match the pin is not our kernel.

## This kernel has been built and it boots

`A-full` builds in about three and a half minutes and boots to a shell in a few seconds under node, with `/proc`, `/sys`, tracefs, `function_graph`, `dmesg`, module loading and fifty thousand kallsyms symbols all working. The numbers are in `RESULTS.md`.

The thing that was expected to break did not. The processor family line in `v86.config` was the worry, because it decides which instructions the compiler may emit and v86 does not implement all of them, and a failure there looks like an instant reboot with no output at all. What actually broke was the config: `tinyconfig` turns off `CONFIG_PRINTK` along with everything else behind `EXPERT`, so the first build produced a kernel with no `dmesg` at all, and the function graph tracer was silently dropped because on 32-bit x86 it depends on the kernel not being built for size. Neither of those is a boot failure. Both are a kernel that boots fine and cannot teach anything, which is exactly what the post build config check is for.

## Building one

```sh
./kxbox/kernel/build.sh A-full
```

It downloads the tarball, checks it, and builds inside a `debian:trixie-slim` container with gcc, binutils and pahole pinned by version in `pin.toml`. The container is the whole reason this is reproducible: a kernel built with a different pahole has different BTF, and BTF is what the blueprints are generated from.

The source tree lives in a docker volume rather than in the working directory. Unpacking ninety thousand files onto a mounted host directory is slow enough to be worth avoiding, and nothing outside the container ever needs to read them.

On an x86 host it builds natively. On anything else it installs `gcc-i686-linux-gnu` and cross compiles, because a 32-bit x86 kernel cannot be built by an aarch64 compiler no matter what `ARCH` says. That is a real deviation from what the pin means even though the compiler version matches, so it is recorded in `toolchain.toml` next to the image rather than left in somebody's shell history.

The output lands in `kxbox/kernel/build/<profile>/` and is not committed. The recipe is in the repository, the artefacts are not.

## Reading the source

The build keeps its tree inside the container, which is fine for building and no use at all for looking things up. `tree.sh` unpacks the same tarball where a person and a checker can read it.

```sh
./kxbox/kernel/tree.sh
python3 -m tools.refcheck --tree kxbox/kernel/build/tree/linux-7.2.2 --confirm
```

It is the pristine tarball rather than a copy of the built tree, and that difference matters. A built tree has generated headers in it, so a citation that resolved against one would resolve for the person who ran the build and for nobody else. What comes out of `tree.sh` is what comes out of kernel.org, checked against the same sha256 the build checks.

It takes a couple of minutes and about 1.6 GB, and `build/` is ignored by git, so `rm -rf kxbox/kernel/build/tree` is how you get the space back.

## Building a module

C09 needs a module in the box, so there is a script for it.

```sh
./kxbox/kernel/module.sh D-lockdep lessons/C09/assets
```

The second argument is a directory with a `.c` file and a `Makefile` in it, and what comes out is a `.ko` beside them. `./kxbox/rootfs/build.sh` picks up any it finds and puts it in the image under `/lib/modules`.

It takes a profile name rather than assuming one, and that is not a convenience. A module carries a `vermagic` string built into it, and that string has the preemption model and a few other switches in it as well as the version, so a module built against `A-full` is refused by `D-lockdep` and the other way round. There is no one module that works in every profile.

The script reconfigures the tree in the container for the profile you asked for before it builds anything, because the tree keeps whatever config was built in it last. It also runs `make modules` first, which is what writes `Module.symvers`. Without that file every out of tree module builds with a page of undefined symbol warnings and then fails to load, which is a bad way to find out.

## Booting a profile that is not A-full

```sh
KXBOX_PROFILE=D-lockdep node kxbox/web/headless.js sh 'cat /proc/lockdep_stats'
```

`A-full` is the default and is what the smoke test and the measurements use. The others exist to be compared against it, and two of them can only be told apart by running them: `D-lockdep` is the same source and the same compiler, and the difference is not visible in the image size or in anything short of a boot.

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

`RESULTS.md`, next to this file. One row per profile per measurement, with the machine it was measured on, because thirty seconds on a developer's laptop and thirty seconds on a five year old Chromebook are different claims.

The build table has real numbers in it now. The boot table has one row from a headless run and no rows from a browser, and the difference is the whole point of keeping them in separate tables.
