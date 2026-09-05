# Tier 1 captures

Recordings from a real Linux machine, taken because Tier 0 cannot produce them.

Tier 0 is the browser emulator, and it is the tier every lesson is written against, because it is the one every reader has. It has two limits that no amount of work removes. It has one CPU, so nothing about more than one CPU can be shown in it. And it has no real clock, so every duration in a Tier 0 trace is a number about v86 rather than about the kernel.

This directory is for the captures that run into those two limits and no others. It is deliberately small, and it should stay small. A capture belongs here only when somebody can say in one sentence why Tier 0 could not have produced it, and that sentence goes in the `.meta.toml`.

## What is different about reading one

Everything in `../tier0/` comes off the same pinned kernel: 7.2.2, 32-bit x86, one processor, built from a config in this repository. That is why a Tier 0 trace can be compared against a Tier 0 trace from six months ago.

A Tier 1 capture comes off whatever machine the person taking it had. The metadata says which one, exactly, and the answer is not going to be 7.2.2 on i386. The capture in here at the moment came off arm64 running 6.8, which is a different architecture and a different kernel from everything else in this repository.

That is fine for what these captures are for, and it is worth being clear about why. `multi-cpu-write.txt` is evidence that the trace file interleaves CPUs. That is a fact about how ftrace writes into per CPU ring buffers and merges them on the way out, and it is true on every architecture Linux runs on. A capture that rested on the exact functions being called would not survive the move, and that is what `../tier0/` is for.

## Taking one

You need a real Linux machine, more than one CPU, and root, because tracefs has to be mounted and written to. A privileged container on a Linux virtual machine is enough and is what was used here.

The `setup` list in each `.meta.toml` is the sequence of writes, in order, and `command` says what ran with the tracer on. Between them they are the whole recipe.

## multi-cpu-write.txt

Six processes, one pinned to each CPU, each writing one byte twice, all released at the same instant from a barrier.

The barrier is the part that took a few tries. Starting six writers with `&` and hoping does not work: each one gets going a few hundred microseconds after the last, their bursts do not overlap, and the trace comes out neatly sorted into six runs of one CPU each. That looks like the opposite of the point. Making them spin on a file until it appears gets their writes into the same few microseconds, and then the trace file has 33 places where the CPU column changes from one line to the next.

Lines 187 to 206 are the ones to read. CPU 2 and CPU 4 alternate almost line by line, and both of them are part way through their own `vfs_write` while it happens, so two lines next to each other belong to two different call stacks and the indentation jumps backwards and forwards between them. Indentation in a function_graph trace belongs to a CPU, not to the file, and this is what that costs you when you forget it.

Two things in the file are nothing to do with the six writers, and both are left in. There is a `lima-gu-1171`, which is the virtual machine's own guest agent, caught writing while the tracer happened to be on. And there are `write_null()` calls, which are the `dd` processes writing their summary lines to `/dev/null` because the command redirected them there. A trace taken on a real machine has other people's work in it, and there is no setting that removes that.

## contended-lock.txt

Four processes, one pinned to each CPU, each writing eight megabytes to the same file, all released at the same instant from the same kind of barrier.

This is `multi-cpu-write.txt` with one thing changed. That capture has six writers on six different files, and this one has four writers on one file. Six files means six inodes, six inodes means six different locks, and nobody waits for anything. One file means one lock, and everybody after the first one queues.

The numbers are not subtle. `dd-2792` spent 10435.87 us inside `down_write` and `dd-2790` spent 14778.45 us, and in the same file, a few hundred lines apart, `contain-1214` spent 0.333 us inside the same call on a file nobody else wanted. That is the difference between waiting and not waiting, measured four orders of magnitude apart, in one capture on one machine.

The line worth reading is not a number. `dd-2790` opens `down_write() {` on CPU 3, and the next line in the file is a task switch banner away from it. Waiting for a rwsem means going to sleep, and here you can watch it happen: the process asks for the lock, does not get it, and loses the CPU inside the call.

The writes are eight megabytes rather than one byte on purpose. A one byte write holds the inode lock for a few microseconds, and four of those on four CPUs mostly slip past each other, so the capture comes out looking uncontended and shows nothing. Making the hold ten milliseconds long makes the queue certain.

One of the four did not wait. `dd-2793` arrived after the other three were done, which the trace shows plainly, because its `down_write` is well past the last `up_write`. A barrier made of a file appearing is good to a few hundred microseconds, and that is enough for three writers out of four, so the fourth is left in rather than tidied away.
