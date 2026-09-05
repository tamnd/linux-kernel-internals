# Repository layout

What lives where, and why the split falls where it does. Directories appear here before they have anything in them, because the plan is public and it is easier to argue with a plan you can see.

```
linux-kernel-internals/
├── kxray/                   # Python: trace, BTF, /proc and dump analysis
│   ├── btf/                 #   BTF reader: types, fields, offsets, holes, type tags
│   ├── trace/               #   ftrace function_graph and trace_event parsers
│   ├── proc/                #   /proc and /sys snapshot parsers
│   ├── source/              #   kernel tree navigation, Kconfig, MAINTAINERS
│   ├── models/              #   the shared model everything else renders
│   ├── replay/              #   recorded Tier 1 session playback
│   └── corpus/              #   pinned artefacts and the diff normaliser
├── kxprobe/                 # C module and BPF programs. GPL-2.0-only.
│   ├── module/              #   an out of tree module for lessons that need one
│   ├── bpf/                 #   CO-RE programs for what ftrace cannot express
│   └── patches/             #   teaching patches against the pinned tree
├── kxbox/                   # Tier 0: the session, the fallback, v86, the kernel image
│   ├── session.py           #   boot(), the Box, and the banner every lesson prints first
│   ├── corpus.py            #   the recorded backend, which is what CI and most readers get
│   ├── bridge.py            #   the Python half of the conversation with v86
│   ├── web/                 #   the browser half: the channel, the shell protocol, the page
│   ├── web/vendor/v86/      #   pinned upstream by commit and sha256, BSD-2-Clause, not committed
│   ├── kernel/              #   pin.toml, config fragments, build.sh, results
│   └── rootfs/              #   a pinned busybox and a thirty line init
├── kxdiff/                  # comparing two traces: policy.py says what, levels.py says how strictly
├── kxshapes/                # the nine shapes, as data, drawn by both renderers below
├── kxwidgets/               # shapes.py draws the nine, the rest compose them into widgets
├── kxmanim/                 # storyboards, the budget, the manim adapter
│   └── storyboards/         #   one toml per animation, checked in CI
├── kxdraw/                  # diagrams as code, out to svg and excalidraw
├── lessons/                 # 103 lessons: build.py, its notebook, assets, grader
├── blueprints/              # the normative specifications: one .md, one .refs.toml, assets/
├── corpora/                 # pinned traces, BTF dumps, /proc snapshots, oopses
├── capstones/               # three tracks, harnesses and scorecards
├── conformance/             # graders, KUnit and kselftest drivers
├── site/                    # the published book: head.yml, docs/, and the staged copies
├── containers/              # the Tier 1 image, devcontainer, CI image
├── tools/                   # lintprose, claimledger, refcheck, bpc, kconfig, nbbuild, sitebuild
└── justfile
```

## Why the split is where it is

The line that matters is the tier boundary. `kxray`, `kxwidgets` and the JavaScript half of `kxbox` have to run in a browser under Pyodide, because that is what makes Tier 0 work with nothing installed. `kxprobe` and the kernel build never can, because one links the kernel and the other is a compiler run.

`kxray` also has to run in Google Colab, which every lesson notebook opens in, so it is installable from the repository with pip and imports without a build step. `kxray.tracefs` is the one module that touches a live machine, and it reads and writes files under `/sys/kernel/tracing` rather than calling anything, which is why it stays in the pure Python half.

That is also why the analysis toolkit is pure Python with no C extensions. It costs some speed and it rules out drgn, which is the tool you would reach for first on a real machine. The trade is worth it, because a reader with no local toolchain can still do the work.

`kxwidgets/shapes.py` is one HTML renderer per shape and it decides nothing. Colours come from `kxray/vocabulary.py`, geometry comes from `kxshapes`, and what is left is tags and inline styling. Everything else in the package composes those fragments into a widget with a title, a footnote and a text fallback. `RENDERS` is the set of shapes that have a renderer, and a test asserts it is all nine, which is the promise that no lesson ever has to be written around a shape that only exists in one medium.

`kxwidgets/` renders the models and never parses anything. It draws plain HTML with the styling written inline, and it ships no JavaScript at all. That is a decision rather than a shortcut. A lesson exists in four places at once: a notebook on somebody's laptop, the same notebook in Colab, the committed output on GitHub, and a page on the published site. A live widget works in the first two and is a blank space in the other two, and most readers read rather than run. The cost is that nothing responds to a click except a fold, so anything interactive is a Python call in the next cell instead.

`kxwidgets/tapediff.py` is the widget for two traces rather than one, and it works out no verdict of its own. `kxdiff` already answers the two questions that make a comparison repeatable, which are what is being compared and how strictly, so the widget takes a policy and a level and draws the answer. What it adds is the two things a person needs to see rather than read: which functions appear on one side and not the other, ringed on both tapes, and which frames the policy took out of the comparison, drawn faintly rather than removed. A pass over most of a trace and a pass over all of it are different results, and the faint boxes are the difference.

