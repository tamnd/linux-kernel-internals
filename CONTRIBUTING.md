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

## The notebook contract

Seven rules, checked by `just notebook-contract` and printed by `just notebook-rules`.

1. The banner comes first. The cell after the setup cell is `kxray.banner()`, and nothing runs before it, so a reader always knows which kernel the lesson is about and whether anything below came off a running machine.
2. Nothing a browser cannot finish. No sleeping, no waiting for typing, no installing outside the setup cell, and every `subprocess.run` gets a `timeout`. A cell that hangs looks the same as a cell that is broken.
3. Every code cell has a one line caption. Pass `note=` in the builder. It becomes the caption under the cell on the site, so a cell with no note is a cell that shows up on the site unexplained.
4. No printing what a widget draws. If a parser returns something one of the four widgets renders, hand it to the widget. Printing a field off it is fine.
5. Twenty code cells at most. Markdown does not count, because markdown is not the work. Z02 sits exactly at twenty, so this bites.
6. Evidence comes through the box or a corpus helper. Use `colab.corpus_text` and friends rather than opening a path under `corpora/`, because a reader in Colab has no checkout and the path resolves to nothing.
7. Nothing is written outside `colab.scratch(slug)`. A lesson that leaves files in somebody's working tree has been rude to them.

The checker reads the committed `.ipynb` and never runs it, so it cannot time a cell. Rule 2 is enforced as the constructs that break the ten second budget rather than as the budget itself. That is a real gap and worth knowing about when you write a cell that is slow for some other reason.

## Claims and evidence

Nothing goes in a lesson that the reader cannot watch happen. That is the whole point of the project, and it is the rule most likely to be broken by accident when you are in a hurry.

Every lesson has a `claims.toml` listing what it tells the reader is true and what backs each one. `just claims` checks it, and so does CI. Run `just claim-kinds` to see the kinds of evidence a claim is allowed to rest on:

- a trace, a `/proc` snapshot or a BTF dump committed under `corpora/`
- a citation into the pinned kernel tree, by file and by a piece of text to find in it, never by a line number, so `refcheck` can find it again after it moves
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

Say which kernel, which config and which architecture. A kernel claim without a configuration attached is not a claim, because the same sentence is true on one build and false on another and the reader cannot tell which one they have. Every lesson's `meta.toml` carries `kernel`, `arch`, `profile` and `tier`, the profile has to be one that `kxbox/kernel/pin.toml` actually builds, and the kernel version has to be the one that profile builds. The pinned tree is Linux 7.2.2 and the pinned configs are in `kxbox/kernel/`.

Evidence has to come off the machine the lesson says it does, or the claim has to say why not. Some of the exceptions are permanent and correct. Tier 0 is the browser kernel under v86, which is uniprocessor, 32 bit and has no real clock, so a claim about a second CPU or about how long something takes has to reach for a Tier 1 capture. A lesson about lockdep has to cite captures taken under the `D-lockdep` profile, because lockdep is not compiled into the default one. When that happens, put the reason in a `why_not_pinned` field on the claim, in a sentence. `just claims` checks that the reason is there, and it also checks the other direction: a `why_not_pinned` on a claim whose evidence now matches is an excuse for a problem that went away, and a wrong explanation is worse than none.

## The corpus and the baseline

Everything under `corpora/` is an artefact with a `.meta.toml` beside it saying where it came from. `just baseline` records how much of each one the parsers understand, in `corpora/BASELINE.toml`, and CI fails when any of it moves.

Every line of every artefact goes in one of three buckets. `read` turned into something. `skipped` was never data, so a blank line, a separator, or a header the kernel prints above the rows. `unparsed` was meant to be data and was not understood. The three have to add up to the number of lines in the file, and the tool checks that first, because a reader whose numbers do not add up is counting some lines and forgetting others.

The bucket to watch is not the last one. A rise in `unparsed` is loud and the tests already catch it. The quiet failure is a line sliding from `read` to `skipped`, which is what a regular expression that stopped matching looks like from outside: nothing raises, nothing is logged, and the lesson shows the reader less than it did last week. Run `just baseline-show` to see the table.

If you change a parser or add an artefact, run `just baseline-write` and say in the commit message why a number moved. A number moving on its own is the failure the file exists to catch. Adding an artefact that no reader claims is an error rather than an omission, so add it to the routing table in `tools/baseline.py` at the same time.

## What this project covers

The kernel is around forty million lines, and `drivers/` alone is roughly two thirds of it. Nothing covers all of that, so this project covers a slice and says which one in `coverage.toml`. Every top-level directory of the kernel tree has an entry there, and so does every subsystem inside the ones in scope. Run `just coverage-show` to read it, and `just coverage-cited` to see every kernel path this project cites and which subsystem owns it.

If you cite a file in a subsystem with no entry, CI fails. That is the point of the file. Nobody ever sits down and decides to start covering the network stack. Somebody cites `net/core/dev.c` in a lesson about something else, and a year later there are eleven half taught subsystems and no finished ones.

The ledger is checked in both directions, so an entry has to name every document that cites into it, and every document it names has to cite into it. Widening what a lesson touches means editing `coverage.toml` in the same pull request, which is how the widening gets seen by a reviewer instead of arriving as a citation nobody looked at.

