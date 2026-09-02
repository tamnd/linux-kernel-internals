"""Every Tier 0 recipe, run against the kernel in this tab and against the committed recording.

This is the M0 criterion about the emulator being on and off, run in the one place it can honestly
be run. Off a browser there is no emulator for `kxbox.boot()` to find, so both halves come back as
the recording and every recipe matches itself. That reads as a pass and is not one. Here there is
a real kernel behind the first half.

What counts as identical, and what two honest runs are allowed to disagree about, is in
`kxbox/bothways.py`. This file is the part that belongs to the page, and it has one job that file
does not: getting the recordings here.

Python in this tab is Pyodide, and Pyodide has a filesystem of its own with nothing in it. The
project arrives as a wheel, which carries the code and not `corpora/`, so the recordings have to
be fetched over the same server the page came from and written down before anything can read them.
That is what the first half of this does. It is not a copy of the corpus in any lasting sense: it
lives in this tab's memory and it is gone when the tab is closed.

It is also the only cell in this project that boots both backends in one process on purpose. A
lesson gets one box and never knows which kind it is, which is the whole design. This one needs
both, so it is written here rather than being something a lesson could reach by accident.

One recipe per run, picked by `KXBOX_RECIPE_INDEX`, and the page reloads between them so that each
one gets a guest that has just booted. That is not tidiness. Every recording in the corpus was taken
as the first thing a fresh guest did, and running three of them in one boot compares them against a
guest that is not in that state. It shows up in ways that are nothing like obvious: `two-writes`
grew an `inode_update_time` subtree its recording does not have, on exactly the runs where
`write-1byte` had gone first, because whether a write updates a timestamp depends on whether
anything has looked at that timestamp since it was last set.
"""

import json
import os
import tomllib
from pathlib import Path

from pyodide.http import pyfetch

import kxbox.bothways as bothways

# Somewhere with nothing else in it. `repo_root()` finds a checkout by looking for a directory
# called `corpora`, so putting one here is what makes the corpus backend work at all in a tab.
ROOT = Path("/kxbox-checkout")
CORPORA = ROOT / "corpora"
RECIPES = "tier0/recipes.toml"


async def grab(relative: str) -> Path:
    """One file out of `corpora/`, off the server, onto the Pyodide filesystem."""
    answer = await pyfetch(f"/corpora/{relative}")
    if answer.status != 200:
        raise RuntimeError(
            f"corpora/{relative} came back {answer.status}. The page needs the committed "
            "recordings to compare against, and serve.py is what serves them."
        )
    out = CORPORA / relative
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(await answer.bytes())
    return out


async def fetch_corpus() -> list[str]:
    """The recipe list, then every file the recipes in it point at."""
    listing = await grab(RECIPES)
    got = [RECIPES]

    for one in tomllib.loads(listing.read_text(encoding="utf-8")).get("recipes", []):
        wanted = [str(one.get("trace", "")), *(str(v) for v in (one.get("files") or {}).values())]
        for relative in [w for w in wanted if w]:
            await grab(relative)
            # The metadata beside it, because a recording that cannot say whether it is evidence
            # is a recording the banner has to describe as unknown.
            await grab(str(Path(relative).with_suffix(".meta.toml")))
            got.append(relative)
    return got


fetched = await fetch_corpus()
# Which recipe this run is for, by position rather than by name, because the page asks for the
# next one before it has ever seen the list and resolving it here saves reading the recipe list in
# JavaScript as well. Out of range means compare everything, which is what a person running this
# file by hand gets, and it is the wrong thing to do for the reason in the docstring.
every = bothways.names(root=ROOT)
at = int(os.environ.get("KXBOX_RECIPE_INDEX", "-1"))
only = every[at] if 0 <= at < len(every) else None
report = bothways.run(root=ROOT, only=only)

json.dumps(
    {
        "live": report.live,
        # Every recipe there is, not only the one that just ran, so the page knows how many more
        # times to reload itself without having to read the recipe list in JavaScript as well.
        "names": every,
        "only": only or "",
        "why": report.why,
        # None when nothing was compared, which the page keeps as null rather than folding into
        # false. Not measured and measured and wrong are different answers.
        "same": report.same,
        "summary": report.summary(),
        "fetched": len(fetched),
        "recipes": [
            {
                "recipe": one.recipe,
                "same": one.same,
                "error": one.error,
                "differences": list(one.differences),
                "calls": one.calls,
                "emulator": str(one.live) if one.live else "",
                "recording": str(one.replay) if one.replay else "",
            }
            for one in report.comparisons
        ],
    }
)
