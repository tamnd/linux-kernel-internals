"""kxbox, the Tier 0 substrate.

A real Linux kernel in a browser tab, and a recording of one for every machine that has no browser
tab. The two are behind one interface and hand back the same objects, which is what makes the
fallback something the build tests rather than something a README promises.

    import kxbox

    box = kxbox.boot()
    print(box.banner())
    tape = box.trace("write-1byte", lambda: box.sh("dd if=/dev/zero of=/tmp/one bs=1 count=1"))

Set `KXBOX_DISABLE=1` to force the recording. Every lesson has to work that way, and CI runs them
all like that, because the emulator is the part most likely to be missing where a reader is
sitting.
"""

from kxbox.bridge import V86, Unavailable
from kxbox.corpus import Corpus, NotRecorded, Recipe, load_recipes
from kxbox.session import DISABLE, Box, Command, boot, disabled, repo_root

__all__ = [
    "DISABLE",
    "V86",
    "Box",
    "Command",
    "Corpus",
    "NotRecorded",
    "Recipe",
    "Unavailable",
    "boot",
    "disabled",
    "load_recipes",
    "repo_root",
]
