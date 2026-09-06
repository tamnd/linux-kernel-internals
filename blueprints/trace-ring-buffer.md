---
blueprint: trace-ring-buffer
title: The trace ring buffer
status: partial
pin: v7.2.2
arch: i386
lessons: []
generated: [2, 5, 7]
config-dependent: [CONFIG_RING_BUFFER, CONFIG_TRACING, CONFIG_RING_BUFFER_ALLOW_SWAP, CONFIG_RING_BUFFER_RECORD_RECURSION, CONFIG_RING_BUFFER_VALIDATE_TIME_DELTAS, CONFIG_RING_BUFFER_PERSISTENT_INJECT, CONFIG_TRACER_SNAPSHOT, CONFIG_ARCH_HAVE_NMI_SAFE_CMPXCHG, CONFIG_GENERIC_ATOMIC64, CONFIG_HAVE_64BIT_ALIGNED_ACCESS, CONFIG_MITIGATION_RETPOLINE, CONFIG_SMP, CONFIG_NR_CPUS]
structures: [trace_buffer, ring_buffer_per_cpu, buffer_page, buffer_data_page, ring_buffer_event, ring_buffer_iter, ring_buffer_cpu_meta, trace_array_cpu, trace_entry]
interfaces: [ring_buffer_alloc, __ring_buffer_alloc, ring_buffer_free, ring_buffer_resize, ring_buffer_size, ring_buffer_lock_reserve, ring_buffer_unlock_commit, ring_buffer_write, ring_buffer_event_data, ring_buffer_event_length, ring_buffer_peek, ring_buffer_consume, ring_buffer_read_page, ring_buffer_iter_dropped, ring_buffer_entries_cpu, ring_buffer_overrun_cpu, ring_buffer_commit_overrun_cpu, ring_buffer_dropped_events_cpu, ring_buffer_bytes_cpu, ring_buffer_read_events_cpu, ring_buffer_oldest_event_ts, ring_buffer_time_stamp, ring_buffer_record_disable, ring_buffer_record_enable, ring_buffer_change_overwrite, ring_buffer_reset_cpu, rb_reserve_next_event, __rb_reserve_next, rb_move_tail, rb_handle_head_page, rb_set_head_page, rb_get_reader_page, rb_commit, rb_end_commit, rb_time_stamp, rb_add_time_stamp, rb_check_pages, trace_buffer_lock_reserve, trace_function, function_trace_call, tracing_stats_read]
ops: []
artefacts: [proc/tier0/ring-overrun]
---

# The trace ring buffer

**Status is `partial`, and this is what that means here.** All seventy five citations in `trace-ring-buffer.refs.toml` resolve against the pinned 7.2.2 source and every anchor in it matches exactly one line in the file it names. Sections 2 and 7 come out of the BTF of the `A-full` build, which is the profile the artefact was taken on, and section 5 comes from one capture on one boot of that kernel. What is left is a person. `complete` needs a name in `reviewed-by`, and nobody has read this through yet.

There is one fact here that changes how you read every trace you will ever take, so it goes first.

A writer into this buffer never blocks, never waits and never fails for lack of room. When the buffer is full it throws the oldest page of events away and carries on. The events are gone, no error is returned to anyone, and the body of the trace file you read afterwards does not say it happened. It starts part way through and reads exactly like a complete trace of a shorter period of time.

The capture in section 5 is that, on purpose. An eight kilobyte buffer, an unfiltered tracer, and about seven thousandths of a second of an idle machine running two small commands. 273 events were still in the buffer. 44002 had been thrown away to make room for them. That is a hundred and sixty one events discarded for every one kept.

The second fact is what the two ways of reading a trace will admit, and the answer is that each of them tells you half. The `trace` file prints two numbers in its header, `entries-in-buffer/entries-written`, and on this buffer they would read `273/44275` [trace-ring-buffer-R76]. That is the whole admission: how many, once, at the top, in a header a reader skips on the way to the lines. Nothing in the body of the file marks where the missing events were. `trace_pipe` is the other way round. It prints `CPU:0 [LOST 44002 EVENTS]` at the position the loss happened and has no header at all, so it says where and not how many overall. Section 3 says exactly where the two paths part company, and section 9 says why they were never made to agree.

