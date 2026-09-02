# Corpora

Pinned evidence. Traces, BTF dumps, `/proc` snapshots, oops text, `herd7` output.

Everything in here is committed, and everything in here is an input to the build rather than a scratch file. A lesson whose evidence is not in the repository is a lesson nobody can check, and a parser without a committed fixture regresses the first time somebody touches it.

## Layout

```
corpora/
├── traces/tier0/    # captures off the pinned kernel running under v86
├── traces/handwritten/  # parser fixtures, written from the documented format
├── btf/             # vmlinux BTF blobs for the pinned kernels, and one small handwritten one
├── proc/            # /proc and /sys snapshots, and three handwritten files
├── oops/            # crash and lockdep text used by the debugging lessons
├── litmus/          # herd7 and klitmus7 output for the memory model lessons
└── tier0/           # recipes.toml, the list of what a Tier 0 session can replay
```

## The Tier 0 recipe list

`tier0/recipes.toml` is what makes the offline fallback work. Each entry has a name, the command that produced it, and which capture answers it. A lesson asks for a recording by name, the emulator runs the command when it is there, and the recording answers when it is not.

A recipe is added by capturing something on a real Tier 0 session and committing it. Not by writing one. `page-fault` is a capture now, taken off the pinned kernel booted under v86 and filed in `traces/tier0/`. `write-1byte` is still handwritten, which is stated in its metadata and in the banner every lesson prints, and it gets replaced the same way.

Taking that first capture corrected two things the recipe had asserted from reading the source. It named `exc_page_fault` as a function to filter on, and ftrace will not attach to that one at all. It named `do_anonymous_page`, which the compiler inlined out of this build. Neither was a careless guess and both were wrong, which is the argument for the whole arrangement.

## What every artefact records

Each file has a sibling `.meta.toml` saying where it came from, so a reader can reproduce it and a future maintainer can tell whether it is still true.

- kernel version, exactly, and the config it was built with
- architecture, and whether it was uniprocessor
- the tier it came from, since Tier 0 is emulated and 32 bit
- the command that produced it
- when it was captured

## The handwritten ones

`traces/handwritten/`, `btf/handwritten/`, `proc/handwritten/` and `oops/handwritten/` are not evidence and never become evidence. They exist because a parser with nothing to parse is a parser nobody can trust, and there is no built kernel yet. Every `.meta.toml` in those four directories says `evidence = false`, and the claim checker rejects a claim that points at one, so the rule is enforced rather than remembered. The graders go further and refuse to run against them at all, because grading somebody on a file nobody captured is the one thing this project promises not to do.

## Why files get regenerated rather than edited

When a kernel bump changes a trace, the fix is to capture it again and let `kxdiff` show what moved. Editing the artefact to match the prose is how a book ends up describing a kernel that never existed.
