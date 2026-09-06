"""The pinned captures, and the two things everybody wants to do with them.

    from kxray import corpus

    one = corpus.get("traces/tier0/write-1byte")
    print(corpus.read(one).found, "frames")
    print(corpus.normalize.of(one.text()).text)

Everything under `corpora/` is a file that came off a real kernel and is never edited afterwards.
This package is the way in. It does two jobs and they are in two modules because they are used at
different moments.

**Loading**, in `index`. Which reader opens which file, what the file says about itself, and how
much of it the reader understood. Ask by id rather than by path and you do not have to know that a
trace goes through `kxray.trace` and a splat goes through `kxray.lockdep`.

**Normalising**, in `normalize`. Replacing the numbers that came from the run rather than from the
kernel, so that two captures of the same work can be compared. Without it every trace differs from
every other trace and a diff is noise.

The order matters. Load first, normalise second, compare third. Normalising is a text substitution
and knows nothing about what it is looking at, which is what keeps it usable on a file this project
has never seen.
"""

from __future__ import annotations

from kxray.corpus import normalize
from kxray.corpus.index import (
    CORPORA,
    READERS,
    ROUTES,
    Artefact,
    Reading,
    at,
    find,
    get,
    identify,
    read,
    route,
    survey,
)
from kxray.corpus.normalize import Legend, Normalised, of, same

__all__ = [
    "CORPORA",
    "READERS",
    "ROUTES",
    "Artefact",
    "Legend",
    "Normalised",
    "Reading",
    "at",
    "find",
    "get",
    "identify",
    "normalize",
    "of",
    "read",
    "route",
    "same",
    "survey",
]
