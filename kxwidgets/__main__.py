"""Draw every widget into one HTML file, so you can look at them without a notebook.

    python3 -m kxwidgets --preview /tmp/kxwidgets.html

Working on a widget by rebuilding a notebook every time is slow enough that people stop looking,
and a visual thing nobody looks at goes wrong quietly. This writes a page with every widget on it,
in about a tenth of a second, from the handwritten fixtures in `corpora/`.

Almost nothing here is evidence. The trace and the BTF blob most of it draws were written by hand
so the parsers had something to work against, both are marked `evidence = false`, and no lesson may
cite either. The preview is for checking that a box is the right width, not for learning anything
about a kernel.

The lock timelines and the tape diffs are the exception, and they have to be. A handwritten trace
cannot show contention, because contention is a fact about a machine rather than about a format,
and writing a plausible ten millisecond wait by hand would be inventing the one number the widget
exists to show. A comparison needs two traces that differ in something worth comparing, and writing
both halves by hand would mean deciding the answer first. So those four are drawn from real
captures in `corpora/traces/`, and the pairs are the point in both cases.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from kxray import btf
from kxray.trace import function_graph
from kxshapes import FrameCard, ObjectBox, PointerThread
from kxwidgets import (
    ContextKey,
    Descent,
    LockTimeline,
    MemoryScale,
    ObjectGraph,
    OpsExplorer,
    PredictionGate,
    StructMap,
    SyscallTape,
    TapeDiff,
)
from kxwidgets.html import page

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "corpora" / "traces" / "handwritten" / "write-1byte.txt"
BLOB = ROOT / "corpora" / "btf" / "handwritten" / "tiny.btf"

# The two real captures, and they are here for the one widget that cannot be shown on a fixture.
CONTENDED = ROOT / "corpora" / "traces" / "tier1" / "contended-lock.txt"
EMULATED = ROOT / "corpora" / "traces" / "tier0" / "write-1byte.txt"
TWO_WRITES = ROOT / "corpora" / "traces" / "tier0" / "two-writes.txt"


def _parse(path: Path):
    return function_graph.parse(path.read_text(encoding="utf-8"), source=str(path))


def gallery() -> str:
    """One of each, built from the handwritten fixtures, plus two lock timelines from captures."""
    tape = function_graph.parse(TRACE.read_text(encoding="utf-8"), source=str(TRACE))
    tiny = btf.parse_file(BLOB)

    gate = PredictionGate(
        "Where does the time in a one byte write actually go?",
        options={
            "a": "in the filesystem, writing the byte out",
            "b": "in the page cache, copying the byte into a page",
            "c": "in the scheduler, waiting for the disk",
        },
        answer="b",
        why=(
            "The byte goes into a page in the page cache and the call returns. Nothing reaches a "
            "disk until writeback runs later, in another process, in a trace your program does "
            "not appear in."
        ),
    )

    descent = Descent(
        {
            "userspace": "write(fd, buf, 1)",
            "entry": "one register becomes one function call",
            "vfs": "the file, without anything knowing what it is stored on",
            "fs": "the filesystem decides where the byte belongs",
            "pagecache": "the byte is copied into a folio and the call returns",
        },
        cards={
            "vfs": [FrameCard.of("demo_vfs_write", path="fs/read_write.c")],
            "fs": [FrameCard.of("demo_shmem_write", path="mm/shmem.c")],
            "pagecache": [FrameCard.of("demo_copy_folio", path="mm/filemap.c")],
        },
        title="A one byte write, drawn from the handwritten fixture",
    )

    task = tiny.layout("demo_task")
    graph = ObjectGraph(
        [ObjectBox.of(task, show=["pid", "comm", "mm", "parent"], locks={"mm": "demo_task.lock"})],
        [
            PointerThread.of("demo_task", "mm", "demo_mm"),
            PointerThread.of("demo_task", "parent", "demo_task", kind="borrowed"),
        ],
        title="demo_task, and what it points at",
    )

    sizes = MemoryScale(
        {
            "struct demo_task": task.size or 64,
            "a page": 4096,
            "a transparent huge page": 2 * 1024 * 1024,
        },
        title="Three sizes a page cache lesson says in one paragraph",
    )

    locks = LockTimeline(
        _parse(CONTENDED),
        timings_are_real=True,
        title="Four writers, one file, a real machine",
    )
    emulated = LockTimeline(
        _parse(EMULATED),
        timings_are_real=False,
        title="The same widget on a Tier 0 capture, where the clock is not real",
    )

    both = _parse(TWO_WRITES)
    compared = TapeDiff(
        _parse(EMULATED),
        both,
        labels=("one write", "two writes"),
        max_depth=3,
        title="What a second write to a pipe adds to the trace",
    )
    side_by_side = TapeDiff(
        both.roots[1],
        both.roots[2],
        labels=("to a file", "to a pipe"),
        max_depth=2,
        shared_scale=True,
        title="One write syscall and another, out of the same trace, on one scale",
    )

    widgets = [
        descent,
        ContextKey(),
        locks,
        emulated,
        compared,
        side_by_side,
        SyscallTape(tape, max_depth=4, title="write-1byte, handwritten fixture"),
        SyscallTape(tape, max_depth=4, by_cpu=True, title="the same trace, one lane per cpu"),
        graph,
        sizes,
        StructMap(tiny.layout("demo_task")),
        StructMap(tiny.layout("demo_flags"), per_row=2),
        StructMap(tiny.layout("demo_value"), per_row=8),
        OpsExplorer(tiny.ops("demo_ops")),
        OpsExplorer(
            tiny.ops("demo_ops", instance="demo_shmem_ops").with_implementations(
                {"open": "demo_shmem_open", "write": "demo_shmem_write"}
            )
        ),
        OpsExplorer(
            tiny.ops("demo_ops", instance="demo_shmem_ops").with_implementations(
                {"open": "demo_shmem_open", "write": "demo_shmem_write"}
            ),
            compact=True,
        ),
        gate,
        gate.check("a"),
    ]

    header = (
        "<h1>kxwidgets</h1>"
        "<p>Every widget, drawn from the handwritten fixtures in corpora. None of that is "
        "evidence and no lesson may cite it. It is here so a widget can be looked at without "
        "building a notebook first. The two lock timelines are the exception, because a "
        "handwritten trace cannot show a lock somebody waited for, so those two come from real "
        "captures.</p>"
    )
    return header + "".join(one.html() for one in widgets)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preview",
        default="/tmp/kxwidgets.html",
        help="where to write the page, defaulting to a temporary file",
    )
    args = parser.parse_args()

    out = Path(args.preview)
    out.write_text(page("kxwidgets", gallery()), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
