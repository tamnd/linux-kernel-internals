# Corpora

Pinned evidence. Traces, BTF dumps, `/proc` snapshots, oops text, `herd7` output.

Everything in here is committed, and everything in here is an input to the build rather than a scratch file. A lesson whose evidence is not in the repository is a lesson nobody can check, and a parser without a committed fixture regresses the first time somebody touches it.

## Layout

```
corpora/
├── traces/          # ftrace function_graph and trace_event captures
├── btf/             # vmlinux BTF blobs for the pinned kernels
├── proc/            # /proc and /sys snapshots
├── oops/            # crash text used by the debugging lessons
└── litmus/          # herd7 and klitmus7 output for the memory model lessons
```

## What every artefact records

Each file has a sibling `.meta.toml` saying where it came from, so a reader can reproduce it and a future maintainer can tell whether it is still true.

- kernel version, exactly, and the config it was built with
- architecture, and whether it was uniprocessor
- the tier it came from, since Tier 0 is emulated and 32 bit
- the command that produced it
- when it was captured

## Why files get regenerated rather than edited

When a kernel bump changes a trace, the fix is to capture it again and let `kxdiff` show what moved. Editing the artefact to match the prose is how a book ends up describing a kernel that never existed.
