"""kxray, the analysis toolkit.

Pure Python on purpose, with no C extensions anywhere, because all of it has to run in a browser
under Pyodide. That rules out drgn, which is the tool you would reach for first on a real machine,
and it is still the right trade: a reader with no toolchain installed can do the work.
"""

__version__ = "0.0.0"


def banner(profile: str = "teaching", root=None) -> str:
    """Print what is behind this notebook. The first cell of every lesson.

    Imported inside the call rather than at the top of this file. `kxray.whereami` reaches for
    `kxbox`, `kxbox` reaches back for `kxray.models`, and a module level import here would make
    that a cycle for anybody who imports `kxray` at all.
    """
    from kxray.whereami import banner as printed

    return printed(profile, root)
