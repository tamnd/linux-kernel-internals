"""The notebook contract.

    python3 -m tools.lintnb            check every committed lesson notebook
    python3 -m tools.lintnb Z02        check one
    python3 -m tools.lintnb --rules    print the seven rules and what each one is for

A lesson is a notebook a stranger opens in Colab on a phone, on a borrowed laptop, or on a machine
with no Linux anywhere near it. That reader has no way to tell a cell that is slow from a cell that
has hung, no way to tell a replayed capture from their own, and nobody to ask. Everything in this
file is a rule that stops one of those from happening, and each one is here because leaving it to
care and attention means it holds for three lessons and then quietly stops.

The seven rules, in the order they matter to a reader:

1. **The banner comes first.** Before any evidence, a lesson prints which kernel it is about, what
   is behind this session and what this runtime can do. A reader who does not know whether a trace
   came off a kernel or out of a file will believe the wrong thing about every number under it.
2. **Nothing a browser cannot finish.** No sleeping, no installing outside the setup cell, and any
   subprocess has to carry a timeout. A cell with no timeout on a machine where the command hangs
   is a notebook that never finishes and never says why.
3. **Every code cell has a caption.** One line, in the builder, saying why the cell is there. It
   becomes the caption on the site, and a cell nobody could write one line about is a cell that
   does not belong in the lesson.
4. **No raw dump where a widget exists.** Printing a whole parsed object gives the reader a wall of
   repr where a picture was available. Printing the raw text a parser is about to read is the
   opposite and is encouraged, so the rule is about parsed objects only.
5. **Twenty code cells at most.** The cap is on the work a reader does, so markdown does not count
   against it. A lesson that needs more than twenty is two lessons.
6. **Kernel evidence comes through the box or the corpus helper.** No cell opens a path under
   `corpora/` by hand. That is what lets `kxbox.bothways` answer the emulator and recording
   question once, for every lesson, rather than each lesson answering it for itself.
7. **Nothing is written outside the scratch directory.** A cell that writes a bare relative path
   drops files wherever the reader started Jupyter. `colab.scratch(slug)` is where writes go.

What this cannot do is time a cell, so rule 2 is enforced as the constructs that break the ten
second cap rather than as the cap itself. Measuring it means executing every notebook against a
real runtime, which is a job for the machine that has one and not for a checker that has to answer
in under a second in the prose job. The constructs are where the failures actually came from.

Rule 6 is delegated on purpose and it is worth saying how. `kxbox.bothways` runs every Tier 0
recipe with the emulator and again with `KXBOX_DISABLE=1` and compares them, so if every recipe
agrees both ways then every lesson does. That argument only holds while lessons get their evidence
through recipes and the corpus helper. A cell that opens a capture by hand steps outside it, and
then the guarantee covers everything except the one cell that broke it.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

LESSONS = Path("lessons")

MAX_CODE_CELLS = 20

# The call that has to come before any evidence. Written as a suffix rather than a whole line so
# that `kxray.banner()`, `banner()` and `kxray.banner(profile="A-full")` all count.
BANNER = "banner"

# A cell whose whole job is making the toolkit importable. It comes before the banner, because
# there is nothing to print a banner with until it has run.
SETUP = ("%pip", "sys.path", "import sys")

# Sleeping in a notebook is always somebody waiting for something they should have waited for
# properly, and it is indistinguishable from a hang to the reader.
FORBIDDEN_CALLS = {
    "time.sleep": "sleeping looks exactly like hanging to a reader",
    "sleep": "sleeping looks exactly like hanging to a reader",
    "input": "a notebook that waits for typing never finishes in a rendered page",
}

# Anything that starts another program has to say how long it is prepared to wait.
SUBPROCESS_CALLS = ("subprocess.run", "subprocess.check_output", "subprocess.call")

# Calls that hand back a parsed object with a widget behind it. Printing one of these gives the
# reader a repr where a picture existed.
HAS_WIDGET = {
    "function_graph.parse": "SyscallTape",
    "function_graph.parse_file": "SyscallTape",
    "parse_file": "SyscallTape",
    "box.tape": "SyscallTape",
    "box.trace": "SyscallTape",
    "lockdep.parse_classes": "LockTable",
    "btf.parse_file": "StructMap",
    "kxdiff.compare": "TapeDiff",
}

# Where a lesson is allowed to write, and how it gets there.
SCRATCH = "colab.scratch"
WRITES = ("write_text", "write_bytes", "mkdir", "touch")

# Reading a committed capture goes through here, so that one place knows how to find it in a
# checkout and how to fetch it in Colab.
CORPUS_HELPERS = ("colab.corpus_text", "colab.corpus_file", "colab.repo_file", "colab.lesson_text")

# The calls that turn a string into a file. A corpus path inside one of these is an open. A corpus
# path anywhere else is a label saying where something came from, which every lesson does.
OPENERS = ("open", "Path", "parse_file", "read_text", "read_bytes")

RULES = (
    ("banner", "The banner comes first, before any evidence"),
    ("timeout", "Nothing a browser cannot finish: no sleeping, no installing, no untimed command"),
    ("caption", "Every code cell has a one line caption, which becomes the caption on the site"),
    ("widget", "No raw dump of a parsed object where a widget exists"),
    ("length", f"{MAX_CODE_CELLS} code cells at most, because markdown is not the work"),
    ("evidence", "Kernel evidence comes through the box or the corpus helper, never by hand"),
    ("scratch", f"Nothing is written outside {SCRATCH}(slug)"),
)


@dataclass(frozen=True)
class Finding:
    where: str
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.rule}: {self.message}"


@dataclass(frozen=True)
class Cell:
    identifier: str
    kind: str
    source: str
    note: str

    @property
    def is_code(self) -> bool:
        return self.kind == "code"

    @property
    def looks_like_setup(self) -> bool:
        """Whether this cell is doing the work of making the toolkit importable.

        Only ever asked of the first code cell. Asking it of any cell would make the rule about
        installing outside the setup cell circular, because a cell that installs something in the
        middle of a lesson would answer yes and exempt itself from the rule about doing that.
        """
        return self.is_code and any(one in self.source for one in SETUP)

    def tree(self) -> ast.Module | None:
        """The cell parsed as Python, or None when it is not.

        A cell is allowed not to be Python. `%pip install` is IPython and Colab needs it, so a
        cell that will not parse is skipped by the rules that need a syntax tree rather than
        reported. The rules that read the text still apply to it.
        """
        try:
            return ast.parse(self.source)
        except SyntaxError:
            return None


def read(path: Path) -> list[Cell]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    return [
        Cell(
            identifier=one.get("id", "?"),
            kind=one.get("cell_type", ""),
            source="".join(one.get("source", [])),
            note=str(one.get("metadata", {}).get("note", "")),
        )
        for one in notebook.get("cells", [])
    ]


def notebooks(root: Path = LESSONS) -> list[Path]:
    return sorted(root.glob("*/*.ipynb"))


def check(path: Path) -> list[Finding]:
    cells = read(path)
    where = path.as_posix()
    code = [one for one in cells if one.is_code]

    setup = code[0] if code and code[0].looks_like_setup else None

    found = _check_banner(where, code, setup)
    found += _check_length(where, code)
    for cell in code:
        found += _check_cell(where, cell, cell is setup)
    return found


def _check_banner(where: str, code: list[Cell], setup: Cell | None) -> list[Finding]:
    """Rule 1. The banner is the first code cell, or the second when there is a setup cell."""
    printed = [one for one in code if _calls(one, BANNER)]
    if not printed:
        return [
            Finding(
                where,
                "banner",
                "no cell calls kxray.banner(), so a reader never learns which kernel this is "
                "about or whether anything below came off a running machine",
            )
        ]
    if len(printed) > 1:
        names = ", ".join(one.identifier for one in printed)
        return [Finding(where, "banner", f"more than one banner cell: {names}")]

    real = [one for one in code if one is not setup]
    if real and real[0].identifier != printed[0].identifier:
        return [
            Finding(
                where,
                "banner",
                f"{real[0].identifier} runs before the banner in {printed[0].identifier}, "
                "so the reader sees output before they know what is behind it",
            )
        ]
    return []


def _calls(cell: Cell, name: str) -> bool:
    """Whether the cell calls something whose name ends in `name`."""
    tree = cell.tree()
    if tree is None:
        return False
    return any(
        _called_name(node).split(".")[-1] == name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    )


def _called_name(node: ast.Call) -> str:
    """The dotted name being called, as text, or an empty string when it is not a name."""
    return _dotted(node.func)


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _check_length(where: str, code: list[Cell]) -> list[Finding]:
    """Rule 5."""
    if len(code) <= MAX_CODE_CELLS:
        return []
    return [
        Finding(
            where,
            "length",
            f"{len(code)} code cells, and the cap is {MAX_CODE_CELLS}. A lesson that needs more "
            "than that is two lessons.",
        )
    ]


def _check_cell(where: str, cell: Cell, is_setup: bool) -> list[Finding]:
    at = f"{where} [{cell.identifier}]"
    found = _check_caption(at, cell)
    # Before the parse, because a cell that installs something is usually a cell that will not
    # parse, `%pip` being IPython rather than Python.
    if "%pip" in cell.source and not is_setup:
        found.append(Finding(at, "timeout", "installs outside the setup cell"))
    tree = cell.tree()
    if tree is None:
        return found
    found += _check_timeout(at, cell, tree)
    found += _check_widget(at, tree)
    found += _check_evidence(at, tree)
    found += _check_scratch(at, tree)
    return found


def _check_caption(at: str, cell: Cell) -> list[Finding]:
    """Rule 3."""
    note = cell.note.strip()
    if not note:
        return [Finding(at, "caption", "no note in the builder, so the site has no caption for it")]
    if "\n" in cell.note.strip("\n"):
        return [Finding(at, "caption", "the note runs to more than one line")]
    if len(note) < 20:
        return [Finding(at, "caption", f"the note is {len(note)} characters, which is not a line")]
    return []


def _check_timeout(at: str, cell: Cell, tree: ast.Module) -> list[Finding]:
    """Rule 2."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node)
        if name in FORBIDDEN_CALLS:
            found.append(Finding(at, "timeout", f"calls {name}, and {FORBIDDEN_CALLS[name]}"))
        if name in SUBPROCESS_CALLS and not _has_keyword(node, "timeout"):
            found.append(
                Finding(
                    at,
                    "timeout",
                    f"{name} with no timeout, so a command that hangs hangs the notebook",
                )
            )
    return found


