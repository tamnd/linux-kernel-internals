# Tier 0 snapshots of /proc

These are copies of files out of `/proc` and `/sys` on the pinned kernel. A trace is a recording of something happening. These are the opposite: a look at what the kernel was willing to say about itself at one moment, with nothing happening at all.

Every file here is real, off the 7.2.2 built for 32-bit x86 with one processor, running under v86. Every `.meta.toml` says `evidence = true`, so a lesson may cite one. Each also records the file in `/proc` it is a copy of, under `path`, and the level the kernel tree gives that path, under `stability`.

## The thing to read before reading any of them

Almost none of these files are documented.

The kernel keeps its own record of what it promises in `Documentation/ABI`, four directories deep, one per level, defined in `Documentation/ABI/README`. On 7.2.2 that tree has 685 files in it. Six of them describe a path in `/proc`, and those six are `/proc/i8k`, `/proc/diskstats`, `/proc/pid/smaps_rollup` and the three files under `/proc/*/attr`. Not `meminfo`. Not `interrupts`. Not `/proc/<pid>/stat`, which is the file behind every process monitor ever written. Not `maps`.

That is worth sitting with rather than being alarmed by. Those files have had the same shape for many years and will keep it, because changing one would break userspace and that is the rule nobody gets to bend. What is missing is anybody having written down which part of the shape you may lean on. So this project reads them, and `kxray.proc.stability` attaches the answer to every read, and printing one of these objects tells you it is leaning on custom rather than on a promise.

Two paths this project reads are stronger than undocumented and worse. The closing section of `Documentation/ABI/README` names, as things that "should not under any circumstances be considered stable", Kconfig, calling out `/proc/config.gz` by name, and kernel symbols, saying not to rely on "the presence, absence, location, or type of any kernel symbol". The second of those is `/proc/kallsyms`, which is next door in `../handwritten/` and which `kxray.kallsyms` reads anyway. Counting ops tables by name on a machine in front of you is a fine thing to do. Shipping the same code inside a tool is not, and now the ledger says so.

## Taking one again

```
node kxbox/web/headless.js sh 'cat /proc/meminfo'
```

No setup, no tracer, nothing to turn on or put back. These are the cheapest artefacts in the corpus to refresh, and the ones most likely to be different after a kernel bump, which is the point of having them.

## version.txt

One line. The release and the build number are worth pulling out and the rest is not: it holds the user and host that built the kernel, then the whole compiler and linker banner, with brackets inside brackets in it, and nothing anywhere promises its shape.

It is also the cheapest confirmation that the kernel running is the kernel the profile asked for. `PREEMPT` is in there because `kxbox/kernel/pin.toml` asked for `CONFIG_PREEMPT=y`, and if it ever stops being in there, half the claims in the concurrency lessons are about a different machine.

`kxray.proc.version` turns the release into a tuple of numbers, because string comparison says 6.9 is newer than 6.10 and it is not.

## meminfo.txt

All of memory as the kernel accounts for it, on a box given 100 MiB.

The unit says `kB` and means KiB. `MemTotal` is 102308 kB, and 102308 times 1024 is a shade under 100 MiB while 102308 times 1000 is nowhere near it. The kernel has spelled it that way since the beginning and every tool on the machine agrees with it, so the parser keeps the kernel's spelling and multiplies by 1024.

The key list is per config. There is no `HugePages_Total` here and there is a `GPUActive`, and a machine built differently prints a different set. Nothing in `kxray.proc` requires a key to be there, and asking for one that is not raises rather than returning zero.

## interrupts.txt and softirqs.txt

Read these two together or the pair is wasted.

`interrupts.txt` counts the hardware asking for attention. There is one column because this box has one CPU. A laptop prints one column per possible CPU, which is not the same as the number online and not the same as the number in the machine, and the header is the only place that number is already worked out. That is why `kxray.proc.percpu` reads the header and refuses to guess.

