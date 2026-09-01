"""Draw all four widgets into one HTML file, so you can look at them without a notebook.

    python3 -m kxwidgets --preview /tmp/kxwidgets.html

Working on a widget by rebuilding a notebook every time is slow enough that people stop looking,
and a visual thing nobody looks at goes wrong quietly. This writes a page with every widget on it,
in about a tenth of a second, from the handwritten fixtures in `corpora/`.

Nothing here is evidence. The trace and the BTF blob it draws were both written by hand so the
parsers had something to work against, both are marked `evidence = false`, and no lesson may cite
either. The preview is for checking that a box is the right width, not for learning anything about
a kernel.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from kxray import btf
from kxray.trace import function_graph
from kxwidgets import OpsExplorer, PredictionGate, StructMap, SyscallTape
from kxwidgets.html import page

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "corpora" / "traces" / "handwritten" / "write-1byte.txt"
BLOB = ROOT / "corpora" / "btf" / "handwritten" / "tiny.btf"


def gallery() -> str:
    """One of each, built from the handwritten fixtures."""
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

    widgets = [
        SyscallTape(tape, max_depth=4, title="write-1byte, handwritten fixture"),
        StructMap(tiny.layout("demo_task")),
        StructMap(tiny.layout("demo_flags"), per_row=2),
        StructMap(tiny.layout("demo_value"), per_row=8),
        OpsExplorer(tiny.ops("demo_ops")),
        OpsExplorer(
            tiny.ops("demo_ops", instance="demo_shmem_ops").with_implementations(
                {"open": "demo_shmem_open", "write": "demo_shmem_write"}
            )
        ),
        gate,
        gate.check("a"),
    ]

    header = (
        "<h1>kxwidgets</h1>"
        "<p>Every widget, drawn from the handwritten fixtures in corpora. None of this is "
        "evidence and no lesson may cite it. It is here so a widget can be looked at without "
        "building a notebook first.</p>"
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
