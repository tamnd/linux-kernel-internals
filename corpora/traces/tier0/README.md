# Tier 0 captures

These are recordings. A kernel ran, a tracer was on, and this is what came out.

That is the difference between this directory and `../handwritten/`, and it is the only difference that matters. Every `.meta.toml` here says `evidence = true`, so a lesson may cite one and a blueprint may rest a claim on one. The handwritten files next door say `evidence = false` and the claim checker refuses them.

Tier 0 is the browser emulator, so everything here comes off the pinned 7.2.2 built for 32-bit x86 with one processor, running under v86. That is a real kernel doing real work and it is not a real machine. What that costs is written in each file's metadata, and the short version is that the order of events is true and the durations are not.

## Taking one

Every capture records the exact command and the exact setup that produced it, so a capture can be taken again and compared rather than argued about. The `setup` list in a `.meta.toml` is the sequence of writes, in order, and `command` is what ran with the tracer on.

```
node kxbox/web/headless.js sh '...'
```

is enough to do it by hand. `kxbox` does the same thing from Python, through `box.tape(name)`, and looks the recording up here when there is no emulator.

Two tracers write files into this directory. Anything named `flat-` came off the flat function tracer, which prints one line per call with no nesting and no duration, and everything else came off `function_graph`, which prints the call tree with a time against each frame. The difference is not cosmetic and it decides which questions a file can answer, so it is in the file name rather than only in the metadata.

## page-fault.txt

One anonymous page, written to for the first time, by `/bin/touchpage`. That program exists because there was no other way to get one fault. Running any busybox applet traces about thirty of them, because a fork copies on write and an exec pages a binary in, and a reader should not have to be told which of thirty faults is theirs.

Three things in this file are worth knowing before reading it.

It does not start at `exc_page_fault`. That function is `noinstr`, and so is `do_user_addr_fault`, which means ftrace is not allowed to attach to either and the kernel rejects the name. Tracing the first instructions after a trap is not safe, so the earliest a fault can be watched is after the handler has decided the address is a user address.

The first line is a `mutex_unlock()` with nothing above it. It is the tail of the `write` that turned tracing on. Traces start in the middle of something, always, and trimming it would make the file tidier and less true.

Several functions the blueprint names are not in it. `__handle_mm_fault`, `handle_pte_fault` and `do_anonymous_page` are all `static` with one caller and the compiler flattened them, so what you see under `handle_mm_fault` is their contents rather than their names. `blueprints/page-fault.md` section 8 has the whole list and how it was confirmed.

## write-1byte.txt

One byte written to a file on tmpfs, by `/bin/writebyte`, which exists for the same reason `/bin/touchpage` does.

`dd if=/dev/zero of=/tmp/one bs=1 count=1` is not one write. The shell writes its prompt, dd writes two lines of summary, busybox writes more on the way past, and filtering to `vfs_write` does not help because every one of those is a `vfs_write` too. That was what this recipe used to say to do, and the capture that came back had nine writes in it with no way to tell which was which. `writebyte` opens the file first, turns the tracer on, writes one byte, and turns it off, so the window contains one write and the two writes that opened and closed it.

The file it writes to is one nothing has written to before, and that is the interesting choice. A second write to the same file finds its page already there and is over in a few frames. A first write has to go and get one, which is why this trace has `shmem_alloc_and_add_folio` and `__folio_alloc_noprof` and `get_page_from_freelist` in it, and why it is eight levels deep instead of four.

The two frames at the edges are the tracer being turned on and off. The first line is a `mutex_unlock()` with nothing above it, the tail of the write that started recording. The last `vfs_write` has no closing brace, because it is the write that stopped recording and recording had stopped by the time it returned. Every trace has that shape at both ends.

What is not in it is worth as much as what is. There is no disk anywhere. The byte went into the page cache and the call returned, and if you were expecting a block layer you can look for it and watch it not be there.

## two-writes.txt

