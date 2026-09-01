# Contributing

This is a book with a build system attached. Most of the rules below exist because prose rots differently from code, and the only rules worth having are the ones a machine can check.

## Getting set up

You need Python 3.11 or newer, [`uv`](https://github.com/astral-sh/uv) and [`just`](https://github.com/casey/just). Nothing else for the parts that run on a laptop.

```sh
git clone https://github.com/tamnd/linux-kernel-internals
cd linux-kernel-internals
just setup
just check
```

`just check` runs what CI runs, in the same order. If it passes on your machine it passes in CI, and if it does not, the failure you see locally is the failure CI will report.

## The house style

Every rule here is enforced by `tools/lintprose`, so you do not have to remember any of it. Run `just prose` and it will tell you.

**Write like a person who has done the thing.** Plain English. Short sentences. No filler that a careful edit would remove, and no phrasing that sounds like it came out of a text generator.

**No dismissive words.** `simply`, `obviously`, `trivially`, `straightforward` and the rest of the list in `rules.py`. Somebody is stuck on that exact thing right now, and the word tells them the problem is them. This is kernel material, so somebody is stuck on every single thing.

**No em dashes and no en dashes.** Use a comma, use a full stop, or rewrite the sentence.

**One paragraph, one line.** Do not hard wrap. A line break inside a sentence means every later edit touches lines that did not change, which buries the real change in the diff. Let your editor soft wrap.

**No horizontal rules.** If a section needs a break, it needs a heading, and a heading gives it a name and an anchor.

**Length caps.** A lesson hook is at most 150 words, a tour at most 1500, a whole lesson at most 2500. Blocks are marked with an HTML comment so the cap follows the writing rather than the file. A lesson that will not fit is two lessons.

## Writing a lesson

A lesson is `lessons/<ID>/build.py`, and the notebook and the `lesson.md` beside it are output. Edit the builder, run `just build-lessons`, and both get rewritten. CI fails when a committed notebook disagrees with its builder, so never edit the `.ipynb` by hand.

The house style above applies to the markdown cells, because `lintprose` reads the generated `lesson.md` and cannot tell where the words came from. Keep each paragraph on one line inside the builder too. That puts most paragraphs over the Python line length, which is why `lessons/*/build.py` is exempt from that one rule and from nothing else.

Every lesson has to run in Google Colab from the badge at the top with nothing installed. That means the first code cell installs the toolkit, no cell reads a file by a relative path, and any cell that needs a live kernel says what to do when there is not one. `lessons/README.md` has the details.

## Claims and evidence

Nothing goes in a lesson that the reader cannot watch happen. That is the whole point of the project, and it is the rule most likely to be broken by accident when you are in a hurry.

Every lesson has a `claims.toml` listing what it tells the reader is true and what backs each one. `just claims` checks it, and so does CI. Run `just claim-kinds` to see the kinds of evidence a claim is allowed to rest on:

- a trace, a `/proc` snapshot or a BTF dump committed under `corpora/`
- a citation into the pinned kernel tree, by file and line, with a context hash so `refcheck` notices when the line moves
- a litmus test under `tools/memory-model/` with its `herd7` output
- something the reader runs and sees for themselves
- an explicit mark saying no one can observe this, of which a lesson gets at most two

A claim looks like this:

```toml
schema = 1
lesson = "Z02"

[[claims]]
id = "Z02-01"
text = "The kernel writes one line per function entry and one per return."
evidence_kind = "trace"
evidence = "corpora/traces/tier0/write-1byte.txt"
verified = true
```

Two rules in there are worth spelling out. Every artefact under `corpora/` has a `.meta.toml` beside it saying where it came from, and a claim marked `verified = true` against an artefact whose metadata says `evidence = false` is a build failure. That is what keeps a handwritten fixture from turning into a fact. And a lesson whose `meta.toml` says `status = "published"` has to have every claim verified, which is how a draft is allowed to be honest about what is still missing.

Say which kernel, which config and which architecture. A kernel claim without a configuration attached is not a claim. The pinned tree is Linux 7.2.2 and the pinned configs are in `kxbox/kernel/`.

Tier 0 is the browser kernel under v86. It is uniprocessor, it is 32 bit, and its timing is emulated. A claim that depends on real concurrency, on 64 bit layout or on real timing cannot cite Tier 0 evidence, and CI will reject it if it tries.

## Pull requests

One idea per pull request. A lesson, a tool, a blueprint, a fix.

Write the body for somebody who has not read the issue. Say what changed, say what you checked, and say what you left undone. The same style rules apply to pull request bodies and issue comments as to lessons.

Lesson identifiers never change. `Z02` is `Z02` forever, because links, graders and the claim ledger all point at it. If a lesson turns out to be two lessons, the second one gets a new identifier at the end of its part.

If your change touches a lesson, run its grader. If it touches a parser, add the input that broke it to `corpora/` as a fixture, so it stays fixed.

## What to work on

The [milestones](https://github.com/tamnd/linux-kernel-internals/milestones) are the plan and each one has an issue with a checklist. Anything in [M0](https://github.com/tamnd/linux-kernel-internals/issues/1) is in flight now. Open questions are tracked with the `kind/open-question` label and are answered as the work reaches them rather than before it starts.

## Licence

Prose and diagrams go in under CC BY-SA 4.0. Tooling goes in under MIT. Anything that links the kernel is GPL-2.0-only, because that is the only option the kernel gives you. By opening a pull request you agree to license your contribution on those terms.
