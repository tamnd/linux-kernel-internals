"""What goes inside the generated sections of a blueprint.

Three of the nine sections are not written by a person. Section 2 is the field layout of every
structure the mechanism is built out of, section 5 is what you can observe while it runs, and
section 7 is the functions and the ops tables it exposes. All three are facts about one build of
one kernel, and facts about one build of one kernel go stale silently, which is the reason books
about the kernel are full of offsets that stopped being true two releases ago.

So they are read out of the kernel instead. Section 2 and section 7 come from BTF, which is the
type information the kernel carries about itself, and section 5 comes from the corpus, which is
recordings of the kernel actually running.

The important part is what happens when the kernel is not there. Nothing is invented, nothing is
copied out of a header file from memory, and nothing is left blank in a way that reads as finished.
Every generated block starts with a line saying where its content came from and whether that source
is evidence, and when there is no source the block says that in the file rather than in a comment
somewhere else. `bpc` reads that line back, which is how a blueprint with no measurements behind it
is stopped from calling itself complete.

    from tools import bpcgen

    request = bpcgen.Request(pin="v7.2.2", arch="x86_64", structures=("vm_fault",))
    text, problems = bpcgen.render(2, request, btf_path="/sys/kernel/btf/vmlinux")
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "0.2"

CORPORA = "corpora"

# How deep the scene table in section 5 goes, counting from each outermost call. Four levels of a
# real write is about a dozen rows and the whole thing is about a hundred, and a hundred row table
# in the middle of a specification is a table nobody reads. The indented tree above it is uncut.
SCENE_DEPTH = 4

# BTF records types and not machines, so the same blob describes a different layout on a 32-bit
# build than on a 64-bit one. The architecture in the header is what decides, and a blueprint that
# does not say which architecture it means is not saying anything.
POINTER_SIZES = {
    "x86_64": 8,
    "arm64": 8,
    "aarch64": 8,
    "riscv64": 8,
    "i386": 4,
    "x86": 4,
    "arm": 4,
}

# The provenance line, which is the first line inside every generated block. It is inside the seal
# on purpose. A comment above the block could be edited without the hash noticing, and provenance
# that can be edited quietly is worse than none.
SOURCE_LINE = re.compile(r"^<!--\s*bpc:source\s+(.*?)\s*-->\s*$")


@dataclass(frozen=True)
class Source:
    """Where a generated section came from, and whether that counts as evidence.

    `kind` is `btf`, `corpus` or `none`. `evidence` is the one that matters: a blob written by hand
    so the reader had something to parse is not the kernel, and a section generated from one holds
    numbers that look exactly like measurements and are not.
    """

    kind: str
    path: str
    evidence: bool
    pin: str
    arch: str

    def line(self) -> str:
        return (
            f"<!-- bpc:source kind={self.kind} path={self.path or 'none'} "
            f"evidence={'true' if self.evidence else 'false'} "
            f"pin={self.pin or 'none'} arch={self.arch or 'none'} -->"
        )


def parse_source(content: str) -> Source | None:
    """Read the provenance line back out of a generated block, or None when there is not one."""
    for raw in content.split("\n"):
        found = SOURCE_LINE.match(raw.strip())
        if not found:
            continue
        pairs = dict(part.split("=", 1) for part in found.group(1).split() if "=" in part)
        return Source(
            kind=_value(pairs, "kind"),
            path=_value(pairs, "path"),
            evidence=pairs.get("evidence") == "true",
            pin=_value(pairs, "pin"),
            arch=_value(pairs, "arch"),
        )
    return None


def _value(pairs: dict[str, str], key: str) -> str:
    # `none` is what an empty field is written as, because a bare `path=` in the middle of a line
    # of attributes is hard to see and harder to parse back.
    got = pairs.get(key, "")
    return "" if got == "none" else got


@dataclass(frozen=True)
class Request:
    """What one blueprint asks the generator for, taken straight from its header."""

    pin: str = ""
    arch: str = ""
    pointer_size: int = 0
    structures: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    ops: tuple[str, ...] = ()
    artefacts: tuple[str, ...] = ()

    @property
    def bytes_per_pointer(self) -> int:
        return self.pointer_size or POINTER_SIZES.get(self.arch, 8)

    @classmethod
    def from_header(cls, header: dict[str, object]):
        def names(key: str) -> tuple[str, ...]:
            value = header.get(key, [])
            if isinstance(value, str):
                value = [value]
            return tuple(str(one).strip("`") for one in value if str(one).strip())

        raw_size = str(header.get("pointer-size", "") or "")
        return cls(
            pin=str(header.get("pin", "")),
            arch=str(header.get("arch", "")),
            pointer_size=int(raw_size) if raw_size.isdigit() else 0,
            structures=names("structures"),
            interfaces=names("interfaces"),
            ops=names("ops"),
            artefacts=names("artefacts"),
        )


@dataclass
class Rendered:
    """One generated section: the text that goes between the markers, and what went wrong."""

    text: str
    source: Source
    problems: list[str] = field(default_factory=list)


# -- where the sources come from ---------------------------------------------------------------


def meta_for(path: Path) -> dict[str, object]:
    """The `.meta.toml` beside a corpus artefact, or an empty dict when there is not one."""
    meta = path.with_suffix(".meta.toml")
    if not meta.exists():
        return {}
    return tomllib.loads(meta.read_text(encoding="utf-8"))


def btf_source(path: Path, request: Request) -> Source:
    """Describe a BTF blob, including whether it is a real kernel or a corpus fixture.

    A blob under `corpora/` is evidence only when its metadata says so, and the handwritten ones
    say so loudly that they are not. A blob anywhere else is a file somebody pointed at deliberately
    on a machine that has a kernel, and that counts.
    """
    meta = meta_for(path)
    evidence = bool(meta["evidence"]) if "evidence" in meta else True
    return Source("btf", str(path), evidence, request.pin, request.arch)


def load_btf(path: Path, request: Request):
    """Parse a BTF blob at the pointer size this blueprint's architecture implies."""
    from kxray import btf as btf_module

    return btf_module.parse_file(path, pointer_size=request.bytes_per_pointer)