The rows underneath the numbered ones are per architecture and per config. Two here, `NMI` and `TLB`. An x86-64 desktop prints around fifteen and an arm64 machine prints a different set again, so there is no list of them anywhere in the code.

`softirqs.txt` counts the work that answering an interrupt did not do itself. Ten vectors, seven of which have never fired on this idle box. The two that have are `TIMER` and `RCU`, which is exactly the pair that `../../traces/tier0/flat-interrupt.txt` catches in the act: `raise_softirq` inside the hardware handler with interrupts off, then `handle_softirqs` four lines later with interrupts back on. That trace is the gap happening once. These two files are the same gap counted since boot.

## self-maps.txt

The whole address space of one process, which was the `cat` that read the file. Seven lines, and four things in them.

`/bin/busybox` appears twice, once `r-xp` and once `rw-p`. A program's text and its data are one file mapped two ways with different permissions, and that is true of every program on every Linux machine rather than being a busybox quirk.

Line three has no name at all. That is anonymous memory, and it is what a first write has to go and find a page for, which is the entire subject of `blueprints/page-fault.md`.

Line three also ends in a space, and that is the trap. The kernel pads every line out to a fixed column before printing the path, and when there is no path the padding is printed anyway. So that line has five whitespace separated fields and every other line has six, and code that reaches for field six works on every maps file it has ever seen until it meets an anonymous mapping. Do not let an editor strip the trailing whitespace from this file.

The two gaps between the mappings are most of the address space. From `0814c000` to `b7f8f000` is about 2.7 GiB of nothing, and a fault anywhere in it is a segmentation fault.

## self-stat.txt and odd-comm-stat.txt

The same file twice, for two processes with different names, and the pair is the point.

`self-stat.txt` is the ordinary case: a process called `cat`. Fifty two fields on one line, which is exactly what Table 1-4 of `Documentation/filesystems/proc.rst` lists. That table is headed "as of 2.6.30-rc7" and still describes 7.2.2 without an error in it, for a file that has no ABI entry at all. Splitting this line on whitespace gives the right answer.

`odd-comm-stat.txt` is the same file for a process whose executable is named `od) d ma`:

```
37 (od) d ma) R 1 0 0 0 -1 4194304 37 0 0 0 0 1 0 0 20 0 1 0 265 ...
```

The kernel prints the command name in brackets and does not escape it. `line.split()` on that gives `37`, `(od)`, `d`, `ma)`, `R`, and every field after the name has slid two places along. The state, field three, comes back as `d`, which is not a state any process is ever in. Nothing raises. All the numbers are still numbers. A monitor reading this would carry on reporting nonsense.

The correct parse is the one `procps` has used for decades and it is not clever: first opening bracket, last closing bracket, and the fields are what is left. `kxray.proc.pidstat` does that, and keeps what the naive split would have said, so a lesson can print the two answers next to each other instead of asking anybody to take the trap on trust.

Getting the capture needed a process with a name like that, and on a busybox rootfs that means a shell script. busybox dispatches on its own `argv[0]` and refuses to run under a name that is not one of its applets, so a copy of `/bin/sleep` called `od) d ma` exits immediately with "applet not found". A script gets its `comm` from the script's own filename, so the name sticks.

One number ties this file to the one above it. `vsize` in `self-stat.txt` is 1298432, and the sizes of the seven mappings in `self-maps.txt` add up to 1298432, because `vsize` is that sum. Two files, two readers, one fact, and a test that checks they still agree.

## self-status.txt

The same process as `self-stat.txt`, printed for a person instead of for a program. Fifty keys, tab separated where meminfo uses spaces, and three of them break the idea that a value is a number.

`Uid` has four values on one line: real, effective, saved and filesystem. `State` has a letter and then the same state spelled out in brackets. `Groups` is empty, and the kernel prints the key and the separator anyway.

So the reader keeps a tuple of words per key and offers a number only when there is exactly one word and it is one. A model with `value: int` on it would have to throw two of those three away and would be wrong about the third.
