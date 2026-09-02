# Z02: Your first trace

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/tamnd/linux-kernel-internals/blob/main/lessons/Z02/Z02.ipynb)

**Status: draft.** The prose is finished and all six of its claims are verified. What is left is a human review, which is a person reading it rather than a check that can be run. See "Where the evidence came from" at the end for which machine produced each thing you are about to see.

## Before you start

Run the cell below first. It installs the toolkit, or finds it without installing anything if you are inside a checkout.

The notebook is generated from `build.py` next to it, so edit the builder and run `just build-lessons`. Editing the notebook by hand lasts until the next build.

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

from kxray import colab, tracefs
from kxray.models import DURATION_MARKERS
from kxray.trace import function_graph
from kxwidgets import PredictionGate, SyscallTape

grader = colab.lesson_module("Z02", "grader")
print("kxray", kxray.__version__, "ready")
```

<!-- block: hook -->

Open a file, write one byte, close it. Three lines of C. On the way through, the kernel makes something like a hundred function calls, takes and drops several locks, walks a page cache, and decides whether anything needs to hit a disk.

You are about to watch all of it happen, by name, in order, with a time next to each one.

Not a diagram of what the kernel probably does. The actual calls your actual kernel made, the moment you asked it to. The machinery ships in the kernel and turning it on takes two `echo` commands.

Before you turn it on, answer this: how many function calls does a one byte write take? Write down a number. You will be wrong, and how you are wrong is the interesting part.

<!-- block: predict -->

## Predict

Fill in the cell below before you run anything else. The grader at the end compares your answers against the trace you capture, so my numbers are not your numbers.

1. How many function calls does writing one byte take? Give an order of magnitude: ten, a hundred, a thousand, ten thousand.
2. What is the name of the outermost kernel function you will see, the one everything else happens inside?
3. How deep does the call stack go? Give a number.
4. Does the write reach the disk before your program's `write()` call returns?

Nobody expects you to get these right. A prediction you got wrong sticks, and a fact you read passively does not.

```python
# Change these, then run the cell. Nothing here is checked until the grader at the end.
answers = {
    "prediction": "",  # a sentence about what you expect to see, in your own words
    "frames": 100,
    "outermost": "vfs_write",
    "depth": 5,
    "reached_disk": True,
    "cpus": 1,
}

for key, question in grader.QUESTIONS.items():
    print(question)
    print(f"  you said: {answers[key]!r}\n")
```

<!-- block: tour -->

## Where the controls are

Everything lives in one directory, `/sys/kernel/tracing`. The whole tracer is driven by reading and writing files, so you can do all of it from a shell.

Four files matter today:

- `current_tracer`, which tracer is running. Write `function_graph` into it.
- `set_graph_function`, which functions to follow. Empty means all of them, which is more output than you want.
- `tracing_on`, a `1` or a `0`. This is the switch you flip around the thing you want to see.
- `trace`, the output. Read it.

![A flow diagram showing three control files feeding into ftrace, a program calling write, the kernel running ksys_write and vfs_write, ftrace recording into one ring buffer per CPU, and the trace file being read out with cat.](https://raw.githubusercontent.com/tamnd/linux-kernel-internals/main/lessons/Z02/assets/how-a-trace-gets-made.svg)

The picture leaves out a lot: no tracepoint layer, no buffer sizing, no locking on the reader side. It has what you need for the next section and nothing else.

Three things have to be true before any of it works: the kernel was built with the tracer, the tracing filesystem is mounted, and you are root. The next cell tells you which of the three you have.

```python
# What this runtime can and cannot do. Read the status line before you believe anything below.
tracefs.report()
print()
print("can capture here:", tracefs.available())
```

## What a line looks like

Here is the shape of the output, with placeholders where your machine puts its own numbers:

```
 <cpu>)   <duration> us  |  vfs_write() {
 <cpu>)   <duration> us  |    rw_verify_area();
 <cpu>) ! <duration> us  |    __kernel_write_iter() {
 <cpu>)   <duration> us  |      some_leaf_function();
 <cpu>) ! <duration> us  |    }
 <cpu>) # <duration> us  |  }
```

Read it left to right. The number in brackets is the CPU, and that column is the thing this lesson exists to teach you.

The character before the duration is a slowness marker, and the kernel prints the marker instead of the threshold: + is over 10 us, ! is over 100 us, # is over 1000 us, * is over 10 ms, @ is over 100 ms, and $ is over 1 s. So a `#` is a millisecond of kernel time, which for a write to a file already in memory is a long time and worth asking about.

