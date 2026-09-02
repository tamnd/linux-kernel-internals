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
