"""Find a lesson's own files when the lesson is running somewhere that is not a checkout.

    from kxray import colab

    grader = colab.lesson_module("Z02", "grader")
    text = colab.lesson_text("Z02", "claims.toml")
    trace = colab.corpus_text("traces/tier1/multi-cpu-write.txt")

A notebook opened from a Colab badge arrives on its own. The package comes from pip, but a
lesson's grader and its claims live next to the lesson rather than inside the package, on
purpose, because they are part of the lesson and get edited with it. The captures in `corpora/`
are outside the package for the same reason and are wanted for the same reason: a lesson about a
trace nobody can take on their own machine has to be able to show the one somebody did take.

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


def repo_url(relative: str) -> str:
    """The raw URL for a path in the repository, given relative to its root."""
    return f"{RAW}/{REPO}/{BRANCH}/{relative}"


def lesson_url(slug: str, name: str) -> str:
    return repo_url(f"lessons/{slug}/{name}")


def repo_file(relative: str, *, quiet: bool = False) -> Path:
    """The path to one file from the repository, downloading it if there is no checkout."""
    root = repo_root()
    if root is not None:
        local = root / relative
        if local.exists():
            return local

    url = repo_url(relative)
    target = CACHE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        if not quiet:
            print(f"fetching {url}")
        with urllib.request.urlopen(url) as response:  # noqa: S310
            target.write_bytes(response.read())
    return target


def lesson_file(slug: str, name: str, *, quiet: bool = False) -> Path:
    """The path to one file from a lesson, downloading it if there is no checkout."""
    return repo_file(f"lessons/{slug}/{name}", quiet=quiet)


def lesson_text(slug: str, name: str) -> str:
    return lesson_file(slug, name).read_text(encoding="utf-8")


def corpus_file(relative: str, *, quiet: bool = False) -> Path:
    """The path to one committed artefact, given relative to `corpora/`.

        colab.corpus_file("traces/tier0/write-1byte.txt")

    Same arrangement as a lesson's own files and for the same reason. A reader on Tier 0 has one
    CPU and no clock, so there are things they cannot capture no matter how willing they are, and
    the honest answer is to hand them the capture somebody else took along with the metadata
    saying whose machine it came off.
    """
    return repo_file(f"corpora/{relative}", quiet=quiet)


def corpus_text(relative: str, *, quiet: bool = False) -> str:
    return corpus_file(relative, quiet=quiet).read_text(encoding="utf-8")


def scratch(slug: str) -> Path:
    """A directory a lesson may write into, made if it is not there.

        path = colab.scratch("C09") / "abba.c"

    A cell that writes to a bare relative path writes wherever the reader happened to start
    Jupyter, which in a checkout is usually the repository. A lesson that leaves a C file and a
    Makefile in somebody's working tree has done something rude, and a reader who then runs
    `git status` gets a confusing answer to a question they asked about something else.

    So writes go here, under the system temporary directory, one directory per lesson. It survives
    a kernel restart, it is the same path every time so the reader can find what they built, and
    the operating system clears it eventually without anybody having to remember to.
    """
    target = CACHE.parent / f"kxray-scratch-{slug}"
    target.mkdir(parents=True, exist_ok=True)
    return target


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
