# Corpora

Pinned evidence. Traces, BTF dumps, `/proc` snapshots, oops text, `herd7` output.

Everything in here is committed, and everything in here is an input to the build rather than a scratch file. A lesson whose evidence is not in the repository is a lesson nobody can check, and a parser without a committed fixture regresses the first time somebody touches it.

## Layout

```
corpora/
├── traces/          # ftrace function_graph and trace_event captures
├── btf/             # vmlinux BTF blobs for the pinned kernels, and one small handwritten one
├── proc/            # /proc and /sys snapshots
├── oops/            # crash text used by the debugging lessons
├── litmus/          # herd7 and klitmus7 output for the memory model lessons
└── tier0/           # recipes.toml, the list of what a Tier 0 session can replay
```

## The Tier 0 recipe list

`tier0/recipes.toml` is what makes the offline fallback work. Each entry has a name, the command that produced it, and which capture answers it. A lesson asks for a recording by name, the emulator runs the command when it is there, and the recording answers when it is not.

A recipe is added by capturing something on a real Tier 0 session and committing it. Not by writing one. The two listed today point at handwritten traces, which is stated in their metadata and in the banner every lesson prints, and they get replaced by captures the day a kernel boots.

## What every artefact records

Each file has a sibling `.meta.toml` saying where it came from, so a reader can reproduce it and a future maintainer can tell whether it is still true.

- kernel version, exactly, and the config it was built with
- architecture, and whether it was uniprocessor
- the tier it came from, since Tier 0 is emulated and 32 bit
- the command that produced it
- when it was captured

## The handwritten ones

`traces/handwritten/` and `btf/handwritten/` are not evidence and never become evidence. They exist because a parser with nothing to parse is a parser nobody can trust, and there is no built kernel yet. Every `.meta.toml` in those two directories says `evidence = false`, and the claim checker rejects a claim that points at one, so the rule is enforced rather than remembered.

## Why files get regenerated rather than edited

When a kernel bump changes a trace, the fix is to capture it again and let `kxdiff` show what moved. Editing the artefact to match the prose is how a book ends up describing a kernel that never existed.
