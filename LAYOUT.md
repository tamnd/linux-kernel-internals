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
├── kxbox/                   # Tier 0: v86, kernel image, rootfs, the JS bridge
│   ├── vendor/v86/          #   pinned upstream, BSD-2-Clause
│   ├── kernel/              #   pin.toml, config fragments, build.sh, results
│   ├── rootfs/              #   busybox, strace, our tools
│   └── bridge/              #   run a command, read a file, collect a trace
├── kxwidgets/               # anywidget: SyscallTape, StructMap, LockTimeline
├── kxmanim/                 # manim scenes and reusable objects
├── kxdraw/                  # diagrams as code, out to svg and excalidraw
├── lessons/                 # 103 lessons: build.py, its notebook, assets, grader
├── blueprints/              # the normative specifications, and bpc, their generator
├── corpora/                 # pinned traces, BTF dumps, /proc snapshots, oopses
├── capstones/               # three tracks, harnesses and scorecards
├── conformance/             # kxdiff, graders, KUnit and kselftest drivers
├── site/                    # the published book
├── containers/              # the Tier 1 image, devcontainer, CI image
├── tools/                   # lintprose, claimledger, refcheck, bpc, kconfig, nbbuild
└── justfile
```

## Why the split is where it is

The line that matters is the tier boundary. `kxray`, `kxwidgets` and the JavaScript half of `kxbox` have to run in a browser under Pyodide, because that is what makes Tier 0 work with nothing installed. `kxprobe` and the kernel build never can, because one links the kernel and the other is a compiler run.

`kxray` also has to run in Google Colab, which every lesson notebook opens in, so it is installable from the repository with pip and imports without a build step. `kxray.tracefs` is the one module that touches a live machine, and it reads and writes files under `/sys/kernel/tracing` rather than calling anything, which is why it stays in the pure Python half.

That is also why the analysis toolkit is pure Python with no C extensions. It costs some speed and it rules out drgn, which is the tool you would reach for first on a real machine. The trade is worth it, because a reader with no local toolchain can still do the work.

`kxbox/kernel/` is the version and the config, and nothing else. `pin.toml` says which kernel, from which URL, with which checksum, and lists the profiles we build. The `config/` fragments say what each profile turns on. `build.sh` downloads, verifies and builds one profile in a container, and `tools/kconfig` checks the whole lot without a toolchain, so a wrong pin fails CI in seconds instead of an hour into a build.

`corpora/` is committed on purpose. A trace that a lesson depends on is an input to the build, not a scratch file, and a lesson whose evidence is not in the repository is a lesson nobody can check.

Two corpus directories are handwritten and are not evidence. `traces/handwritten/` and `btf/handwritten/` exist so the parsers have something to be tested against before a kernel exists, and both are marked `evidence = false` so the claim checker refuses to let a lesson cite them.

## Where to put a new file

A new parser goes in `kxray/`, with its fixture in `corpora/` and its test in `tests/`.

A new lesson goes in `lessons/<ID>/`, where the identifier comes from the curriculum and never changes. The lesson itself is `build.py`, and the `.ipynb` and `lesson.md` beside it are output, written by `just build-lessons` and checked in CI.

A new diagram goes in that lesson's `assets/` as a file named `*.diagram.py`. The `.svg` and `.excalidraw` beside it are output, written by `just diagrams` and checked in CI, so editing them by hand gets reverted by the next build. Every diagram source has to define an `ALT` string, and the build fails without one.

A new checker goes in `tools/`, with tests, and gets wired into `justfile` and CI in the same pull request. A checker that is not in CI is a suggestion.

A citation into the kernel goes in `refs.toml` beside the lesson, anchored on a piece of text rather than on a line number, and the prose refers to it by identifier. A path into this repository that does not exist yet goes in `refcheck.toml` with a reason.

Anything that has to run inside the kernel goes in `kxprobe/`, and it is GPL-2.0-only with `MODULE_LICENSE("GPL")` at the top. There is no choice about this and no exceptions.
