# Handwritten traces

These are not captures. Nobody ran a kernel to produce them. They were written by hand from the format documented in `Documentation/trace/ftrace.rst` and from the code in `kernel/trace/trace_functions_graph.c`, so that the parser had something to be tested against before the browser kernel exists.

Saying that plainly matters, because the whole project rests on not asserting anything the reader cannot watch happen. So:

**No lesson may cite anything in this directory.** They are parser fixtures and nothing else. Every `.meta.toml` here has `evidence = false`, and the claim checker will reject a claim that points at one.

The call sequences are plausible and the arithmetic is consistent, which is what a parser test needs. They are not a record of what any kernel did, and small details are likely to be wrong in ways that do not matter here and would matter a lot in a lesson.

## When these go away

They do not, but they have stopped being the interesting ones. `kxbox` boots the pinned kernel now, and the first real capture is in `../tier0/`, with `evidence = true` and the command that produced it. These stay as parser fixtures, because a real capture is a bad regression test: it is long, it is noisy, and it changes when the kernel changes for reasons that have nothing to do with the parser.

It is worth comparing `page-fault.txt` here with `../tier0/page-fault.txt`, because the two were meant to be the same thing and they are not. This one has `__handle_mm_fault` and `do_anonymous_page` in it, and the real one has neither, because the compiler flattened both. This one starts at `exc_page_fault`, and the real one cannot, because ftrace is not allowed to attach there. Everything in this file was written from the source by somebody being careful, and it is still wrong in two ways that only a capture would find.

## The files

`write-1byte.txt` is the write path for a one byte write to a file on tmpfs, eight levels deep on one CPU. It is the shape the Syscall Tape has to render, so it is the shape the parser is measured against.

`page-fault.txt` exercises everything else in the format at once: the task column that `funcgraph-proc` adds, the interrupt entry and exit markers, a `trace_printk` comment, a task switch banner, and a frame at the end that never closes because the trace was cut off.