def _has_keyword(node: ast.Call, name: str) -> bool:
    return any(one.arg == name for one in node.keywords)


def _check_widget(at: str, tree: ast.Module) -> list[Finding]:
    """Rule 4. Printing a whole parsed object where a widget draws it.

    Only whole objects. `print(tape.frame_count)` is a number and there is no widget for a number,
    and `print(raw)` is the raw text a parser is about to read, which a lesson should show.
    """
    parsed: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            widget = HAS_WIDGET.get(_called_name(node.value))
            if widget:
                parsed.update({one.id: widget for one in node.targets if isinstance(one, ast.Name)})

    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _called_name(node) == "print"):
            continue
        for argument in node.args:
            if isinstance(argument, ast.Name) and argument.id in parsed:
                found.append(
                    Finding(
                        at,
                        "widget",
                        f"prints {argument.id}, and {parsed[argument.id]} draws that",
                    )
                )
    return found


def _check_evidence(at: str, tree: ast.Module) -> list[Finding]:
    """Rule 6. A committed capture is opened through the helper and not by path.

    Opened, and not merely named. Every lesson passes `source="corpora/..."` to a parser so the
    resulting object knows which file it came out of, and half the notebooks print that string at
    the reader. Those are labels, and a rule that could not tell a label from an open would be
    turned off within a week by the first person it was wrong about.
    """
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _called_name(node) in OPENERS):
            continue
        for argument in node.args:
            if not (isinstance(argument, ast.Constant) and isinstance(argument.value, str)):
                continue
            if argument.value.startswith("corpora/") or "/corpora/" in argument.value:
                found.append(
                    Finding(
                        at,
                        "evidence",
                        f"opens {argument.value!r} by path. Use colab.corpus_text(...), which "
                        "finds it in a checkout and fetches it in Colab, and which keeps the "
                        "both ways guarantee covering this lesson.",
                    )
                )
    return found


