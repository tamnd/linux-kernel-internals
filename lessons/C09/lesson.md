# C09: The lock that deadlocks tomorrow

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/tamnd/linux-kernel-internals/blob/main/lessons/C09/C09.ipynb)

**Status: draft.** All five claims are verified. Three resolve against the pinned 7.2.2 source, and the other two came off a boot of that kernel with the module in this lesson loaded into it, which is where the report and the two readings of `/proc/lockdep_stats` in the cells below come from. It stays a draft until somebody has read it end to end and put their name on it. See "Where the evidence came from" at the end.

## Before you start

The cell below installs the toolkit if it is not already there, and finds it without installing anything if you are running inside a checkout. Run it first. Everything after it depends on it.

The notebook is generated from `build.py` next to it. Edit the builder, run `just build-lessons`, and the notebook and the markdown are rewritten together. Editing the notebook by hand works until the next build.

```python
# Colab starts with nothing installed. A checkout already has kxray sitting above this file.
import sys
from pathlib import Path

for parent in [Path.cwd(), *Path.cwd().parents]:
    if (parent / "kxray").is_dir():
        sys.path.insert(0, str(parent))
        break

try:
    import kxray
except ImportError:
    %pip install --quiet "git+https://github.com/tamnd/linux-kernel-internals@main"
    import kxray

from kxray import colab, lockdep
from kxwidgets import PredictionGate

grader = colab.lesson_module("C09", "grader")
print("kxray", kxray.__version__, "ready")
```

<!-- block: hook -->

Here is a kernel module that cannot hang.

Two mutexes. Two threads. The first thread takes `lock_a` and then `lock_b`, and finishes. The second thread starts only after the first one has finished, and takes `lock_b` and then `lock_a`. The orders are opposite, which is the classic deadlock, and there is no instant at which two threads hold anything at once. Nothing can wait for anything. Load it a million times and it never hangs.

Load it once and the kernel prints a deadlock report.

The report is right. The module is broken. Nothing happened.

<!-- block: predict -->

## Predict

Fill in the cell below before you run anything. The grader at the end reads your own report, so an answer that fits mine will not fit yours.

1. Will loading that module hang the machine?
2. If the kernel reports a deadlock that did not happen, what did it look at?
3. Your team has shipped code with an ordering like this for a year and nobody has seen a hang. Does that tell you the ordering is safe?

Nobody expects you to get these right. A prediction you got wrong sticks, and a fact you read passively does not.

```python
# Change these, then run the cell. Nothing here is checked until the grader at the end.
answers = {
    "prediction": "",  # a sentence about what you expect to happen, in your own words
    "who": "kworker",
    "length": 3,
    "cycle": ["lock_b", "lock_a"],
    "learned_in": "abba_second_thread",
    "checker": "on",
}

for key, question in grader.QUESTIONS.items():
    print(question)
    print(f"  you said: {answers[key]!r}\n")
```

<!-- block: tour -->

## It is not watching for hangs

Lockdep does not wait for a deadlock and report it afterwards. It keeps a graph of which lock class has been held while which other one was taken, and it complains at the moment adding an edge would close a cycle, which is usually long before anything could hang.

Think of every lock class in the kernel as a dot. Every time a thread takes one lock while already holding another, draw an arrow from the one it held to the one it took. The arrow means "somewhere in this kernel, there is code that takes these two in this order". Lockdep draws those arrows as it goes and never forgets one.

Before adding a new arrow it asks a single question: is there already a path from the far end back to this end? If there is, the new arrow closes a loop, and a loop is an order in which two threads can wait for each other forever. It reports at that moment, before adding the arrow, which is why the report arrives on a machine that is running perfectly well.

