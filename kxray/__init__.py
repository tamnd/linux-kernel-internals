"""kxray, the analysis toolkit.

Pure Python on purpose, with no C extensions anywhere, because all of it has to run in a browser
under Pyodide. That rules out drgn, which is the tool you would reach for first on a real machine,
and it is still the right trade: a reader with no toolchain installed can do the work.
"""

__version__ = "0.0.0"
