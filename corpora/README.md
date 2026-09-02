# Corpora

Pinned evidence. Traces, BTF dumps, `/proc` snapshots, oops text, `herd7` output.

Everything in here is committed, and everything in here is an input to the build rather than a scratch file. A lesson whose evidence is not in the repository is a lesson nobody can check, and a parser without a committed fixture regresses the first time somebody touches it.

## Layout

```
corpora/
├── traces/tier0/        # captures off the pinned kernel running under v86
├── traces/tier1/        # captures off a real machine, for the things Tier 0 cannot do
├── traces/handwritten/  # parser fixtures, written from the documented format
├── btf/                 # vmlinux BTF blobs for the pinned kernels, and one small handwritten one
├── proc/                # /proc and /sys snapshots, and three handwritten files
├── experiments/         # measurements rather than recordings, so far all Tier 1
├── oops/                # crash and lockdep text used by the debugging lessons
├── litmus/              # herd7 and klitmus7 output for the memory model lessons
└── tier0/               # recipes.toml, the list of what a Tier 0 session can replay
```

## Tier 0 and Tier 1

Almost everything here is Tier 0, off the pinned kernel in a browser tab, because that is the tier every reader has and a capture off it can be compared against a capture off it from a year ago.

Tier 0 has exactly two limits that no amount of work removes. It has one CPU, so nothing about more than one CPU can be shown in it. And it has no real clock, so every duration in a Tier 0 trace is a number about v86 rather than about the kernel.

`traces/tier1/` and `experiments/tier1/` are for captures that hit one of those two and nothing else. A Tier 1 capture came off whatever machine somebody had, so its metadata carries the kernel version, the distribution, the architecture and the CPU count in full, and the one in here at the moment is arm64 running 6.8. That is a fine place to demonstrate that the trace file interleaves CPUs, which is true everywhere Linux runs. It would be a terrible place to demonstrate which functions a write calls. Knowing which of those you are doing is the whole job.

## Experiments

A capture says what the kernel did. An experiment says what it cost, which needs a clock, which is why `experiments/` is Tier 1 and likely to stay that way. Same rules otherwise: output committed exactly as it came out, metadata beside it, nothing edited to match the prose.

## The Tier 0 recipe list

`tier0/recipes.toml` is what makes the offline fallback work. Each entry has a name, the command that produced it, and which capture answers it. A lesson asks for a recording by name, the emulator runs the command when it is there, and the recording answers when it is not.

A recipe is added by capturing something on a real Tier 0 session and committing it. Not by writing one. Both recipes are captures now, taken off the pinned kernel booted under v86 and filed in `traces/tier0/`.

Taking them corrected three things the recipes had asserted from reading the source. `page-fault` named `exc_page_fault` as a function to filter on, and ftrace will not attach to that one at all, because it is `noinstr`. It named `do_anonymous_page`, which the compiler inlined out of this build. And `write-1byte` said its command was `dd if=/dev/zero of=/tmp/one bs=1 count=1`, which produces nine writes rather than one, because the shell writes its prompt and dd writes its summary and all of those are `vfs_write` too. None of the three was a careless guess and all three were wrong, which is the argument for the whole arrangement.

The fix for the third one was a program in the rootfs. `writebyte` opens its file, turns the tracer on, writes one byte, and turns it off, so the only thing in the window is the thing you asked for. It is the same trick `touchpage` uses to get one page fault instead of thirty, and the two share `tiny.h` for the syscall wrappers.

## What every artefact records

Each file has a sibling `.meta.toml` saying where it came from, so a reader can reproduce it and a future maintainer can tell whether it is still true.

- kernel version, exactly, and the config it was built with
- architecture, and whether it was uniprocessor
- the tier it came from, since Tier 0 is emulated and 32 bit
- the command that produced it
- when it was captured

## The handwritten ones

`traces/handwritten/`, `btf/handwritten/`, `proc/handwritten/` and `oops/handwritten/` are not evidence and never become evidence. They exist because a parser with nothing to parse is a parser nobody can trust, and they were written when there was no built kernel to capture from. Every `.meta.toml` in those four directories says `evidence = false`, and the claim checker rejects a claim that points at one, so the rule is enforced rather than remembered. The graders go further and refuse to run against them at all, because grading somebody on a file nobody captured is the one thing this project promises not to do.

They stay after their captures arrive. A handwritten fixture is a small file in a documented format that exercises one parser behaviour, and a real capture is three hundred lines of whatever the machine happened to be doing. Both are useful and they are useful for different things, so replacing one with the other would lose something. What changes when the capture arrives is which of them a claim is allowed to point at, and the answer to that was always the same.

## Why files get regenerated rather than edited

When a kernel bump changes a trace, the fix is to capture it again and let `kxdiff` show what moved. Editing the artefact to match the prose is how a book ends up describing a kernel that never existed.