![A graph with two boxes. On the left a box labelled lock_a, with the address c1a4e0a0 and the words one lock class under it, and on the right the same for lock_b at c1a4e060. A solid arrow runs from lock_a to lock_b, labelled edge one, recorded when the first thread held lock_a and took lock_b. A dashed arrow runs back from lock_b to lock_a, labelled edge two, about to be recorded because the second thread holds lock_b and is taking lock_a. A note by the dashed arrow says it has not been added and that this is the moment lockdep says no. Underneath, three notes say what an edge means, that a loop means there is an order in which two of these block forever, and that nothing here is blocked because both threads finished.](https://raw.githubusercontent.com/tamnd/linux-kernel-internals/main/lessons/C09/assets/the-cycle.svg)

One thread taught it the first arrow. A different thread, minutes later, asked for the second. Neither of them was ever blocked.

## Classes, not locks

The checker reasons about lock classes rather than about individual locks, so every mutex initialised by the same line of source is one class to it, and a report names a line of code rather than the object that was held.

This is the part that makes people argue with a report. You were holding one particular inode's mutex, and the report talks about `&sb->s_type->i_mutex_key` as though every inode in the machine were the same lock. To lockdep they are. A class is a line of source that initialises a lock, and every lock that line ever produces belongs to it.

That is what makes the checker useful and it is also where its false alarms come from. Useful, because one run teaches it about every inode you never opened. False, when two objects of the same class genuinely cannot be held by the same thread and the code says so with `mutex_lock_nested` and a subclass number.

So a report names a line of code and not the thing you were holding, and the fix is a change to an ordering rule rather than to one object.

## How to read the numbered chain

Skip the drawing at the bottom of a report. Read the numbered entries in the middle. The numbered chain in the middle of a report is the cycle itself, printed highest number first, so the entry numbered zero is the lock being taken right now and the entry at the top of the chain is the lock already held.

Read them upward, from `#0` to the top, and you have the path that already existed. The edge from the lock at the top back down to `#0` is the one the kernel was about to add. That is the whole cycle, and every other part of the report is a rendering of it.

Each numbered entry carries a stack, and the stack is not where the deadlock would happen. It is where lockdep learned that edge, which is often a different subsystem written by somebody who has never heard of yours. Finding that stack is the actual work of fixing one of these.

The cell below parses a report into that shape, so the pieces have names you can ask for.

```python
import subprocess

PASTED = """"""  # paste a report between the quotes, or leave it empty to read your own dmesg

text = PASTED
if not text.strip():
    try:
        text = subprocess.run(["dmesg"], capture_output=True, text=True, check=False).stdout
    except FileNotFoundError:
        text = ""

found = lockdep.splats(text, source="dmesg on this machine")
print(f"{len(found)} complete reports in {len(text.splitlines())} lines of log")
for one in found:
    print()
    print(one.summary())
```

## The thing that will catch you

Answer the question in the next cell before you read on. This is the one that costs people a weekend.

```python
PredictionGate(
    "Your team has shipped code that takes these two locks in both orders. It has been in "
    "production for a year across ten thousand machines and nobody has ever seen a hang. "
    "What does that tell you?",
    options={
        "a": "the ordering is safe in practice, so leave it alone",
        "b": "the ordering is unsafe and you have been lucky",
        "c": "the ordering is safe on those machines and unsafe on faster ones",
    },
    answer="b",
    why="A deadlock needs the two orderings to overlap in time, and the odds of that on any one "
    "run can be tiny. The cycle is in the code either way. A year of luck is a year of luck, and "
    "the run that stops being lucky is the one with a new scheduler, a new core count or a "
    "customer doing something nobody tried.",
)
```

Here is the same point drawn as a timeline, with the two threads of that module separated by a wait.

![A timeline running left to right, with an arrow across the top labelled time, and two rows under it. The top row is the first thread: it takes lock_a, then takes lock_b, then releases both and exits. The bottom row is the second thread, and it starts only after the top row has finished, with a labelled gap between them saying the first thread has already exited. The second thread takes lock_b, then reaches for lock_a, and at that point a marker on the timeline says lockdep reports a cycle. A note underneath says the two rows never overlap, so no thread ever waited for another one, and that the report is about the order the locks were taken in rather than about anything that happened at the same time.](https://raw.githubusercontent.com/tamnd/linux-kernel-internals/main/lessons/C09/assets/never-overlapped.svg)

Testing looks for the row where the two overlap. Lockdep does not need that row to exist.

<!-- block: experiment -->

## Build it and load it

A report can arrive on a run where no thread ever blocked and nothing ever waited, because a cycle in the lock graph is a property of the code and a hang is a property of the timing.

This one is in the repository already. `corpora/oops/tier0/lockdep-ab-ba.txt` is the report this module printed on the pinned kernel, and the cells below fall back to it when you are somewhere that cannot load a module, which includes Colab. Read it either way. Making one yourself is better and it is not a prerequisite for the rest of the lesson.

To make your own you need a Linux machine you can build modules on and a kernel built with `CONFIG_PROVE_LOCKING`. Check that first, because on a kernel without it this module loads, does nothing visible, and teaches you the wrong thing.

```sh
zcat /proc/config.gz | grep PROVE_LOCKING     # or look in /boot/config-$(uname -r)
```

Then build and load:

```sh
make
sudo dmesg -C
sudo insmod abba.ko
dmesg
```

The next cell writes `abba.c` and its `Makefile` into the current directory so you have them to hand.

```python
for name in ("abba.c", "Makefile"):
    Path(name).write_text(colab.lesson_text("C09", f"assets/{name}"))
    print(f"wrote {name}")

print()
print(colab.lesson_text("C09", "assets/abba.c").split("#include")[0].strip()[:600])
```

## Look at it before anything parses it

The unedited report is the evidence. Everything after this is a rendering of it, and a rendering can be wrong in ways the text is not.

```python
MINE = """"""  # paste the report your own machine printed between the quotes

raw = MINE if MINE.strip() else PASTED
where = "pasted above"

if not raw.strip() and found:
    raw, where = text, "dmesg on this machine"

if not raw.strip():
    raw = colab.corpus_text("oops/tier0/lockdep-ab-ba.txt")
    where = "corpora/oops/tier0/lockdep-ab-ba.txt, off the pinned kernel"

print(f"reading a report from {where}")
print()
print("\n".join(raw.splitlines()[:24]))
```

Now take it apart. The parser refuses a report that was only half copied rather than filling in the missing part, because a guessed lock ordering is worse than no answer.

```python
mine = None
if raw.strip():
    try:
        mine = lockdep.parse_splat(raw, source=where)
        print(mine.summary())
        print()
        print(mine.scenario or "no scenario block in this report")
    except (lockdep.Truncated, lockdep.NotASplat) as refused:
        print("the parser refused:", refused)
```

Look at the scenario block that cell printed. It has two columns, CPU0 and CPU1, and the machine that produced this report has one processor. Nothing in that block happened.

That is not a bug. Lockdep is not describing a run, it is describing the interleaving that would deadlock given two processors and the wrong timing, and it prints that whether or not either is available.

## The checker turns itself off

There is a second half to this, and it is the reason a lockdep report is worth acting on the day it appears rather than the week after. Lockdep switches itself off after its first report of the boot, and from that moment it checks nothing at all, which is readable in the debug_locks line of /proc/lockdep_stats.

One report per boot. After that the graph stops being updated and nothing is checked, so a second ordering bug in the same boot is silent, and a clean log from that point on is not evidence of anything. This is also why a machine that has been up for a month and has one old splat in its log is a machine with no lock checking on it.

The next cell reads your own file if you have one. Under it are the two readings that back the claim, taken a moment apart on one boot with the `insmod` between them. One boot and not two: every number in that file except `debug_locks` depends on what the kernel did on the way up, so two boots would differ in fifteen places for reasons unrelated to the report.

```python
lockdep.report()

stats = lockdep.read_stats()
if stats is not None:
    for name, used in sorted(stats.near_limits(0.5)):
        print(f"{name} is {used:.0%} full")
```

```python
before = lockdep.parse_stats(colab.corpus_text("proc/tier0/lockdep-stats-before.txt"))
after = lockdep.parse_stats(colab.corpus_text("proc/tier0/lockdep-stats-after.txt"))

print(f"{'':22} before   after")
for field in ("debug_locks", "lock_classes", "direct_dependencies", "dependency_chains"):
    print(f"{field:22} {before.values[field]:6}  {after.values[field]:6}")

print()
print("lockdep is off:", before.off, "->", after.off)
```

Everything except `debug_locks` went up. Loading a module registers its lock classes, and the work lockdep did before it gave up is still recorded, so the graph is larger than it was. Nothing consults it any more.

There is no line in that file saying a report happened. `debug_locks` going to zero is the only trace of it, which is why this is the thing to look at rather than a quiet log.

Now grade yourself. The grader has no stored answer key and there is nowhere for one to hide, because the lock names, the task name and the addresses all come off the report your machine printed. It refuses to grade you against the handwritten fixtures under `corpora/`, because grading somebody on a report nobody's kernel produced is the one thing this project promises not to do.

```python
if mine is None:
    print("no report parsed yet, so there is nothing to grade")
else:
    try:
        print(grader.report(grader.grade(mine, answers, stats)))
    except ValueError as refused:
        print("the grader refused:", refused)
```

<!-- block: change -->

## Change something

Reading a report is one skill. Making one appear and then making it go away is the one that matters.

Do these in order, rebooting between the ones that need a fresh checker.

1. Swap the two `mutex_lock` calls in `abba_second_thread` so both threads take `lock_a` first, then rebuild, reboot and load. No report. You have not changed when anything runs, only the order two locks are taken in, and that was the entire bug.
2. Put the original order back, and this time make the two threads overlap on purpose by dropping the `wait_for_completion` and putting a one second sleep between the two locks in each thread. Now it really can hang, and on a single processor machine it often still will not. Whether it hangs is timing. Whether it is reported is not.
3. Load the broken module twice in one boot. The second load prints nothing at all, and `debug_locks` in `/proc/lockdep_stats` says why.
4. Add a third lock and make a cycle of three: thread one takes a then b, thread two takes b then c, thread three takes c then a. Read the numbered chain and count the entries.

You know it worked when the report disappears in step one and nothing else about the module changed. If it disappeared for some other reason, check `debug_locks` first, because a checker that has already fired reports nothing no matter what you write.

Then answer the question the lesson opened with. A module that cannot hang got reported for deadlocking, and now you can say what the kernel looked at instead of the hang.

## Where the evidence came from

Five claims are registered in `claims.toml` beside this file and all five are verified.

Three of them resolve against the pinned 7.2.2 source. Each names an anchor in `refs.toml`, and `refcheck` will not let a claim say verified against a citation nobody has found in a real tree.

The other two came off one boot. The kernel is the `D-lockdep` profile, which is the same source and the same compiler as the one the rest of this book uses with `CONFIG_PROVE_LOCKING` turned on. `abba.ko` was built against that profile and loaded into it, and three files came out: the report in `corpora/oops/tier0/`, and the two readings of `/proc/lockdep_stats` in `corpora/proc/tier0/`, taken either side of the `insmod`.

One boot rather than three runs, deliberately. The last line of the report is the module saying both threads finished and nothing waited, printed after the report rather than before it, and that ordering is the claim. Split across runs it would be two facts instead of one.

There are still three handwritten fixtures behind the parser: a report in `corpora/oops/handwritten/`, and the two `/proc` files in `corpora/proc/handwritten/`. They exist so the parser had something to parse before there was a kernel to take a real one off, they are marked `evidence = false`, and no claim points at any of them. The claim ledger fails the build if one ever tries, and the grader refuses them outright. The handwritten report guessed pid 1481 and some stack offsets. The real ones are pid 40 and different offsets, which changed nothing in the lesson and is worth knowing anyway.

What is left is a `reviewed-by` naming a person who has read this end to end. That is the only reason it still says draft.