def artefact_paths(request: Request, root: Path) -> list[tuple[str, Path | None]]:
    """Resolve each artefact id to a file under `corpora/`, or to None when it is not there."""
    out: list[tuple[str, Path | None]] = []
    for one in request.artefacts:
        base = root / CORPORA / one
        matches = sorted(base.parent.glob(base.name + ".*")) if base.parent.exists() else []
        real = [m for m in matches if not m.name.endswith(".meta.toml")]
        out.append((one, real[0] if real else None))
    return out


# -- section 2, the structures -----------------------------------------------------------------


def section_2(request: Request, root: Path, btf_path: Path | None) -> Rendered:
    """The field layout of every structure the blueprint names, with offsets, sizes and holes."""
    if btf_path is None:
        source = Source("none", "", False, request.pin, request.arch)
        lead = "this mechanism is built out of"
        return Rendered(_waiting_on_btf(request.structures, "structure", lead, source), source)

    from kxray.btf.format import BtfError

    source = btf_source(btf_path, request)
    btf = load_btf(btf_path, request)
    problems: list[str] = []
    out = [source.line(), ""]
    out.append(
        f"Generated by bpc {VERSION} from `{btf_path}`, for {request.arch} with "
        f"{request.bytes_per_pointer} byte pointers. Offsets are byte offsets from the start of "
        f"the structure. A hole is padding the compiler inserted and not a field you can use."
    )
    out.append("")
    if not source.evidence:
        out.append(_not_evidence(str(btf_path), meta_for(btf_path)))
        out.append("")

    for name in request.structures:
        try:
            layout = btf.layout(name)
        except (KeyError, BtfError) as problem:
            problems.append(f"section 2: {name}: {problem}")
            out.append(f"### struct {name}")
            out.append("")
            out.append(f"Not in `{btf_path}`, so there is nothing to generate for it.")
            out.append("")
            continue
        out.extend(_layout_block(layout))

    if not request.structures:
        out.append(
            "This blueprint names no structures in its header, so there is nothing to lay out. "
            "Add `structures: [name, name]` to the header and generate again."
        )
        out.append("")

    return Rendered("\n".join(out).rstrip() + "\n", source, problems)


