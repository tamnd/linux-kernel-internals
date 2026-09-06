---
blueprint: lock-ordering
title: The lock ordering checker
status: partial
pin: v7.2.2
arch: i386
lessons: []
generated: [2, 5, 7]
config-dependent: [CONFIG_LOCKDEP, CONFIG_PROVE_LOCKING, CONFIG_DEBUG_LOCK_ALLOC, CONFIG_LOCK_STAT, CONFIG_DEBUG_LOCKDEP, CONFIG_LOCKDEP_BITS, CONFIG_LOCKDEP_CHAINS_BITS, CONFIG_LOCKDEP_STACK_TRACE_BITS, CONFIG_LOCKDEP_CIRCULAR_QUEUE_BITS, CONFIG_PREEMPT_RT, CONFIG_PROVE_RAW_LOCK_NESTING, CONFIG_SMP, CONFIG_NR_CPUS]
structures: [lock_class, lockdep_map, held_lock, lock_list, lock_chain, lock_trace, lock_class_key]
interfaces: [lock_acquire, lock_release, lock_sync, lock_is_held_type, lockdep_init_map_type, lockdep_register_key, lockdep_unregister_key, lockdep_set_lock_cmp_fn, lockdep_reset_lock, lock_set_class, lock_downgrade, lock_pin_lock, lock_unpin_lock, lockdep_init_task, debug_check_no_locks_held, lockdep_rcu_suspicious, __lock_acquire, register_lock_class, look_up_lock_class, validate_chain, check_prev_add, check_prevs_add, check_noncircular, __bfs, print_circular_bug, lookup_chain_cache, add_chain_cache, iterate_chain_key, debug_locks_off, lock_acquired, lock_contended]
ops: []
artefacts: [oops/tier0/lockdep-ab-ba, proc/tier0/lockdep-stats-before, proc/tier0/lockdep-stats-after]
---

# The lock ordering checker

**Status is `partial`, and this is what that means here.** All fifty nine citations in `lock-ordering.refs.toml` resolve against the pinned 7.2.2 source and every anchor in it matches exactly one line in the file it names. Sections 2 and 7 come out of the BTF of the `D-lockdep` build, which is the profile that turns this mechanism on, and section 5 comes from three artefacts taken on one boot of that kernel. What is left is a person. `complete` needs a name in `reviewed-by`, and nobody has read this through yet.

One thing about this mechanism is worth saying before anything else, because it is what readers get wrong and it is not a detail. This code does not watch for a deadlock. It never looks at a thread that is waiting, it has no timer, and nothing in it runs when the machine hangs. What it does is keep a directed graph whose nodes are lock classes and whose edges mean this one was held while that one was taken, and every time it is about to add an edge it asks whether that edge would close a cycle. The question is asked during an acquire, on one processor, with nothing waiting for anything at all. That is why a report can arrive from a run that finished perfectly, on a machine with one processor, from two threads that never overlapped in time.

The second thing is the part that costs people an afternoon. The first report of a boot switches the whole mechanism off. Not the reporting, the mechanism. Everything after it is unchecked, and the only place that fact is written down is one line of a `/proc` file.

The picture below is both of those in one frame.

