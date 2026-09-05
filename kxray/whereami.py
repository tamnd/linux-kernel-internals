"""What is behind this notebook, printed before a reader believes anything it says.

    from kxray import banner

    banner()

This is the first cell of every lesson, and `tools/lintnb` fails a lesson where it is not.

A reader looking at a trace needs to know four things before the trace means anything: which
kernel it is about, whether it came off a running machine or out of a file, what this runtime can
do for them, and which of those two the numbers in front of them came from. Get that wrong and
every conclusion afterwards is wrong in a way that looks fine. Somebody reads a duration off a
replayed capture and believes it is their machine, or reads a one CPU trace and concludes the
kernel does not use more than one.

So the banner says all four, every time, in the same order, and it says which parts are missing
rather than leaving them out. The Tier 0 limits are printed even when Tier 0 is not what is
running, because "uniprocessor, 32 bit x86, emulated timing" is the sentence a reader forgets
first and the one that invalidates the most conclusions.

`kxbox` is imported inside the function rather than at the top. `kxbox` imports `kxray.models`, so
importing it here at module level is a cycle, and it is also a hundred milliseconds a reader pays
whether or not the lesson ever boots a box.

The file is called `whereami` and not `banner` because `kxray.banner` is the function a lesson
calls. A submodule of the same name would take that attribute away from the function the first
time anything imported it, and the second call in a session would fail with a module not being
callable. That is a five minute bug to find and it would find a reader rather than a test.
"""

from __future__ import annotations

import platform
import sys
import tomllib
from pathlib import Path

from kxray import tracefs

PIN = Path("kxbox/kernel/pin.toml")

# What Tier 0 is. Repeated here rather than imported from `kxbox.session`, because the banner has
# to print it even on a machine where booting a box fails.
LIMITS = "uniprocessor, 32 bit x86, emulated timing"


def pinned(root: Path | None = None) -> dict:
    """The kernel this project teaches, out of the pin. Empty when the pin cannot be found."""
    found = _find(PIN, root)
    if found is None:
        return {}
    return tomllib.loads(found.read_text(encoding="utf-8")).get("kernel", {})


def _find(relative: Path, root: Path | None = None) -> Path | None:
    if root is not None:
        return root / relative if (root / relative).exists() else None
    from kxray import colab

    checkout = colab.repo_root()
    if checkout is not None and (checkout / relative).exists():
        return checkout / relative
    return None


def _kernel_line(kernel: dict) -> str:
    if not kernel:
        # A reader who pip installed the package has no checkout and so no pin file. Saying so is
        # better than printing a version this cannot actually stand behind.
        return "kernel:  no pin file here, so this is running outside a checkout"
    version = kernel.get("version", "?")
    moniker = kernel.get("moniker", "")
    released = kernel.get("released", "")
    return f"kernel:  Linux {version}, {moniker}, released {released}"


def _box_lines(profile: str) -> list[str]:
    """What Tier 0 is behind this notebook, or why there is nothing behind it."""
    try:
        import kxbox
    except ImportError as missing:
        return [f"tier 0:  kxbox is not installed here: {missing}"]

    try:
        box = kxbox.boot(profile=profile)
    except Exception as failed:  # noqa: BLE001
        # A banner that raises is worse than a banner that says it could not look. This runs
        # before anything else in a lesson, so it has to survive a runtime it was not written for.
        return [f"tier 0:  could not start a session: {failed}"]

    lines = [f"tier 0:  {LIMITS}"]
    lines += [f"         {one}" for one in box.banner().splitlines()]
    return lines


def _runtime_lines() -> list[str]:
    found = tracefs.find()
    return [
        f"tier 1:  {platform.system()} {platform.release()} on {platform.machine()}, "
        f"Python {sys.version_info.major}.{sys.version_info.minor}",
        f"         tracefs {found.root if found else 'not found'}",
        f"         {tracefs.explain()}",
    ]


def verdict() -> str:
    """One line saying where the numbers in this notebook are about to come from.

    The rest of the banner is facts. This is the sentence a reader in a hurry reads instead, so it
    has to be the one that stops them believing the wrong thing.
    """
    if tracefs.available():
        return "you can capture your own traces here, and the numbers will be yours"
    if tracefs.find() is not None:
        return "tracing is here and not writable, so captures are replays until you are root"
    return "nothing here can trace, so every capture below is one somebody else took"


def text(profile: str = "teaching", root: Path | None = None) -> str:
    """The banner, as a string, for a test or a caption."""
    lines = [
        f"kxray:   {_version()}",
        _kernel_line(pinned(root)),
        *_box_lines(profile),
        *_runtime_lines(),
        f"so:      {verdict()}",
    ]
    return "\n".join(lines)


def _version() -> str:
    from kxray import __version__

    return f"version {__version__}"


def banner(profile: str = "teaching", root: Path | None = None) -> str:
    """Print what is behind this notebook, and hand the same text back."""
    printed = text(profile, root)
    print(printed)
    return printed
