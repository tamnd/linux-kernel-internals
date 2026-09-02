"""Build S05.

    python3 lessons/S05/build.py            write S05.ipynb and lesson.md
    python3 lessons/S05/build.py --check    fail if either one is out of date

This file is the lesson. The notebook and the markdown are both generated from it, so a paragraph
exists once and the two outputs cannot disagree about what the lesson says.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.nbbuild import Lesson  # noqa: E402

lesson = Lesson("S05")

lesson.md(f"""# S05: The first ops plug

{lesson.badge}

**Status: draft.** The prose is finished and two of the six claims settle themselves the moment you run the notebook on a Linux machine. The other four are not settled. See "What is not settled yet" at the end, which says what is missing and what will fix it.
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

from kxray import btf, colab, kallsyms, tracefs
from kxray.trace import function_graph
from kxwidgets import OpsExplorer, PredictionGate

grader = colab.lesson_module("S05", "grader")
print("kxray", kxray.__version__, "ready")""",
    note="Setup. Has to be the first code cell, because everything below imports from it.",
)

lesson.block("hook")
lesson.md("""Write one byte to a file on your disk. Write one byte to a pipe. Write one byte to `/dev/null`. Three destinations that have nothing in common: a spinning disk with a journal, a small buffer in memory with a reader waiting on the other end, and a driver whose whole job is to throw the byte away.

Your program made the same call all three times. The kernel ran the same function all three times. Somewhere under that function the three paths split apart and never meet again.

Now go and look for the code that decided which way to go. Search the whole virtual filesystem layer for a switch on the file type, or an if that names ext4, or a table of filesystem names. There is none. Not hidden, not clever, absent.

So what chose?
""")

lesson.block("predict")
lesson.md("""## Predict

Fill in the cell below before you run anything else. The grader at the end compares your answers against your own kernel, so an answer that is right on my machine is not right on yours.

1. Roughly how many of these operations tables does a running kernel have? Ten, a hundred, a thousand, ten thousand.
2. Two thousand files are open on ext4 at once. How many copies of the ext4 file operations table are in memory?
3. If a filesystem leaves an operation out of its table, what happens when somebody asks for it?

Nobody expects you to get these right. A prediction you got wrong sticks, and a fact you read passively does not.
""")

lesson.code(
    """# Change these, then run the cell. Nothing here is checked until the grader at the end.
answers = {
    "prediction": "",  # a sentence about what you expect to see, in your own words
    "tables": 100,
    "file_ops": 40,
    "readonly": "half",
    "hidden": False,
    "worker": "ext4_file_write_iter",
}

for key, question in grader.QUESTIONS.items():
    print(question)
    print(f"  you said: {answers[key]!r}\\n")""",
    note="The predictions. Deliberately pre-filled with plausible wrong answers.",
)

lesson.block("tour")
lesson.md(f"""## The answer is a pointer

{lesson.claim("S05-01")}.

That is the whole mechanism. C has no classes and the compiler builds no dispatch table for you, so the kernel writes one by hand: a struct whose members are function pointers, one instance of that struct per implementation, and a pointer to the instance hanging off every object that needs it. The struct is `struct file_operations`. The instances are `ext4_file_operations`, `shmem_file_operations`, `pipefifo_fops` and several hundred more.

When you write to a file, the VFS reaches into the open file, takes the pointer it finds in `f_op`, follows it to a table, reads the `write_iter` slot, and calls it. It has no idea what it called.

{lesson.image("one-write-three-tables.svg", "One write call at the top leading into vfs_write, and three arrows fanning out from vfs_write to three boxes: ext4_file_operations with ext4_file_write_iter under it, shmem_file_operations with shmem_file_write_iter under it, and pipefifo_fops with pipe_write under it.")}

The people who wrote ext4 chose the code. The people who wrote the VFS chose the slot. Neither had to know about the other, and a filesystem written next year plugs in without a line changing above the fork.
""")

lesson.md(f"""## When the pointer gets there

A file does not work this out on every call. {lesson.claim("S05-02")}.

Open is where the choosing happens. The inode on disk belongs to a filesystem, that filesystem put its own table into the inode when the inode was set up, and open copies that pointer into the new `struct file`. From then on the file carries its implementation with it, and every read, write, seek and close follows the same pointer without asking anything.

This is why an open file descriptor keeps working after the file is renamed, and why two descriptors on the same file can behave differently if they were opened through different paths onto different filesystems.
""")

lesson.md(f"""## Count them on your own machine

{lesson.claim("S05-03")}.

You do not need root, a debugger, or anything installed. `/proc/kallsyms` lists every symbol in the running kernel by name, and the naming convention is consistent enough to count: a table instance ends in `_operations`, `_ops` or `_fops`.