![A picture in three parts. On the left, a small directed graph labelled the lock graph, with two round-cornered nodes, lock_a and lock_b. A solid arrow runs from lock_a down to lock_b labelled held while taking, meaning lock_a was held while lock_b was taken. A dashed arrow runs back up from lock_b to lock_a labelled about to be added, and under it a red box reads that adding this edge closes a cycle, so refuse it, print, and switch off. A note underneath says a node is a lock class, which is a line of source rather than an object, so every mutex initialised on one line is one node here however many of them exist. In the middle, two columns headed first thread and second thread, with five steps in time order reading down: the first thread takes lock_a, takes lock_b, then releases both and exits, and only then the second thread takes lock_b and takes lock_a. A note beside them says both threads ran to the end, neither ever waited for the other, and the report came out anyway, because the cycle is a property of the code and a hang is a property of the timing. On the right, a column of the four things the checker does on every single acquire, in order: find or register the lock class, push it on this task's held lock stack, mix the class index into the chain key, and look the chain key up in the chain cache, with a fifth box below reading that a miss walks the graph backwards looking for a path home. A note says a hit means this exact sequence of held locks has been seen before and nothing below runs, and that this is the whole reason the checker is affordable. Across the bottom is a red band reading that debug_locks goes to 0 on the first report of the boot, and under it two lines saying that from that moment nothing is checked at all, a second bug loaded afterwards is silent, a quiet log means nothing, and the only place it shows is the debug_locks line of /proc/lockdep_stats.](assets/lock-ordering-cycle.svg)

## §1 Purpose and boundary

This mechanism owns the bookkeeping that happens around every lock operation in the kernel and the graph that bookkeeping feeds. It is responsible for turning a lock into a class, remembering which locks a task currently holds and in what order it took them, recording the pairs of classes that have ever been nested, refusing to record a pair that would close a cycle, and printing a report when it refuses.

It deserves a specification of its own because it is the only part of the kernel that is asked to prove something about code it is not running. Everything else in the tree reacts to what happened. This reacts to what could happen on a machine with more processors, different timing and a different scheduler, from evidence gathered on the machine it is actually on. That difference is the source of every surprising thing about it, including the reports with no hang behind them and the silence after the first one.

What it is not responsible for:

- Making locks work. Waiting, wakeups, ownership handoff and the fast paths are each lock type's own mechanism, and this one is called from them rather than being part of them.
- Getting a machine out of a deadlock. Nothing here recovers, retries or breaks a cycle. When the cycle is real and the timing lines up, the machine hangs, and this code is not running when it does.
- Measuring contention. How long a lock was held and how often it was contended is `CONFIG_LOCK_STAT`, which reuses the same hooks and the same classes but answers a different question. Section 8 says what it costs.
- Deciding what is a valid order in the first place. The checker has no rules of its own about which lock should be outermost. It learns the order from whatever the kernel did first and treats every later disagreement as the bug.
- The read side critical section tracking that `lockdep_rcu_suspicious` sits on top of. That is the RCU blueprint. This mechanism supplies the held lock stack it reads and nothing more.
- Interrupt state tracking, which is a second graph problem layered on this one. It is named in section 6 where its report is, and it is a blueprint of its own.
- Anything about how a lock is initialised beyond the key. Which lock types exist and what their fast paths look like belongs with each type.

## §2 Data structures

Generated, and the block below says what from. Hand editing it fails the build.

<!-- bpc:generated section=2 hash=5d332993a32a3e37 -->
<!-- bpc:source kind=btf path=kxbox/kernel/build/D-lockdep/vmlinux evidence=true pin=v7.2.2 arch=i386 -->

Generated by bpc 0.2 from `kxbox/kernel/build/D-lockdep/vmlinux`, for i386 with 4 byte pointers. Offsets are byte offsets from the start of the structure. A hole is padding the compiler inserted and not a field you can use.

### struct lock_class

140 bytes, 26 field(s), 1 bytes of padding in 1 hole(s).

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 8 | `hash_entry` | `struct hlist_node` |
| 0 | 4 | `hash_entry.next` | `struct hlist_node *` |
| 4 | 4 | `hash_entry.pprev` | `struct hlist_node **` |
| 8 | 8 | `lock_entry` | `struct list_head` |
| 8 | 4 | `lock_entry.next` | `struct list_head *` |
| 12 | 4 | `lock_entry.prev` | `struct list_head *` |
| 16 | 8 | `locks_after` | `struct list_head` |
| 16 | 4 | `locks_after.next` | `struct list_head *` |
| 20 | 4 | `locks_after.prev` | `struct list_head *` |
| 24 | 8 | `locks_before` | `struct list_head` |
| 24 | 4 | `locks_before.next` | `struct list_head *` |
| 28 | 4 | `locks_before.prev` | `struct list_head *` |
| 32 | 4 | `key` | `const struct lockdep_subclass_key *` |
| 36 | 4 | `cmp_fn` | `lock_cmp_fn` |
| 40 | 4 | `print_fn` | `lock_print_fn` |
| 44 | 4 | `subclass` | `unsigned int` |
| 48 | 4 | `dep_gen_id` | `unsigned int` |
| 52 | 4 | `usage_mask` | `long unsigned int` |
| 56 | 40 | `usage_traces` | `const struct lock_trace *[10]` |
| 96 | 4 | `name` | `const char *` |
| 100 | 4 | `name_version` | `int` |
| 104 | 1 | `wait_type_inner` | `u8` |
| 105 | 1 | `wait_type_outer` | `u8` |
| 106 | 1 | `lock_type` | `u8` |
| 108 | 16 | `contention_point` | `long unsigned int[4]` |
| 124 | 16 | `contending_point` | `long unsigned int[4]` |

- 1 byte hole at offset 107, after `lock_type`.

### struct lockdep_map

28 bytes, 8 field(s), 1 bytes of padding in 1 hole(s).

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 4 | `key` | `struct lock_class_key *` |
| 4 | 8 | `class_cache` | `struct lock_class *[2]` |
| 12 | 4 | `name` | `const char *` |
| 16 | 1 | `wait_type_outer` | `u8` |
| 17 | 1 | `wait_type_inner` | `u8` |
| 18 | 1 | `lock_type` | `u8` |
| 20 | 4 | `cpu` | `int` |
| 24 | 4 | `ip` | `long unsigned int` |

- 1 byte hole at offset 19, after `lock_type`.

### struct held_lock

44 bytes, 15 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 8 | `prev_chain_key` | `u64` |
| 8 | 4 | `acquire_ip` | `long unsigned int` |
| 12 | 4 | `instance` | `struct lockdep_map *` |
| 16 | 4 | `nest_lock` | `struct lockdep_map *` |
| 20 | 8 | `waittime_stamp` | `u64` |
| 28 | 8 | `holdtime_stamp` | `u64` |
| 36 | 13 bits | `class_idx` | `unsigned int` |
| 37 | 2 bits | `irq_context` | `unsigned int` |
| 37 | 1 bits | `trylock` | `unsigned int` |
| 38 | 2 bits | `read` | `unsigned int` |
| 38 | 1 bits | `check` | `unsigned int` |
| 38 | 1 bits | `hardirqs_off` | `unsigned int` |
| 38 | 1 bits | `sync` | `unsigned int` |
| 38 | 11 bits | `references` | `unsigned int` |
| 40 | 4 | `pin_count` | `unsigned int` |

### struct lock_list

28 bytes, 10 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 8 | `entry` | `struct list_head` |
| 0 | 4 | `entry.next` | `struct list_head *` |
| 4 | 4 | `entry.prev` | `struct list_head *` |
| 8 | 4 | `class` | `struct lock_class *` |
| 12 | 4 | `links_to` | `struct lock_class *` |
| 16 | 4 | `trace` | `const struct lock_trace *` |
| 20 | 2 | `distance` | `u16` |
| 22 | 1 | `dep` | `u8` |
| 23 | 1 | `only_xr` | `u8` |
| 24 | 4 | `parent` | `struct lock_list *` |

### struct lock_chain

20 bytes, 7 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 2 bits | `irq_context` | `unsigned int` |
| 0 | 6 bits | `depth` | `unsigned int` |
| 1 | 24 bits | `base` | `unsigned int` |
| 4 | 8 | `entry` | `struct hlist_node` |
| 4 | 4 | `entry.next` | `struct hlist_node *` |
| 8 | 4 | `entry.pprev` | `struct hlist_node **` |
| 12 | 8 | `chain_key` | `u64` |

### struct lock_trace

16 bytes, 6 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 8 | `hash_entry` | `struct hlist_node` |
| 0 | 4 | `hash_entry.next` | `struct hlist_node *` |
| 4 | 4 | `hash_entry.pprev` | `struct hlist_node **` |
| 8 | 4 | `hash` | `u32` |
| 12 | 4 | `nr_entries` | `u32` |
| 16 | 0 | `entries` | `long unsigned int[0]` |

### struct lock_class_key

8 bytes, 4 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 8 | `hash_entry` | `struct hlist_node` |
| 0 | 4 | `hash_entry.next` | `struct hlist_node *` |
| 0 | 8 | `subkeys` | `struct lockdep_subclass_key[8]` |
| 4 | 4 | `hash_entry.pprev` | `struct hlist_node **` |
<!-- bpc:end section=2 -->

## §3 Algorithms

Numbered from the moment a lock is taken. Steps 1 to 8 run on every acquire of every lock on the machine, and their cost is the cost of running this kernel at all. Steps 9 to 16 run only when step 8 misses, which after boot is rare. Steps 17 to 19 are the report.

1. The lock's own code calls one entry point, and every lock type in the kernel calls the same one [lock-ordering-R13]. Three things happen before any checking. A tracepoint fires, so a tracer can see the acquire whether or not any of this is compiled in. The master switch is tested, and if it is off the function returns immediately, which is the whole of what step 19 leaves behind. Then interrupts are disabled for the rest of the call, because everything below touches data that an interrupt handler taking a lock would re-enter.

2. Read one byte of the lock's own memory on purpose [lock-ordering-R14]. Nothing is done with the value. This is the first thing in the kernel to touch a lock on the way in, so a lock in memory that has already been freed is caught here by the memory checker, which produces a report naming the free, rather than three steps later as a confusing complaint about a key.

3. Find the class this lock belongs to [lock-ordering-R5]. A class is identified by a key, and a key is an address [lock-ordering-R2]. For a lock declared with the usual initialiser macro that address is a static variable the macro created next to the lock, which is why every lock initialised by one line of source is one class no matter how many of them exist [lock-ordering-R1]. That is the single fact behind most of the confusion a first report causes: the two locks named in it may be two of ten thousand objects, and the report is about the line they were created on.

4. Refuse a key that is not in the kernel image or in the per cpu area [lock-ordering-R3]. A key in heap memory could be freed and the address reused for something else, at which point two unrelated locks would silently become one class. A lock that was never initialised at all has no key, and the fallback is to use the lock's own address [lock-ordering-R4], so a statically declared lock that nobody initialised still gets a class of its own.

5. Do the lookup without taking anything [lock-ordering-R6]. This runs on every acquire on every processor, so a lock around it would instantly be the most contended lock in the kernel. It walks a hash table under RCU. Only a miss takes the graph lock and allocates, and the allocation is a pop off a free list filled once at boot [lock-ordering-R7], because this code runs with interrupts off and cannot call the allocator. The pool holds 8192 classes [lock-ordering-R8], and running out of it prints and switches off [lock-ordering-R9] rather than failing the acquire. Two shortcuts sit in front of the lookup: a lock can be given up to eight subclasses [lock-ordering-R10] to tell the checker apart two locks of one class it is legitimately nesting, and the first two subclasses have their class pointer cached in the lock itself [lock-ordering-R11], so everything above subclass 1 pays for the hash walk on every single acquire.

6. Push the lock onto this task's held lock stack [lock-ordering-R12]. The stack is an array inside the task structure, forty eight entries deep [lock-ordering-R58], which is a fixed memory cost on every thread on a kernel built with this on. Going past the end dumps every lock held and switches off [lock-ordering-R57]. The entry is filled in before any checking runs, and one of its fields is the chain key the push is about to displace [lock-ordering-R15], which is how the release path restores the key without recomputing anything.

7. Mix the class into the chain key [lock-ordering-R16]. The chain key is a running hash of every class currently held, in the order they were taken [lock-ordering-R17], and it lives in the task [lock-ordering-R18], so it costs nothing to maintain and needs no lock. An acquire that happens inside an interrupt does not extend the interrupted task's chain, it starts a new one [lock-ordering-R19], because the locks the interrupted code was holding are not locks the handler is nesting inside.

8. Look the chain key up in the chain cache [lock-ordering-R20]. This is the step the whole design is built around. A hit means this exact sequence of held locks, in this exact order, has been validated before, and there is nothing left to do. Everything below is skipped. This is why the cost of the checker falls away as a machine finishes booting instead of growing with its uptime, and it is why the artefacts in section 5 show a machine that has settled at a few thousand chains rather than one still discovering them.

9. On a miss, gate on what kind of acquire this was [lock-ordering-R23]. A `trylock` records nothing, because code that is allowed to fail is allowed to ask in any order it likes. A lock the caller explicitly asked not to be checked records nothing either.

10. Ask the cheap question first: is this class already on this task's own held stack [lock-ordering-R24]. That is a deadlock with one thread and one lock and needs no graph at all. The exception is two read acquires of one reader-writer lock, which is allowed and is why the entry records whether the acquire was for reading [lock-ordering-R25].

11. Check the wait context [lock-ordering-R46], which is the second thing this mechanism does and has nothing to do with ordering. Wait types are an ordered list running from a lock that cannot even be preempted up to one that can sleep [lock-ordering-R48], and the rule is that a lock whose wait type is looser than the tightest one already held is a bug [lock-ordering-R47]. Taking a mutex inside a spinlock is caught here, immediately, without needing a second thread or a second run.

12. Walk out from the innermost held lock and offer each one as the source of a new edge [lock-ordering-R27]. Not every held lock gets an edge to the new one, and the rule for which do is written down where it is applied [lock-ordering-R26]. The walk stops at the first entry that was a `trylock`, which is what keeps the number of edges from growing with the square of the stack depth.

13. For each candidate pair, decide whether to add the edge [lock-ordering-R28]. Before adding it, search the graph for a path that already runs the other way [lock-ordering-R29]. The argument order there is worth reading twice: the search starts at the lock being taken now and looks for the lock already held, which is backwards from the way the edge is described in every sentence around it. The search itself is breadth first [lock-ordering-R31], which is not a performance choice, it is so that the cycle in the report is the shortest one that exists and the report stays small enough to read. Its queue is a fixed size ring [lock-ordering-R32], so the search can also give up, and giving up is a different outcome from finding nothing.

14. Two filters run after the search rather than before it [lock-ordering-R30]. An edge that already exists is not added twice [lock-ordering-R33], and an edge already implied by a path through other edges is not added at all [lock-ordering-R34]. The second one is what keeps the graph from filling up on a machine that has been running for a month.

15. Add the edge, twice [lock-ordering-R35]. Once forwards and once backwards, because both the forward search and the backward search have to be cheap, and the extra memory buys not having a slow direction. The insert is an RCU list add [lock-ordering-R36], so the lockless readers walking the graph never have to be stopped. How many edges fit is a build time choice [lock-ordering-R37], and it is fifteen bits on the profile this blueprint was generated from. Running out prints and switches off [lock-ordering-R38].

16. Record the sequence in the chain cache so it is never checked again [lock-ordering-R21], with its own ceiling and its own way of running out [lock-ordering-R22].

17. When step 13 found a path, print the report [lock-ordering-R39]. The first thing it does, before printing a single character, is switch the mechanism off and release the graph lock in one step [lock-ordering-R41]. That function returns whether this call was the one that did it, and every reporting path in the file is written as a test of it, which is why exactly one report comes out of a boot no matter how many bugs are on the machine.

18. Print the chain highest number first [lock-ordering-R40]. That ordering is decided in the printing rather than anywhere in the data, and it is why `#0` in a report is the lock being taken at the moment the report happened and the highest number is the outermost lock held.

19. Everything after that is the shape of a kernel with the checker off. The bookkeeping in steps 1 to 8 still runs, because the master switch is tested at the top of the entry point and not everywhere, but nothing is validated, no report can be printed, and the counters in section 5 stop moving. The internal limits reached in steps 5, 6, 15 and 16 print their own two line notice instead of a report [lock-ordering-R42], and the second of those two lines is the string to search a log for. The only durable, readable trace of any of this is one line of `/proc/lockdep_stats` [lock-ordering-R43].

The whole graph is protected by one lock, and it is a raw architecture spinlock rather than any of the lock types the kernel offers [lock-ordering-R44]. It has to be [lock-ordering-R45]. Every kernel lock calls into this file on acquire, so a kernel lock used here would call into the code it is protecting, from inside it, with interrupts already off.

## §4 Invariants, locking and context

### §4a Invariants

1. A class key is an address that cannot be freed and reused while the class exists, so two live classes never share a key [lock-ordering-R3]. [checked: `static_obj` refuses a key that is neither in the image nor per cpu, and prints `trying to register non-static key`]
2. The chain key held in a task is the hash of exactly the classes in that task's held lock stack, in the order they were taken [lock-ordering-R15]. [checked: the displaced value is saved in the entry being pushed and restored on release rather than recomputed]
3. A task's held lock stack never has more than `MAX_LOCK_DEPTH` entries in it [lock-ordering-R58] [lock-ordering-R57]. [checked: `BUG_ON` on the depth at the top of the acquire]
4. The dependency graph has no cycle in it at any moment when the checker is on [lock-ordering-R30] [lock-ordering-R35]. [checked: the search runs before the edge is added rather than after]
5. Every edge in the graph is stored in both directions, so the forward and backward searches see the same graph. [checked: two calls to `add_lock_to_list` on the one success path]
6. No two acquires modify the graph at the same time, on any number of processors [lock-ordering-R44]. [checked: the raw spinlock is held across every modification]
7. When the master switch is off, nothing is added to the graph and no report is printed [lock-ordering-R13] [lock-ordering-R41]. [checked: the switch is tested at the top of the entry point, and it is cleared before printing rather than after]
8. At most one report is printed per boot [lock-ordering-R41]. [checked: every report path tests the return of the clear-and-unlock, which is true for exactly one caller]
9. A hit in the chain cache means every pair of classes in that sequence is already an edge in the graph. It follows from steps 12 to 16 running to completion before step 16 records the chain, and nothing verifies it afterwards. [unchecked]
10. Every edge that was added has a stack trace recorded with it [lock-ordering-R59]. [checked: the edge is not added when the trace cannot be saved]

### §4b Locking discipline

What protects each thing this mechanism touches:

| Thing | Protected by |
|---|---|
| the class hash table, for lookup [lock-ordering-R6] | `rcu` |
| the class hash table, for insert [lock-ordering-R7] | `graph_lock` |
| the free list classes are allocated from | `graph_lock` |
| the edge lists that make up the graph, for reading [lock-ordering-R36] | `rcu` |
| the edge lists, for writing [lock-ordering-R35] | `graph_lock` |
| the chain cache | `graph_lock` |
| a task's held lock stack | `owner`, it is inside the task and only that task touches it |
| a task's chain key [lock-ordering-R18] | `owner`, same |
| the two cached class pointers in a lock [lock-ordering-R11] | `none`, defended below |
| the master switch | `atomic`, and it only ever goes one way |
| the breadth first search queue [lock-ordering-R32] | `graph_lock`, it is one shared ring and the search runs under the lock |

The `none` needs its defence. The cached class pointer in a `lockdep_map` can be written by two processors at once, and the write is a single aligned pointer store of a value both of them computed from the same key, so both are writing the same address. Reading a stale null costs one hash lookup and reading the value costs nothing. This is a deliberate unlocked write, not an oversight, and it is the kind of thing that is worth writing down in a specification because a reader will otherwise find it and assume it is a bug.

Acquisition order, written as a chain with `>` meaning taken before:

`(any kernel lock) > graph_lock`

That is the entire order, and it is the reason the graph lock has to be a raw architecture spinlock [lock-ordering-R45]. It is the innermost lock in the kernel by construction. Nothing can be taken while holding it, because taking anything would call back into this file, so there is no second pair to write down.

### §4c Execution context

`lock_acquire` [lock-ordering-R13] is called from everywhere in the kernel, which makes this the shortest table in the project.

| Context | Allowed | What it may do |
|---|---|---|
| `P` | yes | everything below, and this is where nearly all class registration happens |
| `PP` | yes | the same, it disables interrupts itself |
| `A` | yes | the same, and this is the common case inside a spinlock |
| `SI` | yes | the same, with the chain starting fresh [lock-ordering-R19] |
| `HI` | yes | the same |
| `NMI` | yes | the same, and this is the one worth thinking about |

Nothing here sleeps, nothing here allocates, and nothing here takes a lock the kernel would recognise as a lock. That is not a coincidence, it is the specification. Code called from inside every lock acquire in the kernel, including the ones in an interrupt handler, has no context left to be picky about.

The NMI case earns its own paragraph because it looks impossible and is not. An NMI can land while a processor holds the graph lock, and code in that NMI can take a lock and arrive here. The graph lock is a plain spin, so spinning on it from an NMI on the same processor would hang the machine forever. What saves it is that acquiring the graph lock is not a blocking operation in this file: the callers test whether they got it and give up quietly when they did not, so an NMI that arrives at the wrong moment silently records nothing. That is a real hole in coverage, it is accepted deliberately, and it is a good example of what this mechanism trades away to be callable from anywhere.

The `PREEMPT_RT` delta is larger here than in any other blueprint in this project so far, and it runs in the opposite direction to the usual one. On RT a `spin_lock` becomes a sleeping lock, so the wait context rules in step 11 change meaning entirely: a nesting that is legal on a mainline build becomes a bug on an RT build, and the same source file will produce a report on one and silence on the other. `CONFIG_PROVE_RAW_LOCK_NESTING` exists to make a mainline build enforce the RT rules, so that the bug is found by people who are not running RT. Section 8 says what it changes.

## §5 Observable behaviour

Generated, and the block below says what from. Hand editing it fails the build.

<!-- bpc:generated section=5 hash=1b3b45e3e866243e -->
<!-- bpc:source kind=corpus path=corpora evidence=true pin=v7.2.2 arch=i386 -->

Generated by bpc 0.2 from 3 artefact(s) in `corpora/`. Every claim in this section points at a file that can be replayed, which is the difference between a specification of observable behaviour and a description of it.

### `corpora/oops/tier0/lockdep-ab-ba.txt`

Not a trace. Taken by `insmod /lib/modules/abba.ko`, recording a real circular locking dependency report, printed on a run where nothing blocked and nothing waited, taken off the pinned kernel with lockdep in it.

`abba_second` at pid 40 on kernel 7.2.2, holding `lock_b` and asking for `lock_a`. A cycle of 2: `lock_a` -> `lock_b` -> `lock_a`.

| | Class | Usage | Wait type | Address | Where the report caught it |
|---|---|---|---|---|---|
| holding | `lock_b` | `+.+.` | `4:4` | `c78250b8` | `abba_second_thread+0x1e/0x60 [abba]` |
| acquiring | `lock_a` | `+.+.` | `4:4` | `c7825118` | `abba_second_thread+0x2a/0x60 [abba]` |

The addresses are printed by the kernel and are not what the report is about. The checker works in classes, and a class is a line of source rather than an object, so two locks at two addresses initialised on the same line are one class here.

The chain, highest number first, which is the order the kernel prints it in. `#0` is the one being taken at the moment the report is printed.

| Link | Class | Usage | First recorded at | Frames |
|---|---|---|---|---|
| #0 | `lock_a` | `+.+.` | `__lock_acquire+0x165d/0x2740` | 9 |
| #1 | `lock_b` | `+.+.` | `__mutex_lock+0x87/0xd30` | 7 |

The interleaving the kernel says would deadlock, over 2 processor(s), rebuilt here from the parse rather than copied out of the file.

```
CPU0                CPU1
----                ----
lock(lock_b);
                    lock(lock_a);
                    lock(lock_b);
lock(lock_a);
```

Where `lock_a` was taken, as `#0` records it.

```
__lock_acquire+0x165d/0x2740
lock_acquire+0x8c/0x230
__mutex_lock+0x87/0xd30
mutex_lock_nested+0x1a/0x20
abba_second_thread+0x2a/0x60 [abba]
kthread+0xe8/0x130
ret_from_fork+0x20d/0x270
ret_from_fork_asm+0x12/0x20
restore_all_switch_stack+0x0/0x81
```

Where `lock_b` was taken, as `#1` records it.

```
__mutex_lock+0x87/0xd30
mutex_lock_nested+0x1a/0x20
abba_first_thread+0x20/0x50 [abba]
kthread+0xe8/0x130
ret_from_fork+0x20d/0x270
ret_from_fork_asm+0x12/0x20
restore_all_switch_stack+0x0/0x81
```

### `corpora/proc/tier0/lockdep-stats-before.txt` and `corpora/proc/tier0/lockdep-stats-after.txt`

Not a trace. Taken by `cat /proc/lockdep_stats`, recording /proc/lockdep_stats read on a boot that has not had a lockdep report yet, so debug_locks is still one.

51 counter(s) read, 1 line(s) skipped, 0 line(s) the parser could not read, and 51 counter(s), 1 skipped, 0 unread in the other.

`debug_locks` in `lockdep-stats-before` is 1, which is the checker on, so every lock taken from here is checked.
In `lockdep-stats-after` it is 0, which is the checker off, so nothing taken from here is checked and there will be no second report.

| Counter | `lockdep-stats-before` | `lockdep-stats-after` | Change | Ceiling |
|---|---|---|---|---|
| `lock_classes` | 391 | 401 | +10 | 8192, 4.8% used |
| `dynamic_keys` | 44 | 44 | none | none printed |
| `direct_dependencies` | 2268 | 2324 | +56 | 32768, 6.9% used |
| `indirect_dependencies` | 4141 | 4318 | +177 | none printed |
| `all_direct_dependencies` | 19132 | 19732 | +600 | none printed |
| `dependency_chains` | 1949 | 2011 | +62 | 65536, 3.0% used |
| `dependency_chain_hlocks_used` | 5937 | 6101 | +164 | 327680, 1.8% used |
| `dependency_chain_hlocks_lost` | 0 | 0 | none | none printed |
| `in_hardirq_chains` | 24 | 24 | none | none printed |
| `in_softirq_chains` | 40 | 40 | none | none printed |
| `in_process_chains` | 1885 | 1947 | +62 | none printed |
| `stack_trace_entries` | 31181 | 31872 | +691 | 524288, 5.9% used |
| `number_of_stack_traces` | 1560 | 1601 | +41 | none printed |
| `number_of_stack_hash_chains` | 1462 | 1497 | +35 | none printed |
| `combined_max_dependencies` | 1933150 | 1996700 | +63550 | none printed |
| `hardirq_safe_locks` | 25 | 25 | none | none printed |
| `hardirq_unsafe_locks` | 248 | 256 | +8 | none printed |
| `softirq_safe_locks` | 32 | 32 | none | none printed |
| `softirq_unsafe_locks` | 241 | 249 | +8 | none printed |
| `irq_safe_locks` | 43 | 43 | none | none printed |
| `irq_unsafe_locks` | 248 | 256 | +8 | none printed |
| `hardirq_read_safe_locks` | 1 | 1 | none | none printed |
| `hardirq_read_unsafe_locks` | 21 | 23 | +2 | none printed |
| `softirq_read_safe_locks` | 1 | 1 | none | none printed |
| `softirq_read_unsafe_locks` | 21 | 23 | +2 | none printed |
| `irq_read_safe_locks` | 1 | 1 | none | none printed |
| `irq_read_unsafe_locks` | 21 | 23 | +2 | none printed |
| `uncategorized_locks` | 90 | 91 | +1 | none printed |
| `unused_locks` | 1 | 1 | none | none printed |
| `max_locking_depth` | 10 | 10 | none | none printed |
| `max_bfs_queue_depth` | 52 | 52 | none | none printed |
| `max_lock_class_index` | 390 | 400 | +10 | none printed |
| `chain_lookup_misses` | 2060 | 2122 | +62 | none printed |
| `chain_lookup_hits` | 282409 | 289122 | +6713 | none printed |
| `cyclic_checks` | 1775 | 1827 | +52 | none printed |
| `redundant_checks` | 0 | 0 | none | none printed |
| `redundant_links` | 0 | 0 | none | none printed |
| `find_mask_forwards_checks` | 189 | 189 | none | none printed |
| `find_mask_backwards_checks` | 535 | 555 | +20 | none printed |
| `hardirq_on_events` | 147071 | 150692 | +3621 | none printed |
| `hardirq_off_events` | 147070 | 150691 | +3621 | none printed |
| `redundant_hardirq_ons` | 0 | 0 | none | none printed |
| `redundant_hardirq_offs` | 1 | 1 | none | none printed |
| `softirq_on_events` | 515 | 551 | +36 | none printed |
| `softirq_off_events` | 515 | 551 | +36 | none printed |
| `redundant_softirq_ons` | 0 | 0 | none | none printed |
| `redundant_softirq_offs` | 0 | 0 | none | none printed |
| `debug_locks` | 1 | 0 | -1 | none printed |
| `zapped_classes` | 2 | 2 | none | none printed |
| `zapped_lock_chains` | 111 | 111 | none | none printed |
| `large_chain_blocks` | 1 | 1 | none | none printed |
<!-- bpc:end section=5 -->

## §6 Edge cases and failure modes

- **allocation-failure.** Nothing here calls the allocator, so the failure is running out of one of five fixed pools instead. Classes [lock-ordering-R9], edges [lock-ordering-R38], chains [lock-ordering-R22], stack trace storage [lock-ordering-R59] and the held stack depth [lock-ordering-R57] each have a limit and each end the same way, which is that the mechanism switches itself off for the rest of the boot. There is no degraded mode. A kernel that has exhausted any one of them is a kernel with no checking on it, and the way to tell is the first counter in section 5 that is at its ceiling. Four of the five limits are build time choices, so hitting one is usually a reason to rebuild rather than a bug.

- **concurrent-entry.** Every processor is in this code constantly, which is why the read paths are lockless and the write paths take one raw spinlock. Two processors registering the same new class at the same time is resolved by the loser finding the class already present after it takes the lock. Two processors finding two different cycles at the same time is resolved by exactly one of them printing [lock-ordering-R41]. The interesting case is the one that produces no answer at all: a search that cannot get the graph lock records nothing and returns, so on a busy machine a small number of acquires go unchecked, and there is no counter for how many.

- **wrong-context.** There is no wrong context, and that is the specification rather than an accident. The one situation the code cannot handle is an NMI arriving on a processor that already holds the graph lock, and section 4c says what happens then, which is that the acquire is silently not checked.

- **signal.** Nothing here is interruptible and nothing here can be reached from a signal delivery path in a way that matters. The related failure is different and worth naming: a lock still held on the way back to userspace [lock-ordering-R55]. That is checked on the system call exit path, and it catches a class of bug that no acquire would ever see, because the code that leaked the lock has already returned successfully.

- **object-freed.** Two separate cases, and both have their own report. Memory holding a lock that somebody still holds being freed [lock-ordering-R53] is detected because the allocator calls in to ask, so the report comes out of `kfree` and not out of an acquire. A class key being freed is the other one, and it is why step 4 refuses a key that is not in the image, since a freed and reused key would quietly merge two unrelated classes and produce reports that name locks with nothing to do with each other.

- **refcount-zero.** There are no reference counts in this mechanism. Classes are never freed one at a time, only in ranges when a module unloads, and the held lock stack is owned by exactly one task for its whole life. The nearest thing to this failure is a release with no matching acquire [lock-ordering-R54], which is usually a lock taken on one thread and released on another.

- **boundary-cases.** Zero locks held is the normal state and makes step 12 do nothing. One lock held is where the first edges come from. The maximum is forty eight [lock-ordering-R58], and a task that reaches it is almost always in a recursion rather than genuinely holding forty eight locks. On the size of the graph, the boundary that bites first in practice is not the number of classes but the number of edges, because a class is a line of source and there are only so many of those, while edges grow with the ways they get combined.

- **hostile-input.** Nothing here reads anything from userspace, so the input under discussion is the kernel's own behaviour. An unprivileged program can still steer it: a workload that exercises many distinct lock orderings adds edges, and every edge is permanent for the life of the boot. Nothing is ever removed except by module unload. On a kernel built with this on, that is a way for a program to consume a fixed kernel resource until the checker switches itself off, which is one of the several reasons this is a debugging configuration and not a production one.

- **bug-message.** The message this blueprint is mostly about is the circular dependency warning [lock-ordering-R50]. Six others come from the same file and mean quite different things, and telling them apart from the first line is most of the skill. Recursive locking [lock-ordering-R51] is one thread taking one class twice and needs no second thread to reproduce. The interrupt inversion report [lock-ordering-R52] has no cycle in it at all and is about a lock taken with interrupts on that is also taken from a handler. Invalid wait context [lock-ordering-R49] is the step 11 check and is the one that looks least like the others. Held lock freed [lock-ordering-R53], bad unlock balance [lock-ordering-R54] and a lock held returning to userspace [lock-ordering-R55] are each about lifetime rather than order. Suspicious RCU usage [lock-ordering-R56] is a different subsystem borrowing this one's held lock stack to answer a question about read side sections. And the two line notice with `turning off the locking correctness validator` in it [lock-ordering-R42] is not a bug report at all, it is this mechanism saying it has stopped working.

## §7 Interfaces

Generated, and the block below says what from. Hand editing it fails the build.

<!-- bpc:generated section=7 hash=9602468a091e113e -->
<!-- bpc:source kind=btf path=kxbox/kernel/build/D-lockdep/vmlinux evidence=true pin=v7.2.2 arch=i386 -->

Generated by bpc 0.2 from `kxbox/kernel/build/D-lockdep/vmlinux`. Signatures are what the kernel's own type information records, so a parameter with no name here is a parameter BTF has no name for rather than one the blueprint forgot.

### Functions

| Symbol | Signature |
|---|---|
| `lock_acquire` | `static void lock_acquire(struct lockdep_map *lock, unsigned int subclass, int trylock, int read, int check, struct lockdep_map *nest_lock, long unsigned int ip)` |
| `lock_release` | `static void lock_release(struct lockdep_map *lock, long unsigned int ip)` |
| `lock_sync` | `static void lock_sync(struct lockdep_map *lock, unsigned int subclass, int read, int check, struct lockdep_map *nest_lock, long unsigned int ip)` |
| `lock_is_held_type` | `static int lock_is_held_type(const struct lockdep_map *lock, int read)` |
| `lockdep_init_map_type` | `static void lockdep_init_map_type(struct lockdep_map *lock, const char *name, struct lock_class_key *key, int subclass, u8 inner, u8 outer, u8 lock_type)` |
| `lockdep_register_key` | `static void lockdep_register_key(struct lock_class_key *key)` |
| `lockdep_unregister_key` | `static void lockdep_unregister_key(struct lock_class_key *key)` |
| `lockdep_set_lock_cmp_fn` | `static void lockdep_set_lock_cmp_fn(struct lockdep_map *lock, lock_cmp_fn cmp_fn, lock_print_fn print_fn)` |
| `lockdep_reset_lock` | `static void lockdep_reset_lock(struct lockdep_map *lock)` |
| `lock_set_class` | `static void lock_set_class(struct lockdep_map *lock, const char *name, struct lock_class_key *key, unsigned int subclass, long unsigned int ip)` |
| `lock_downgrade` | `static void lock_downgrade(struct lockdep_map *lock, long unsigned int ip)` |
| `lock_pin_lock` | `static struct pin_cookie lock_pin_lock(struct lockdep_map *lock)` |
| `lock_unpin_lock` | `static void lock_unpin_lock(struct lockdep_map *lock, struct pin_cookie cookie)` |
| `lockdep_init_task` | `static void lockdep_init_task(struct task_struct *task)` |
| `debug_check_no_locks_held` | `static void debug_check_no_locks_held(void)` |
| `lockdep_rcu_suspicious` | `static void lockdep_rcu_suspicious(const char *file, const int line, const char *s)` |
| `__lock_acquire` | `static int __lock_acquire(struct lockdep_map *lock, unsigned int subclass, int trylock, int read, int check, int hardirqs_off, struct lockdep_map *nest_lock, long unsigned int ip, int references, int pin_count, int sync)` |
| `register_lock_class` | `static struct lock_class * register_lock_class(struct lockdep_map *lock, unsigned int subclass, int force)` |
| `look_up_lock_class` | `static struct lock_class * look_up_lock_class(const struct lockdep_map *lock, unsigned int subclass)` |
| `validate_chain` | no symbol in this build, inlined or configured out |
| `check_prev_add` | no symbol in this build, inlined or configured out |
| `check_prevs_add` | no symbol in this build, inlined or configured out |
| `check_noncircular` | `static enum bfs_result check_noncircular(struct held_lock *src, struct held_lock *target, const struct lock_trace **trace)` |
| `__bfs` | `static enum bfs_result __bfs(struct lock_list *source_entry, void *data, bool (struct lock_list *, void *) *match, bool (struct lock_list *, void *) *skip, struct lock_list **target_entry, int offset)` |
| `print_circular_bug` | `static void print_circular_bug(struct lock_list *this, struct lock_list *target, struct held_lock *check_src, struct held_lock *check_tgt)` |
| `lookup_chain_cache` | no symbol in this build, inlined or configured out |
| `add_chain_cache` | no symbol in this build, inlined or configured out |
| `iterate_chain_key` | no symbol in this build, inlined or configured out |
| `debug_locks_off` | `static int debug_locks_off(void)` |
| `lock_acquired` | `static void lock_acquired(struct lockdep_map *lock, long unsigned int ip)` |
| `lock_contended` | `static void lock_contended(struct lockdep_map *lock, long unsigned int ip)` |
<!-- bpc:end section=7 -->

## §8 Configuration and architecture dependence

Which symbols change what is written above:

- `CONFIG_LOCKDEP` is the switch for the bookkeeping, which is steps 1 to 8 and the held lock stack in every task. Without it the entry point is an empty inline and forty eight entries come off every thread. Everything in this blueprint requires it.
- `CONFIG_PROVE_LOCKING` is the switch for the checking, which is steps 9 to 18. A kernel with the first and not the second keeps the held lock stack, so `lockdep_assert_held` and the RCU checks still work, and never builds a graph or prints an ordering report. This split is worth knowing because it is what several subsystems actually depend on.
- `CONFIG_DEBUG_LOCK_ALLOC` is what makes each lock type call in on acquire and release at all. It is selected by the two above rather than chosen on its own.
- `CONFIG_LOCK_STAT` adds contention and hold time accounting on the same hooks and the same classes. It is a different question answered by the same plumbing, and it makes every acquire more expensive whether or not anything is contended. The `D-lockdep` profile has it on, which is why the counters in section 5 include rows a `PROVE_LOCKING` only build would not have.
- `CONFIG_DEBUG_LOCKDEP` adds internal self checks and, more usefully, the extra rows in `/proc/lockdep_stats` that report how full each pool is. Without it the artefacts in section 5 would be missing exactly the numbers a reader needs to know whether they are about to run out.
- `CONFIG_LOCKDEP_BITS` [lock-ordering-R37], `CONFIG_LOCKDEP_CHAINS_BITS` and `CONFIG_LOCKDEP_STACK_TRACE_BITS` set three of the five ceilings in section 6. They are powers of two and they cost memory that is allocated at boot whether it is used or not. `CONFIG_LOCKDEP_CIRCULAR_QUEUE_BITS` sets the size of the search queue [lock-ordering-R32], and raising it lets the search run further before giving up on a large graph.
- `CONFIG_PREEMPT_RT` changes the wait type of nearly every lock in the kernel, so it changes which nestings step 11 refuses. `CONFIG_PROVE_RAW_LOCK_NESTING` applies the RT rules on a build that is not RT, which is how those bugs get found by everyone rather than by the few people running RT kernels.
- `CONFIG_SMP` and `CONFIG_NR_CPUS` change nothing about this mechanism, and that is the most important line in this section. The pinned machine has one processor. Every claim in this blueprint, and the report in section 5, was produced on a machine where two threads cannot run at the same time. A checker that needed two processors to find a cycle would be useless, and this one does not, which is why it works at all.

Architecture dependence:

Almost none. The graph, the classes, the chains and the searches are the same code everywhere. The architecture shows through in three places. The graph lock is a raw architecture spinlock [lock-ordering-R44], so it is the architecture's own primitive with nothing on top. The stack traces recorded with each edge come from the architecture's unwinder, and a build with a poor unwinder produces reports whose second half is much less useful. And the pointer size changes every structure in section 2, which on this 32-bit machine makes a `lock_class` 140 bytes where a 64-bit build would be closer to twice that, so the fixed memory this mechanism costs is not a constant across machines.

### The functions section 7 cannot find

Six of the functions named in the header of this blueprint have no symbol in the `D-lockdep` build, and section 7 says so in its table rather than leaving them out. They are `validate_chain`, `check_prev_add`, `check_prevs_add`, `lookup_chain_cache`, `add_chain_cache` and `iterate_chain_key`, which is to say most of steps 7 to 16.

Every one of them is `static` with one caller, in a file the compiler has plenty of freedom in, and there is nothing surprising about the compiler inlining them. The work happens. Steps 7 to 16 run on the machine. There is no symbol, no frame, and no way to attach a tracer to any of them on this build.

This is the second distinct reason a function can be missing from a build and it is worth keeping apart from the first. A symbol can be absent because the configuration removed the code, in which case the work does not happen. A symbol can be absent because the compiler inlined it, in which case the work happens and is unobservable. Both look identical from outside, and the only thing that can tell them apart for a given build is that build. That is the argument for generating section 7 from the kernel's own type information rather than typing a list of function names into a document.

## §9 Reimplementation notes

Forced by the problem rather than by Linux:

- That checking has to happen at acquire time and not at wait time. A deadlock detector that waits for the deadlock finds one bug on one machine with one interleaving, which is worth very little. Any kernel that wants to find ordering bugs before they hang a machine has to check the order at the moment the order is created.
- That there has to be some unit coarser than an object. A graph with one node per lock object on a running kernel would have millions of nodes and would learn nothing, because the two objects that will one day deadlock are usually not the two that were nested during the test run.

Choices Linux made that another kernel could make differently:

- **The class is the initialisation site.** This is the choice everything else follows from, and it is the one that produces confusing reports, because the report names a line and the reader is thinking about an object. A kernel could make the class the type instead, which would be coarser and produce more false reports, or could let each subsystem define its own classes explicitly, which would be more accurate and would need every subsystem to do the work. Linux takes the site for free from a macro and then provides subclasses [lock-ordering-R10] as an escape hatch for the cases where the free answer is wrong. The escape hatch has eight slots and two of them are fast [lock-ordering-R11], which tells you how often it was expected to be needed.

- **Refusing a dynamically allocated key** [lock-ordering-R3]. This is a real restriction and it is why subsystems that create locks at runtime have to register a key separately. A kernel could allow it and track key lifetime with a reference count, which would cost a count on an object that exists in the millions. Linux made the cheap check and pushed the work onto the few subsystems that need it.

- **Switching everything off on the first report** [lock-ordering-R41]. The argument for it is sound: after a cycle is found the graph is known to be wrong, so every later report would be suspect, and a machine that is printing lock reports in a loop with the graph lock involved is a machine nobody can debug. The cost is that finding two bugs takes two boots, and that a clean log is not evidence of anything. A kernel could switch off only the reporting for a class already implicated, or could rate limit rather than stop. There is a good case for both of those, and this blueprint would be shorter if Linux had picked one of them.

- **Never removing anything from the graph.** Edges are permanent for the life of the boot, and removal only happens in bulk when a module unloads. A kernel could age edges out, which would let a long running machine keep checking rather than fill up, at the price of forgetting an ordering it once knew and needing to relearn it. Linux chose to be exactly right about everything it has seen and to stop when it runs out of room.

- **One global lock for the entire graph** [lock-ordering-R44]. On a machine with many processors this is a single point every unlocked acquire has to avoid touching, which is why so much effort went into the lockless read paths and the chain cache. A kernel could partition the graph, but the cycles it is looking for cross partitions by definition, so any partitioning scheme needs a way to search across the pieces and that way is the hard part. Linux made the read path free and accepted a global lock on the rare write path.

- **The chain cache as the affordability mechanism** [lock-ordering-R20]. Everything about the cost profile of this mechanism comes from step 8. Checking is expensive and almost never runs, so the price of the whole thing is a hash, a push and a lookup on each acquire. A kernel could instead cache per pair of classes rather than per sequence, which is a smaller cache with a lower hit rate, or could sample rather than check every acquire, which would be cheaper and would miss orderings that only ever happen once. Caching the whole held sequence is what makes it possible to say that every acquire on the machine was checked, which is a much stronger claim than any sampling scheme can make.
