"""Build Z02.

    python3 lessons/Z02/build.py            write Z02.ipynb and lesson.md
    python3 lessons/Z02/build.py --check    fail if either one is out of date

This file is the lesson. The notebook and the markdown are both generated from it, so a paragraph
exists once and the two outputs cannot disagree about what the lesson says.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.nbbuild import Lesson  # noqa: E402

lesson = Lesson("Z02")

lesson.md(f"""# Z02: Your first trace

{lesson.badge}

**Status: draft.** The prose is finished. None of its claims are verified, because verifying them needs a kernel you can run in a browser tab and that is still being built. See "What is not settled yet" at the end, which says exactly what is missing and what will fix it.
""")

lesson.md("""## Before you start

The cell below installs the toolkit if it is not already there, and finds it without installing anything if you are running inside a checkout. Run it first. Everything after it depends on it.

The notebook is generated from `build.py` next to it. Edit the builder, run `just build-lessons`, and the notebook and the markdown are rewritten together. Editing the notebook by hand works until the next build.
""")

lesson.code(
    """# Colab starts with nothing installed. A checkout already has kxray sitting above this file.
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

grader = colab.lesson_module("Z02", "grader")
print("kxray", kxray.__version__, "ready")""",
    note="Setup. Has to be the first code cell, because everything below imports from it.",
)

lesson.block("hook")
lesson.md("""Open a file, write one byte, close it. Three lines of C. On the way through, the kernel does something on the order of a hundred function calls, takes and drops several locks, walks a page cache, and decides whether anything needs to hit a disk.

You are about to watch all of it happen, by name, in order, with a time next to each one.

Not a diagram of what the kernel probably does. The actual calls your actual kernel made, the moment you asked it to. The machinery for this ships in the kernel, it has been there for years, and turning it on takes two `echo` commands.

Before you turn it on, answer this: how many function calls does a one byte write take? Write down a number. You will be wrong, and how you are wrong is the interesting part.
""")

lesson.block("predict")
lesson.md("""## Predict

Fill in the cell below before you run anything else. The grader at the end compares your answers against the trace you capture, so a number that is right on my machine is not right on yours.

1. How many function calls does writing one byte take? Give an order of magnitude: ten, a hundred, a thousand, ten thousand.
2. What is the name of the outermost kernel function you will see, the one everything else happens inside?
3. How deep does the call stack go? Give a number.
4. Does the write reach the disk before your program's `write()` call returns?

Nobody expects you to get these right. The point of writing them down is that a prediction you got wrong sticks, and a fact you read passively does not.
""")

lesson.code(
    """# Change these, then run the cell. Nothing here is checked until the grader at the end.
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
    print(f"  you said: {answers[key]!r}\\n")""",
    note="The predictions. Deliberately pre-filled with plausible wrong answers.",
)

lesson.block("tour")
lesson.md(f"""## Where the controls are

Everything lives in one directory, `/sys/kernel/tracing`. It is a filesystem interface, so the whole tracer is driven by reading and writing files, and you can do all of it from a shell.

Four files matter today:

- `current_tracer`, which tracer is running. Write `function_graph` into it.
- `set_graph_function`, which functions to follow. Empty means all of them, which is more output than you want.
- `tracing_on`, a `1` or a `0`. This is the switch you flip around the thing you want to see.
- `trace`, the output. Read it.

{lesson.image("how-a-trace-gets-made.svg", "A flow diagram showing three control files feeding into ftrace, a program calling write, the kernel running ksys_write and vfs_write, ftrace recording into one ring buffer per CPU, and the trace file being read out with cat.")}

The picture leaves out a lot. There is no tracepoint layer in it, no buffer sizing, no locking on the reader side. It has the pieces you need to read the next section and nothing else, which is the job of the first diagram in a book.

Three things have to be true before any of it works: the kernel was built with the tracer, the tracing filesystem is mounted, and you are root. Colab is a real Linux machine, so the first line of the next cell is the truth about the machine you are on right now, whatever it says.
""")

lesson.code(
    """# What this runtime can and cannot do. Read the status line before you believe anything below.
tracefs.report()
print()
print("can capture here:", tracefs.available())""",
    note="Says up front whether the reader gets a live capture or has to bring a trace.",
)

lesson.md(f"""## What a line looks like

Here is the shape of the output. The values are written as placeholders, because the real numbers come from your machine and not from mine:

```
 <cpu>)   <duration> us  |  vfs_write() {{
 <cpu>)   <duration> us  |    rw_verify_area();
 <cpu>) ! <duration> us  |    __kernel_write_iter() {{
 <cpu>)   <duration> us  |      some_leaf_function();
 <cpu>) ! <duration> us  |    }}
 <cpu>) # <duration> us  |  }}
```

Read it left to right. The number in brackets is the CPU. Hold on to that one, it is the thing this lesson exists to teach you.