`kxwidgets/locks.py` is the widget that is allowed to say it does not know. A wait of ten microseconds inside `down_write` means somebody was holding the lock on a real machine and means the emulator was slow on Tier 0, and nothing in the trace tells the two apart, so `LockTimeline` takes `timings_are_real` from the capture's `.meta.toml` and refuses to use the word contention until it has been told. That pattern is worth copying. A widget that quietly guesses on the reader's behalf is worse than one with a blank column, because the guess looks exactly like a measurement.

`kxray/vocabulary.py` is the one list of what a shape means. Which colour a subsystem is, which order the eight layers go in, which glyph each of the six execution contexts gets, and what a solid line versus a dashed line promises about a pointer. It sits in `kxray` rather than in a renderer because a colour bound to `fs/` is a fact about the kernel, and because a diagram, a widget and an animation of the same thing have to agree or the reader concludes that one of the three is lying. Colour is never the only channel: everything in that file carries a name as well, and a renderer prints it.

`kxray/layout.py` is the arithmetic that turns a tree of frames into rectangles. It is in `kxray` for the same reason. A widget and an animation of the same trace call it and get the same answer, so the wide box is in the same place in both.

`kxshapes/` is the next step up from that. It is the nine shapes every picture in this book is built out of, held as plain data rather than as drawing: a frame card, a layer band, an object box, a pointer thread, an ops plug, a trace cell, a CPU lane, a context badge and a memory slot. A test asserts there are exactly nine, because a closed set is the point. Each shape works out its own rows, its own labels and its own alt text, and neither renderer is allowed to work any of that out again. It is a package of its own rather than a module inside either renderer, and that is the whole reason it exists. If the arithmetic lived in `kxwidgets` then `kxmanim` would have to redo it, and two renderers doing their own arithmetic are two renderers that can disagree, in the worst possible way, which is that both pictures look fine and one of them is wrong.

`kxdiff/` is two files and the claim that comparing two traces is two questions rather than one. `policy.py` answers what the comparison is about, which means what to leave out before comparing anything: interrupts, work whose presence the clock decides, work the kernel had been putting off, and anything belonging to another task. `levels.py` answers how strictly to compare what is left, and it offers five answers because a claim about the path a system call took and a claim about where its time went are different claims and need different checks. The plan had this under `conformance/`. It is at the top level instead because `kxbox/bothways.py` imports it and that runs in the browser under Pyodide, so it has to be in the wheel, and because the first thing it was used for was checking the emulator against a recording rather than grading anybody's answer.

Keeping the two halves apart is worth the extra file. The code started inside `kxbox/bothways.py` doing both at once, and every time the comparison failed for a boring reason the fix landed in the same function as the rules about what a trace means. After about seven of those nobody could tell which lines were the check and which were the excuses. Every name in `policy.py` now carries the run that put it there, because a list of things to ignore is exactly where a check stops being a check.

`kxmanim/` is for the three or four ideas in the whole book that are sequences in time, and it is deliberately awkward to use for anything else. A beat has to say which of the nine shapes it shows, and a name that is not one of the nine is refused. There is a ninety second budget. Every storyboard has to name a still that makes the same point without moving, and the checker fails when that file is not on disk. Captions and alt text go through the same house style rules the lessons go through. Only `kxmanim/scene.py` imports manim, and it imports it lazily, so the rules run in CI in a fraction of a second while the renderer stays a thing you install on purpose with `just setup-animation`.

`kxbox/kernel/` is the version and the config, and nothing else. `pin.toml` says which kernel, from which URL, with which checksum, and lists the profiles we build. The `config/` fragments say what each profile turns on. `build.sh` downloads, verifies and builds one profile in a container, and `tools/kconfig` checks the whole lot without a toolchain, so a wrong pin fails CI in seconds instead of an hour into a build.

`tools/bpc.py` and `tools/bpcgen.py` are split for one reason. `bpc` is the checker and it runs on every push, so it has to load in a fraction of a second and must not need a BTF reader or a trace parser to answer a question about the shape of a document. `bpcgen` is the generator, and it does need those, so it imports them lazily inside the functions that use them. `bpc` imports `bpcgen` and not the other way round.

`site/` is MkDocs, and it is mostly generated. `head.yml` and the three pages in `site/docs/` are written by hand. `mkdocs.yml` is `head.yml` with a navigation tree appended, worked out from the lessons and blueprints that are on disk, so a lesson cannot be added and left with no page and cannot be removed and leave a dead entry. `site/docs/stylesheets/vocabulary.css` comes out of `kxray/vocabulary.py`, so the site is painted from the same list the diagrams and the widgets read.

The lessons and the blueprints are copied into `site/docs/` at build time and those copies are ignored by git. MkDocs can only see what is under its docs directory, and a file that exists twice in a repository is a file that will disagree with itself.

