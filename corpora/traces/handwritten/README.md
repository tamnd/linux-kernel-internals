# Handwritten traces

These are not captures. Nobody ran a kernel to produce them. They were written by hand from the format documented in `Documentation/trace/ftrace.rst` and from the code in `kernel/trace/trace_functions_graph.c`, so that the parser had something to be tested against before the browser kernel exists.

Saying that plainly matters, because the whole project rests on not asserting anything the reader cannot watch happen. So:

**No lesson may cite anything in this directory.** They are parser fixtures and nothing else. Every `.meta.toml` here has `evidence = false`, and the claim checker will reject a claim that points at one.

The call sequences are plausible and the arithmetic is consistent, which is what a parser test needs. They are not a record of what any kernel did, and small details are likely to be wrong in ways that do not matter here and would matter a lot in a lesson.

## When these go away

They do not, but they stop being the interesting ones. Once `kxbox` boots the pinned kernel, real captures land in `corpora/traces/` beside them, with `evidence = true` and the command that produced them. At that point these stay as parser fixtures, because a real capture is a bad regression test: it is long, it is noisy, and it changes when the kernel changes for reasons that have nothing to do with the parser.

## The files

`write-1byte.txt` is the write path for a one byte write to a file on tmpfs, eight levels deep on one CPU. It is the shape the Syscall Tape has to render, so it is the shape the parser is measured against.

`page-fault.txt` exercises everything else in the format at once: the task column that `funcgraph-proc` adds, the interrupt entry and exit markers, a `trace_printk` comment, a task switch banner, and a frame at the end that never closes because the trace was cut off.