After the bar comes the indentation, two spaces per level, and then the function. With the function_graph tracer on, the kernel writes a line when a function is entered and a line when it returns, and a function that calls nothing gets a single line with its duration. The duration lands on the closing line of a branch because that is the first moment the kernel knew it, so a leaf costs one line and a branch costs two. Count lines expecting to count calls and your number lands between the two.

```python
# The marker table, from kxray.models, so the parser and the lesson cannot disagree about it.
for marker, meaning in DURATION_MARKERS.items():
    print(f"  {marker}   {meaning}")
```

## The thing that will catch you

Answer the question in the next cell before you read on. People get this one wrong for months without noticing.

```python
PredictionGate(
    "Two lines in a row, the same indentation, one starting `0)` and the next starting `1)`. "
    "Is the second call happening inside the first one?",
    options={
        "a": "yes, the indentation is the call stack",
        "b": "no, they are two different CPUs and have nothing to do with each other",
        "c": "sometimes, it depends on the tracer options",
    },
    answer="b",
    why="The trace file is every CPU's ring buffer read out together. The indentation belongs to "
    "the CPU in brackets and not to the file, so two lines at the same depth from two CPUs are "
    "two separate stacks that happen to be printed next to each other.",
)
```

The trace file holds the output of every CPU in one stream, so indentation belongs to a CPU and not to the file, and two lines next to each other can come from two different call stacks.

The second line is not inside the first no matter how it is indented. Build a tree out of this with one depth counter and you get a tree that looks fine and is wrong, because the shape stays plausible. There is one depth per CPU, which is why the parser in `kxray.trace` keeps one stack per CPU.

