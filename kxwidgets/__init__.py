"""kxwidgets, the four things a lesson shows a reader.

    from kxwidgets import SyscallTape, StructMap, OpsExplorer, PredictionGate

`SyscallTape` draws a trace. `StructMap` draws a struct. `OpsExplorer` draws a table of function
pointers. `PredictionGate` asks a question and folds the answer away underneath it.

Every one of them renders to plain HTML with the styling inline, and none of them ship a line of
JavaScript. That was a decision and not a shortcut. A lesson exists in four places at once: a
notebook on somebody's laptop, the same notebook in Colab, the committed output on GitHub, and a
page on the published site. A live widget works in the first two and is a blank space in the other
two, and most readers read rather than run. Plain HTML looks the same in all four.

The cost is that nothing here responds to a click except a fold, so anything interactive has to be
a Python call in the next cell. `PredictionGate.check` is that pattern: you commit in code, and
the answer comes back as another widget.

Every widget also draws itself as text, through `.text()` or `str()`. That is the version a screen
reader gets, the version a test asserts on, and the version that shows up in a diff.
"""

from kxwidgets.gate import PredictionGate, Verdict
from kxwidgets.html import Widget, card, page
from kxwidgets.ops import OpsExplorer
from kxwidgets.structmap import StructMap
from kxwidgets.tape import SyscallTape

__all__ = [
    "OpsExplorer",
    "PredictionGate",
    "StructMap",
    "SyscallTape",
    "Verdict",
    "Widget",
    "card",
    "page",
]