Two warnings about that file. The addresses come back as zeros unless you are root, which is `kptr_restrict` doing its job rather than the file being broken. And counting by name is a lower bound rather than a total, because a few tables are named something else. `ext4_aops` is a real address space operations table and no suffix rule catches it.
""")

lesson.code(
    """# What this runtime knows about its own kernel. Read the status line before you believe anything.
kallsyms.report()""",
    note="Says up front whether the reader gets their own numbers or has to borrow somebody's.",
)

lesson.code(
    """found = kallsyms.symbols() if kallsyms.available() else []

if not found:
    print("no symbol table here:", kallsyms.explain())
else:
    tables = kallsyms.ops_tables(found)
    print(f"{len(found)} symbols, {len(tables)} of them named like an ops table")
    print()
    for family, count in kallsyms.families(found).items():
        print(f"  {family:12} {count}")
    print()
    for one in kallsyms.named(tables, "file_operations")[:8]:
        print(f"  {one.kind}  {one.name}")""",
    note="S05-03 settles here, on the reader's kernel, with no stored number to compare against.",
)

lesson.md(f"""## One table, every file

Here is the part that pays for the lesson. {lesson.claim("S05-04")}.

The section letter in the middle column of `/proc/kallsyms` is the same code `nm` uses. `r` and `R` mean read only data, which is what `const` looks like from outside the compiler. Almost every ops table is `const`, so it cannot be modified after the kernel is built, so there is no reason to have more than one of it.
""")

lesson.code(
    """if found:
    tables = kallsyms.ops_tables(found)
    readonly = [one for one in tables if one.readonly]
    writable = [one for one in tables if one.writable]
    print(f"read only:  {len(readonly)}")
    print(f"writable:   {len(writable)}")
    print(f"so {len(readonly) / len(tables):.0%} of the tables on this machine are const")
    print()
    print("the writable ones are worth a look, they are usually built at runtime:")
    for one in writable[:6]:
        print(f"  {one.kind}  {one.name}")""",
    note="S05-04 settles here. The writable minority is printed because it is the interesting half.",
)

lesson.md("""## The thing that will catch you

Answer the question in the next cell before you read on. This is the one people get wrong for months.
""")

lesson.code(
    """PredictionGate(
    "Two thousand files are open on ext4 right now. How many copies of "
    "ext4_file_operations are in memory?",
    options={
        "a": "two thousand, one per open file",
        "b": "one per mounted ext4 filesystem",
        "c": "one, for the whole machine",
    },
    answer="c",
    why="The table is const and lives in read only data, so there is exactly one of it and every "
    "open file points at the same address. Nothing about one particular file can be stored in it. "
    "Everything that differs between two open files lives in the file, usually in private_data.",
)""",
    note="Answer it, then open the fold. The answer is in the notebook, so this is a speed bump.",
)

lesson.md(f"""The table is shared, which means it holds no state about you.

{lesson.image("many-files-one-table.svg", "Three boxes on the left, each a struct file with an f_op field and a private_data field, and three arrows from their f_op fields all meeting at a single box on the right holding const struct file_operations ext4_file_operations, marked read only data.")}

That constraint shapes the whole design. A filesystem that wants per file state cannot put it in the table, so it hangs it off `private_data` in the file. When you meet `private_data` in a driver and wonder why the kernel is passing state around in a void pointer, this is the reason.
""")

lesson.md(f"""## Most of it is empty

Open a real table and count what is filled. A `struct file_operations` has more than thirty slots, a filesystem fills eight or ten, and the rest are null.

That is not sloppiness, it is the arrangement working. {lesson.claim("S05-05")}. Asking a pipe to `mmap` comes back as an error rather than as a jump to address zero, so a filesystem that does not want to implement something implements nothing at all.

The cell below draws a real table if your kernel ships BTF at `/sys/kernel/btf/vmlinux`, which most kernels since 2020 do. What it draws is the shape of the type, with every slot empty, because BTF describes types and what sits in a slot is a fact about a running kernel.
""")

lesson.code(
    """VMLINUX = Path("/sys/kernel/btf/vmlinux")

if not VMLINUX.exists():
    print(f"{VMLINUX} is not here, so there is no type information to draw")
    print("on a machine that has it, this cell shows every slot in a struct file_operations")
else:
    vmlinux = btf.parse_file(VMLINUX)
    OpsExplorer(vmlinux.ops("file_operations"))""",
    note="Shape only. Filling the slots wants a live dump, which is C09's job rather than this one.",
)

lesson.block("experiment")
lesson.md(f"""## Watch the split happen

Everything so far has been names in a symbol table. Now watch two writes take two different paths.

{lesson.claim("S05-06")}.

The next cell writes one byte to a regular file and one byte to a pipe, tracing each one, and prints what ran directly underneath `vfs_write`. Same call, same size, same process, and two different function names come back.

If your runtime cannot trace, run this on a Linux machine you control and paste the output in:

