# Notation

One page. Everything a blueprint or a diagram in this project uses to mean something, in one place, so that a symbol never has two meanings and a reader never has to guess.

If you are adding notation, add it here first. A symbol that is not on this page is not allowed in a blueprint, and `bpc` is where that rule will end up once the set stops moving.

## Execution context

Six contexts, and every entry point in a blueprint declares its answer for all six in section 4c. These are the short tags:

| Tag | Context | Can it sleep |
|---|---|---|
| `P` | process context, preemption enabled | yes |
| `PP` | process context, preemption disabled | no |
| `A` | atomic, holding a spinlock | no |
| `SI` | softirq | no |
| `HI` | hardirq | no |
| `NMI` | non maskable interrupt | no, and almost nothing else either |

A blueprint writes `P, SI` to mean the entry point is callable from process context and from softirq context, and from nowhere else.

`PREEMPT_RT` changes the answers, which is why it gets its own line rather than a footnote. On `PREEMPT_RT` a `spin_lock()` sleeps, so code that was `A` on a mainline build is `P` on an RT build, and advice written without saying which build it meant is advice for a kernel the reader may not be running.

## Locking

Written in section 4b, once per field and once per step.

| Notation | Meaning |
|---|---|
| `mmap_lock (w)` | the named lock, held for write |
| `mmap_lock (r)` | the named lock, held for read |
| `rcu` | read side is under `rcu_read_lock()`, writers publish and wait for a grace period |
| `percpu` | protected by being per CPU, with preemption disabled |
| `atomic` | protected by the operation being atomic and nothing else |
| `owner` | one owner at this point in the lifetime, by construction |
| `caller-ref` | protected by a reference the caller is holding |
| `none` | nothing protects it, and that is either a bug or a claim worth defending |

Lock order is written as a chain with `>` meaning taken before: `mmap_lock > i_rwsem > folio_lock`. A blueprint states the order for every pair of locks it takes, because a cycle nobody wrote down is a deadlock nobody predicted.

## Invariants

Every invariant in section 4a is numbered and ends with what enforces it:

```
1. A folio in the page cache carries a reference for the cache itself. [checked: WARN_ON in filemap_remove_folio]
2. The tree and the counter agree at every quiescent point. [unchecked]
```

`[unchecked]` is allowed and is counted. An invariant that nothing enforces is where the next bug lives, so the count goes on the scorecard rather than being an argument in review.

## Edge cases

Section 6 uses a fixed set of tags so that a missing case is visible rather than absent:

`allocation-failure`, `concurrent-entry`, `wrong-context`, `signal`, `object-freed`, `refcount-zero`, `boundary-cases`, `hostile-input`, `bug-message`.

A blueprint at `complete` needs all nine. One at `stub` or `partial` needs whichever it has, and the ones it does not have are visible on the index by their absence.

## Diagrams

Diagrams are built by `kxdraw`, so the notation is the four styles it offers and nothing else.

| Style | Used for |
|---|---|
| `plain` | ordinary kernel structures and functions |
| `accent` | the thing the diagram is about, and the reader's own code |
| `muted` | context, files, and anything the reader is not being asked to look at |
| `warn` | the failure path, and anything that can lose data |

A dashed box means a group rather than an object. A dashed arrow means a path taken later or by somebody else, which is how writeback and workqueue handoffs are drawn. A solid arrow is a call or a data flow in the moment being described, and it is labelled whenever the label is not the obvious one.

Every diagram carries alt text, and the build fails without it.

## References

A blueprint cites the kernel by path and line: `mm/memory.c:5310`. Once `refcheck` is running, each citation also carries a hash of the lines around it, so the build notices when the line moves rather than silently pointing at whatever is there now.

A blueprint never references a lesson. Not "as we saw", not "recall that", not "see the chapter". If an implementer needs it, it goes in the blueprint even if the lesson already said it, and `bpc` fails the build on the phrases.
