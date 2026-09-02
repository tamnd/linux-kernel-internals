"""kxmanim, animations of things that only make sense as sequences.

Most of what a kernel does is a shape, and a shape is better as a diagram or a widget than as a
video. Three things are not shapes. A syscall descending through the layers, a lock being taken
while another CPU waits for it, and a page fault being resolved are all sequences in time, and a
still picture of a sequence in time is a picture with the interesting part missing.

So this package exists for those, and it is deliberately hard to use for anything else. There is a
ninety second budget. Every animation has to name a still picture that makes the same point without
moving, because most readers of the book will never press play, and it has to carry captions and
alt text written by a person.

The nine shapes it draws are not here. They are in `kxshapes`, which `kxwidgets` uses as well, so
that a video of a trace and a widget of the same trace agree box for box rather than each working
the boxes out for themselves.

Two layers, and only the second one needs manim installed:

    storyboard.py   the plan, the rules, the caption track and the transcript
    scene.py        the adapter that hands the numbers to manim

    python3 -m kxmanim --check          check every storyboard, no manim needed
    python3 -m kxmanim --captions out   write the caption tracks and the transcripts
"""

from kxmanim.storyboard import BUDGET_SECONDS, Beat, Storyboard, load_all

__all__ = [
    "BUDGET_SECONDS",
    "Beat",
    "Storyboard",
    "load_all",
]