```sh
cd /sys/kernel/tracing
sudo sh -c 'echo function_graph > current_tracer; echo vfs_write > set_graph_function'
sudo sh -c 'echo > trace; echo 1 > tracing_on; dd if=/dev/zero of=/tmp/one bs=1 count=1 2>/dev/null; echo 0 > tracing_on'
sudo cat trace
```
""")

lesson.code(
    """import os


def write_to_pipe() -> None:
    reader, writer = os.pipe()
    try:
        os.write(writer, b"x")
        os.read(reader, 1)
    finally:
        os.close(writer)
        os.close(reader)


PASTED = ""  # paste a trace between the quotes if this runtime cannot capture one

captures, source = {}, ""
if PASTED.strip():
    captures, source = {"pasted": PASTED}, "<pasted into this notebook>"
elif tracefs.available():
    here = tracefs.find()
    captures = {
        "regular file": here.capture(tracefs.write_one_byte(), function="vfs_write"),
        "pipe": here.capture(write_to_pipe, function="vfs_write"),
        "/dev/null": here.capture(tracefs.write_one_byte("/dev/null"), function="vfs_write"),
    }
    source = "/sys/kernel/tracing/trace"
else:
    print("nothing captured:", tracefs.explain())

print(f"{len(captures)} captures from {source or 'nowhere yet'}")""",
    note="S05-06 stays unverified until this runs against the pinned kernel under kxbox.",
)

lesson.md("""## Look at it before anything parses it

The unedited text is the evidence. Everything after this is a rendering of it, and a rendering can be wrong in ways the text is not.
""")

lesson.code(
    """for label, raw in captures.items():
    print(f"--- {label} " + "-" * 40)
    print("\\n".join(raw.splitlines()[:16]) or "empty")
    print()""",
    note="Raw first, always. A reader who never sees the raw text is trusting the parser blind.",
)

lesson.md("""## Then name the function that did the work

One line per destination. The name in the second column is the slot that was plugged in when the file was opened.
""")

lesson.code(
    """tapes = {label: function_graph.parse(raw, source=source) for label, raw in captures.items()}

for label, tape in tapes.items():
    write = next((f for f in tape.walk() if f.name == "vfs_write"), None)
    under = [child.name for child in write.children] if write else []
    print(f"{label:14} {under or 'vfs_write not in this capture'}")""",
    note="The payoff cell. Three destinations, three different names, one caller above them.",
)

lesson.md("""Now grade yourself. The grader has no stored answer key and there is nowhere for one to hide, because every correct value is computed from the symbol table you read. It refuses to grade you against the handwritten fixture in `corpora/proc/handwritten/`, because grading somebody on a file nobody read off a kernel is the one thing this project promises not to do.
""")

lesson.code(
    """if not found:
    print("there is no symbol table here, so there is nothing to grade")
else:
    tape = tapes.get("regular file") or next(iter(tapes.values()), None)
    try:
        print(grader.report(grader.grade(found, answers, tape, "/proc/kallsyms")))
    except ValueError as refused:
        print("the grader refused:", refused)""",
    note="Grading against the reader's own kernel, or a refusal that explains itself.",
)

lesson.block("change")
lesson.md("""## Change something

Reading about dispatch is one skill. Making the dispatch land somewhere else is the one that matters.

Do these in order, and after each one look at the function name under `vfs_write`.

1. Change the target of the first capture from a file on disk to a file under `/dev/shm`, which is tmpfs. The name should change from an ext4 function to a shmem one, with nothing else about your program different.
2. Open the same file twice, write through both descriptors, and confirm both go to the same function. Two files, one table, which is the trap from earlier seen from the other side.
3. Write to a socket instead. The name changes again, and this time the table is not a file operations table at all, which is the thread S06 picks up.

You know it worked when the name under `vfs_write` changes and everything above it stays identical. If the whole trace changed shape, you probably changed the size of the write as well, and the thing to compare is the name rather than the number of calls.

Then answer the question the lesson opened with. Nothing in the VFS switches on the file type, and now you can say what does the choosing and when it was chosen.
""")

lesson.md("""## What is not settled yet

This lesson is a draft, and here is the exact reason.

Six claims are registered in `claims.toml` beside this file. The two counting claims settle themselves as soon as a reader runs the notebook on a Linux machine, because the number comes off their own kernel. The three source claims each name a citation in `refs.toml`, and none of the three is confirmed, because confirming one means finding its anchor in a real 7.2.2 tree and there is not one here yet.

The last claim wants a capture of two writes going two different ways. That needs the pinned kernel booted, which needs `kxbox`, which is written and tested and has never had a kernel to boot. Until then the experiment runs on whatever Linux the reader has, which is honest evidence about their kernel and not about ours.

There is a handwritten symbol table in `corpora/proc/handwritten/`. It exists so the parser had something to test against, it is marked `evidence = false`, and no claim here points at it. The claim ledger fails the build if one ever tries.
""")

raise SystemExit(lesson.save())