def _check_scratch(at: str, tree: ast.Module) -> list[Finding]:
    """Rule 7. A write goes under `colab.scratch(slug)` and nowhere else."""
    rooted = _scratch_names(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node)
        if name.split(".")[-1] not in WRITES:
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if not _under_scratch(node.func.value, rooted):
            found.append(
                Finding(
                    at,
                    "scratch",
                    f"calls {name.split('.')[-1]}() on something that is not under "
                    f"{SCRATCH}(), so it writes wherever the reader started Jupyter",
                )
            )
    return found


def _scratch_names(tree: ast.Module) -> set[str]:
    """Every name in the cell that was bound to `colab.scratch(...)`.

    A cell almost never writes to the call directly. It takes the directory once, gives it a name,
    and joins onto that name, so a rule that only knew about the call would fire on every correct
    cell and pass the one that wrote to a bare path.
    """
    names = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.expr)):
            continue
        if _under_scratch(node.value, set()):
            names |= {one.id for one in node.targets if isinstance(one, ast.Name)}
    return names


def _under_scratch(node: ast.expr, rooted: set[str]) -> bool:
    """Whether an expression is rooted at `colab.scratch(...)`, however many joins deep."""
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call) and _called_name(inner) == SCRATCH:
            return True
        if isinstance(inner, ast.Name) and inner.id in rooted:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lintnb", description="Check the notebook contract.")
    ap.add_argument("slugs", nargs="*", help="Lessons to check, by slug. Default is all of them.")
    ap.add_argument("--rules", action="store_true", help="Print the seven rules and stop")
    args = ap.parse_args(argv)

    if args.rules:
        for number, (name, what) in enumerate(RULES, start=1):
            print(f"{number}. {name:9} {what}")
        return 0

    paths = notebooks()
    if args.slugs:
        paths = [one for one in paths if one.parent.name in args.slugs]
        missing = set(args.slugs) - {one.parent.name for one in paths}
        for slug in sorted(missing):
            print(f"lintnb: no notebook for {slug}", file=sys.stderr)
        if missing:
            return 1

    findings = [one for path in paths for one in check(path)]
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} problem(s) in {len(paths)} notebook(s)", file=sys.stderr)
        return 1

    print(f"lintnb: {len(paths)} notebook(s) keep the contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