def _layout_block(layout) -> list[str]:
    from kxray.vocabulary import tags_for

    out = [f"### {layout.name}", ""]
    size = "unknown size" if layout.size is None else f"{layout.size} bytes"
    holes = (
        "no padding"
        if not layout.holes
        else f"{layout.padding} bytes of padding in {len(layout.holes)} hole(s)"
    )
    out.append(f"{size}, {len(layout.fields)} field(s), {holes}.")
    out.append("")
    out.append("| Offset | Size | Field | Type |")
    out.append("|---|---|---|---|")

    seen_tags = []
    for one in layout.fields:
        size_cell = "?" if one.size is None else str(one.size)
        if one.is_bitfield:
            size_cell = f"{one.bitfield_size} bits"
        tags = tags_for(one.type_name)
        seen_tags.extend(tag for tag in tags if tag not in seen_tags)
        glyphs = ("&nbsp;" + " ".join(tag.glyph for tag in tags)) if tags else ""
        out.append(
            f"| {one.byte_offset} | {size_cell} | `{one.path}` | `{one.type_name}`{glyphs} |"
        )
    out.append("")

    if seen_tags:
        legend = ", ".join(f"{tag.glyph} is `{tag.marker}`, {tag.meaning}" for tag in seen_tags)
        out.append(f"Glyphs in the type column: {legend}.")
        out.append("")

    for hole in layout.holes:
        out.append(f"- {hole.size} byte hole at offset {hole.byte_offset}, after `{hole.after}`.")
    if layout.holes:
        out.append("")
    return out


# -- section 5, what you can observe -----------------------------------------------------------


def section_5(request: Request, root: Path, btf_path: Path | None) -> Rendered:
    """What the mechanism looks like from outside, taken from recordings in the corpus."""
    found = artefact_paths(request, root)
    real = [(one, path) for one, path in found if path is not None]
    problems = [f"section 5: no artefact in corpora for {one!r}" for one, path in found if not path]

    metas = {one: meta_for(path) for one, path in real}
    evidence = bool(real) and all(bool(meta.get("evidence")) for meta in metas.values())
    source = Source(
        "corpus" if real else "none",
        CORPORA if real else "",
        evidence,
        request.pin,
        request.arch,
    )

    out = [source.line(), ""]
    if not real:
        out.append(
            f"Generated by bpc {VERSION} from no artefacts, because this blueprint names none in "
            f"its header or none of the ones it names are in the corpus. Nothing here is observed."
        )
        out.append("")
        out.append(
            "When a kernel has been built and traced, add `artefacts: [path/under/corpora]` to "
            "the header and generate again. Each artefact then appears below with what it "
            "records, what fires and in what order, and whether it is a capture from a real "
            "machine or a fixture."
        )
        out.append("")
        return Rendered("\n".join(out).rstrip() + "\n", source, problems)

    out.append(
        f"Generated by bpc {VERSION} from {len(real)} artefact(s) in `{CORPORA}/`. Every claim in "
        f"this section points at a file that can be replayed, which is the difference between a "
        f"specification of observable behaviour and a description of it."
    )
    out.append("")

    partners, hidden = _pair_up(real, metas)
    for one, path in real:
        if one in hidden:
            continue
        out.extend(_artefact_block(one, path, metas[one], root, partners.get(one)))

    return Rendered("\n".join(out).rstrip() + "\n", source, problems)


def _pair_up(
    real: list[tuple[str, Path]], metas: dict[str, dict]
) -> tuple[dict[str, tuple[str, Path]], set[str]]:
    """Which artefacts are two readings of one thing, so they get drawn beside each other.

    A `/proc` file read before something happened and again after it is two files whose numbers
    only mean anything next to each other. Fifty counters in one column and fifty in another,
    pages apart, is not a specification of what changed, it is homework.

    Which two go together is not worked out from the file names here. A capture that is half of a
    pair says so in its own metadata under `pair`, because that is a fact about how it was taken.
    Which of the two is the before is the order the blueprint lists them in, so the author decides
    it and nothing here guesses from a word in a filename.
    """
    by_name = {path.name: (one, path) for one, path in real}
    partners: dict[str, tuple[str, Path]] = {}
    hidden: set[str] = set()
    for one, _path in real:
        if one in hidden:
            continue
        named = str(metas[one].get("pair", ""))
        found = by_name.get(named)
        if found is None or found[0] == one:
            continue
        partners[one] = found
        hidden.add(found[0])
    return partners, hidden