{lesson.claim("Z02-02")}. So when you see `#` you are looking at a millisecond of kernel time, which for a write to a file that is already in memory is a long time and worth asking about.

After the bar comes the indentation, two spaces per level, and then the function. {lesson.claim("Z02-01")}. The duration lands on the closing line of a branch because that is the first moment the kernel knew it, so a leaf costs one line and a branch costs two, and if you count lines expecting to count calls your number will be somewhere between the two.
""")

lesson.code(
    """# The marker table, from kxray.models, so the parser and the lesson cannot disagree about it.
for marker, meaning in DURATION_MARKERS.items():
    print(f"  {marker}   {meaning}")""",
    note="Z02-02 is a source claim, so this cell is a convenience rather than the evidence.",
)

lesson.md(f"""## The thing that will catch you

{lesson.claim("Z02-03")}.

The second line is not inside the first one no matter how it is indented. If you build a tree out of this by tracking one depth counter, you will get a tree. It will look fine. It will be wrong, and it will be wrong in a way that survives a lot of reading, because the shape stays plausible.

There is one depth per CPU. The parser in `kxray.trace` keeps one stack per CPU for exactly this reason, and the first test written against it was the one with two CPUs interleaved. The cell below feeds it a two CPU sample and shows you two outermost calls rather than one nested pair.

On Tier 0 you will not see this, because v86 gives you a single processor and every line says `0)`. That makes it a good place to learn the format and a bad place to learn the trap, so the trap is here in writing, and the two CPU capture is a Tier 1 experiment.
""")

lesson.code(
    '''# Two CPUs, interleaved. Written by hand in this cell so you can see the shape, and no claim in
# this lesson rests on it. What it shows is the parser, not the kernel.
INTERLEAVED = """\\
# tracer: function_graph
#
 0)              |  vfs_write() {
 1)              |  vfs_read() {
 0)   0.412 us   |    rw_verify_area();
 1)   0.233 us   |    security_file_permission();
 0) + 12.004 us  |  }
 1) + 10.881 us  |  }
"""

demo = function_graph.parse(INTERLEAVED, source="<handwritten in this cell, not a capture>")
print("cpus:              ", demo.cpus)
print("outermost calls:   ", [f.name for f in demo.roots])
print("vfs_read's parent: ", demo.roots[1].parent, "because it belongs to another CPU's stack")''',
    note="Z02-03 is unverified. This shows the trap on made up input until a real two CPU capture exists.",
)

lesson.md(f"""## The buffer is a ring

The kernel is not writing to a file. It is writing into a fixed size ring buffer, one per CPU, and the `trace` file is a view onto that buffer.

{lesson.claim("Z02-04")}. Fill it and the oldest entries go, without an error, without a warning, and without a gap in the output where the missing lines were. The field is called `overrun`, and if you never look at that file you will never know it happened.

This is the single most common way to be confused by ftrace. The function you were looking for is not missing, it scrolled. Trace less, or trace for a shorter time, or make the buffer bigger with `buffer_size_kb`.
""")

lesson.code(
    """found = tracefs.find()
if found is None:
    print("no tracing filesystem here:", tracefs.explain())
    print("on a machine that has one, the file to read is:")
    print("  /sys/kernel/tracing/per_cpu/cpu0/stats")
else:
    stats = found.stats(0)
    print("entries:", stats.get("entries"), " overrun:", stats.get("overrun"))
    print("a non zero overrun means the trace you are reading is missing its oldest lines")""",
    note="Z02-04 wants a snapshot with a non zero overrun, which needs a buffer filled on purpose.",
)

lesson.md(f"""## Watching changes what you watch

Turning on `function_graph` puts a real cost on every function the kernel calls, because every one of them now has a recording step at the entry and at the return.

{lesson.claim("Z02-06")}. So the durations you are reading are the durations of a kernel that is being traced. They are true, and they are not what the same code costs when nobody is looking.

The cell below measures both, if your runtime lets it. Being told about the observer effect is worth less than a number you produced, so produce one.
""")

lesson.code(
    """import time

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
    print("tracer on:  not measurable here,", tracefs.explain())""",
    note="Z02-06 is verified the moment a reader runs this against a live kernel and sees two numbers.",
)

lesson.block("experiment")
lesson.md(f"""## Capture your own trace

{lesson.claim("Z02-05")}. Now watch it.

If the status line above said you can capture, the next cell does the whole sequence: tracing off, tracer set, filter set, buffer cleared, tracing on, one byte written, tracing off, trace read, and the machine put back the way it was found.

If it said you cannot, run this on a Linux machine you control and paste the output into `PASTED` in the cell below:

```sh
cd /sys/kernel/tracing
sudo sh -c 'echo 0 > tracing_on; echo function_graph > current_tracer; echo vfs_write > set_graph_function; echo > trace'
sudo sh -c 'echo 1 > tracing_on; dd if=/dev/zero of=/tmp/one bs=1 count=1 2>/dev/null; echo 0 > tracing_on'
sudo cat trace
```
""")

lesson.code(
    """PASTED = ""  # paste a trace between the quotes if this runtime cannot capture one