![One file on the left holding six interleaved lines, and an arrow labelled split by the CPU column leading to two boxes on the right: CPU 0 with a call stack three deep, and CPU 1 with a single call that was never inside it.](https://raw.githubusercontent.com/tamnd/linux-kernel-internals/main/lessons/Z02/assets/one-file-two-stacks.svg)

You will not see this on Tier 0 and no setting will make you, because v86 gives you one processor and every line of your own capture says `0)`. So the capture below is not yours. Six processes on a six CPU machine, one pinned to each, released from a barrier so their writes land in the same few microseconds. Without the barrier each finishes before the next starts and the trace comes out in six tidy blocks, which shows nothing.

```python
# A real six CPU trace, downloaded from the repository. You cannot take this one on Tier 0.
raw_many = colab.corpus_text("traces/tier1/multi-cpu-write.txt")
many = function_graph.parse(raw_many, source="corpora/traces/tier1/multi-cpu-write.txt")

print("cpus:       ", many.cpus)
print("calls:      ", many.frame_count)
print("outermost:  ", len(many.roots), "separate trees, not one")

# The lines in file order, which is the order you would read them in.
in_file_order = sorted(many.walk(), key=lambda f: f.line)
changes = sum(1 for a, b in zip(in_file_order, in_file_order[1:]) if a.cpu != b.cpu)
print("the CPU column changes", changes, "times in", len(raw_many.splitlines()), "lines")
```

Now the part worth staring at: twenty lines from the middle of that file. Read them as one stack and it is gibberish, with braces closing that never opened. Read the first column and it is two CPUs doing two ordinary things at once.

```python
for number, line in enumerate(raw_many.splitlines()[186:206], start=187):
    print(f"{number:4}  {line}")
```

```python
# The same point made by the parser rather than by eye. Every pair of lines that are next to
# each other in the file, from different CPUs, where both are nested inside something.
for a, b in zip(in_file_order, in_file_order[1:]):
    if a.cpu != b.cpu and a.parent is not None and b.parent is not None:
        print(f"line {a.line:4} cpu {a.cpu}  {a.name} (inside {a.parent.name})")
        print(f"line {b.line:4} cpu {b.cpu}  {b.name} (inside {b.parent.name})")
        print("  next to each other in the file, and neither is inside the other")
        break
```

## The buffer is a ring

The kernel is not writing to a file. It writes into a fixed size ring buffer, one per CPU, and the `trace` file is a view onto that buffer.

The buffer behind the trace file is a ring, so a trace that runs for long enough loses its oldest lines, and the count of what was lost is in the per CPU stats file rather than in the trace. Fill it and the oldest entries go, with no error, no warning, and no gap where they were. The field is called `overrun`, and if you never read that file you never find out.

This is the most common way to be confused by ftrace. The function you were looking for is not missing, it scrolled. Trace less, or make the buffer bigger with `buffer_size_kb`.

Here is what it looks like on purpose: the buffer shrunk to the smallest the kernel would take, no filter, and one `ls -l /proc`.

```python
print(colab.corpus_text("proc/tier0/ring-overrun.txt"))
```

273 events kept, 44002 thrown away to make room for them, in seven thousandths of a second, from one `ls`.

The trace file after that had 204 lines in it and not one of them says anything is missing. No gap, no warning, no marker. It starts part way through and reads exactly like a complete trace of a shorter period, which is the worst way for a file to be wrong.

One other thing from that run. The buffer was asked for as 8 kilobytes and read back as 11, because `buffer_size_kb` is a request the kernel rounds up to whole pages. Read it back rather than assuming.

```python
found = tracefs.find()
if found is None:
    print("no tracing filesystem here:", tracefs.explain())
    print("on a machine that has one, the file to read is:")
    print("  /sys/kernel/tracing/per_cpu/cpu0/stats")
else:
    stats = found.stats(0)
    print("entries:", stats.get("entries"), " overrun:", stats.get("overrun"))
    print("a non zero overrun means the trace you are reading is missing its oldest lines")
```

## Watching changes what you watch

Turning on `function_graph` costs something on every function the kernel calls, because each one now has a recording step at the entry and at the return.

Tracing every function costs the traced work real time, so the same write measured with the tracer on takes longer than with it off. So the durations you are reading are the durations of a kernel that is being traced. They are true, and they are not what the same code costs when nobody is looking.

How much? On a real machine, a one byte write to tmpfs costs about 257 nanoseconds untraced and about 6619 with `function_graph` on. Roughly twenty five times, on one of the cheapest things you can ask a kernel to do.

That is a Tier 1 measurement and it had to be. v86 has no real clock, so timing anything under it measures the emulator, which is why every Tier 0 capture says `timings_are_real = false`.

```python
print(colab.corpus_text("experiments/tier1/tracer-cost.txt"))
```

The filter barely helped there, for a reason worth seeing: the thing being measured is nothing but writes, so filtering to `vfs_write` filtered nothing out. On a machine doing anything else it is the difference between a readable trace and a buffer that has already thrown away what you wanted.

Turn the tracer on to find out why something is slow and you have made it twenty five times slower in the act of looking. Tracing tells you what happened and in what order. It does not tell you how long it took.

Now produce your own number, which will not match mine.

```python
import time

action = tracefs.write_one_byte()


def per_write_us(rounds: int = 2000) -> float:
    start = time.perf_counter_ns()
    for _ in range(rounds):
        action()
    return (time.perf_counter_ns() - start) / rounds / 1000


quiet = per_write_us()
print(f"tracer off: {quiet:6.2f} us per write")

if tracefs.available():
    measured = {}
    tracefs.find().capture(lambda: measured.setdefault("us", per_write_us()))
    print(f"tracer on:  {measured['us']:6.2f} us per write")
    print(f"the tracer costs {measured['us'] / quiet:.1f}x on this machine")
else:
    print("tracer on:  not measurable here,", tracefs.explain())
```

<!-- block: experiment -->

## Capture your own trace

Writing one byte to a file enters the kernel at the write system call and reaches the filesystem through vfs_write, and the work underneath that is where the time goes. Now watch it.

If the status line above said you can capture, the next cell runs the whole sequence and puts the machine back. If not, run this on a Linux machine you control and paste the output into `PASTED`:

```sh
cd /sys/kernel/tracing
sudo sh -c 'echo 0 > tracing_on; echo function_graph > current_tracer; echo vfs_write > set_graph_function; echo > trace'
sudo sh -c 'echo 1 > tracing_on; dd if=/dev/zero of=/tmp/one bs=1 count=1 2>/dev/null; echo 0 > tracing_on'
sudo cat trace
```

Expect that to be messier than you want, and the mess is the lesson. It is not one write: the shell writes its prompt, `dd` writes two lines of summary, and anything else writing in that fraction of a second is in there too. Filtering to `vfs_write` does not save you, because all of those are `vfs_write` as well. No shell command fixes it, which is why the box has a program called `writebyte` that opens its file first, turns the tracer on, writes one byte, and turns it off.

```python
PASTED = ""  # paste a trace between the quotes if this runtime cannot capture one

raw, source = "", ""
if PASTED.strip():
    raw, source = PASTED, "<pasted into this notebook>"
elif tracefs.available():
    raw, source = tracefs.capture_write(function="vfs_write"), "/sys/kernel/tracing/trace"
else:
    print("nothing captured here:", tracefs.explain())

print(f"{len(raw.splitlines())} lines from {source or 'nowhere yet'}")
```

If that came back with nothing, the next cell falls back to the committed capture off the pinned kernel. Everything below works the same either way.

```python
if not raw.strip():
    raw = colab.corpus_text("traces/tier0/write-1byte.txt")
    source = "corpora/traces/tier0/write-1byte.txt"
    print("using the committed capture from the pinned kernel")

print(f"{len(raw.splitlines())} lines from {source}")
```

## Look at it before anything parses it

The unedited text is the evidence. Everything after this point renders it, and a rendering can be wrong in ways the text is not.

```python
print("\n".join(raw.splitlines()[:40]) or "nothing captured yet, see the cell above")
```

## Then parse it

The same text as a tape: a forest of frames, one stack per CPU, durations attached.

```python
tape = function_graph.parse(raw, source=source)

print("calls:     ", tape.frame_count)
print("max depth: ", tape.max_depth)
print("cpus:      ", tape.cpus)
print("outermost: ", [f.name for f in tape.roots])
print("unparsed:  ", len(tape.unparsed))
print()
print(tape.tree(max_depth=3))
```

## Then look at it

The same tape drawn. Each box is a call, the width is how long it took, and the row underneath is what that call called. The wide box is where your write actually went.

Position from left is call order rather than a clock, because `function_graph` records how long a call took and not when it started. The gap at the right hand end of a box is the time that call spent in itself rather than in anything below it, and on a write that gap is usually small: a function whose whole job is to call the next one down.

```python
SyscallTape(tape, max_depth=4)
```

## Two wrong answers worth having

Both feel correct, which is why they are worth meeting before the grader does.

**Counting lines instead of calls.** Branches cost two lines and leaves cost one, so the parser's frame count and `wc -l` are different numbers, and the gap is how many calls were branches.

**Assuming the write reached the disk.** It almost certainly did not. Your byte went into the page cache and the call returned, and writeback happens later, in another process, in a trace with none of your program in it. If you predicted a disk, look for the function you expected and notice it is absent. An absent function is evidence too.

Now grade yourself. Every correct value is computed from the file you captured rather than stored, and the grader refuses the handwritten fixtures in `corpora/`, because grading somebody on a trace nobody captured is the one thing this project promises not to do.

```python
if not tape.roots:
    print("there is no trace here yet, so there is nothing to grade")
else:
    try:
        print(grader.report(grader.grade(tape, answers)))
    except ValueError as refused:
        print("the grader refused:", refused)
```

<!-- block: change -->

## Change something

Reading a trace is one skill. Making the tracer show you only what you asked for is the one that matters, because the full output of a busy kernel is not something a person reads.

Do these in order, and capture again after each one.

1. Write `vfs_write` into `set_graph_function`. Now you get the one call you care about instead of everything the CPU touched, and your frame count should fall a long way.
2. Write `3` into `max_graph_depth`. The tree gets flat, the leaves vanish, and the durations on what remains do not change, because the depth limit changes what gets printed rather than what runs.
3. Set the depth back to `0` and check that you are back where you started.

You know it worked when the frame count moves the way you expected and the outermost function is still there. If it disappeared, you filtered too hard, and the fix is in `set_graph_function`.

The cell below runs all three side by side. Then answer the question you started with. How far off was your first number, and in which direction?

```python
def counted(**kwargs) -> str:
    if not tracefs.available():
        return "not available here"
    text = tracefs.capture_write(**kwargs)
    return f"{function_graph.parse(text).frame_count} calls"


for label, kwargs in [
    ("everything", {}),
    ("vfs_write only", {"function": "vfs_write"}),
    ("vfs_write, three deep", {"function": "vfs_write", "max_depth": 3}),
    ("back where you started", {}),
]:
    print(f"{label:24} {counted(**kwargs)}")
```

## Where the evidence came from

All six claims are registered in `claims.toml` beside this file and all six are verified. Here is what each rests on, because "verified" is worth nothing if you cannot see how.

The two claims about what the tracer prints are source claims, each naming an anchor in the pinned 7.2.2 tree rather than a line number, and `refcheck` fails the build if an anchor stops resolving.

The one byte write and the ring buffer overrun are both off that pinned kernel under v86: `corpora/traces/tier0/write-1byte.txt` and `corpora/proc/tier0/ring-overrun.txt`, each with metadata saying how to take it again.

The other two could not be settled on Tier 0 at any price. Interleaving needs more than one CPU and v86 is uniprocessor. Timing the tracer needs a clock and v86 has none. Both came off a six CPU arm64 machine running 6.8, a different architecture and a different kernel from everything else here. That is in their metadata rather than glossed over, and it is an acceptable trade only because neither depends on the architecture.

So why is this still a draft? `meta.toml` also wants a `reviewed-by` naming a person who has read it, and nobody has. Signing that without the reading would make every other check here worth less.
