# The two tiers

Every experiment in this book says which of two machines it runs on, and the difference between them is not a detail.

## Tier 0, the kernel in your browser tab

A real Linux kernel, booted under [v86](https://github.com/copy/v86), which is an x86 emulator compiled to WebAssembly. It gives you `/proc`, `/sys/kernel/tracing`, `dmesg`, `insmod` and a shell. It is self hosted, so there is no third party service in the way, no account, and no rate limit.

The whole point is that it needs nothing installed and nothing privileged. You open a page and you have a kernel.

What it is not:

- It is **uniprocessor**. Two things never run at the same instant on it.
- It is **32 bit**. Every pointer is four bytes and every structure is laid out differently from the machine on your desk.
- Its **timing is emulated**. A number of nanoseconds out of Tier 0 is a number about the emulator.

So a claim that depends on real concurrency, on 64 bit layout or on real timing cannot rest on Tier 0 evidence, and the claim checker rejects it if it tries. This is enforced rather than remembered, because it is exactly the kind of rule that gets forgotten at the end of a long afternoon.

## Tier 1, a real Linux machine

A container, a virtual machine, a spare laptop, or Google Colab, which is itself a real Linux machine and is why the lesson notebooks work there.

Tier 1 is where the claims that Tier 0 cannot carry get made. Real SMP, real 64 bit layout, real timing, real hardware behaviour, lockdep on a kernel that can actually deadlock.

## Why both

A book that needed Tier 1 for everything would lose most of its readers at the setup instructions. A book that only had Tier 0 would teach a uniprocessor 32 bit kernel and quietly leave people with a model that breaks the first time they look at a real machine.

So every lesson runs on Tier 0 with nothing installed, and every lesson that has something to say about concurrency, layout or timing also has a Tier 1 experiment that says it properly. Where both exist, the lesson says which is which on the page, and the normalised output of the two is compared in the build so they cannot drift apart.

## What you need

Nothing for Tier 0.

For Tier 1, either a Linux machine you can install packages on, or a Colab runtime, which is free and which every lesson notebook opens in from a badge.