def _artefact_block(
    one: str,
    path: Path,
    meta: dict[str, object],
    root: Path,
    partner: tuple[str, Path] | None = None,
) -> list[str]:
    relative = path.relative_to(root) if path.is_relative_to(root) else path
    heading = f"### `{relative}`"
    if partner is not None:
        other = partner[1].relative_to(root) if partner[1].is_relative_to(root) else partner[1]
        heading = f"### `{relative}` and `{other}`"
    out = [heading, ""]

    describes = str(meta.get("describes", "not described"))
    tracer = str(meta.get("tracer", ""))
    if tracer:
        out.append(f"Tracer `{tracer}`, recording {describes}.")
    else:
        # Nothing traced this one. Somebody read a file, or copied what the kernel printed, and
        # the command that did it is in the metadata, so say that rather than printing the word
        # `unknown` next to a capture whose provenance is written down two lines away.
        how = str(meta.get("command", "")).strip()
        taken = f"`{how}`" if how else "no command recorded"
        out.append(f"Not a trace. Taken by {taken}, recording {describes}.")
    out.append("")

    if not meta.get("evidence"):
        out.append(_not_evidence(str(relative), meta))
        out.append("")

    if tracer == "function_graph":
        out.extend(_function_graph_block(path))
        return out

    body = READERS.get(_route(path, root))
    if body is not None:
        out.extend(body(path, partner[1] if partner else None))
    return out


def _route(path: Path, root: Path) -> str:
    """Which reader in `kxray` opens this artefact, by the same table the corpus tools use.

    Dispatching on the reader rather than on a new key in the metadata means a parser and the
    blueprints that quote it never disagree about what a file is. `kxray/corpus/index.py` already
    has to know, because `tools/baseline` accounts every line of every artefact through it, and a
    second table here would be a second thing to keep in step.
    """
    from kxray.corpus import index

    base = root / CORPORA
    try:
        return index.route(path, base) or ""
    except ValueError:
        return ""


def _function_graph_block(path: Path) -> list[str]:
    """A capture as a blueprint reads it: the shape of the calls, then the drawing as a table.

    Two blocks, and they are two on purpose. The indented tree says what called what, which is the
    thing a specification is about. The scene table says what the picture of it looks like, which
    is the thing a reader is going to see in the notebook and in the animation, and it comes out of
    `kxshapes.scene` rather than out of anything here. Before that existed a blueprint printed the
    tree and a notebook drew boxes and nothing anywhere connected the two, so a widget that started
    placing a box differently would not have shown up in a single generated document.

    The depth is capped. A blueprint is read on a page and a table with two hundred rows in it is
    not read at all, and the tree above it is uncut, so nothing is hidden, only unlisted.
    """
    from kxray.trace import parse_file
    from kxshapes.scene import scene_of

    tape = parse_file(path)
    cpus = ", ".join(str(cpu) for cpu in tape.cpus) or "none"
    out = [
        f"{tape.frame_count} frame(s) in {len(tape.roots)} call(s), nested {tape.max_depth} deep "
        f"at the deepest, on CPU {cpus}. "
        + (
            "An interrupt landed inside this recording, so some of it ran in a context that "
            "cannot sleep."
            if tape.touched_interrupt_context
            else "No interrupt landed inside this recording."
        ),
        "",
        "```",
        tape.tree(),
        "```",
        "",
    ]

    scene = scene_of(tape, max_depth=SCENE_DEPTH)
    if scene.empty:
        return out
    out += [
        "Drawn, this is the tape a lesson shows. Same numbers, same order, same widths, because "
        f"the widget and the animation are handed this arrangement rather than working out one of "
        f"their own. Cut at {SCENE_DEPTH} levels from each outermost call.",
        "",
        f"{scene.alt()} Primitives used: {', '.join(scene.uses())}.",
        "",
        "```",
        scene.table(),
        "```",
        "",
    ]
    return out


