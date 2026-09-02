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
