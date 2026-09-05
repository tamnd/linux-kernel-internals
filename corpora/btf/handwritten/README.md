# A handwritten BTF blob

`tiny.btf` is not a kernel. Nobody built one to produce it. It was written by `make.py` in this directory, from the format documented in `Documentation/bpf/btf.rst`, so that the BTF reader had something to be tested against before there is a kernel to read BTF from.

Saying that plainly matters, because the whole project rests on not asserting anything the reader cannot watch happen. So:

**No lesson may cite anything in this directory.** It is a parser fixture and nothing else. The `.meta.toml` beside it has `evidence = false`, and the claim checker will reject a claim that points at it.

The types in it are made up, and they are named `demo_` so that nobody mistakes them for kernel structs. The offsets are the ones a 64-bit compiler would pick for the fields as written. That is a property of the fixture, not a measurement of anything.

## Why it is shaped the way it is

Every kind in the format appears at least once, so a change to the reader that breaks one of the rare kinds fails a test rather than surfacing in a lesson six months later. That includes the ones nobody thinks about: `enum64`, `type_tag`, `decl_tag`, `datasec`, a forward declaration, and a function with static linkage.

There are three holes in it on purpose. `demo_task` has six bytes of padding in the middle, because `flags` and `waiting` are one byte each and `weight` has to start on an eight byte boundary. `demo_arg` has four bytes of padding at the end, because a struct has to be a multiple of the alignment of its widest member, and a trailing hole is the one people miss. A layout with no padding in it teaches nobody anything about padding.

`demo_annotated` is four pointers, three of them carrying a type tag: `__user`, `__rcu` and `__percpu`. All four are the same size and sit at the offsets you would expect, which is the point of it. An annotation changes nothing about memory, and the only thing separating a pointer you may follow from one that will crash the machine is a tag riding on the type. The fourth pointer is annotated with nothing, because a test where every field matches proves less than one with a control in it.

`demo_flags` holds three bitfields in one byte, written the modern way, with the width in the member record and `kind_flag` set on the struct. There is an older encoding that narrows the int type behind the member instead, and the reader handles both, because both are still in the wild.

## Rebuilding it

```
python3 corpora/btf/handwritten/make.py
```

The bytes are committed and a test rebuilds them and compares, so an edit to the writer that changes the fixture fails CI with the file name rather than turning up as a puzzling reader test failure.

## When this goes away

It does not, but it stops being the interesting one. Once there is a built kernel, the real `/sys/kernel/btf/vmlinux` gets read and the answers get checked against `pahole` output, with `evidence = true` and the command that produced it. This stays as a fixture, because a real vmlinux blob is a bad regression test: it is five megabytes, it has ninety thousand types in it, and it changes for reasons that have nothing to do with the reader.
