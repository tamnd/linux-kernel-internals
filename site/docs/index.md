# Linux kernel internals

A visual teardown of the Linux kernel, taught from zero, with a real kernel booting in your browser.

**Status: early.** The toolkit and the checkers are being built in the open. One lesson exists as a draft and one blueprint exists as partial, and both of them say on their own first screen what is finished and what is not. Nothing here pretends to be further along than it is.

## What this is trying to fix

The tree is 37 million lines and there is no entry point. The thing you are studying is also the thing keeping your debugger alive. It is concurrent from the first function you look at. And the standard books were written before folios, EEVDF, blk-mq, io_uring, eBPF, BTF, MGLRU, `PREEMPT_RT`, Rust and `sched_ext`, which means they are not stale at the edges, they are wrong at the centre.

The usual result is that people read about the kernel for months, feel like they understand it, and still cannot answer "what happened when I called `write()`" with anything they can check.

## What is different here

**Nothing is asserted that you cannot watch happen.** Every claim in a lesson is registered with the evidence behind it, and a build check refuses a claim whose evidence is a file somebody wrote by hand. A lesson is allowed at most two claims nobody can observe, and it has to say which two.

**The field offsets are read out of the kernel.** Sections 2, 5 and 7 of every blueprint are generated from the kernel's own type information rather than typed in by a person, so they cannot quietly stop being true. When there is no kernel to read, those sections say so instead of guessing.

**Predict before you look.** Every experiment asks you to commit to an answer first. You write one byte. How many bytes reach the disk? Being wrong on the record is what makes the correction stick.

**Concurrency is never deferred.** Every trace carries which CPU it ran on and in which context, from the first lesson. Every structure arrives with the rule that protects it.

**Every claim names a kernel, a config and an architecture.** On a `PREEMPT_RT` kernel `spin_lock()` sleeps and half the usual advice inverts. A kernel claim with no configuration attached is not a claim.

## Where to start

[How to read this](how-to-read-this.md) is two minutes and explains the three passes and why the lessons are notebooks.

[The two tiers](tiers.md) explains the browser kernel and the real machine, and which one you need for what.

[All lessons](lessons/index.md) is the list, with a link that opens each one in Google Colab and runs it with nothing installed.

[All blueprints](blueprints/index.md) is the specifications, which are written for somebody implementing rather than somebody learning.