def _lockdep_splat_block(path: Path, partner: Path | None = None) -> list[str]:
    """A lock ordering report as a blueprint reads it: who, the cycle, and the stacks behind it.

    The report is very nearly the whole of what this mechanism lets you observe. No counter goes up
    when a cycle is found, no tracepoint fires, and the function that finds it returns into code
    that carries on as if nothing happened. So printing the report back in the shape the parser
    understood it is the section, and it doubles as proof that the shape is understood rather than
    the words being quoted.
    """
    from kxray.lockdep import parse_splat

    splat = parse_splat(path.read_text(encoding="utf-8"))
    cycle = " -> ".join(f"`{name}`" for name in splat.cycle)
    out = [
        f"`{splat.task}` at pid {splat.pid} on kernel {splat.kernel}, holding "
        f"`{splat.holding.name}` and asking for `{splat.acquiring.name}`. "
        f"A cycle of {splat.length}: {cycle}.",
        "",
        "| | Class | Usage | Wait type | Address | Where the report caught it |",
        "|---|---|---|---|---|---|",
    ]
    for role, ref in (("holding", splat.holding), ("acquiring", splat.acquiring)):
        out.append(
            f"| {role} | `{ref.name}` | `{ref.usage}` | `{ref.wait}` | `{ref.address}` "
            f"| `{ref.where}` |"
        )
    out += [
        "",
        "The addresses are printed by the kernel and are not what the report is about. The checker "
        "works in classes, and a class is a line of source rather than an object, so two locks at "
        "two addresses initialised on the same line are one class here.",
        "",
        "The chain, highest number first, which is the order the kernel prints it in. `#0` is the "
        "one being taken at the moment the report is printed.",
        "",
        "| Link | Class | Usage | First recorded at | Frames |",
        "|---|---|---|---|---|",
    ]
    for link in splat.chain:
        where = link.stack[0] if link.stack else "no stack recorded"
        out.append(
            f"| #{link.index} | `{link.name}` | `{link.usage}` | `{where}` | {len(link.stack)} |"
        )
    out.append("")

    if splat.scenario.steps:
        columns = splat.scenario.columns
        out += [
            f"The interleaving the kernel says would deadlock, over {len(columns)} processor(s), "
            f"rebuilt here from the parse rather than copied out of the file.",
            "",
            "```",
        ]
        width = 20
        out.append("".join(name.ljust(width) for name in columns).rstrip())
        out.append("".join(("-" * len(name)).ljust(width) for name in columns).rstrip())
        for column, step in splat.scenario.steps:
            out.append((" " * width * column + step).rstrip())
        out += ["```", ""]

    for link in splat.chain:
        if not link.stack:
            continue
        out += [f"Where `{link.name}` was taken, as `#{link.index}` records it.", "", "```"]
        out += list(link.stack)
        out += ["```", ""]
    return out


def _lockdep_stats_block(path: Path, partner: Path | None = None) -> list[str]:
    """The counters `/proc/lockdep_stats` carries, and what they were on either side of an event.

    Every counter is in the table and none of them is chosen here, because a generator that picks
    the interesting rows is a generator with an opinion, and an opinion in a generated section is
    the thing the seal exists to keep out. The rows that moved are the ones a reader will look at,
    and the change column makes them findable without anything here deciding which they are.
    """
    from kxray.lockdep import account_stats, parse_stats

    def read(one: Path):
        text = one.read_text(encoding="utf-8")
        return parse_stats(text), account_stats(text)

    stats, lines = read(path)
    other, other_lines = read(partner) if partner is not None else (None, None)

    left = path.stem
    right = partner.stem if partner is not None else ""
    counting = (
        f"{len(stats.values)} counter(s) read, {lines.skipped} line(s) skipped, "
        f"{lines.unparsed} line(s) the parser could not read"
    )
    if other is not None:
        counting += (
            f", and {len(other.values)} counter(s), {other_lines.skipped} skipped, "
            f"{other_lines.unparsed} unread in the other"
        )
    out = [counting + ".", ""]

    on = "on, so every lock taken from here is checked"
    gone = "off, so nothing taken from here is checked and there will be no second report"
    out.append(f"`debug_locks` in `{left}` is {stats.debug_locks}, which is the checker {on}.")
    if stats.off:
        out[-1] = f"`debug_locks` in `{left}` is {stats.debug_locks}, which is the checker {gone}."
    if other is not None:
        state = gone if other.off else on
        out.append(f"In `{right}` it is {other.debug_locks}, which is the checker {state}.")
    out.append("")

    later = other.values if other else {}
    names = list(stats.values) + [n for n in later if n not in stats.values]
    if other is None:
        out += ["| Counter | Value | Ceiling |", "|---|---|---|"]
        for name in names:
            out.append(f"| `{name}` | {stats.values[name]} | {_ceiling(stats, name)} |")
        out.append("")
        return out

    out += [f"| Counter | `{left}` | `{right}` | Change | Ceiling |", "|---|---|---|---|---|"]
    for name in names:
        was = stats.values.get(name)
        now = other.values.get(name)
        moved = "" if was is None or now is None else f"{now - was:+d}"
        if moved == "+0":
            moved = "none"
        out.append(
            f"| `{name}` | {'not in this one' if was is None else was} "
            f"| {'not in this one' if now is None else now} | {moved} | {_ceiling(stats, name)} |"
        )
    out.append("")
    return out