raw, source = "", ""
if PASTED.strip():
    raw, source = PASTED, "<pasted into this notebook>"
elif tracefs.available():
    raw, source = tracefs.capture_write(function="vfs_write"), "/sys/kernel/tracing/trace"
else:
    print("nothing captured:", tracefs.explain())

print(f"{len(raw.splitlines())} lines from {source or 'nowhere yet'}")""",
    note="The capture. Z02-05 stays unverified until this runs against the pinned kernel.",
)

lesson.md("""## Look at it before anything parses it

The unedited text is the evidence. Everything after this point is a rendering of it, and a rendering can be wrong in ways the text is not, so read the text first.
""")

lesson.code(
    """print("\\n".join(raw.splitlines()[:40]) or "nothing captured yet, see the cell above")""",
    note="Raw first, always. A reader who never sees the raw text is trusting the parser blind.",
)

lesson.md("""## Then parse it

Now the same text as a tape: a forest of frames, one stack per CPU, with the durations attached.
""")

lesson.code(
    """tape = function_graph.parse(raw, source=source)

print("calls:     ", tape.frame_count)
print("max depth: ", tape.max_depth)
print("cpus:      ", tape.cpus)
print("outermost: ", [f.name for f in tape.roots])
print("unparsed:  ", len(tape.unparsed))
print()
print(tape.tree(max_depth=3))""",
    note="`unparsed` is printed on purpose. A parser that silently drops lines is a parser that lies.",
)

lesson.md("""## Two wrong answers worth having

Both of these feel correct, which is what makes them worth meeting before the grader does.

**Counting lines instead of calls.** Branches cost two lines and leaves cost one. The frame count from the parser and the line count from `wc -l` are different numbers, and the gap between them tells you how many of the calls were branches.

**Assuming the write reached the disk.** It almost certainly did not. Your byte went into the page cache and the call returned, and the writeback happens later, in another process, in a trace that does not have your program in it anywhere. If you predicted that the disk was involved, look for the function you expected and notice that it is absent. An absent function is evidence too.

Now grade yourself. The grader never compares you against a stored answer, and there is nowhere for one to hide, because every correct value is computed from the file you captured. It also refuses to grade you against the handwritten fixtures in `corpora/`, because grading somebody on a trace nobody captured is the one thing this project promises not to do.
""")

lesson.code(
    """if not tape.roots:
    print("there is no trace here yet, so there is nothing to grade")
else:
    try:
        print(grader.report(grader.grade(tape, answers)))
    except ValueError as refused:
        print("the grader refused:", refused)""",
    note="Grading against the reader's own trace, or a refusal that explains itself.",
)

lesson.block("change")
lesson.md("""## Change something

Reading a trace is one skill. Making the tracer show you what you asked for is the one that matters, because the full output of a busy kernel is not something a person reads.

Do these in order, and after each one, capture again and compare with what you had before.

1. Write `vfs_write` into `set_graph_function`, then capture again. Now you get the one call you care about instead of everything the CPU touched. Your frame count should fall a long way.
2. Write `3` into `max_graph_depth`, then capture again. The tree gets flat, the leaf functions vanish, and the durations on what remains do not change, because the depth limit changes what gets printed rather than what runs.
3. Set the depth back to `0`, capture once more, and check that you are back where you started.

You know it worked when the frame count moves the way you expected and the outermost function is still there. If the outermost function disappeared, you filtered too hard, and the fix is in `set_graph_function` rather than anywhere else.

The cell below runs all three so you can see the three numbers side by side. Then answer the question you started with. How far off was your first number, and in which direction?
""")

lesson.code(
    """def counted(**kwargs) -> str:
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
    print(f"{label:24} {counted(**kwargs)}")""",
    note="The three changes, run back to back, so the reader compares numbers rather than descriptions.",
)

lesson.md("""## What is not settled yet

This lesson is a draft, and here is the exact reason.

Every claim it makes is registered in `claims.toml` beside this file, and every one is marked unverified. The trace claims need a real capture on the pinned kernel, and there is no way to make one until `kxbox` boots that kernel in a browser. The two source claims each name a citation in `refs.toml` beside this file, and neither citation is confirmed, because confirming one means finding its anchor in a real kernel tree and there is not one here yet.

There are handwritten traces in `corpora/traces/handwritten/`. They exist so the parser had something to test against, they are marked `evidence = false`, and no claim here points at them. The claim ledger fails the build if one ever tries.

When the capture exists, the placeholders in the output above get replaced by real numbers from a real run, the claims get verified, and the status in `meta.toml` moves to published. Not before.
""")

raise SystemExit(lesson.save())
