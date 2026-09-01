# Blueprints

A blueprint is a normative specification of one mechanism. You should be able to implement against it without reading the lesson, and no blueprint is allowed to point at a lesson.

There are 60 of them planned, one per mechanism that a lesson teaches and a capstone depends on.

## The nine sections

Every blueprint has all nine, in the same order, so a reader who has read one can find anything in any of the others. `bpc` checks that, and `TEMPLATE.md` is the file you copy.

1. **Purpose and boundary.** What this mechanism owns, and the list of what it does not, each pointing at the blueprint that does.
2. **Data structures.** Fields, offsets, sizes and type tags. Generated from BTF.
3. **Algorithms.** What it does, as numbered steps, written for somebody who has never read Linux.
4. **Invariants, locking and context.** Split three ways: 4a invariants and what checks each one, 4b which rule protects every field and in what order locks are taken, 4c which of the six execution contexts each entry point runs in and what changes under `PREEMPT_RT`.
5. **Observable behaviour.** Tracepoints, `/proc` and `/sys` changes, counters, trace frames. Generated from the corpus.
6. **Edge cases and failure modes.** Nine required cases, including the exact text of the `BUG_ON` or `WARN_ON`.
7. **Interfaces.** Prototypes, ops structs, export class, and the userspace visible surface. Generated from BTF and the tree.
8. **Configuration and architecture dependence.** Which `CONFIG_*` symbols change any of the above, and what differs between architectures.
9. **Reimplementation notes.** Which of Linux's choices are forced and which are arbitrary.

Section 4 is why this set has nine sections rather than the seven this file used to list. A kernel mechanism without its concurrency rules is described rather than specified, and splitting invariants from locking from context is what stops the three from being written as one vague paragraph.

## Generated, not transcribed

Sections 2, 5 and 7 are produced by `bpc`, the blueprint compiler, from the BTF of the pinned kernel and from its Kconfig. Hand editing them fails the build.

This is the point. Field offsets in books about the kernel are wrong within a release or two, and a reader has no way to tell. Here they cannot be stale, because the build reads them out of the same kernel the lessons are traced on.

Today `bpc` is version 0.1 and generates nothing, because there is no pinned kernel to read BTF from. What it does now is guard the shape: the nine sections in order, the header fields, an invariant that names what checks it, the nine edge cases on anything marked `complete`, and a seal on each generated section so that a hand edit fails the build. The guard has to exist before the first generated section does, rather than after somebody has already edited one.

## Notation

`NOTATION.md` is the whole notation, on one page. Execution context tags, locking notation, the invariant format, the edge case tags and the diagram styles. A symbol that is not on that page is not allowed in a blueprint.

## The rule with teeth

A blueprint never says to see the lesson. An implementer reading it has not read the lesson and is not going to, so anything they need goes in the blueprint even when the lesson already said it. `bpc` fails the build on the phrases people reach for when they are about to break this rule.