def _tracefs_stats_block(path: Path, partner: Path | None = None) -> list[str]:
    """The per CPU ring buffer counters, and the arithmetic that is already in them.

    The three derived lines below are addition and division on numbers that are in the file, and
    nothing is chosen here about which counters matter. They are worked out rather than typed
    because the whole point of this artefact is a ratio, and a reader who has to do the sum by hand
    is a reader who takes the file at face value and reads the trace as if it were complete.
    """
    from kxray.tracefs import account_stats, parse_stats, parse_timestamps, window

    text = path.read_text(encoding="utf-8")
    stats = parse_stats(text)
    lines = account_stats(text)
    clocks = parse_timestamps(text)

    out = [
        f"{len(stats)} counter(s) read, {lines.skipped} line(s) skipped, "
        f"{lines.unparsed} line(s) the parser could not read. The skipped ones are the "
        f"{len(clocks)} clock reading(s) in this file, which are not counts of anything and are "
        "read separately.",
        "",
        "| Counter | Value |",
        "|---|---|",
    ]
    for name, value in stats.items():
        out.append(f"| `{name}` | {value} |")
    for name, reading in clocks.items():
        out.append(f"| `{name}` | {reading:.6f} |")
    out.append("")

    kept = stats.get("entries")
    lost = stats.get("overrun")
    read = stats.get("read events", 0)
    if kept is not None and lost is not None:
        written = kept + lost + read
        out.append(
            f"{written} event(s) were written into this buffer. {kept} are still in it, {lost} "
            f"were thrown away to make room, and {read} have been read out."
        )
        if kept:
            out.append(
                f"That is {lost / kept:.0f} event(s) discarded for every one kept, and "
                f"{lost / written * 100:.1f}% of everything the tracer recorded."
            )
        out.append("")

    held = window(text)
    if held is not None:
        out += [
            f"The oldest event still in the buffer is {held:.6f} second(s) older than the clock "
            "reading taken as the file was read, so that is the whole of the machine's history "
            "this buffer was holding.",
            "",
        ]
    return out


def _ceiling(stats, name: str) -> str:
    """The build time limit on a counter, when the file prints one, as a fraction used.

    Five of the counters come with the maximum the kernel was built for printed beside them, and
    those five are the ones that can run out. The rest have no ceiling to report and say so, which
    is different from having a ceiling nobody measured.
    """
    if name not in stats.maxima:
        return "none printed"
    return f"{stats.maxima[name]}, {stats.headroom(name) * 100:.1f}% used"


# Which of the readers above draws which artefact. The tracer captures are dispatched a few lines
# up on the `tracer` key in their metadata, because that is a fact about how they were taken.
# Everything else in the corpus was taken by reading a file or by copying what the kernel printed,
# and what decides how to draw one of those is which parser understands it, which `kxray` already
# writes down. An artefact whose reader is not in here still gets its heading and its description.
READERS = {
    "lockdep-splat": _lockdep_splat_block,
    "lockdep-stats": _lockdep_stats_block,
    "tracefs-stats": _tracefs_stats_block,
}


# -- section 7, the interfaces -------------------------------------------------------------------