`kxbox/` has two backends behind one interface and they hand back the same objects. That is not tidiness. A fallback written as a branch gives you one path that runs constantly and one that runs for a reader on a Tuesday, and the second one is the one that will be broken. `box.trace(...)` returns a `kxray.models.Tape` whether it came off a kernel or out of `corpora/tier0/`, so the widget and the blueprint downstream cannot tell which they got. `KXBOX_DISABLE=1` forces the recording and CI runs everything that way.

`kxbox/web/` is split four ways for one reason, which is that only one of the four needs an emulator. `channel.js` is the blocking call and knows there are two threads. `guest.js` builds a line of shell and reads the answer back out of a serial stream, with no state and no emulator in it. `host.js` queues commands onto the one shell the guest has and gives each of them a deadline, and it reaches the emulator through an object with `send` and `listen`, so a test can hand it something else. `page.js` is the wiring.

`kxbox/web/headless.js` boots the same kernel under node instead of on a page, which is what makes a boot something CI and a bisect can do rather than something a person has to click through. It shares `serialFor` and `waitForBoot` with `page.js` and everything below them, so the two ways in can disagree about the machine but not about us.

`kxbox/rootfs/` is the userland the kernel boots into: a pinned busybox and a thirty line init that mounts four filesystems and prints one marker. It stops there on purpose. An init that turns a tracer on behind the reader's back makes every lesson about that tracer a lie.

`kxbox/web/serve.py` is there because a blocking worker needs a `SharedArrayBuffer`, a useful `SharedArrayBuffer` needs the page to be cross origin isolated, and that needs two response headers `python3 -m http.server` does not send. Getting it wrong does not look like a header problem, it looks like the emulator hanging, so the headers have a test.

`corpora/` is committed on purpose. A trace that a lesson depends on is an input to the build, not a scratch file, and a lesson whose evidence is not in the repository is a lesson nobody can check.

Two corpus directories are handwritten and are not evidence. `traces/handwritten/` and `btf/handwritten/` exist so the parsers have something to be tested against before a kernel exists, and both are marked `evidence = false` so the claim checker refuses to let a lesson cite them.

`corpora/traces/tier1/` and `corpora/experiments/tier1/` are the exception to everything else being Tier 0, and the bar for putting something in either is a sentence saying why Tier 0 could not produce it. There are only two such sentences and both are permanent: v86 is a uniprocessor emulator, so nothing about more than one CPU can be shown on it, and it has no real clock, so nothing can be timed on it. A Tier 1 capture comes off whatever machine somebody had rather than off the pinned kernel, so its metadata carries the version, the distribution, the architecture and the CPU count in full.

## Where to put a new file

A new parser goes in `kxray/`, with its fixture in `corpora/` and its test in `tests/`.

A new lesson goes in `lessons/<ID>/`, where the identifier comes from the curriculum and never changes. The lesson itself is `build.py`, and the `.ipynb` and `lesson.md` beside it are output, written by `just build-lessons` and checked in CI.

A new diagram goes in that lesson's `assets/` as a file named `*.diagram.py`. The `.svg` and `.excalidraw` beside it are output, written by `just diagrams` and checked in CI, so editing them by hand gets reverted by the next build. Every diagram source has to define an `ALT` string, and the build fails without one.

A new widget goes in `kxwidgets/`, takes a model out of `kxray.models` or a shape out of `kxshapes` and nothing else, and has to draw itself as text as well as as HTML. The text version is what a screen reader gets and what a test asserts on, so a widget without one is not finished. Add it to the preview page in `kxwidgets/__main__.py` in the same pull request, because a visual thing nobody looks at goes wrong quietly.

A new animation goes in `kxmanim/storyboards/` as a `.toml` file, and it starts at `status = "draft"`, which is a status that refuses to render. Write the beats, the captions and the alt text first and the drawing second. If writing the alt text is hard, the scene is trying to say two things at once and the fix is two scenes or one fewer. The still it names has to exist before the check passes, because most readers of this book will never press play.

A new blueprint goes in `blueprints/` as `<name>.md`, copied from `TEMPLATE.md`, with `<name>.refs.toml` beside it for its citations and any diagrams in `blueprints/assets/`. Write sections 1, 3, 4, 6, 8 and 9 by hand and leave 2, 5 and 7 to `just blueprints-generate`, which fills them from BTF and the corpus and reseals them. Do not type inside a sealed block.

A new Tier 0 recording goes in `corpora/` with its `.meta.toml`, and gets a name in `corpora/tier0/recipes.toml`. The name is what a lesson asks for and what the fallback answers, so a capture that is not listed there is a capture no lesson can reach.

A new checker goes in `tools/`, with tests, and gets wired into `justfile` and CI in the same pull request. A checker that is not in CI is a suggestion.

A citation into the kernel goes in `refs.toml` beside the lesson, or in `<name>.refs.toml` beside the blueprint, anchored on a piece of text rather than on a line number, and the prose refers to it by identifier. A path into this repository that does not exist yet goes in `refcheck.toml` with a reason.

Anything that has to run inside the kernel goes in `kxprobe/`, and it is GPL-2.0-only with `MODULE_LICENSE("GPL")` at the top. There is no choice about this and no exceptions.
