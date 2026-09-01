"""Find a lesson's own files when the lesson is running somewhere that is not a checkout.

    from kxray import colab

    grader = colab.lesson_module("Z02", "grader")
    text = colab.lesson_text("Z02", "claims.toml")

A notebook opened from a Colab badge arrives on its own. The package comes from pip, but a
lesson's grader and its claims live next to the lesson rather than inside the package, on
purpose, because they are part of the lesson and get edited with it.

So this looks in a checkout first and falls back to downloading from the repository. On your
laptop you get the file you are editing. In Colab you get the one on the default branch, and the
URL it came from is printed, because a notebook that quietly downloads and runs code is a
notebook you should not trust.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import urllib.request
from pathlib import Path
from types import ModuleType

REPO = "tamnd/linux-kernel-internals"
BRANCH = "main"
RAW = "https://raw.githubusercontent.com"

CACHE = Path(tempfile.gettempdir()) / "kxray-lessons"


def in_colab() -> bool:
    return "google.colab" in sys.modules


def repo_root() -> Path | None:
    """The checkout this is running inside, or None.

    A directory counts when it has both `lessons/` and `pyproject.toml`, so a stray `lessons`
    folder somewhere above your working directory does not get mistaken for the repository.
    """
    starts = [Path.cwd(), Path(__file__).resolve().parent]
    for start in starts:
        for directory in [start, *start.resolve().parents]:
            if (directory / "lessons").is_dir() and (directory / "pyproject.toml").is_file():
                return directory
    return None


def lesson_url(slug: str, name: str) -> str:
    return f"{RAW}/{REPO}/{BRANCH}/lessons/{slug}/{name}"


def lesson_file(slug: str, name: str, *, quiet: bool = False) -> Path:
    """The path to one file from a lesson, downloading it if there is no checkout."""
    root = repo_root()
    if root is not None:
        local = root / "lessons" / slug / name
        if local.exists():
            return local

    url = lesson_url(slug, name)
    target = CACHE / slug / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        if not quiet:
            print(f"fetching {url}")
        with urllib.request.urlopen(url) as response:  # noqa: S310
            target.write_bytes(response.read())
    return target


def lesson_text(slug: str, name: str) -> str:
    return lesson_file(slug, name).read_text(encoding="utf-8")


def lesson_module(slug: str, name: str) -> ModuleType:
    """Import a Python file from a lesson directory, by lesson and stem.

    The module goes into `sys.modules` before it runs. A dataclass declared inside it looks
    itself up there while the class body is being executed, so leaving that out gives you an
    AttributeError from inside the standard library with nothing pointing back to here.
    """
    path = lesson_file(slug, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"lesson_{slug}_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
