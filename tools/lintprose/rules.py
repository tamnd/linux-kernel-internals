"""The rules themselves.

Each rule takes the parsed document and yields findings. Rules only ever look at prose.
Code blocks, front matter, tables and link targets are handed to them already stripped,
because otherwise every rule grows its own set of exceptions and they stop agreeing with
each other about what counts as prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Words that are a small insult to whoever is finding this hard, and in kernel material
# somebody is finding every single thing hard.
DISMISSIVE = [
    "simply",
    "just",
    "obviously",
    "trivially",
    "merely",
    "of course",
    "clearly",
    "straightforward",
    "easy",
    "easily",
]

# Filler that reads like it was generated. None of it survives a careful edit.
FILLER = [
    "it is important to note",
    "it should be noted",
    "it is worth noting",
    "delve",
    "leverage",
    "utilise",
    "utilize",
    "seamless",
    "robust",
    "cutting-edge",
    "in today's world",
    "let's dive in",
    "in conclusion",
]

# Sentences end with one of these. A prose line that ends with anything else, and is
# followed by more prose, has a line break sitting in the middle of a sentence.
SENTENCE_END = tuple(".!?:")

# The markers bpc puts around a generated section of a blueprint.
GENERATED_OPEN = re.compile(r"^<!--\s*bpc:generated\b")
GENERATED_CLOSE = re.compile(r"^<!--\s*bpc:end\b")

WORD_CAPS = {
    "hook": 150,
    "tour": 1500,
    "lesson": 2500,
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.message}"


@dataclass
class Line:
    """One line of a document, with enough context for the rules to judge it."""

    number: int
    text: str
    is_prose: bool


def parse(text: str) -> list[Line]:
    """Split a document into lines and mark which ones are prose.

    Prose means a paragraph or a heading. Front matter, fenced code, indented code,
    tables, HTML comments and reference link definitions are not prose, and no rule
    should ever see them.
    """
    lines = text.split("\n")
    out: list[Line] = []
    in_fence = False
    in_front_matter = False
    in_generated = False
    fence_marker = ""

    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()

        # Front matter, but only when it opens on the very first line.
        if i == 1 and stripped == "---":
            in_front_matter = True
            out.append(Line(i, raw, False))
            continue
        if in_front_matter:
            if stripped == "---":
                in_front_matter = False
            out.append(Line(i, raw, False))
            continue

        # Fenced code, either ``` or ~~~, closed only by the marker that opened it.
        fence = re.match(r"^\s*(`{3,}|~{3,})", raw)
        if fence:
            marker = fence.group(1)[0] * 3
            if not in_fence:
                in_fence = True
                fence_marker = marker
                out.append(Line(i, raw, False))
                continue
            if marker == fence_marker:
                in_fence = False
                out.append(Line(i, raw, False))
                continue
        if in_fence:
            out.append(Line(i, raw, False))
            continue

        # A generated section of a blueprint. Nobody wrote it, so the house style has nothing
        # to say about it, and where the generator puts its line breaks is not a style choice.
        if GENERATED_OPEN.match(stripped):
            in_generated = True
            out.append(Line(i, raw, False))
            continue
        if in_generated:
            if GENERATED_CLOSE.match(stripped):
                in_generated = False
            out.append(Line(i, raw, False))
            continue

        out.append(Line(i, raw, _is_prose(raw, stripped)))

    return out


def _is_prose(raw: str, stripped: str) -> bool:
    """True for a paragraph or a heading, false for everything a rule must not read."""
    if not stripped:
        return False
    if raw.startswith(("    ", "\t")):  # indented code
        return False
    if stripped.startswith("|") or re.match(r"^\|?[\s:|-]+\|[\s:|-]*$", stripped):  # table
        return False
    if stripped.startswith("<!--"):
        return False
    # What is left is a paragraph or a heading, unless it is a reference link definition.
    return re.match(r"^\[[^\]]+\]:\s", stripped) is None


def _prose_only(text: str) -> str:
    """Strip the parts of a line that a word rule should not read.

    Inline code, URLs and link targets carry kernel symbol names and file paths, and
    those legitimately contain words the rules ban.
    """
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\]\([^)]*\)", "] ", text)
    text = re.sub(r"https?://\S+", " ", text)
    return text


def rule_dismissive(path: str, lines: list[Line]) -> list[Finding]:
    """Words that tell a stuck reader the problem is them."""
    found = []
    for ln in lines:
        if not ln.is_prose:
            continue
        text = _prose_only(ln.text).lower()
        for word in DISMISSIVE:
            if re.search(rf"\b{re.escape(word)}\b", text):
                found.append(
                    Finding(
                        path,
                        ln.number,
                        "dismissive",
                        f'"{word}" tells a stuck reader the problem is them',
                    )
                )
    return found


def rule_filler(path: str, lines: list[Line]) -> list[Finding]:
    """Phrases a careful edit would remove, and that read as generated."""
    found = []
    for ln in lines:
        if not ln.is_prose:
            continue
        text = _prose_only(ln.text).lower()
        for phrase in FILLER:
            if phrase in text:
                found.append(
                    Finding(path, ln.number, "filler", f'"{phrase}" does not earn its space')
                )
    return found


def rule_dashes(path: str, lines: list[Line]) -> list[Finding]:
    """Em dashes and en dashes in prose. Use a comma or a full stop."""
    found = []
    for ln in lines:
        if not ln.is_prose:
            continue
        for char, name in (("—", "em dash"), ("–", "en dash")):
            if char in _prose_only(ln.text):
                found.append(
                    Finding(
                        path,
                        ln.number,
                        "dash",
                        f"{name} found, use a comma, a full stop or rewrite the sentence",
                    )
                )
    return found


def rule_mid_sentence_break(path: str, lines: list[Line]) -> list[Finding]:
    """A paragraph is one line. A line break inside a sentence is a diff that reflows.

    Hard wrapping looks tidy in an editor and makes every later edit touch lines that did
    not change, which buries the real change in a pull request.
    """
    found = []
    for idx, ln in enumerate(lines):
        if not ln.is_prose:
            continue
        text = ln.text.rstrip()
        stripped = text.strip()
        if not stripped or stripped.startswith(("#", ">", "-", "*", "+")):
            continue
        if re.match(r"^\d+\.\s", stripped):
            continue
        if text.endswith(SENTENCE_END) or text.endswith(("\\", "|", ")", '"')):
            continue
        nxt = lines[idx + 1] if idx + 1 < len(lines) else None
        if nxt is None or not nxt.is_prose:
            continue
        nxt_stripped = nxt.text.strip()
        if not nxt_stripped or nxt_stripped.startswith(("#", ">", "-", "*", "+", "|")):
            continue
        found.append(
            Finding(
                path,
                ln.number,
                "mid-sentence-break",
                "line break inside a sentence, keep each paragraph on one line",
            )
        )
    return found


def rule_page_break(path: str, lines: list[Line]) -> list[Finding]:
    """Horizontal rules. A section break should be a heading with a name."""
    found = []
    for ln in lines:
        if ln.is_prose and ln.text.strip() in ("---", "***", "___"):
            found.append(
                Finding(
                    path,
                    ln.number,
                    "page-break",
                    "horizontal rule, use a heading so the section has a name",
                )
            )
    return found


def rule_word_cap(path: str, lines: list[Line]) -> list[Finding]:
    """Length caps, per block, for lessons only.

    Blocks are marked with an HTML comment so the cap follows the writing rather than the
    file. A lesson that needs more than the cap is two lessons.
    """
    normalised = path.replace("\\", "/")
    if not (normalised.startswith("lessons/") or "/lessons/" in normalised):
        return []

    found: list[Finding] = []
    block: str | None = None
    start = 0
    words = 0
    total = 0

    def close(end_line: int) -> None:
        nonlocal block, words
        if block and block in WORD_CAPS and words > WORD_CAPS[block]:
            found.append(
                Finding(
                    path,
                    start,
                    "word-cap",
                    f"{block} is {words} words, the cap is {WORD_CAPS[block]}",
                )
            )
        block, words = None, 0

    for ln in lines:
        marker = re.match(r"^\s*<!--\s*block:\s*(\w+)\s*-->\s*$", ln.text)
        if marker:
            close(ln.number)
            block = marker.group(1)
            start = ln.number
            continue
        if ln.is_prose:
            n = len(_prose_only(ln.text).split())
            total += n
            if block:
                words += n
    close(len(lines))

    if total > WORD_CAPS["lesson"]:
        found.append(
            Finding(
                path,
                1,
                "word-cap",
                f"lesson is {total} words, the cap is {WORD_CAPS['lesson']}, split it in two",
            )
        )
    return found


ALL_RULES = [
    rule_dismissive,
    rule_filler,
    rule_dashes,
    rule_mid_sentence_break,
    rule_page_break,
    rule_word_cap,
]


def check_text(text: str, path: str = "<text>") -> list[Finding]:
    lines = parse(text)
    found: list[Finding] = []
    for rule in ALL_RULES:
        found.extend(rule(path, lines))
    return sorted(found, key=lambda f: (f.line, f.rule))


def check_file(path: Path | str) -> list[Finding]:
    p = Path(path)
    return check_text(p.read_text(encoding="utf-8"), str(p))
