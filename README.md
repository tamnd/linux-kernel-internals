# linux-kernel-internals

A complete visual teardown of the Linux kernel, taught from zero, with a real kernel booting in your browser.

Status: early. The toolkit and the checkers are being built in the open and the first lesson exists as a draft. The work is laid out in [13 milestones](https://github.com/tamnd/linux-kernel-internals/milestones), starting with [M0](https://github.com/tamnd/linux-kernel-internals/issues/1), which exists to find out whether the central idea works at all.

## The problem

Everything good about learning the Linux kernel is also a reason people give up on it.

The tree is 37 million lines and there is no entry point. There is no `main()` you can usefully step through, and `drivers/` alone is 69 percent of the code. Open the repository and you get a directory listing.

The thing you are studying is also the thing keeping your debugger alive. You cannot put a breakpoint in `schedule()` on your laptop and go make coffee.

It is concurrent from the first function you look at. Not as an advanced topic. The first interesting function is already reentrant, preemptible, callable from an interrupt, and protected by a lock whose rules are written in a comment three files away.

And the standard books are twenty years old. Not stale at the edges, wrong at the centre. Folios, EEVDF, blk-mq, io_uring, eBPF, BTF, MGLRU, PREEMPT_RT, Rust and sched_ext all arrived after them. Work through *Understanding the Linux Kernel* today and you come out with a confident, detailed, obsolete model, which is worse than no model because it resists correction.

The usual result is that people read about the kernel for months, feel like they understand it, and still cannot answer "what happened when I called `write()`" with anything they can check.

## The approach

**A real kernel in a browser tab.** Not a simulation and not a diagram. A real Linux kernel booted under [v86](https://github.com/copy/v86), with `/proc`, `/sys/kernel/tracing`, `dmesg`, `insmod` and a shell. It is self hosted, so there is no third party service to depend on and no rate limit to negotiate. Every lesson has an experiment you run with nothing installed.

**Nothing is asserted that you cannot watch happen.** The kernel exports a live, typed, queryable view of its own running state through five separate mechanisms, so there is very little excuse for an unbacked claim. Every claim in the book is registered in a public ledger with the evidence that backs it, and a lesson is allowed at most two claims that nobody can observe.

**Predict before you look.** Every experiment asks you to guess first, then explains why the wrong answers were tempting. You write one byte. How many bytes reach the disk? Does `read()` on a cached file even enter the kernel? Most experienced programmers get these wrong, and being wrong on the record is what makes the correction stick.

**Concurrency is never deferred.** Every trace carries which CPU it ran on and in which context, from the first lesson. Every structure is introduced together with the rule that protects it. Teaching the sequential story first and adding locks later is how every other introduction does it, and it produces people who think the kernel is a big single threaded program with some locks bolted on.

**Every part ends in a change.** Reading kernel code is not the skill. Changing it and surviving the consequences is. Boss fights are graded by the kernel's own tooling wherever possible: KUnit, kselftest, lockdep, KASAN, sparse, checkpatch, xfstests.

**Say which kernel, which config, which architecture.** On a PREEMPT_RT kernel `spin_lock()` sleeps and half the standard advice inverts. `struct task_struct` is 1,162 lines of declaration and about a third of it is behind `#ifdef`. A kernel claim without a configuration attached is not a claim, and most existing writing about Linux breaks this constantly.

## What gets built

103 lessons across thirteen parts, in three passes over the same ground. See it, understand it, change it. Someone who stops after the first pass has a complete shallow model rather than a deep understanding of the first third and nothing else.

60 blueprints. Each one a normative specification you could implement against without reading the lesson, and none of them allowed to say "see the chapter". The structure sections are generated from BTF, straight out of the running kernel, so the field offsets in this book cannot be stale or wrong.

Three capstones, each with a real external grader that will fail work that only looks correct. A filesystem, judged by xfstests. A device driver, written in C and then again in Rust, judged by the kernel's own debug options and by fault injection. A `sched_ext` scheduler, which you can load on the machine you are sitting at, watch fail, and get your machine back, because the watchdog evicts it. No previous generation of kernel learners could do that last one.

## The lessons

Every lesson is a Jupyter notebook. Click the badge and it opens in Google Colab and runs there with nothing installed, because the first cell installs the toolkit and everything after it is the lesson.

Colab is a real Linux machine, which is what makes this work. A lesson that needs a running kernel prints what your runtime can and cannot do before it asks you to do anything, so you are never following instructions that were never going to work on the machine you are sitting at.

| Lesson | What you come out able to do | Status | Run it |
| --- | --- | --- | --- |
| Z02, your first trace | Turn on `function_graph`, read the output, and know why the indentation belongs to a CPU rather than to the file | draft | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/tamnd/linux-kernel-internals/blob/main/lessons/Z02/Z02.ipynb) |
| S05, the first ops plug | Count the operations tables in your own kernel, and say what chose the code that ran when you wrote a byte | draft | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/tamnd/linux-kernel-internals/blob/main/lessons/S05/S05.ipynb) |
| C09, lockdep | Not started | planned | |

There is also a book, built from the same files, where each lesson page is the notebook with the output it was committed with. It builds in CI on every pull request and it is not published yet, because turning on GitHub Pages is a decision rather than a build step. Until it is, `just setup-site && just site-serve` gives you the whole thing on localhost.

Three lessons is the M0 pilot. They exist to find out whether the format works before 100 more get written in it.

## How a lesson is put together

One directory per lesson, and one file in it that you edit:

```
lessons/Z02/
├── build.py       the lesson itself, prose and cells, the file you edit
├── Z02.ipynb      generated, committed, what the Colab badge opens
├── lesson.md      generated, committed, what you read here on GitHub
├── meta.toml      draft or published, and which kernel, architecture and tier
├── claims.toml    every claim the lesson makes, and the evidence behind it
├── grader.py      what has to be true before the lesson is done
└── assets/        diagrams as Python, with the svg and excalidraw beside them
```

A notebook is JSON with the prose stored as lists of strings. Change one word in a paragraph and the diff is unreadable, so the source is `build.py` and the notebook is output. `just build-lessons` rewrites both outputs, and CI fails when a committed notebook and its builder disagree. The notebook stays committed anyway, because somebody who clicked a badge cannot run a build step first.

Writing a lesson in Python buys two things that hand editing a notebook cannot. The Colab badge is generated from the path the notebook is about to be written to, so it cannot point at the wrong lesson, which is the first mistake anybody makes when copying a lesson. And `lesson.claim("Z02-05")` fetches the claim's own words out of `claims.toml` and records where in the lesson it was made, then the build fails unless the next cell is code and it arrives before the next heading. A lesson cannot assert something and quietly never show it.

## What this will not claim

That it covers the Linux kernel. The coverage ledger will be published as a treemap sized by lines of code, and it will show plainly that most of `drivers/` is out of scope.

That it makes anyone a kernel maintainer. It should make you someone who can trace a system call, read an oops, write a module that survives KASAN and lockdep, and send a patch that will not get laughed at.

That the capstone artifacts are production software. A capstone filesystem is not one to keep anything in.

## Related

Same approach, different subjects: [cpython-internals](https://github.com/tamnd/cpython-internals) and [gcc-internals](https://github.com/tamnd/gcc-internals).

## Licence

Prose and diagrams under CC BY-SA 4.0. Tooling under a permissive licence. Anything that links the kernel is GPL-2.0-only, because that is the only option the kernel gives you.
