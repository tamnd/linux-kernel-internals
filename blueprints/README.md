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

`bpc` is version 0.2 and it does generate. Point it at a BTF blob and section 2 becomes a field table with real offsets, sizes and type tags, and section 7 becomes prototypes and an ops table with a row per slot. Section 5 comes from the trace corpus instead. Run it with no blob and it still writes those sections, but what it writes is the empty state, which names every structure and every interface the mechanism needs and then says plainly that nothing has been read yet.

The empty state used to be what was committed, because no kernel had been built for this project yet. It is not any more. Both blueprints here now carry sections generated from the BTF of the pinned kernel and from captures taken on it, and the provenance line inside each block says so. What the empty state is still for is a blueprint written before its kernel is available, and it exists so that the alternative never gets used, which was to invent a plausible field table. An invented offset in a published blueprint reads exactly like a real one.

### How a generated section says where it came from

The first line inside every generated block is a provenance line:

    <!-- bpc:source kind=btf path=corpora/btf/handwritten/tiny.btf evidence=false pin=v7.2.2 arch=x86_64 -->

It is inside the seal, so it cannot be changed without breaking the hash. `kind` is `btf`, `corpus` or `none`. `evidence` is false when the source is a handwritten fixture rather than something read off a real kernel, and a blueprint with `status: complete` fails the build if any generated section is not evidence. A fixture generated field table and a kernel generated one look identical on the page, so the difference is written down and enforced rather than left to memory.

### Two layers against a hand edit

The seal catches an edit to a generated section. Resealing after an edit defeats the seal, so the plain `bpc` run also regenerates every section into memory and compares. An edit that was resealed still fails, and so does a section whose corpus has moved on underneath it.

## Citations

A blueprint that says something about Linux points at the code it got that from. The marker goes in the middle of the sentence, like `[page-fault-R13]`, and it resolves against `page-fault.refs.toml` sitting beside the document.

Each entry gives a path and an anchor, where the anchor is at least twelve characters of text to find in that file. Never a line number. A line number is right on the day it is typed and wrong after the next patch, and it fails silently, because a stale line number still points at a line.

`refcheck` checks both directions. A marker with no entry fails, and so does an entry that nothing points at, which is nearly always a sentence that got rewritten and quietly lost its evidence.

Unpacking the pinned source with `./kxbox/kernel/tree.sh` and then running `python3 -m tools.refcheck --tree kxbox/kernel/build/tree/linux-7.2.2 --confirm` finds every anchor, writes down the line it landed on and flips `confirmed`. All seventy three citations in this directory are confirmed against 7.2.2. The tree itself is not committed, it takes about 1.6 GB, and `rm -rf kxbox/kernel/build/tree` is how the space comes back.

Two things that confirming has caught so far, both worth expecting. An anchor that names a function which has since moved to another file fails loudly, which is the case this whole arrangement exists for. An anchor that matches in more than one place also fails, and that one is more common than it sounds: a single line of C is rarely unique, and `if (count > MAX_RW_COUNT)` appears three times in `fs/read_write.c` alone. The answer to the second is a longer anchor, and when there is no longer anchor to be had, the answer is to cite the function around it and say in the citations file why.

## Notation

`NOTATION.md` is the whole notation, on one page. Execution context tags, locking notation, the invariant format, the edge case tags and the diagram styles. A symbol that is not on that page is not allowed in a blueprint.

## The rule with teeth

A blueprint never says to see the lesson. An implementer reading it has not read the lesson and is not going to, so anything they need goes in the blueprint even when the lesson already said it. `bpc` fails the build on the phrases people reach for when they are about to break this rule.
