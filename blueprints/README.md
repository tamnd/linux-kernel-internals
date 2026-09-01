# Blueprints

A blueprint is a normative specification of one mechanism. You should be able to implement against it without reading the lesson, and no blueprint is allowed to say "see the chapter".

There are 60 of them planned, one per mechanism that a lesson teaches and a capstone depends on.

## The sections

Every blueprint has the same seven sections, in the same order, so a reader who has read one can find anything in any of the others.

1. **Contract.** What the mechanism promises, and to whom.
2. **Structures.** Fields, offsets, types and type tags. Generated from BTF.
3. **States.** What the thing can be, and what moves it between those states.
4. **Concurrency.** Which lock covers which field, what context each entry point runs in, and what is allowed to sleep.
5. **Entry points.** Prototypes and their meaning. Generated from BTF.
6. **Failure.** What goes wrong, what the caller sees, and what gets cleaned up.
7. **Configuration.** Which Kconfig symbols change any of the above. Generated from the tree.

## Generated, not transcribed

Sections 2, 5 and 7 are produced by `bpc`, the blueprint compiler, from the BTF of the pinned kernel and from its Kconfig. Hand editing them fails the build.

This is the point. Field offsets in books about the kernel are wrong within a release or two, and a reader has no way to tell. Here they cannot be stale, because the build reads them out of the same kernel the lessons are traced on.
