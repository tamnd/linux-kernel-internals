"""Every page fault, and the small number of questions that decide what happens to it.

A page fault feels like one event with many possible outcomes, and that is the wrong shape to hold
in your head. It is a short chain of questions, always asked in the same order, and each question
either ends the fault or passes it to the next one. Four of the answers end it badly. Four end it
with a page mapped and the instruction restarted.

This is the picture for the blueprint's section 3. The numbered steps there are the same chain in
words, with the citations attached.
"""

from kxdraw import Scene

ALT = (
    "A decision chain running down the left side of the picture with its outcomes on the right. "
    "At the top, a box: hardware traps on vector 14, with the faulting address in CR2 and an "
    "error code. Below it, the first question, is the address in kernel space, with an arrow "
    "right to a red box reading look for a fixup, otherwise oops. Below that, the second "
    "question, is there a VMA covering this address, with an arrow right to a red box reading "
    "SIGSEGV. Below that, the third question, do the VMA flags allow this access, with an arrow "
    "right to the same red SIGSEGV outcome. Below that, a blue box, walk the page tables and look "
    "at the entry, with four arrows leading right to four outcomes stacked vertically: entry "
    "empty and the VMA is anonymous, allocate a folio; entry empty and the VMA is file backed, go "
    "to the page cache; entry holds a swap entry, read it back from disk, which is a major fault; "
    "entry present but read only and this was a write, copy it. Underneath, a note saying the "
    "first three questions are the ones that can end in a signal, and that everything below the "
    "fourth ends with a page mapped and the instruction restarted."
)


def scene() -> Scene:
    s = Scene("What a page fault decides", width=1120, height=760)

    s.note(40, 44, "What a page fault decides", font_size=20)
    s.note(
        40,
        70,
        "The same questions, in the same order, for every fault on x86-64.",
        font_size=13,
        muted=True,
    )

    trap = s.box(
        40,
        104,
        460,
        56,
        "hardware traps on vector 14\nfaulting address in CR2, reason in the error code",
        style="muted",
        font_size=13,
    )

    kernel_space = s.box(
        40, 196, 460, 48, "is the address in kernel space?", style="plain", font_size=14
    )
    oops = s.box(
        640,
        196,
        440,
        48,
        "look for a fixup, otherwise oops",
        style="warn",
        font_size=14,
    )

    has_vma = s.box(
        40, 288, 460, 48, "is there a VMA covering this address?", style="plain", font_size=14
    )
    segv = s.box(640, 288, 440, 48, "SIGSEGV", style="warn", font_size=14)

    allowed = s.box(
        40, 380, 460, 48, "do the VMA flags allow this access?", style="plain", font_size=14
    )

    walk = s.box(
        40,
        472,
        460,
        56,
        "walk the page tables, look at the entry",
        style="accent",
        font_size=14,
    )

    anon = s.box(640, 400, 440, 44, "empty, VMA is anonymous: allocate a folio", font_size=13)
    cache = s.box(
        640, 456, 440, 44, "empty, VMA is file backed: go to the page cache", font_size=13
    )
    swap = s.box(640, 512, 440, 44, "swap entry: read it back in, a major fault", font_size=13)
    cow = s.box(
        640, 568, 440, 44, "present but read only, and this was a write: copy it", font_size=13
    )

    s.arrow(trap, kernel_space)
    s.arrow(kernel_space, oops, label="yes")
    s.arrow(kernel_space, has_vma, label="no")
    s.arrow(has_vma, segv, label="no")
    s.arrow(has_vma, allowed, label="yes")
    s.arrow(allowed, segv, label="no", dashed=True)
    s.arrow(allowed, walk, label="yes")

    for outcome in (anon, cache, swap, cow):
        s.arrow(walk, outcome)

    s.note(
        40,
        640,
        "The first three questions are the only ones that can end in a signal.",
        font_size=14,
    )
    s.note(
        40,
        664,
        "Everything past the fourth ends with a page mapped and the instruction restarted.",
        font_size=14,
    )
    s.note(
        40,
        702,
        "The restart is why a fault is invisible from userspace. The same instruction runs twice "
        "and the second one works.",
        font_size=13,
        muted=True,
    )
    return s
