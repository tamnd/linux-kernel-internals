"""`/proc/version`, taken apart as far as it can honestly be taken apart.

    from kxray.proc import version

    banner = version.parse_file("corpora/proc/tier0/version.txt", "/proc/version")
    print(banner.release, banner.parts, banner.at_least(6, 0))

One line, and everything that reads it reads it with a regex:

    Linux version 7.2.2 (kxbox@kxbox) (i686-linux-gnu-gcc (Debian 14.2.0-19) 14.2.0,
    GNU ld (GNU Binutils for Debian) 2.44) #1 PREEMPT @0

which is one line in the file and is wrapped here to fit.

The release is worth pulling out, because a lesson that says a thing is true of 6.1 and not 5.15
has to be able to check. The build number after the hash is worth pulling out. The bit in the
middle is the user and host that built the kernel and then the entire compiler and linker banner,
which has brackets inside brackets in it, and there is no promise anywhere about its shape. So it
stays as text under `rest`, and anybody who wants the compiler out of it can decide for themselves
how much they trust what they find.

`parts` is the release as a tuple of numbers, which is the only comparison that behaves. String
comparison says 6.9 is newer than 6.10 and it is not. Anything that is not a number ends the
tuple, so `6.1.0-13-amd64` gives `(6, 1, 0)` and a distribution's suffix does not turn into
nonsense.
"""

from __future__ import annotations

import re
from pathlib import Path

from kxray.models import READ, SKIPPED, UNPARSED, Lines, Version
from kxray.proc.stability import classify

# `Linux version <release> <everything else>`. The word Linux is not assumed, because the same
# banner format is used by kernels that call themselves something else and the interesting field
# is the second one either way.
BANNER_RE = re.compile(r"^\S+ version (?P<release>\S+)\s*(?P<rest>.*)$")

# The build count and whatever the build appended to it, which on the pinned kernel is
# `#1 PREEMPT @0`. Its shape is set by the build and is not worth relying on beyond the number.
BUILD_RE = re.compile(r"(#\d+\S*)")


def parse(text: str, path: str = "", source: str = "<text>") -> Version:
    lines = Lines()
    body = ""
    for line in text.splitlines():
        if body or not line.strip():
            lines.count(SKIPPED)
            continue
        body = line

    found = BANNER_RE.match(body) if body else None
    if found is None:
        if body:
            lines.count(UNPARSED)
        return Version(
            source=source,
            path=path,
            promise=classify(path) if path else classify(""),
            lines=lines,
            text=body,
        )

    lines.count(READ)
    build = BUILD_RE.search(found["rest"])
    return Version(
        source=source,
        path=path,
        promise=classify(path) if path else classify(""),
        lines=lines,
        release=found["release"],
        build=build.group(1) if build else "",
        rest=found["rest"].strip(),
        text=body,
    )


def parse_file(path: Path | str, kernel_path: str = "") -> Version:
    found = Path(path)
    return parse(found.read_text(encoding="utf-8"), kernel_path, found.as_posix())


def account(text: str) -> Lines:
    return parse(text).lines


def report(banner: Version) -> str:
    lines = [
        banner.banner(),
        f"release: {banner.release}  {banner.parts}",
        f"build:   {banner.build or 'not printed'}",
        f"rest:    {banner.rest[:60]}{'...' if len(banner.rest) > 60 else ''}",
    ]
    text = "\n".join(lines)
    print(text)
    return text