One byte to a file on tmpfs and one byte to a pipe, by `/bin/twowrites`, in one tracer window.

Two writes in one window rather than two windows with one write each, which would have been tidier. The point of the file is that the same `vfs_write` went two different ways, and that is only something a capture shows if both ways are in the same capture. Two traces taken a second apart could differ because something else on the machine changed, and nobody could rule it out from the files.

It corrected two names. The pipe write calls `anon_pipe_write` and not `pipe_write`, which is what it was called for years and what most writing about pipes still says, and S05 and its diagram both had the old name. And there is no `new_sync_write` between `vfs_write` and `shmem_file_write_iter`. The handwritten fixture had one because that is the shape the code used to have.

The two trees are different all the way down and not the same calls under two names. Both allocate a page, and the tmpfs one goes four levels deep to do it while the pipe one calls the allocator itself. Only the pipe one ends with `__wake_up_sync_key` and `kill_fasync`, because a pipe has a reader waiting and a file does not.

## flat-write.txt

The same write as `write-1byte.txt`, by the same `/bin/writebyte`, recorded by the flat function tracer instead. It is here to be read side by side with that file, because the two show the same seven or so functions and disagree about what a trace is for.

`write-1byte.txt` shows the shape. It nests, so you can see that `generic_perform_write` happens inside `shmem_file_write_iter` and not after it, and it puts a duration on every frame. `flat-write.txt` shows the state. It does not nest, so the same seven calls arrive as a flat list in time order, and in exchange every line carries the flags column that says what the machine was doing when the call happened.

The flags column here is `.....` on all seven lines and that is the point of having this file. Nothing ran with interrupts off, nothing was in a handler, the preemption count was zero the whole way down, and so the whole write is `process` context and every rule that applies to sleeping code applies to all of it. That is the ordinary case, and it is worth seeing on its own before reading `flat-interrupt.txt`, where none of it holds.

The file is filtered to six function names. Unfiltered, the flat tracer records every call the kernel makes, and one second of a machine doing nothing is tens of thousands of lines. `set_ftrace_filter` is how the tracer is turned into an answer rather than a log, and the `setup` list in the metadata has the exact six.

The last line is a second `vfs_write` and it is not the byte going in twice. It is the `echo 0 > tracing_on` that stopped the recording, which is a write like any other and therefore matches the filter. The tracer records the act of switching itself off. That is the flat tracer's version of the unclosed brace at the end of every function_graph capture.

## flat-interrupt.txt

One second of an idle machine with the filter set to the interrupt and softirq path. Eight lines, and the flags column changes four times in them.

Read the task name first and then stop trusting it. Every line says `sleep`, and `sleep` did none of this. A timer interrupt runs on whichever task was on the CPU when it arrived and borrows that task's stack and its name, so the comm column answers who got interrupted rather than who ran. On a machine with real work on it, the same interrupt handler shows up under a different name every time it fires. The flags column is the only thing on the line that says which context the code was actually in, and this file exists to make that unavoidable.

Then read the transitions. `d.h2.` and `d.h1.` are the hardware interrupt handler: interrupts off, preemption count raised. `dN.1.` is after `irq_exit_rcu` has noticed there are softirqs waiting, still with interrupts off, with `N` saying something in the handler asked for a reschedule. `.Ns1.` is the softirq itself, interrupts back on, and the `s` naming the context. Four lines, four different sets of rules about what the code on them is allowed to do.

The middle of the file is the thing that is hard to show any other way. `raise_softirq` and `__raise_softirq_irqoff` are the request, `handle_softirqs` three lines later is the service, and the four lines in between are the gap. The interrupt handler did not do the RCU work. It wrote down that the work was needed and got out, and the work ran afterwards with interrupts on. That gap is what deferred work means, and here it is with timestamps on it.

What this file cannot tell you is how long any of it took. The timestamps are the emulator's. Order is true, intervals are not, and the cost of a softirq is a Tier 1 question.
