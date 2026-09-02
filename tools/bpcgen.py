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

    for one, path in real:
        out.extend(_artefact_block(one, path, metas[one], root))

    return Rendered("\n".join(out).rstrip() + "\n", source, problems)


def _artefact_block(one: str, path: Path, meta: dict[str, object], root: Path) -> list[str]:
    relative = path.relative_to(root) if path.is_relative_to(root) else path
    out = [f"### `{relative}`", ""]

    tracer = str(meta.get("tracer", "unknown"))
    describes = str(meta.get("describes", "not described"))
    out.append(f"Tracer `{tracer}`, recording {describes}.")
    out.append("")

    if not meta.get("evidence"):
        out.append(_not_evidence(str(relative), meta))
        out.append("")

    if tracer == "function_graph":
        out.extend(_function_graph_block(path))
    return out


def _function_graph_block(path: Path) -> list[str]:
    from kxray.trace import parse_file

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
    return out


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
