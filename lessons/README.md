# Lessons

One directory per lesson, named for its identifier. Identifiers come from the curriculum and never change, because links, graders and the claim ledger all point at them.

```
lessons/Z02/
├── lesson.md        # the prose, in blocks, each with a word cap
├── notebook.py      # the marimo notebook the reader runs
├── claims.toml      # every claim, with the evidence that backs it
├── grader.py        # what has to be true before the lesson is done
└── assets/          # diagrams, animation sources, images
```

## The blocks

A lesson is written in blocks, marked with an HTML comment so the length caps follow the writing rather than the file.

- `hook`, at most 150 words. Why anyone should care, and a question they cannot answer yet.
- `predict`. A guess the reader writes down before running anything.
- `tour`, at most 1500 words. What actually happens, with the evidence beside it.
- `experiment`. The thing they run, and the wrong answers that were tempting.
- `change`. A modification they make, and how they know it worked.

The whole file is capped at 2500 words. A lesson that will not fit is two lessons.

## Nothing here is empty yet

The first three lessons are the M0 pilot, and they exist to find out whether the format works before 100 more get written in it.

- `Z02`, your first trace
- `S05`, the first ops plug
- `C09`, lockdep