The four statuses have to be earned. `taught` needs a lesson and at least one blueprint marked complete. `partial` needs something written. `mentioned` is for a subsystem you point at on the way past, and it may not name a blueprint. `out-of-scope` needs a reason in a sentence, and nothing may cite into it. Nothing is `taught` yet, because no blueprint is complete yet.

## Writing a blueprint

A blueprint is `blueprints/<name>.md`, copied from `TEMPLATE.md`, and it specifies one mechanism well enough that somebody could implement it without reading the lesson. It never says to see the lesson, and `bpc` fails the build on the phrases people reach for when they are about to break that rule.

You write sections 1, 3, 4, 6, 8 and 9. Sections 2, 5 and 7 are generated by `just blueprints-generate`, which reads the field offsets out of BTF and the observable behaviour out of the trace corpus, and then reseals each block. Do not type inside a sealed block. Two separate checks catch it: the seal hash, and a run of the generator that compares against what is committed, which is what catches an edit that was resealed afterwards.

Every generated block starts with a line saying what it came from and whether that source is evidence. A handwritten fixture is not evidence, and a blueprint with `status: complete` fails the build if any generated section rests on one. A fixture generated field table and a real one look the same on the page, which is exactly why this is checked rather than remembered.

Cite the kernel from the middle of the sentence, like `[page-fault-R13]`, with the entries in `<name>.refs.toml` beside the document. `refcheck` fails on a marker with no entry and on an entry that nothing cites. Anchor on at least twelve characters of text to find, never on a line number.

The notation is all on one page in `blueprints/NOTATION.md`. Six execution contexts, the locking notation, the invariant format, the nine edge case tags and the four diagram styles. A symbol that is not on that page does not go in a blueprint.

## Pictures

There are three ways to draw something here and they are not interchangeable.

A **diagram** is a `*.diagram.py` file in a lesson's `assets/`, and it is the right answer for a shape: how the parts fit together, what points at what, where a boundary is. The `.svg` and `.excalidraw` beside it are output. Every diagram source defines an `ALT` string and the build fails without one.

A **widget** is a class in `kxwidgets/`, and it is the right answer for something a reader wants to look at their own data through. It draws plain HTML with the styling inline, ships no JavaScript, and has to draw itself as text as well, because that text is what a screen reader gets and what a test asserts on.

An **animation** is a storyboard in `kxmanim/storyboards/`, and it is the right answer only for a sequence in time. There are about four of those in the whole book. Before you write one, read the rules in `kxmanim/storyboard.py`, because they are enforced by `just storyboards` and by CI: ninety seconds at most, one idea stated as the title, only the nine shapes from `kxshapes`, a caption and a piece of alt text on every beat, and a still picture that makes the same point without moving. Write the captions and the alt text first. If the alt text is hard to write, the scene is doing two things and the fix is to cut one of them.

All three share one vocabulary, in `kxray/vocabulary.py`. Teal is a filesystem everywhere. The eight layers run top to bottom everywhere. A dashed pointer means no reference is held everywhere. If you need a shape that is not in there, that is a conversation before it is a commit.

Widgets and animations share more than the vocabulary. The nine shapes they are both built out of live in `kxshapes/`, as data rather than as drawing, so a widget of a trace and a video of the same trace agree box for box instead of each working the boxes out on its own. Reach for a shape there before you write layout arithmetic in a renderer. If the shape you want is genuinely not one of the nine, that is the same conversation, because the set is closed and a test asserts the count.

Colour is never the only thing carrying the meaning. Whatever the colour says, the label says too.

## The site

The book is MkDocs with the Material theme, and the lesson pages are the committed notebooks rendered with the output they were committed with. Nothing is executed when the site is built.

```sh
just setup-site
just site-serve
```

`site/head.yml` and the pages in `site/docs/` are yours to edit. `site/mkdocs.yml` is generated, and so is `site/docs/stylesheets/vocabulary.css`. Run `just site` after adding a lesson or a blueprint, and commit what it changes. CI fails when either is out of date, which is what stops a new lesson from being published as a page nobody can reach.

Adding a lesson or a blueprint needs nothing else. The navigation is worked out from what is on disk.

## Pull requests

One idea per pull request. A lesson, a tool, a blueprint, a fix.

Write the body for somebody who has not read the issue. Say what changed, say what you checked, and say what you left undone. The same style rules apply to pull request bodies and issue comments as to lessons.

Lesson identifiers never change. `Z02` is `Z02` forever, because links, graders and the claim ledger all point at it. If a lesson turns out to be two lessons, the second one gets a new identifier at the end of its part.

If your change touches a lesson, run its grader. If it touches a parser, add the input that broke it to `corpora/` as a fixture, so it stays fixed.

## What to work on

The [milestones](https://github.com/tamnd/linux-kernel-internals/milestones) are the plan and each one has an issue with a checklist. Anything in [M0](https://github.com/tamnd/linux-kernel-internals/issues/1) is in flight now. Open questions are tracked with the `kind/open-question` label and are answered as the work reaches them rather than before it starts.

## Licence

Prose and diagrams go in under CC BY-SA 4.0. Tooling goes in under MIT. Anything that links the kernel is GPL-2.0-only, because that is the only option the kernel gives you. By opening a pull request you agree to license your contribution on those terms.
