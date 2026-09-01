# How to read this

## Three passes over the same ground

The book goes over the kernel three times rather than once, and each pass goes deeper on everything rather than further into a corner.

**Tourist.** See it. You watch the mechanism run and you learn what it looks like from outside. You come out able to recognise it in a trace.

**Mechanic.** Understand it. You read the structures and the algorithm and you learn why it is built the way it is. You come out able to predict what it will do.

**Surgeon.** Change it. You modify it, break it in a way you chose, and survive the consequences. You come out able to work on it.

Somebody who stops after the first pass has a complete shallow model of the whole kernel. That is worth a lot more than a deep understanding of the first third and nothing at all after it, which is what a linear book leaves you with when you put it down.

## Every lesson is a notebook

Click the Colab link on any lesson and it opens on a machine that can run it, with nothing installed. The first cell installs the toolkit and everything after it is the lesson.

Colab is a real Linux machine, which is what makes that work. A lesson that needs a running kernel prints what your runtime can and cannot do before it asks you to do anything, so you are never following instructions that were never going to work where you are sitting.

The page you are reading on this site is the same notebook with the output it was committed with. Nothing is executed when the site is built, because output produced on a build machine is a fact about the build machine.

## Every part ends in a change

Reading kernel code is not the skill. Changing it and surviving the consequences is.

Each part finishes with a boss fight, graded wherever possible by the kernel's own tooling rather than by us: KUnit, kselftest, lockdep, KASAN, sparse, checkpatch, xfstests. A grader that will fail work which only looks correct is worth more than one that agrees with you.

## What the status words mean

A lesson or a blueprint carries a status and it means something specific.

**draft** means written and unverified. The prose is finished and none of its claims have been watched happening. It is published in that state on purpose, because the alternative is a private folder nobody can argue with.

**published** means every claim is verified against evidence that is in the repository.

**stub** and **partial** are the blueprint versions. A blueprint is complete only when its generated sections came from a real build of the pinned kernel and its citations have been resolved against a real tree.

## If you find something wrong

Open an issue. A claim in this book that turns out to be false is the most useful thing anybody can send, because the whole design of the project is an argument that such claims can be caught.