def section_7(request: Request, root: Path, btf_path: Path | None) -> Rendered:
    """The functions and the ops tables, written the way the kernel's own type information has."""
    wanted = request.interfaces + request.ops
    if btf_path is None:
        source = Source("none", "", False, request.pin, request.arch)
        lead = "this mechanism exposes, and that other code calls or fills in"
        return Rendered(_waiting_on_btf(wanted, "interface", lead, source), source)

    from kxray.btf.format import BtfError

    source = btf_source(btf_path, request)
    btf = load_btf(btf_path, request)
    problems: list[str] = []
    out = [source.line(), ""]
    out.append(
        f"Generated by bpc {VERSION} from `{btf_path}`. Signatures are what the kernel's own type "
        f"information records, so a parameter with no name here is a parameter BTF has no name for "
        f"rather than one the blueprint forgot."
    )
    out.append("")
    if not source.evidence:
        out.append(_not_evidence(str(btf_path), meta_for(btf_path)))
        out.append("")

    if request.interfaces:
        out.append("### Functions")
        out.append("")
        out.append("| Symbol | Signature |")
        out.append("|---|---|")
        for name in request.interfaces:
            try:
                out.append(f"| `{name}` | `{btf.signature(name)}` |")
            except (KeyError, BtfError) as problem:
                problems.append(f"section 7: {name}: {problem}")
                # BTF records the functions this build actually emitted. A name missing from it is
                # a real fact about the build rather than a gap in the blueprint, and there are
                # only two ways it happens: the compiler inlined the function away, or the config
                # never compiled it. Which one is a question for the prose, so the table says the
                # thing it knows and leaves the reason to somebody who checked.
                out.append(f"| `{name}` | no symbol in this build, inlined or configured out |")
        out.append("")

    for name in request.ops:
        try:
            table = btf.ops(name)
        except (KeyError, BtfError) as problem:
            problems.append(f"section 7: {name}: {problem}")
            out.append(f"### struct {name}")
            out.append("")
            out.append(f"Not in `{btf_path}`, so there is nothing to generate for it.")
            out.append("")
            continue
        out.extend(_ops_block(table))

    if not wanted:
        out.append(
            "This blueprint names no interfaces in its header, so there is nothing to generate. "
            "Add `interfaces: [function]` and `ops: [struct]` to the header and generate again."
        )
        out.append("")

    return Rendered("\n".join(out).rstrip() + "\n", source, problems)


def _ops_block(table) -> list[str]:
    out = [f"### {table.name}", ""]
    size = "unknown size" if table.size is None else f"{table.size} bytes"
    out.append(
        f"{len(table.slots)} operation(s) and {len(table.data_fields)} data field(s), {size}."
    )
    out.append("")
    out.append("| Offset | Operation | Signature | Filled by |")
    out.append("|---|---|---|---|")
    for slot in table.slots:
        filled = f"`{slot.filled_by}`" if slot.filled else "no instance has been read"
        out.append(f"| {slot.byte_offset} | `{slot.name}` | `{slot.signature}` | {filled} |")
    out.append("")
    if not any(slot.filled for slot in table.slots):
        out.append(
            "Every slot reads as empty because what a function pointer holds is a fact about a "
            "running machine and not about a type. Filling them in needs an instance read out of "
            "a kernel that is running."
        )
        out.append("")
    return out


# -- the shared bits ------------------------------------------------------------------------------


def _waiting_on_btf(names: tuple[str, ...], noun: str, lead: str, source: Source) -> str:
    """The block that gets written when there is no BTF, which is the honest empty state.

    It is not a placeholder in the usual sense. It names every structure the blueprint depends on,
    which is information an implementer wants and which nothing else in the file carries, and it
    says in the file itself that no offsets exist yet.
    """
    out = [source.line(), ""]
    out.append(
        f"Generated by bpc {VERSION} with no BTF to read, so there are no offsets, no sizes and "
        f"no signatures here yet. Building the pinned kernel and running "
        f"`just blueprints-generate` fills this in from the type information that kernel carries "
        f"about itself."
    )
    out.append("")
    if names:
        out.append(f"The {len(names)} {noun}(s) {lead}:")
        out.append("")
        for name in names:
            out.append(f"- `{name}`")
        out.append("")
    else:
        out.append(
            f"This blueprint names no {noun}s in its header, so there would be nothing to "
            f"generate even with a kernel to read."
        )
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _not_evidence(path: str, meta: dict[str, object]) -> str:
    reason = str(meta.get("reason", "")).strip()
    tail = f" {reason}" if reason else ""
    return (
        f"**`{path}` is not evidence.** It was written by hand so the tooling had something to "
        f"work against, so what is below is the shape of a real answer and not a real "
        f"answer.{tail}"
    )


RENDERERS = {2: section_2, 5: section_5, 7: section_7}


def render(
    section: int, request: Request, *, root: Path | str = ".", btf_path: Path | str | None = None
) -> Rendered:
    """Generate one section. `section` is 2, 5 or 7, and nothing else is generated."""
    if section not in RENDERERS:
        raise KeyError(f"section {section} is written by a person, not generated")
    return RENDERERS[section](request, Path(root), Path(btf_path) if btf_path is not None else None)