![A picture in four parts, about how a full trace buffer loses events without saying so. Across the top, a ring of four boxes labelled sub buffer 0 to sub buffer 3, joined left to right by arrows with a dashed arrow wrapping from the last one back to the first. The first box is also labelled head, the oldest, the third is labelled tail, writing here now, and a separate box sits outside the ring labelled reader page, off the ring, with a note that the writer will never touch it. Underneath on the left, a column headed what one writer does, with three boxes reading down: read the tail page, read the two timestamps, and add my length to the write index with one atomic add. That last box forks. The left branch is labelled it fits and holds one box reading write the data and commit. The right branch is labelled it does not fit and holds three boxes in a red style reading the next page is the head, throw that whole page away and add its events to overrun, and move the tail onto it. A note beside the red branch says nothing waits, nothing fails, and no caller is told. On the lower left, a small table of the counters as the capture read them, with entries 273, overrun 44002, commit overrun 0 and dropped events 0, and a line under it reading 44275 events written, 99.4% of them thrown away, in 0.007 seconds. On the right, two columns headed the two ways to read a trace. The left column, trace_pipe, has boxes reading consuming read, take overrun minus last overrun, and print CPU:0 LOST 44002 EVENTS. The right column, the trace file, has boxes reading iterator read, ask for the iterator's missed events flag, and a red box reading the writer never sets that bit on an ordinary buffer, so nothing marks the body. An arrow leads from that red box to a wide box holding the header line of the trace file, entries-in-buffer slash entries-written 273 slash 44275. Across the bottom is a red band reading each way of reading a trace tells you half of what was lost, and under it a line saying trace_pipe says where and prints no header, while the trace file says how many, once, in a header a reader skips, and marks nothing in the body.](assets/trace-ring-buffer-overrun.svg)

## §1 Purpose and boundary

This mechanism owns a per processor circular buffer of variable length records, and the rules for putting a record into it from any execution context on the machine without taking a lock. It is responsible for handing a writer a piece of memory of the size it asked for, for deciding what happens when there is no room, for keeping the counters that say what it did, and for letting a reader on another processor take completed pages out of the ring while writers are still filling it.

It deserves a specification of its own because it is the one piece of the tracing stack that is not about tracing. It has no idea what an event means, it has no format for a record beyond a four byte header, and the same code carries function traces, event traces, `printk` output under some configurations, and anything else a subsystem wants to record. Every claim any lesson in this project makes about what a trace contains rests on this code first and on the tracer second.

What it is not responsible for:

- What goes in a record. Event formats, the type field, and the tables that turn a record back into text are the trace events mechanism, and this file never looks past the length.
- Deciding when to record anything. Which functions are traced, which filters apply and when tracing is on belongs to the function tracer and the event machinery. This is called after all of that has already said yes.
- Presenting a trace. The reading paths here hand out pages and events. Turning them into the lines a person reads is the trace output mechanism, and section 3 stops at the boundary.
- The files under the tracing filesystem. Their names, their permissions and the parsing of what you write into them belongs elsewhere. This blueprint cites two of those files where their contents are the only evidence of something this mechanism did.
- Memory allocation. Pages come from the page allocator at setup and resize time, and never during a write, which is the constraint that shapes everything in section 3.
- The clock. What `trace_clock_local` reads and how well it agrees between processors is its own subject. This mechanism stores whatever the clock returns and knows only that it goes forward.
- Persistent buffers that survive a reboot. That is a real feature in this file and it is a different specification, named in sections 6 and 8 where it changes an answer given here.

## §2 Data structures

Generated, and the block below says what from. Hand editing it fails the build.

<!-- bpc:generated section=2 hash=e95ddb7ba25139d9 -->
<!-- bpc:source kind=btf path=kxbox/kernel/build/A-full/vmlinux evidence=true pin=v7.2.2 arch=i386 -->

Generated by bpc 0.2 from `kxbox/kernel/build/A-full/vmlinux`, for i386 with 4 byte pointers. Offsets are byte offsets from the start of the structure. A hole is padding the compiler inserted and not a field you can use.

### struct trace_buffer

132 bytes, 61 field(s), 3 bytes of padding in 1 hole(s).

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 4 | `flags` | `unsigned int` |
| 4 | 4 | `cpus` | `int` |
| 8 | 4 | `record_disabled` | `atomic_t` |
| 8 | 4 | `record_disabled.counter` | `int` |
| 12 | 4 | `resizing` | `atomic_t` |
| 12 | 4 | `resizing.counter` | `int` |
| 16 | 4 | `cpumask` | `cpumask_var_t` |
| 20 | 4 | `reader_lock_key` | `struct lock_class_key *` |
| 24 | 8 | `mutex` | `struct mutex` |
| 24 | 4 | `mutex.owner` | `atomic_long_t` |
| 24 | 4 | `mutex.owner.counter` | `int` |
| 28 | 0 | `mutex.wait_lock` | `raw_spinlock_t` |
| 28 | 0 | `mutex.wait_lock.raw_lock` | `arch_spinlock_t` |
| 28 | 4 | `mutex.first_waiter` | `struct mutex_waiter *` |
| 32 | 4 | `buffers` | `struct ring_buffer_per_cpu **` |
| 36 | 4 | `remote` | `struct ring_buffer_remote *` |
| 40 | 8 | `node` | `struct hlist_node` |
| 40 | 4 | `node.next` | `struct hlist_node *` |
| 44 | 4 | `node.pprev` | `struct hlist_node **` |
| 48 | 4 | `clock` | `u64 (void) *` |
| 52 | 40 | `irq_work` | `struct rb_irq_work` |
| 52 | 16 | `irq_work.work` | `struct irq_work` |
| 52 | 8 | `irq_work.work.node` | `struct __call_single_node` |
| 52 | 4 | `irq_work.work.node.llist` | `struct llist_node` |
| 52 | 4 | `irq_work.work.node.llist.next` | `struct llist_node *` |
| 56 | 4 | `irq_work.work.node.u_flags` | `unsigned int` |
| 56 | 4 | `irq_work.work.node.a_flags` | `atomic_t` |
| 56 | 4 | `irq_work.work.node.a_flags.counter` | `int` |
| 60 | 4 | `irq_work.work.func` | `void (struct irq_work *) *` |
| 64 | 4 | `irq_work.work.irqwait` | `struct rcuwait` |
| 64 | 4 | `irq_work.work.irqwait.task` | `struct task_struct *` |
| 68 | 8 | `irq_work.waiters` | `wait_queue_head_t` |
| 68 | 0 | `irq_work.waiters.lock` | `spinlock_t` |
| 68 | 0 | `irq_work.waiters.lock.rlock` | `struct raw_spinlock` |
| 68 | 0 | `irq_work.waiters.lock.rlock.raw_lock` | `arch_spinlock_t` |
| 68 | 8 | `irq_work.waiters.head` | `struct list_head` |
| 68 | 4 | `irq_work.waiters.head.next` | `struct list_head *` |
| 72 | 4 | `irq_work.waiters.head.prev` | `struct list_head *` |
| 76 | 8 | `irq_work.full_waiters` | `wait_queue_head_t` |
| 76 | 0 | `irq_work.full_waiters.lock` | `spinlock_t` |
| 76 | 0 | `irq_work.full_waiters.lock.rlock` | `struct raw_spinlock` |
| 76 | 0 | `irq_work.full_waiters.lock.rlock.raw_lock` | `arch_spinlock_t` |
| 76 | 8 | `irq_work.full_waiters.head` | `struct list_head` |
| 76 | 4 | `irq_work.full_waiters.head.next` | `struct list_head *` |
| 80 | 4 | `irq_work.full_waiters.head.prev` | `struct list_head *` |
| 84 | 4 | `irq_work.seq` | `atomic_t` |
| 84 | 4 | `irq_work.seq.counter` | `int` |
| 88 | 1 | `irq_work.waiters_pending` | `bool` |
| 89 | 1 | `irq_work.full_waiters_pending` | `bool` |
| 90 | 1 | `irq_work.wakeup_full` | `bool` |
| 92 | 1 | `time_stamp_abs` | `bool` |
| 96 | 4 | `range_addr_start` | `long unsigned int` |
| 100 | 4 | `range_addr_end` | `long unsigned int` |
| 104 | 12 | `flush_nb` | `struct notifier_block` |
| 104 | 4 | `flush_nb.notifier_call` | `notifier_fn_t` |
| 108 | 4 | `flush_nb.next` | `struct notifier_block *` |
| 112 | 4 | `flush_nb.priority` | `int` |
| 116 | 4 | `meta` | `struct ring_buffer_meta *` |
| 120 | 4 | `subbuf_size` | `unsigned int` |
| 124 | 4 | `subbuf_order` | `unsigned int` |
| 128 | 4 | `max_data_size` | `unsigned int` |

- 3 byte hole at offset 93, after `time_stamp_abs`.

### struct ring_buffer_per_cpu

304 bytes, 128 field(s), 4 bytes of padding in 1 hole(s).

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 4 | `cpu` | `int` |
| 4 | 4 | `record_disabled` | `atomic_t` |
| 4 | 4 | `record_disabled.counter` | `int` |
| 8 | 4 | `resize_disabled` | `atomic_t` |
| 8 | 4 | `resize_disabled.counter` | `int` |
| 12 | 4 | `buffer` | `struct trace_buffer *` |
| 16 | 0 | `reader_lock` | `raw_spinlock_t` |
| 16 | 0 | `reader_lock.raw_lock` | `arch_spinlock_t` |
| 16 | 0 | `lock` | `arch_spinlock_t` |
| 16 | 0 | `lock_key` | `struct lock_class_key` |
| 16 | 4 | `free_page` | `struct buffer_data_page *` |
| 20 | 4 | `nr_pages` | `long unsigned int` |
| 24 | 4 | `current_context` | `unsigned int` |
| 28 | 4 | `pages` | `struct list_head *` |
| 32 | 4 | `cnt` | `long unsigned int` |
| 36 | 4 | `head_page` | `struct buffer_page *` |
| 40 | 4 | `tail_page` | `struct buffer_page *` |
| 44 | 4 | `commit_page` | `struct buffer_page *` |
| 48 | 4 | `reader_page` | `struct buffer_page *` |
| 52 | 4 | `lost_events` | `long unsigned int` |
| 56 | 4 | `last_overrun` | `long unsigned int` |
| 60 | 4 | `nest` | `long unsigned int` |
| 64 | 4 | `entries_bytes` | `local_t` |
| 64 | 4 | `entries_bytes.a` | `atomic_long_t` |
| 64 | 4 | `entries_bytes.a.counter` | `int` |
| 68 | 4 | `entries` | `local_t` |
| 68 | 4 | `entries.a` | `atomic_long_t` |
| 68 | 4 | `entries.a.counter` | `int` |
| 72 | 4 | `overrun` | `local_t` |
| 72 | 4 | `overrun.a` | `atomic_long_t` |
| 72 | 4 | `overrun.a.counter` | `int` |
| 76 | 4 | `commit_overrun` | `local_t` |
| 76 | 4 | `commit_overrun.a` | `atomic_long_t` |
| 76 | 4 | `commit_overrun.a.counter` | `int` |
| 80 | 4 | `dropped_events` | `local_t` |
| 80 | 4 | `dropped_events.a` | `atomic_long_t` |
| 80 | 4 | `dropped_events.a.counter` | `int` |
| 84 | 4 | `committing` | `local_t` |
| 84 | 4 | `committing.a` | `atomic_long_t` |
| 84 | 4 | `committing.a.counter` | `int` |
| 88 | 4 | `commits` | `local_t` |
| 88 | 4 | `commits.a` | `atomic_long_t` |
| 88 | 4 | `commits.a.counter` | `int` |
| 92 | 4 | `pages_touched` | `local_t` |
| 92 | 4 | `pages_touched.a` | `atomic_long_t` |
| 92 | 4 | `pages_touched.a.counter` | `int` |
| 96 | 4 | `pages_lost` | `local_t` |
| 96 | 4 | `pages_lost.a` | `atomic_long_t` |
| 96 | 4 | `pages_lost.a.counter` | `int` |
| 100 | 4 | `pages_read` | `local_t` |
| 100 | 4 | `pages_read.a` | `atomic_long_t` |
| 100 | 4 | `pages_read.a.counter` | `int` |
| 104 | 4 | `last_pages_touch` | `long int` |
| 108 | 4 | `shortest_full` | `size_t` |
| 112 | 4 | `read` | `long unsigned int` |
| 116 | 4 | `read_bytes` | `long unsigned int` |
| 120 | 8 | `write_stamp` | `rb_time_t` |
| 120 | 8 | `write_stamp.time` | `local64_t` |
| 120 | 8 | `write_stamp.time.a` | `atomic64_t` |
| 120 | 8 | `write_stamp.time.a.counter` | `s64` |
| 128 | 8 | `before_stamp` | `rb_time_t` |
| 128 | 8 | `before_stamp.time` | `local64_t` |
| 128 | 8 | `before_stamp.time.a` | `atomic64_t` |
| 128 | 8 | `before_stamp.time.a.counter` | `s64` |
| 136 | 40 | `event_stamp` | `u64[5]` |
| 176 | 8 | `read_stamp` | `u64` |
| 184 | 4 | `pages_removed` | `long unsigned int` |
| 188 | 4 | `mapped` | `unsigned int` |
| 192 | 4 | `user_mapped` | `unsigned int` |
| 196 | 8 | `mapping_lock` | `struct mutex` |
| 196 | 4 | `mapping_lock.owner` | `atomic_long_t` |
| 196 | 4 | `mapping_lock.owner.counter` | `int` |
| 200 | 0 | `mapping_lock.wait_lock` | `raw_spinlock_t` |
| 200 | 0 | `mapping_lock.wait_lock.raw_lock` | `arch_spinlock_t` |
| 200 | 4 | `mapping_lock.first_waiter` | `struct mutex_waiter *` |
| 204 | 4 | `subbuf_ids` | `struct buffer_page **` |
| 208 | 4 | `meta_page` | `struct trace_buffer_meta *` |
| 212 | 4 | `ring_meta` | `struct ring_buffer_cpu_meta *` |
| 216 | 4 | `remote` | `struct ring_buffer_remote *` |
| 220 | 4 | `nr_pages_to_update` | `long int` |
| 224 | 8 | `new_pages` | `struct list_head` |
| 224 | 4 | `new_pages.next` | `struct list_head *` |
| 228 | 4 | `new_pages.prev` | `struct list_head *` |
| 232 | 16 | `update_pages_work` | `struct work_struct` |
| 232 | 4 | `update_pages_work.data` | `atomic_long_t` |
| 232 | 4 | `update_pages_work.data.counter` | `int` |
| 236 | 8 | `update_pages_work.entry` | `struct list_head` |
| 236 | 4 | `update_pages_work.entry.next` | `struct list_head *` |
| 240 | 4 | `update_pages_work.entry.prev` | `struct list_head *` |
| 244 | 4 | `update_pages_work.func` | `work_func_t` |
| 248 | 12 | `update_done` | `struct completion` |
| 248 | 4 | `update_done.done` | `unsigned int` |
| 252 | 8 | `update_done.wait` | `struct swait_queue_head` |
| 252 | 0 | `update_done.wait.lock` | `raw_spinlock_t` |
| 252 | 0 | `update_done.wait.lock.raw_lock` | `arch_spinlock_t` |
| 252 | 8 | `update_done.wait.task_list` | `struct list_head` |
| 252 | 4 | `update_done.wait.task_list.next` | `struct list_head *` |
| 256 | 4 | `update_done.wait.task_list.prev` | `struct list_head *` |
| 260 | 40 | `irq_work` | `struct rb_irq_work` |
| 260 | 16 | `irq_work.work` | `struct irq_work` |
| 260 | 8 | `irq_work.work.node` | `struct __call_single_node` |
| 260 | 4 | `irq_work.work.node.llist` | `struct llist_node` |
| 260 | 4 | `irq_work.work.node.llist.next` | `struct llist_node *` |
| 264 | 4 | `irq_work.work.node.u_flags` | `unsigned int` |
| 264 | 4 | `irq_work.work.node.a_flags` | `atomic_t` |
| 264 | 4 | `irq_work.work.node.a_flags.counter` | `int` |
| 268 | 4 | `irq_work.work.func` | `void (struct irq_work *) *` |
| 272 | 4 | `irq_work.work.irqwait` | `struct rcuwait` |
| 272 | 4 | `irq_work.work.irqwait.task` | `struct task_struct *` |
| 276 | 8 | `irq_work.waiters` | `wait_queue_head_t` |
| 276 | 0 | `irq_work.waiters.lock` | `spinlock_t` |
| 276 | 0 | `irq_work.waiters.lock.rlock` | `struct raw_spinlock` |
| 276 | 0 | `irq_work.waiters.lock.rlock.raw_lock` | `arch_spinlock_t` |
| 276 | 8 | `irq_work.waiters.head` | `struct list_head` |
| 276 | 4 | `irq_work.waiters.head.next` | `struct list_head *` |
| 280 | 4 | `irq_work.waiters.head.prev` | `struct list_head *` |
| 284 | 8 | `irq_work.full_waiters` | `wait_queue_head_t` |
| 284 | 0 | `irq_work.full_waiters.lock` | `spinlock_t` |
| 284 | 0 | `irq_work.full_waiters.lock.rlock` | `struct raw_spinlock` |
| 284 | 0 | `irq_work.full_waiters.lock.rlock.raw_lock` | `arch_spinlock_t` |
| 284 | 8 | `irq_work.full_waiters.head` | `struct list_head` |
| 284 | 4 | `irq_work.full_waiters.head.next` | `struct list_head *` |
| 288 | 4 | `irq_work.full_waiters.head.prev` | `struct list_head *` |
| 292 | 4 | `irq_work.seq` | `atomic_t` |
| 292 | 4 | `irq_work.seq.counter` | `int` |
| 296 | 1 | `irq_work.waiters_pending` | `bool` |
| 297 | 1 | `irq_work.full_waiters_pending` | `bool` |
| 298 | 1 | `irq_work.wakeup_full` | `bool` |

- 4 byte hole at offset 300, after `irq_work.wakeup_full`.

### struct buffer_page

36 bytes, 15 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 8 | `list` | `struct list_head` |
| 0 | 4 | `list.next` | `struct list_head *` |
| 4 | 4 | `list.prev` | `struct list_head *` |
| 8 | 4 | `write` | `local_t` |
| 8 | 4 | `write.a` | `atomic_long_t` |
| 8 | 4 | `write.a.counter` | `int` |
| 12 | 4 | `read` | `unsigned int` |
| 16 | 4 | `entries` | `local_t` |
| 16 | 4 | `entries.a` | `atomic_long_t` |
| 16 | 4 | `entries.a.counter` | `int` |
| 20 | 4 | `real_end` | `long unsigned int` |
| 24 | 4 | `order` | `unsigned int` |
| 28 | 30 bits | `id` | `u32` |
| 31 | 1 bits | `range` | `u32` |
| 32 | 4 | `page` | `struct buffer_data_page *` |

### struct buffer_data_page

12 bytes, 5 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 8 | `time_stamp` | `u64` |
| 8 | 4 | `commit` | `local_t` |
| 8 | 4 | `commit.a` | `atomic_long_t` |
| 8 | 4 | `commit.a.counter` | `int` |
| 12 | 0 | `data` | `unsigned char[0]` |

### struct ring_buffer_event

4 bytes, 3 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 5 bits | `type_len` | `u32` |
| 0 | 27 bits | `time_delta` | `u32` |
| 4 | 0 | `array` | `u32[0]` |

### struct ring_buffer_iter

56 bytes, 12 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 4 | `cpu_buffer` | `struct ring_buffer_per_cpu *` |
| 4 | 4 | `head` | `long unsigned int` |
| 8 | 4 | `next_event` | `long unsigned int` |
| 12 | 4 | `head_page` | `struct buffer_page *` |
| 16 | 4 | `cache_reader_page` | `struct buffer_page *` |
| 20 | 4 | `cache_read` | `long unsigned int` |
| 24 | 4 | `cache_pages_removed` | `long unsigned int` |
| 28 | 8 | `read_stamp` | `u64` |
| 36 | 8 | `page_stamp` | `u64` |
| 44 | 4 | `event` | `struct ring_buffer_event *` |
| 48 | 4 | `event_size` | `size_t` |
| 52 | 4 | `missed_events` | `int` |

### struct ring_buffer_cpu_meta

20 bytes, 6 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 4 | `first_buffer` | `long unsigned int` |
| 4 | 4 | `head_buffer` | `long unsigned int` |
| 8 | 4 | `commit_buffer` | `long unsigned int` |
| 12 | 4 | `subbuf_size` | `__u32` |
| 16 | 4 | `nr_subbufs` | `__u32` |
| 20 | 0 | `buffers` | `int[0]` |

### struct trace_array_cpu

80 bytes, 19 field(s), 3 bytes of padding in 1 hole(s).

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 4 | `disabled` | `local_t` |
| 0 | 4 | `disabled.a` | `atomic_long_t` |
| 0 | 4 | `disabled.a.counter` | `int` |
| 4 | 4 | `entries` | `long unsigned int` |
| 8 | 4 | `saved_latency` | `long unsigned int` |
| 12 | 4 | `critical_start` | `long unsigned int` |
| 16 | 4 | `critical_end` | `long unsigned int` |
| 20 | 4 | `critical_sequence` | `long unsigned int` |
| 24 | 4 | `nice` | `long unsigned int` |
| 28 | 4 | `policy` | `long unsigned int` |
| 32 | 4 | `rt_priority` | `long unsigned int` |
| 36 | 4 | `skipped_entries` | `long unsigned int` |
| 40 | 8 | `preempt_timestamp` | `u64` |
| 48 | 4 | `pid` | `pid_t` |
| 52 | 4 | `uid` | `kuid_t` |
| 52 | 4 | `uid.val` | `uid_t` |
| 56 | 16 | `comm` | `char[16]` |
| 72 | 4 | `ftrace_ignore_pid` | `int` |
| 76 | 1 | `ignore_pid` | `bool` |

- 3 byte hole at offset 77, after `ignore_pid`.

### struct trace_entry

8 bytes, 4 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 2 | `type` | `short unsigned int` |
| 2 | 1 | `flags` | `unsigned char` |
| 3 | 1 | `preempt_count` | `unsigned char` |
| 4 | 4 | `pid` | `int` |
<!-- bpc:end section=2 -->

Two things in that table are worth saying in words, because the sizes on their own mislead. A `struct buffer_page` is not a page of events, it is the management record for one [trace-ring-buffer-R3], so its size in the table is a few tens of bytes and the memory it stands for is four thousand. And it carries a field for where the data on its page actually stopped [trace-ring-buffer-R4], which is not the same as how far the write index got, because a write that ran off the end of a page is moved to the next one and leaves the tail of the old page unused.

## §3 Algorithms

Numbered from the moment something in the kernel decides to record an event. Steps 1 to 12 are one writer putting one record in. Steps 13 to 16 are what happens when it does not fit, which is where the events go. Steps 17 to 22 are a reader taking pages out, and the last three of those are where the two ways of reading a trace stop agreeing with each other.

1. Turn off preemption and test four things, in order [trace-ring-buffer-R15]. Recording disabled for the whole buffer, this processor not being one the buffer has a per processor area for, recording disabled for this processor alone, and a length larger than the biggest record the buffer can hold [trace-ring-buffer-R16]. Any of the four returns a null pointer. The caller is expected to check it and give up, and nothing counts how often that happened.

2. Take the recursion guard [trace-ring-buffer-R17]. There is one word of bits per processor, one bit per execution context, and the bit is chosen from the current interrupt nesting level rather than from anything the caller says [trace-ring-buffer-R18]. If the bit is already set, this context is already inside a reserve on this processor, which means something being traced is on the path the tracer itself takes, and the answer is to refuse. One extra bit exists for the window where the hardware has changed context and the preempt count has not been updated yet [trace-ring-buffer-R19], and the whole set is five bits wide so that a tracer that deliberately nests can shift past it [trace-ring-buffer-R20].

3. Refuse an NMI on an architecture that cannot do a compare and swap safely from one [trace-ring-buffer-R21]. This is the only architecture question in the mechanism and it is answered by dropping the event. On the pinned machine the answer is that it can, so this never fires here, and a reimplementation on a machine where it does not is a reimplementation that cannot trace NMIs at all.

4. Open a commit [trace-ring-buffer-R22]. Two counters on the per processor area go up before any space is claimed. Their job is to identify, later, which writer is the outermost one on this processor, because an interrupt can land in the middle of everything below and start its own record.

5. Work out the real length [trace-ring-buffer-R23]. The caller's length is rounded up to the alignment and given a four byte header. Every size from here on is this number and not the caller's, which is why an event's footprint is not a function of its payload alone.

6. Read the tail page into a local variable, once [trace-ring-buffer-R25]. This is the first of four steps the code labels A, B, C and D, and everything about the timestamp logic is about which of them another writer landed between.

7. Read the two saved timestamps and the clock, and decide what kind of timestamp this record needs. If the two saved values disagree, somebody is in the middle of an update, and this record is forced to carry a full timestamp extension rather than a delta [trace-ring-buffer-R29]. The delta is twenty seven bits [trace-ring-buffer-R30], so a gap longer than about a hundred and thirty four milliseconds also forces an extension. Even the absolute form is not a whole clock reading [trace-ring-buffer-R31].

8. One atomic add claims the space [trace-ring-buffer-R26]. This is the entire concurrency control for writing. After it, no two writers on this processor can believe they own the same bytes, because each got a different return value from the same add. There is no lock, no retry loop around it and no failure case.

9. Compare where the add landed against the size of a sub buffer [trace-ring-buffer-R32]. If it is past the end, go to step 13. Everything interesting in this blueprint is downstream of this one comparison.

10. If it fits, find out whether anything interrupted between step 6 and step 8, by testing whether the write index moved by exactly this record's length [trace-ring-buffer-R27]. When nothing did, this is the fast path and the record gets a small delta [trace-ring-buffer-R28]. When something did, the record is left carrying a full timestamp, which the previous step already made room for.

11. The caller writes its data into the pointer it was handed. Nothing in this mechanism is involved, nothing checks that it happened, and a caller that reserves and never commits leaves a hole that the reader will see as padding.

12. Commit [trace-ring-buffer-R70]. The event counter goes up here and not at step 8 [trace-ring-buffer-R71], which is the reason a reserved and abandoned record is counted nowhere. Then the commit pointer is walked forward to the tail, and the writer that gets to do that walk is the outermost one, because interrupts nest like a stack and the outer one finishes last [trace-ring-buffer-R72]. The walk has a ceiling on how far it will go [trace-ring-buffer-R73], since it is chasing a structure other writers are still changing. The pair opened in step 4 is closed here [trace-ring-buffer-R74].

13. The record did not fit, so move the tail [trace-ring-buffer-R33]. The code says plainly what it is up against [trace-ring-buffer-R34]: a reader on another processor, and interrupts on this one, both of which can be moving the same pointers.

14. First check whether the next page is the still open commit [trace-ring-buffer-R35]. That means writers nested inside one unfinished record have gone all the way around the ring, which the code treats as something that should not happen [trace-ring-buffer-R36]. It bumps the commit overrun counter and gives up on the record. This is the counter that reads zero in section 5, and a non zero value there is a report about the tracer rather than about what was being traced [trace-ring-buffer-R68].

15. Then check whether the next page is the head page, which is to say the oldest one [trace-ring-buffer-R37]. If it is, the buffer is full, and there are two behaviours [trace-ring-buffer-R38]. With overwrite off, the new event is dropped and a different counter goes up [trace-ring-buffer-R39]. With overwrite on, which is the default and what section 5 was captured under, the oldest page is thrown away.

16. Throwing it away is one function [trace-ring-buffer-R40] and it is the only place in this mechanism where data is deliberately lost. It moves the head forward with a compare and swap whose result has four possible meanings, all four of which are legitimate and are listed in the code [trace-ring-buffer-R41]. The writer that wins adds the whole discarded page's event count to the overrun counter in one go [trace-ring-buffer-R42] and takes that page's bytes back off the byte count [trace-ring-buffer-R43]. Then the tail moves onto the freed page [trace-ring-buffer-R44] and the reserve is failed with a retry [trace-ring-buffer-R45], so the caller goes round the loop and reserves again on a page that now has room. The retry loop has a ceiling of a thousand [trace-ring-buffer-R24].

    The pointer scheme that makes step 16 safe without a lock is described in a comment rather than in code [trace-ring-buffer-R46], and it is worth reading before reimplementing any of this. The low two bits of a page's forward list pointer say whether the page after it is the head and whether somebody is in the middle of moving it [trace-ring-buffer-R47]. Three of the four values are states and the fourth is only ever a return value [trace-ring-buffer-R48]. The head pointer itself is not trusted at all, because a reader may have moved it, and the tag on the page before it is trusted instead [trace-ring-buffer-R49].

17. A reader starts by taking the one lock in this mechanism [trace-ring-buffer-R51]. There is no matching writer lock. The asymmetry is the specification: readers are rare, run in process context and can afford a lock, and writers are called from everywhere and cannot.

18. The reader gives the ring its own empty page and takes the oldest page out [trace-ring-buffer-R52]. That is the swap, and it is why reading a trace copies nothing. The swap is one compare and swap against the tagged pointer from step 16 [trace-ring-buffer-R53], and losing it means a writer moved the head underneath, in which case the reader starts the swap again.

19. While it holds that page, the reader reads the overrun counter [trace-ring-buffer-R54] and subtracts the value it read at its previous swap [trace-ring-buffer-R55]. The difference is how many events were lost between two reads, this is the only place in the kernel that subtraction is done, and the answer is left on the per processor area for a consumer to pick up [trace-ring-buffer-R56].

20. A consuming read takes that number with it [trace-ring-buffer-R57]. This is what `trace_pipe` uses, and it is why `trace_pipe` can print a line saying how many events it missed [trace-ring-buffer-R63].

21. An iterating read asks a different question [trace-ring-buffer-R58]. It calls a function that reports whether the iterator has a missed events flag set [trace-ring-buffer-R59], and that flag has exactly one place it is ever set from, which is a bit in a page's commit field [trace-ring-buffer-R60]. On an ordinary buffer the writer never sets that bit. The kernel says so in a comment next to the one place that does set it [trace-ring-buffer-R61], which is a persistent buffer being recovered across a reboot [trace-ring-buffer-R62]. So on the machine in section 5 the flag is zero, the count is never consulted, and nothing in the body of the `trace` file marks the place where the 44002 events were.

22. The `trace` file gets its number from somewhere else entirely, and this is the step that stops the previous one being read as the whole story. The header of that file is printed by the same seq_file machinery that prints the lines [trace-ring-buffer-R76], and the second of its two numbers is not a counter at all: it is this processor's kept events plus this processor's overrun, added up at the moment the header is printed [trace-ring-buffer-R77]. So the file does say how many are missing, once, at the top, and never says where. That header is also a display option rather than part of the format, and turning `context-info` off removes it [trace-ring-buffer-R78].

## §4 Invariants, locking and context

### §4a Invariants

1. No two records on one processor ever overlap in the buffer. [checked: one atomic add on the write index gives every writer a different return value, and nothing else allocates space]
2. A record is counted in `entries` if and only if it was committed [trace-ring-buffer-R71]. [checked: the increment is in the commit and not in the reserve]
3. `entries` reported by the stats file is what was written, minus what was thrown away, minus what has been read [trace-ring-buffer-R64]. [checked: the reported value is computed from the three counters at read time rather than maintained]
4. Only one writer per processor is inside a reserve for a given execution context at a time [trace-ring-buffer-R17]. [checked: the bit is tested and set on the way in, and cleared on every exit path]
5. Every event thrown away is added to `overrun` before the page holding it can be reused [trace-ring-buffer-R42]. [checked: the add happens on the branch that won the compare and swap, before the tail is allowed onto the page]
6. A writer never waits and never fails for lack of space. [checked: the only failure paths in the reserve are the four refusals in step 1, the recursion guard, the NMI gate and a thousand retries]
7. The page the reader holds is not in the ring, so no writer can be writing to it [trace-ring-buffer-R2] [trace-ring-buffer-R50]. [checked: the swap puts an empty page in the ring before the old one is handed over, under a compare and swap]
8. The commit pointer never passes the tail pointer. [checked: the commit walk stops when the two are equal, and it is bounded]
9. A page's event count and the bytes it holds are consistent with the counters after a discard [trace-ring-buffer-R43]. It follows from the count being added and the bytes subtracted on the same branch, and nothing verifies it afterwards. [unchecked]
10. The number of events lost between two consuming reads equals the difference in the overrun counter across them [trace-ring-buffer-R55]. [checked: the reader records the counter under the same lock and page ownership it does the swap under]
11. On an ordinary buffer, an iterating reader's missed events flag is always zero [trace-ring-buffer-R61]. [unchecked]

Invariant 11 is the one this blueprint exists to write down. Nothing in the kernel enforces it, nothing tests it, and it is not stated anywhere except in a comment about a different case. It is why the body of a trace file reads the same whether nothing was lost or almost everything was, and why the only thing that separates those two cases is a pair of numbers in the header and a counter in another file.

### §4b Locking discipline

What protects each thing this mechanism touches:

| Thing | Protected by |
|---|---|
| the write index on the tail page [trace-ring-buffer-R26] | `atomic`, one add per writer and the return value is the claim |
| the tail page pointer [trace-ring-buffer-R44] | `cmpxchg`, and losing the exchange means somebody else did the work |
| the head page pointer [trace-ring-buffer-R53] | `cmpxchg` on a tagged list pointer, against both readers and interrupts |
| the two low bits of a page's list pointer [trace-ring-buffer-R47] | `cmpxchg`, they are the protocol rather than the payload |
| the commit page pointer [trace-ring-buffer-R72] | `owner`, only the outermost writer on the processor moves it |
| the recursion guard word [trace-ring-buffer-R17] | `percpu`, and preemption is off across the whole reserve |
| `entries`, `overrun`, `commit_overrun`, `dropped_events` | `percpu`, they are `local_t` and only this processor writes them |
| the reader page and the read position [trace-ring-buffer-R51] | `reader_lock`, a raw spinlock held across the swap |
| the head page during a swap | `lock`, the raw architecture spinlock inside the reader lock |
| `last_overrun` and `lost_events` [trace-ring-buffer-R55] | `reader_lock`, they are the reader's own state |
| the page list itself, on resize [trace-ring-buffer-R7] | `mutex` on the buffer, and writing is stopped first |

Acquisition order, written as a chain with `>` meaning taken before:

`buffer mutex > reader_lock > lock`

Writers take none of these. That is the whole design, and it is why a writer can be an NMI handler.

The raw architecture spinlock inside the reader lock deserves the same defence the lock ordering blueprint gives to its own. It is a raw architecture primitive rather than any lock the kernel offers, because a kernel lock would call into the tracing hooks, which call back into this file, from inside it.

### §4c Execution context

| Context | Allowed | What it may do |
|---|---|---|
| `P` | yes | reserve, commit, and read through either path |
| `PP` | yes | reserve and commit, and preemption is turned off across the reserve anyway |
| `A` | yes | reserve and commit |
| `SI` | yes | reserve and commit, in its own recursion bit |
| `HI` | yes | reserve and commit, in its own recursion bit |
| `NMI` | yes | reserve and commit, on an architecture with a safe compare and swap [trace-ring-buffer-R21] |

Reading is process context only. Everything else is every context there is, and that is the specification rather than a happy accident. A tracer that cannot record from an NMI cannot tell you what the machine was doing when it hung, which is one of the two things people reach for a tracer to find out.

Nothing in a write path sleeps, allocates, or takes a lock. The five bit recursion guard is what makes the last of those safe to say: code being traced that is itself on the tracer's path is caught by a bit test rather than by a deadlock.

The `PREEMPT_RT` delta is small and it is on the reader side. Writers already run with preemption disabled and take nothing, so nothing changes for them. The reader lock is a raw spinlock and stays a spinning lock on RT, which is deliberate, because the code inside it cannot sleep.

## §5 Observable behaviour

Generated, and the block below says what from. Hand editing it fails the build.

<!-- bpc:generated section=5 hash=7c9a483d1232c1cc -->
<!-- bpc:source kind=corpus path=corpora evidence=true pin=v7.2.2 arch=i386 -->

Generated by bpc 0.2 from 1 artefact(s) in `corpora/`. Every claim in this section points at a file that can be replayed, which is the difference between a specification of observable behaviour and a description of it.

### `corpora/proc/tier0/ring-overrun.txt`

Not a trace. Taken by `ls -l /proc > /dev/null; busybox true`, recording per_cpu/cpu0/stats after deliberately overflowing a small ring buffer, so the count of lost events is large and the count of kept events is small.

6 counter(s) read, 2 line(s) skipped, 0 line(s) the parser could not read. The skipped ones are the 2 clock reading(s) in this file, which are not counts of anything and are read separately.

| Counter | Value |
|---|---|
| `entries` | 273 |
| `overrun` | 44002 |
| `commit overrun` | 0 |
| `bytes` | 8264 |
| `dropped events` | 0 |
| `read events` | 0 |
| `oldest event ts` | 2.109723 |
| `now ts` | 2.116975 |

44275 event(s) were written into this buffer. 273 are still in it, 44002 were thrown away to make room, and 0 have been read out.
That is 161 event(s) discarded for every one kept, and 99.4% of everything the tracer recorded.

The oldest event still in the buffer is 0.007252 second(s) older than the clock reading taken as the file was read, so that is the whole of the machine's history this buffer was holding.
<!-- bpc:end section=5 -->

Two numbers in that table need arithmetic that the file does not do for you, and both are in this blueprint because a reader who does not do it draws the wrong conclusion.

The buffer was asked for as 8 kilobytes and reads back as 11. A request in bytes is divided by the usable size of a sub buffer, rounded up, with a floor of two [trace-ring-buffer-R7]. The usable size is a page minus a twelve byte header [trace-ring-buffer-R5] [trace-ring-buffer-R6], so on this machine it is 4084 rather than 4096. 8192 over 4084 rounds up to three sub buffers, and the size read back is usable bytes times sub buffers [trace-ring-buffer-R8], which is three times 4084, or 12252 bytes, and the file prints kilobytes rounded down [trace-ring-buffer-R10], so it says 11. The memory actually taken is four pages, because the reader page is allocated on top of the sub buffers asked for [trace-ring-buffer-R14]. You asked for 8, the file says 11, and 16 kilobytes went. The kernel's own documentation says the number is a request rather than a setting [trace-ring-buffer-R11], and a write to that file also turns off the growing the tracer would otherwise do on its own [trace-ring-buffer-R9].

The other one is the pair of counters that look like they mean the same thing. `overrun` is events lost because the buffer was full and overwrite was on [trace-ring-buffer-R67]. `dropped events` is events lost because overwrite was off [trace-ring-buffer-R69]. Exactly one of them can be non zero on a given buffer, they are never both, and the artefact has 44002 in one and 0 in the other. A reader who looks at the zero and stops has concluded that nothing was lost. `entries` is what is still there rather than what was written [trace-ring-buffer-R66], and the eight lines of that file are printed in one function in a fixed order with nothing else in it [trace-ring-buffer-R65].

## §6 Edge cases and failure modes

- **allocation-failure.** Nothing on a write path allocates, so this failure lives entirely at setup and resize. A resize that cannot get pages leaves the buffer at its old size and returns an error to the write on the size file, which is the one place in this mechanism where a user gets told something went wrong. The interesting consequence is the opposite one: because a writer cannot allocate, a full buffer cannot grow, and the only thing left to do with a full buffer is throw events out of it.

- **concurrent-entry.** This is the mechanism's whole subject. Two writers on one processor are impossible in the same context and normal across contexts, and they are separated by one atomic add [trace-ring-buffer-R26] plus a bit per context [trace-ring-buffer-R17]. A writer and a reader on two processors race over the head page and are separated by a compare and swap on a tagged pointer [trace-ring-buffer-R53], where the loser retries rather than waits. Two readers are serialised by the one lock [trace-ring-buffer-R51]. The case worth naming is a writer interrupting another writer in the middle of the timestamp update, which is not prevented at all: it is detected afterwards [trace-ring-buffer-R27] and paid for with a larger record [trace-ring-buffer-R29].

- **wrong-context.** There is no wrong context for a write, which is the point. The two situations that come closest are an NMI on an architecture without a safe compare and swap, where the event is dropped [trace-ring-buffer-R21], and code on the tracer's own path being traced, where the recursion guard refuses [trace-ring-buffer-R17]. Both are silent to the caller. A count of the second exists only when the kernel is built to keep one.

- **signal.** Nothing here is interruptible in the signal sense and no write path can be reached from signal delivery in a way that matters. The nearest real case is a reader blocked waiting for the buffer to fill, which is interruptible, and which is a path this blueprint names and does not open.

- **object-freed.** Freeing a buffer while a writer is inside it is prevented by the callers rather than by anything here, which is a real boundary and is worth stating rather than assuming. Within the mechanism, the lifetime question that does come up is a page leaving the ring: once the reader has swapped a page out, the writer will never touch it again [trace-ring-buffer-R2], and that guarantee is what makes reading safe without stopping anything.

- **refcount-zero.** There are no reference counts in this mechanism. Pages are owned by the ring or by the reader and never by both, and ownership moves by compare and swap rather than by counting.

- **boundary-cases.** The floor on buffer size is two sub buffers [trace-ring-buffer-R7], and the artefact is close to it at three, which is what makes the loss rate so extreme. A record larger than a sub buffer can never be stored and is refused in step 1. An empty buffer makes the reader's swap do nothing. The boundary that bites in practice is none of these: it is a buffer that is large enough to look fine on an idle machine and three orders of magnitude too small under load, which is the same buffer.

- **hostile-input.** Nothing here reads anything from userspace. The steering an unprivileged program can do is on the workload rather than on the mechanism, and it is significant: on a machine where tracing is on, a program that generates events quickly pushes everything else out of the buffer, and there is no fairness of any kind between the things being traced. A trace taken during a noisy workload is a trace of the noisy workload.

- **bug-message.** This mechanism prints almost nothing. Its warnings are internal consistency checks that fire when the structure it walks has come apart, and each of them switches nothing off and carries on. The two ceilings that produce one are the thousand retry limit in the reserve [trace-ring-buffer-R24] and the bounded commit walk [trace-ring-buffer-R73]. Neither is a message about the code being traced. The message a person actually wants, which is that events were lost, is not a warning at all. It is a counter [trace-ring-buffer-R42], two numbers in a header a reader skips [trace-ring-buffer-R76], and on one of the two read paths one line of output at the place it happened [trace-ring-buffer-R63].

## §7 Interfaces

Generated, and the block below says what from. Hand editing it fails the build.

<!-- bpc:generated section=7 hash=71c51beb310874db -->
<!-- bpc:source kind=btf path=kxbox/kernel/build/A-full/vmlinux evidence=true pin=v7.2.2 arch=i386 -->

Generated by bpc 0.2 from `kxbox/kernel/build/A-full/vmlinux`. Signatures are what the kernel's own type information records, so a parameter with no name here is a parameter BTF has no name for rather than one the blueprint forgot.

### Functions

| Symbol | Signature |
|---|---|
| `ring_buffer_alloc` | no symbol in this build, inlined or configured out |
| `__ring_buffer_alloc` | `static struct trace_buffer * __ring_buffer_alloc(long unsigned int size, unsigned int flags, struct lock_class_key *key)` |
| `ring_buffer_free` | `static void ring_buffer_free(struct trace_buffer *buffer)` |
| `ring_buffer_resize` | `static int ring_buffer_resize(struct trace_buffer *buffer, long unsigned int size, int cpu_id)` |
| `ring_buffer_size` | `static long unsigned int ring_buffer_size(struct trace_buffer *buffer, int cpu)` |
| `ring_buffer_lock_reserve` | `static struct ring_buffer_event * ring_buffer_lock_reserve(struct trace_buffer *buffer, long unsigned int length)` |
| `ring_buffer_unlock_commit` | `static int ring_buffer_unlock_commit(struct trace_buffer *buffer)` |
| `ring_buffer_write` | `static int ring_buffer_write(struct trace_buffer *buffer, long unsigned int length, void *data)` |
| `ring_buffer_event_data` | `static void * ring_buffer_event_data(struct ring_buffer_event *event)` |
| `ring_buffer_event_length` | `static unsigned int ring_buffer_event_length(struct ring_buffer_event *event)` |
| `ring_buffer_peek` | `static struct ring_buffer_event * ring_buffer_peek(struct trace_buffer *buffer, int cpu, u64 *ts, long unsigned int *lost_events)` |
| `ring_buffer_consume` | `static struct ring_buffer_event * ring_buffer_consume(struct trace_buffer *buffer, int cpu, u64 *ts, long unsigned int *lost_events)` |
| `ring_buffer_read_page` | `static int ring_buffer_read_page(struct trace_buffer *buffer, struct buffer_data_read_page *data_page, size_t len, int cpu, int full)` |
| `ring_buffer_iter_dropped` | `static bool ring_buffer_iter_dropped(struct ring_buffer_iter *iter)` |
| `ring_buffer_entries_cpu` | `static long unsigned int ring_buffer_entries_cpu(struct trace_buffer *buffer, int cpu)` |
| `ring_buffer_overrun_cpu` | `static long unsigned int ring_buffer_overrun_cpu(struct trace_buffer *buffer, int cpu)` |
| `ring_buffer_commit_overrun_cpu` | `static long unsigned int ring_buffer_commit_overrun_cpu(struct trace_buffer *buffer, int cpu)` |
| `ring_buffer_dropped_events_cpu` | `static long unsigned int ring_buffer_dropped_events_cpu(struct trace_buffer *buffer, int cpu)` |
| `ring_buffer_bytes_cpu` | `static long unsigned int ring_buffer_bytes_cpu(struct trace_buffer *buffer, int cpu)` |
| `ring_buffer_read_events_cpu` | `static long unsigned int ring_buffer_read_events_cpu(struct trace_buffer *buffer, int cpu)` |
| `ring_buffer_oldest_event_ts` | `static u64 ring_buffer_oldest_event_ts(struct trace_buffer *buffer, int cpu)` |
| `ring_buffer_time_stamp` | `static u64 ring_buffer_time_stamp(struct trace_buffer *buffer)` |
| `ring_buffer_record_disable` | `static void ring_buffer_record_disable(struct trace_buffer *buffer)` |
| `ring_buffer_record_enable` | `static void ring_buffer_record_enable(struct trace_buffer *buffer)` |
| `ring_buffer_change_overwrite` | `static void ring_buffer_change_overwrite(struct trace_buffer *buffer, int val)` |
| `ring_buffer_reset_cpu` | `static void ring_buffer_reset_cpu(struct trace_buffer *buffer, int cpu)` |
| `rb_reserve_next_event` | no symbol in this build, inlined or configured out |
| `__rb_reserve_next` | `static struct ring_buffer_event * __rb_reserve_next(struct ring_buffer_per_cpu *cpu_buffer, struct rb_event_info *info)` |
| `rb_move_tail` | `static struct ring_buffer_event * rb_move_tail(struct ring_buffer_per_cpu *cpu_buffer, long unsigned int tail, struct rb_event_info *info)` |
| `rb_handle_head_page` | no symbol in this build, inlined or configured out |
| `rb_set_head_page` | `static struct buffer_page * rb_set_head_page(struct ring_buffer_per_cpu *cpu_buffer)` |
| `rb_get_reader_page` | no symbol in this build, inlined or configured out |
| `rb_commit` | `static void rb_commit(struct ring_buffer_per_cpu *cpu_buffer)` |
| `rb_end_commit` | no symbol in this build, inlined or configured out |
| `rb_time_stamp` | no symbol in this build, inlined or configured out |
| `rb_add_time_stamp` | no symbol in this build, inlined or configured out |
| `rb_check_pages` | `static void rb_check_pages(struct ring_buffer_per_cpu *cpu_buffer)` |
| `trace_buffer_lock_reserve` | `static struct ring_buffer_event * trace_buffer_lock_reserve(struct trace_buffer *buffer, int type, long unsigned int len, unsigned int trace_ctx)` |
| `trace_function` | `static void trace_function(struct trace_array *tr, long unsigned int ip, long unsigned int parent_ip, unsigned int trace_ctx, struct ftrace_regs *fregs)` |
| `function_trace_call` | `static void function_trace_call(long unsigned int ip, long unsigned int parent_ip, struct ftrace_ops *op, struct ftrace_regs *fregs)` |
| `tracing_stats_read` | `static ssize_t tracing_stats_read(struct file *filp, char *ubuf, size_t count, loff_t *ppos)` |
<!-- bpc:end section=7 -->

## §8 Configuration and architecture dependence

Which symbols change what is written above:

- `CONFIG_RING_BUFFER` is the switch for the whole file. It is selected by tracing rather than chosen, and a kernel with tracing on always has it.
- `CONFIG_TRACING` brings the users. Without it the buffer is compiled and nothing calls it, which is a state worth knowing about because the memory is still described in section 2.
- `CONFIG_RING_BUFFER_ALLOW_SWAP` adds a check inside the reserve for the buffer having been swapped out from under the writer, which is how the latency tracers take a snapshot. It costs a read and a branch on every single event on a kernel that has it.
- `CONFIG_RING_BUFFER_RECORD_RECURSION` counts the events the recursion guard in step 2 refused. Without it those events are dropped and nothing anywhere says how many, which makes it the closest thing this mechanism has to a missing counter.
- `CONFIG_RING_BUFFER_VALIDATE_TIME_DELTAS` checks the timestamp arithmetic in step 7 as it runs. It is expensive and it is the only way to find out that the fast path in step 10 has gone wrong.
- `CONFIG_RING_BUFFER_PERSISTENT_INJECT` and the persistent buffer support are the one case where the missed events bit is set inside the write buffer [trace-ring-buffer-R62], which is to say the one case where invariant 11 does not hold.
- `CONFIG_TRACER_SNAPSHOT` gives the buffer a twin that gets resized alongside it, so a resize on a kernel with it costs twice the memory and can half fail.
- `CONFIG_ARCH_HAVE_NMI_SAFE_CMPXCHG` and `CONFIG_GENERIC_ATOMIC64` together decide step 3 [trace-ring-buffer-R21]. x86 has the first and not the second, so NMIs are traced on the pinned machine. On an architecture that fails the test, every NMI event is silently dropped, and no counter records it.
- `CONFIG_HAVE_64BIT_ALIGNED_ACCESS` changes the alignment records are rounded to in step 5, which changes how many fit on a page, which changes the loss rate in section 5. x86 does not set it.
- `CONFIG_MITIGATION_RETPOLINE` causes the timestamp read to test for the default clock and call it directly rather than through a function pointer, which is a performance detail that changes what a profile of this code looks like and nothing else.
- `CONFIG_SMP` and `CONFIG_NR_CPUS` decide how many of these buffers exist and therefore the total memory, and change nothing about the algorithm. The pinned machine has one processor, so every reader and writer race in section 3 was reasoned about here and not observed. That is stated plainly rather than glossed: this blueprint's evidence covers the counters and the loss behaviour, and does not cover the cross processor swap.

Architecture dependence:

Three places, and they are more consequential than in most of this project. The compare and swap in steps 16 and 18 is the architecture's own, and its behaviour in an NMI is the subject of step 3. The pointer tagging in step 16 assumes that a `list_head` address has its low two bits free, which is an alignment assumption every architecture Linux supports happens to satisfy and which a reimplementation on a machine with byte aligned structures could not make. And the twelve byte page header in section 5's arithmetic is twelve because a pointer is four bytes here; on a 64-bit build it is sixteen, so the same request in kilobytes gives a different number of usable bytes and the same experiment gives different numbers.

### The functions section 7 cannot find

Seven of the names in this blueprint's header have no symbol in the `A-full` build, and section 7 prints that rather than leaving them out. Six of them are `static` functions the compiler inlined: the retry loop around the reserve, the head page handler from step 16, the reader page swap from step 18, the commit close from step 12, and the clock read and the timestamp extension writer from step 7. Those are the same case the lock ordering blueprint documents, which is that the work happens and there is no frame to attach anything to.

The seventh is a different case and it is the more interesting one. `ring_buffer_alloc` is not a function at all. It is a macro [trace-ring-buffer-R12] that declares a static variable and calls the real function with its address [trace-ring-buffer-R13]. The variable is a lock class key, and it is there so that every ring buffer in the kernel gets a lock class of its own, which is the mechanism in the lock ordering blueprint reaching into this one. A name that every caller writes, that appears in no build, that is not missing and was never a function, is worth one paragraph in a specification because a reader who greps for it and finds nothing draws exactly the wrong conclusion.

## §9 Reimplementation notes

Forced by the problem rather than by Linux:

- That a writer cannot take a lock. Once you accept that the tracer has to work from an interrupt handler, an NMI and the inside of the scheduler, every synchronisation primitive that can wait is off the table, and what is left is one atomic operation per writer.
- That the buffer is per processor, and that a writer only ever writes to its own [trace-ring-buffer-R1]. A shared buffer needs the writers to agree with each other, and agreeing costs either a lock or a contended atomic on the hottest path in the machine. Splitting per processor removes the writer to writer problem entirely and pays for it by making the reader assemble a merged order afterwards.
- That a full buffer has to do something and neither option is good. Losing the oldest or losing the newest is a real choice with no third answer, and any implementation has to pick one and count what it did.

Choices Linux made that another kernel could make differently:

- **Overwrite as the default** [trace-ring-buffer-R38]. Keeping the newest events means the trace covers the moment you were interested in, and it means a trace of an overloaded system is a trace of its last few milliseconds. A kernel could default the other way, which would make a full buffer stop recording and leave the beginning intact. Both are defensible and the counters are named after the choice, which is why one of them is always zero and reading the wrong one is such a common mistake.

- **Not telling the writer** [trace-ring-buffer-R42]. The reserve returns a valid pointer on the path where a whole page was thrown out. The writer that caused the loss is never told, and neither is the writer whose events were lost, since it finished long ago. A kernel could return a flag on the reserve, which would cost a branch on the hottest path in the tracer to deliver news that no caller could act on anyway. Linux put it in a counter, and the cost of that is section 5.

- **Two read paths, each of which tells you half** [trace-ring-buffer-R57] [trace-ring-buffer-R58]. The consuming reader carries an exact count out to the place the loss happened and prints it there [trace-ring-buffer-R63], and has no header. The iterating reader has a flag that is never set, so it marks nothing in the body, and its file prints a total in a header computed separately from the same counters [trace-ring-buffer-R77]. Neither of them gives a reader both numbers. That is not a design somebody sat down and chose, it is two mechanisms that grew separately, and the result is that the same buffer read two ways is described two different ways. A kernel starting fresh would give both readers both answers, and doing it here would cost the writer nothing, because everything either of them would need is already being maintained.

- **Tagging pointers with the state of a lockless protocol** [trace-ring-buffer-R47]. It costs no memory and it makes the compare and swap that moves the head atomic with the check that it is the head. The price is that the head pointer cannot be trusted on its own [trace-ring-buffer-R49] and every piece of code that walks the list has to mask the bits off, which is a class of bug that does not exist in an implementation with a separate state word. A kernel could keep the state in the page structure instead and accept a second atomic.

- **The reader page swap rather than a copy** [trace-ring-buffer-R52]. Reading a trace moves a pointer and copies nothing, which is what lets a reader keep up with a tracer that is filling pages faster than they can be formatted. The cost is the entire protocol in step 16, because the reader is now editing the same list the writers are walking. A kernel could copy under the reader lock and delete most of the difficulty in this file, at the price of a memory copy per page and a much shorter distance between the tracer and the point where reading falls behind.

- **A four byte event header with a twenty seven bit delta** [trace-ring-buffer-R30]. Timestamps are almost always small differences, so storing a difference rather than a reading saves four bytes on every event in the machine. The price is the whole of step 7: an occasional extension record, a fast path and a slow path, two saved timestamps per processor, and a piece of reasoning about interrupts landing between two labelled statements that is among the harder things in the tracing subsystem to be sure about. A kernel could store a full timestamp on every event and delete that reasoning, at a cost of about a quarter of the buffer. The header is also small enough that the kernel does not describe it with a header file: the field widths are printed to userspace by hand from one function, with a comment saying so and asking whoever changes the layout to keep the two in step [trace-ring-buffer-R75].
