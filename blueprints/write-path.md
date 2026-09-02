---
blueprint: write-path
title: The buffered write path
status: partial
pin: v7.2.2
arch: i386
lessons: []
generated: [2, 5, 7]
config-dependent: [CONFIG_SECURITY, CONFIG_FSNOTIFY, CONFIG_TASK_XACCT, CONFIG_TASK_IO_ACCOUNTING, CONFIG_MEMCG, CONFIG_FS_DAX, CONFIG_TRANSPARENT_HUGEPAGE, CONFIG_BLOCK, CONFIG_TMPFS]
structures: [file, kiocb, iov_iter, address_space, folio]
interfaces: [ksys_write, vfs_write, rw_verify_area, generic_write_checks, generic_write_checks_count, file_remove_privs, file_update_time, generic_file_write_iter, __generic_file_write_iter, generic_perform_write, shmem_file_write_iter, shmem_write_begin, shmem_write_end, balance_dirty_pages_ratelimited, folio_mark_dirty, copy_folio_from_iter_atomic, shmem_get_folio, new_sync_write]
ops: [file_operations, address_space_operations]
artefacts: [traces/tier0/write-1byte, traces/tier0/two-writes]
---

# The buffered write path

**Status is `partial`, and this is what that means here.** All thirty seven citations in `write-path.refs.toml` resolve against the pinned 7.2.2 source, and every anchor in it matches exactly one line in the file it names. There were thirty eight, and the one that went is worth a sentence: the line that caps the write size appears three times in one file, word for word, so there is no anchor that finds it and only it, and the comment in the citations file says so rather than leaving a confident anchor that would silently point at the read path. Sections 2 and 7 come out of the BTF of the kernel this project boots, and section 5 comes from two captures taken on that kernel. What is left is a person. `complete` needs a name in `reviewed-by`, and nobody has read this through yet.

One thing about this mechanism is worth saying before anything else, because it is the thing readers get wrong and it is not a detail. A `write` that returns 1 has not written anything to a disk. It has copied one byte into a folio in the page cache and set a flag on that folio, and then it returned. Everything that gets the byte to storage happens later, on a different thread, at a time nothing in this path chooses. The whole of section 3 is arranged around finding that ending rather than sliding past it.

The picture below is the descent in one frame, with the line across it marking where the system call returns.

![A descent down the left side of the picture, from the write system call to a dirty folio in the page cache, with a note on the right of each step saying what it decides. From the top: the write system call looks up the file descriptor; vfs_write checks the file is open for writing and asks the security modules; the file operations table is consulted, and a box off to the side notes that a file with a write_iter but no write is wrapped in a kiocb and an iov_iter, which is nearly every file; the filesystem's write_iter takes the inode lock, checks the size limits, drops setuid bits and updates the modification time; then generic_perform_write, whose three steps are drawn below it and repeat once per folio, which are write_begin to find or allocate the folio, an atomic copy of the bytes in from userspace, and write_end to mark it dirty and unlock it. Underneath is a red band across the whole width reading that the system call returns here and the byte is in memory with a dirty flag on it. Below that band, in grey, are the three things that happen later and on another thread: writeback finds the dirty folio, the filesystem builds block requests, and the device stores it. Notes at the bottom say that a write returning 1 has promised one byte is in the page cache and nothing more, and that fsync is what turns that into a promise about storage.](assets/write-path-descent.svg)

## §1 Purpose and boundary

This mechanism owns everything between a program calling `write` and one folio in the page cache holding the new bytes with a dirty flag set on it. It is responsible for finding the file behind the descriptor, refusing the calls that have to be refused, deciding how much of the request can be satisfied, and handing the bytes to the filesystem in units the filesystem can work in.

It deserves a specification of its own because it is the busiest path in the kernel that is allowed to return before the work is finished. The system call has to leave the machine in a state where somebody else can finish the job later and where a reader of the file in the meantime sees the new bytes rather than the old ones. Those two requirements together are why the page cache exists, and they are the reason this path ends where it does.

What it is not responsible for:

- Getting the bytes to storage. That is the `writeback` blueprint. This path sets a flag and returns.
- Making a durability promise. That is the `fsync` blueprint, which is a separate system call with a separate mechanism.
- Finding or allocating the folio itself, and the rules for what lives in the page cache. That is the `page-cache` blueprint. This path asks for a folio and takes what it is given.
- Turning a descriptor number into a `struct file`, and what happens when two threads share one. That is the `file-descriptors` blueprint.
- Writes that skip the page cache entirely. That is the `direct-io` blueprint, and section 3 says where those leave.
- Deciding when a writer has to wait for writeback to catch up. That is the `dirty-throttling` blueprint. This path calls into it once per folio and can sleep there.
- What the filesystem does with the folio after it is dirty. That is each filesystem's own blueprint.
- The fault taken when the source buffer is not resident. That is the `page-fault` blueprint, and section 4c says why the interaction between the two is the sharpest constraint in this path.

## §2 Data structures

Generated, and the block below says what from. Hand editing it fails the build.

<!-- bpc:generated section=2 hash=d4d716356a3729f2 -->
<!-- bpc:source kind=btf path=kxbox/kernel/build/A-full/vmlinux evidence=true pin=v7.2.2 arch=i386 -->

Generated by bpc 0.2 from `kxbox/kernel/build/A-full/vmlinux`, for i386 with 4 byte pointers. Offsets are byte offsets from the start of the structure. A hole is padding the compiler inserted and not a field you can use.

### struct file

104 bytes, 47 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 0 | `f_lock` | `spinlock_t` |
| 0 | 0 | `f_lock.rlock` | `struct raw_spinlock` |
| 0 | 0 | `f_lock.rlock.raw_lock` | `arch_spinlock_t` |
| 0 | 4 | `f_mode` | `fmode_t` |
| 4 | 4 | `f_op` | `const struct file_operations *` |
| 8 | 4 | `f_mapping` | `struct address_space *` |
| 12 | 4 | `private_data` | `void *` |
| 16 | 4 | `f_inode` | `struct inode *` |
| 20 | 4 | `f_flags` | `unsigned int` |
| 24 | 4 | `f_iocb_flags` | `unsigned int` |
| 28 | 4 | `f_cred` | `const struct cred *` |
| 32 | 4 | `f_owner` | `struct fown_struct *` |
| 36 | 8 | `f_path` | `const struct path` |
| 36 | 4 | `f_path.mnt` | `struct vfsmount *` |
| 36 | 8 | `__f_path` | `struct path` |
| 36 | 4 | `__f_path.mnt` | `struct vfsmount *` |
| 40 | 4 | `f_path.dentry` | `struct dentry *` |
| 40 | 4 | `__f_path.dentry` | `struct dentry *` |
| 44 | 8 | `f_pos_lock` | `struct mutex` |
| 44 | 4 | `f_pos_lock.owner` | `atomic_long_t` |
| 44 | 4 | `f_pos_lock.owner.counter` | `int` |
| 44 | 8 | `f_pipe` | `u64` |
| 48 | 0 | `f_pos_lock.wait_lock` | `raw_spinlock_t` |
| 48 | 0 | `f_pos_lock.wait_lock.raw_lock` | `arch_spinlock_t` |
| 48 | 4 | `f_pos_lock.first_waiter` | `struct mutex_waiter *` |
| 52 | 8 | `f_pos` | `loff_t` |
| 60 | 4 | `f_wb_err` | `errseq_t` |
| 64 | 4 | `f_sb_err` | `errseq_t` |
| 68 | 4 | `f_ep` | `struct hlist_head *` |
| 72 | 8 | `f_task_work` | `struct callback_head` |
| 72 | 4 | `f_task_work.next` | `struct callback_head *` |
| 72 | 4 | `f_llist` | `struct llist_node` |
| 72 | 4 | `f_llist.next` | `struct llist_node *` |
| 72 | 28 | `f_ra` | `struct file_ra_state` |
| 72 | 4 | `f_ra.start` | `long unsigned int` |
| 72 | 4 | `f_freeptr` | `freeptr_t` |
| 72 | 4 | `f_freeptr.v` | `long unsigned int` |
| 76 | 4 | `f_task_work.func` | `void (struct callback_head *) *` |
| 76 | 4 | `f_ra.size` | `unsigned int` |
| 80 | 4 | `f_ra.async_size` | `unsigned int` |
| 84 | 4 | `f_ra.ra_pages` | `unsigned int` |
| 88 | 2 | `f_ra.order` | `short unsigned int` |
| 90 | 2 | `f_ra.mmap_miss` | `short unsigned int` |
| 92 | 8 | `f_ra.prev_pos` | `loff_t` |
| 100 | 4 | `f_ref` | `file_ref_t` |
| 100 | 4 | `f_ref.refcnt` | `atomic_t` |
| 100 | 4 | `f_ref.refcnt.counter` | `int` |

### struct kiocb

32 bytes, 8 field(s), 1 bytes of padding in 1 hole(s).

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 4 | `ki_filp` | `struct file *` |
| 4 | 8 | `ki_pos` | `loff_t` |
| 12 | 4 | `ki_complete` | `void (struct kiocb *, long int) *` |
| 16 | 4 | `private` | `void *` |
| 20 | 4 | `ki_flags` | `int` |
| 24 | 2 | `ki_ioprio` | `u16` |
| 26 | 1 | `ki_write_stream` | `u8` |
| 28 | 4 | `ki_waitq` | `struct wait_page_queue *` |

- 1 byte hole at offset 27, after `ki_write_stream`.

### struct iov_iter

24 bytes, 17 field(s), 1 bytes of padding in 1 hole(s).

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 1 | `iter_type` | `u8` |
| 1 | 1 | `nofault` | `bool` |
| 2 | 1 | `data_source` | `bool` |
| 4 | 4 | `iov_offset` | `size_t` |
| 8 | 8 | `__ubuf_iovec` | `struct iovec` |
| 8 | 4 | `__ubuf_iovec.iov_base` | `void *` |
| 8 | 4 | `__iov` | `const struct iovec *` |
| 8 | 4 | `kvec` | `const struct kvec *` |
| 8 | 4 | `bvec` | `const struct bio_vec *` |
| 8 | 4 | `folioq` | `const struct folio_queue *` |
| 8 | 4 | `xarray` | `struct xarray *` |
| 8 | 4 | `ubuf` | `void *` |
| 12 | 4 | `__ubuf_iovec.iov_len` | `__kernel_size_t` |
| 12 | 4 | `count` | `size_t` |
| 16 | 4 | `nr_segs` | `long unsigned int` |
| 16 | 1 | `folioq_slot` | `u8` |
| 16 | 8 | `xarray_start` | `loff_t` |

- 1 byte hole at offset 3, after `data_source`.

### struct address_space

72 bytes, 38 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 4 | `host` | `struct inode *` |
| 4 | 8 | `i_pages` | `struct xarray` |
| 4 | 0 | `i_pages.xa_lock` | `spinlock_t` |
| 4 | 0 | `i_pages.xa_lock.rlock` | `struct raw_spinlock` |
| 4 | 0 | `i_pages.xa_lock.rlock.raw_lock` | `arch_spinlock_t` |
| 4 | 4 | `i_pages.xa_flags` | `gfp_t` |
| 8 | 4 | `i_pages.xa_head` | `void *` |
| 12 | 12 | `invalidate_lock` | `struct rw_semaphore` |
| 12 | 4 | `invalidate_lock.count` | `atomic_long_t` |
| 12 | 4 | `invalidate_lock.count.counter` | `int` |
| 16 | 4 | `invalidate_lock.owner` | `atomic_long_t` |
| 16 | 4 | `invalidate_lock.owner.counter` | `int` |
| 20 | 0 | `invalidate_lock.wait_lock` | `raw_spinlock_t` |
| 20 | 0 | `invalidate_lock.wait_lock.raw_lock` | `arch_spinlock_t` |
| 20 | 4 | `invalidate_lock.first_waiter` | `struct rwsem_waiter *` |
| 24 | 4 | `gfp_mask` | `gfp_t` |
| 28 | 4 | `i_mmap_writable` | `atomic_t` |
| 28 | 4 | `i_mmap_writable.counter` | `int` |
| 32 | 8 | `i_mmap` | `struct rb_root_cached` |
| 32 | 4 | `i_mmap.rb_root` | `struct rb_root` |
| 32 | 4 | `i_mmap.rb_root.rb_node` | `struct rb_node *` |
| 36 | 4 | `i_mmap.rb_leftmost` | `struct rb_node *` |
| 40 | 4 | `nrpages` | `long unsigned int` |
| 44 | 4 | `writeback_index` | `long unsigned int` |
| 48 | 4 | `a_ops` | `const struct address_space_operations *` |
| 52 | 4 | `flags` | `long unsigned int` |
| 56 | 4 | `wb_err` | `errseq_t` |
| 60 | 0 | `i_private_lock` | `spinlock_t` |
| 60 | 0 | `i_private_lock.rlock` | `struct raw_spinlock` |
| 60 | 0 | `i_private_lock.rlock.raw_lock` | `arch_spinlock_t` |
| 60 | 12 | `i_mmap_rwsem` | `struct rw_semaphore` |
| 60 | 4 | `i_mmap_rwsem.count` | `atomic_long_t` |
| 60 | 4 | `i_mmap_rwsem.count.counter` | `int` |
| 64 | 4 | `i_mmap_rwsem.owner` | `atomic_long_t` |
| 64 | 4 | `i_mmap_rwsem.owner.counter` | `int` |
| 68 | 0 | `i_mmap_rwsem.wait_lock` | `raw_spinlock_t` |
| 68 | 0 | `i_mmap_rwsem.wait_lock.raw_lock` | `arch_spinlock_t` |
| 68 | 4 | `i_mmap_rwsem.first_waiter` | `struct rwsem_waiter *` |

### struct folio

128 bytes, 187 field(s), no padding.

| Offset | Size | Field | Type |
|---|---|---|---|
| 0 | 4 | `flags` | `memdesc_flags_t` |
| 0 | 4 | `flags.f` | `long unsigned int` |
| 0 | 32 | `page` | `struct page` |
| 0 | 4 | `page.flags` | `memdesc_flags_t` |
| 0 | 4 | `page.flags.f` | `long unsigned int` |
| 4 | 8 | `lru` | `struct list_head` |
| 4 | 4 | `lru.next` | `struct list_head *` |
| 4 | 4 | `__filler` | `void *` |
| 4 | 4 | `pgmap` | `struct dev_pagemap *` |
| 4 | 8 | `page.lru` | `struct list_head` |
| 4 | 4 | `page.lru.next` | `struct list_head *` |
| 4 | 8 | `page.buddy_list` | `struct list_head` |
| 4 | 4 | `page.buddy_list.next` | `struct list_head *` |
| 4 | 8 | `page.pcp_list` | `struct list_head` |
| 4 | 4 | `page.pcp_list.next` | `struct list_head *` |
| 4 | 4 | `page.pcp_llist` | `struct llist_node` |
| 4 | 4 | `page.pcp_llist.next` | `struct llist_node *` |
| 4 | 4 | `page.pp_magic` | `long unsigned int` |
| 4 | 4 | `page.compound_info` | `long unsigned int` |
| 4 | 4 | `page._unused_pgmap_compound_info` | `void *` |
| 4 | 8 | `page.callback_head` | `struct callback_head` |
| 4 | 4 | `page.callback_head.next` | `struct callback_head *` |
| 8 | 4 | `lru.prev` | `struct list_head *` |
| 8 | 4 | `mlock_count` | `unsigned int` |
| 8 | 4 | `page.lru.prev` | `struct list_head *` |
| 8 | 4 | `page.buddy_list.prev` | `struct list_head *` |
| 8 | 4 | `page.pcp_list.prev` | `struct list_head *` |
| 8 | 4 | `page.pp` | `struct page_pool *` |
| 8 | 4 | `page.zone_device_data` | `void *` |
| 8 | 4 | `page.callback_head.func` | `void (struct callback_head *) *` |
| 12 | 4 | `mapping` | `struct address_space *` |
| 12 | 4 | `page.mapping` | `struct address_space *` |
| 12 | 4 | `page._pp_mapping_pad` | `long unsigned int` |
| 16 | 4 | `index` | `long unsigned int` |
| 16 | 4 | `share` | `long unsigned int` |
| 16 | 4 | `page.__folio_index` | `long unsigned int` |
| 16 | 4 | `page.share` | `long unsigned int` |
| 16 | 4 | `page.dma_addr` | `long unsigned int` |
| 20 | 4 | `private` | `void *` |
| 20 | 4 | `swap` | `swp_entry_t` |
| 20 | 4 | `swap.val` | `long unsigned int` |
| 20 | 4 | `page.private` | `long unsigned int` |
| 20 | 4 | `page.pp_ref_count` | `atomic_long_t` |
| 20 | 4 | `page.pp_ref_count.counter` | `int` |
| 24 | 4 | `_mapcount` | `atomic_t` |
| 24 | 4 | `_mapcount.counter` | `int` |
| 24 | 4 | `page.page_type` | `unsigned int` |
| 24 | 4 | `page._mapcount` | `atomic_t` |
| 24 | 4 | `page._mapcount.counter` | `int` |
| 28 | 4 | `_refcount` | `atomic_t` |
| 28 | 4 | `_refcount.counter` | `int` |
| 28 | 4 | `page._refcount` | `atomic_t` |
| 28 | 4 | `page._refcount.counter` | `int` |
| 32 | 4 | `_flags_1` | `long unsigned int` |
| 32 | 32 | `__page_1` | `struct page` |
| 32 | 4 | `__page_1.flags` | `memdesc_flags_t` |
| 32 | 4 | `__page_1.flags.f` | `long unsigned int` |
| 36 | 4 | `_head_1` | `long unsigned int` |
| 36 | 8 | `__page_1.lru` | `struct list_head` |
| 36 | 4 | `__page_1.lru.next` | `struct list_head *` |
| 36 | 8 | `__page_1.buddy_list` | `struct list_head` |
| 36 | 4 | `__page_1.buddy_list.next` | `struct list_head *` |
| 36 | 8 | `__page_1.pcp_list` | `struct list_head` |
| 36 | 4 | `__page_1.pcp_list.next` | `struct list_head *` |
| 36 | 4 | `__page_1.pcp_llist` | `struct llist_node` |
| 36 | 4 | `__page_1.pcp_llist.next` | `struct llist_node *` |
| 36 | 4 | `__page_1.pp_magic` | `long unsigned int` |
| 36 | 4 | `__page_1.compound_info` | `long unsigned int` |
| 36 | 4 | `__page_1._unused_pgmap_compound_info` | `void *` |
| 36 | 8 | `__page_1.callback_head` | `struct callback_head` |
| 36 | 4 | `__page_1.callback_head.next` | `struct callback_head *` |
| 40 | 4 | `_large_mapcount` | `atomic_t` |
| 40 | 4 | `_large_mapcount.counter` | `int` |
| 40 | 16 | `_usable_1` | `long unsigned int[4]` |
| 40 | 4 | `__page_1.lru.prev` | `struct list_head *` |
| 40 | 4 | `__page_1.buddy_list.prev` | `struct list_head *` |
| 40 | 4 | `__page_1.pcp_list.prev` | `struct list_head *` |
| 40 | 4 | `__page_1.pp` | `struct page_pool *` |
| 40 | 4 | `__page_1.zone_device_data` | `void *` |
| 40 | 4 | `__page_1.callback_head.func` | `void (struct callback_head *) *` |
| 44 | 4 | `_nr_pages_mapped` | `atomic_t` |
| 44 | 4 | `_nr_pages_mapped.counter` | `int` |
| 44 | 4 | `__page_1.mapping` | `struct address_space *` |
| 44 | 4 | `__page_1._pp_mapping_pad` | `long unsigned int` |
| 48 | 4 | `_mm_id_mapcount` | `mm_id_mapcount_t[2]` |
| 48 | 4 | `__page_1.__folio_index` | `long unsigned int` |
| 48 | 4 | `__page_1.share` | `long unsigned int` |
| 48 | 4 | `__page_1.dma_addr` | `long unsigned int` |
| 52 | 4 | `_mm_id` | `mm_id_t[2]` |
| 52 | 4 | `_mm_ids` | `long unsigned int` |
| 52 | 4 | `__page_1.private` | `long unsigned int` |
| 52 | 4 | `__page_1.pp_ref_count` | `atomic_long_t` |
| 52 | 4 | `__page_1.pp_ref_count.counter` | `int` |
| 56 | 4 | `_mapcount_1` | `atomic_t` |
| 56 | 4 | `_mapcount_1.counter` | `int` |
| 56 | 4 | `__page_1.page_type` | `unsigned int` |
| 56 | 4 | `__page_1._mapcount` | `atomic_t` |
| 56 | 4 | `__page_1._mapcount.counter` | `int` |
| 60 | 4 | `_refcount_1` | `atomic_t` |
| 60 | 4 | `_refcount_1.counter` | `int` |
| 60 | 4 | `__page_1._refcount` | `atomic_t` |
| 60 | 4 | `__page_1._refcount.counter` | `int` |
| 64 | 4 | `_flags_2` | `long unsigned int` |
| 64 | 32 | `__page_2` | `struct page` |
| 64 | 4 | `__page_2.flags` | `memdesc_flags_t` |
| 64 | 4 | `__page_2.flags.f` | `long unsigned int` |
| 68 | 4 | `_head_2` | `long unsigned int` |
| 68 | 8 | `__page_2.lru` | `struct list_head` |
| 68 | 4 | `__page_2.lru.next` | `struct list_head *` |
| 68 | 8 | `__page_2.buddy_list` | `struct list_head` |
| 68 | 4 | `__page_2.buddy_list.next` | `struct list_head *` |
| 68 | 8 | `__page_2.pcp_list` | `struct list_head` |
| 68 | 4 | `__page_2.pcp_list.next` | `struct list_head *` |
| 68 | 4 | `__page_2.pcp_llist` | `struct llist_node` |
| 68 | 4 | `__page_2.pcp_llist.next` | `struct llist_node *` |
| 68 | 4 | `__page_2.pp_magic` | `long unsigned int` |
| 68 | 4 | `__page_2.compound_info` | `long unsigned int` |
| 68 | 4 | `__page_2._unused_pgmap_compound_info` | `void *` |
| 68 | 8 | `__page_2.callback_head` | `struct callback_head` |
| 68 | 4 | `__page_2.callback_head.next` | `struct callback_head *` |
| 72 | 8 | `_deferred_list` | `struct list_head` |
| 72 | 4 | `_deferred_list.next` | `struct list_head *` |
| 72 | 4 | `__page_2.lru.prev` | `struct list_head *` |
| 72 | 4 | `__page_2.buddy_list.prev` | `struct list_head *` |
| 72 | 4 | `__page_2.pcp_list.prev` | `struct list_head *` |
| 72 | 4 | `__page_2.pp` | `struct page_pool *` |
| 72 | 4 | `__page_2.zone_device_data` | `void *` |
| 72 | 4 | `__page_2.callback_head.func` | `void (struct callback_head *) *` |
| 76 | 4 | `_deferred_list.prev` | `struct list_head *` |
| 76 | 4 | `__page_2.mapping` | `struct address_space *` |
| 76 | 4 | `__page_2._pp_mapping_pad` | `long unsigned int` |
| 80 | 4 | `_entire_mapcount` | `atomic_t` |
| 80 | 4 | `_entire_mapcount.counter` | `int` |
| 80 | 4 | `__page_2.__folio_index` | `long unsigned int` |
| 80 | 4 | `__page_2.share` | `long unsigned int` |
| 80 | 4 | `__page_2.dma_addr` | `long unsigned int` |
| 84 | 4 | `_pincount` | `atomic_t` |
| 84 | 4 | `_pincount.counter` | `int` |
| 84 | 4 | `__page_2.private` | `long unsigned int` |
| 84 | 4 | `__page_2.pp_ref_count` | `atomic_long_t` |
| 84 | 4 | `__page_2.pp_ref_count.counter` | `int` |
| 88 | 4 | `__page_2.page_type` | `unsigned int` |
| 88 | 4 | `__page_2._mapcount` | `atomic_t` |
| 88 | 4 | `__page_2._mapcount.counter` | `int` |
| 92 | 4 | `__page_2._refcount` | `atomic_t` |
| 92 | 4 | `__page_2._refcount.counter` | `int` |
| 96 | 4 | `_flags_3` | `long unsigned int` |
| 96 | 32 | `__page_3` | `struct page` |
| 96 | 4 | `__page_3.flags` | `memdesc_flags_t` |
| 96 | 4 | `__page_3.flags.f` | `long unsigned int` |
| 100 | 4 | `_head_3` | `long unsigned int` |
| 100 | 8 | `__page_3.lru` | `struct list_head` |
| 100 | 4 | `__page_3.lru.next` | `struct list_head *` |
| 100 | 8 | `__page_3.buddy_list` | `struct list_head` |
| 100 | 4 | `__page_3.buddy_list.next` | `struct list_head *` |
| 100 | 8 | `__page_3.pcp_list` | `struct list_head` |
| 100 | 4 | `__page_3.pcp_list.next` | `struct list_head *` |
| 100 | 4 | `__page_3.pcp_llist` | `struct llist_node` |
| 100 | 4 | `__page_3.pcp_llist.next` | `struct llist_node *` |
| 100 | 4 | `__page_3.pp_magic` | `long unsigned int` |
| 100 | 4 | `__page_3.compound_info` | `long unsigned int` |
| 100 | 4 | `__page_3._unused_pgmap_compound_info` | `void *` |
| 100 | 8 | `__page_3.callback_head` | `struct callback_head` |
| 100 | 4 | `__page_3.callback_head.next` | `struct callback_head *` |
| 104 | 4 | `_hugetlb_subpool` | `void *` |
| 104 | 4 | `__page_3.lru.prev` | `struct list_head *` |
| 104 | 4 | `__page_3.buddy_list.prev` | `struct list_head *` |
| 104 | 4 | `__page_3.pcp_list.prev` | `struct list_head *` |
| 104 | 4 | `__page_3.pp` | `struct page_pool *` |
| 104 | 4 | `__page_3.zone_device_data` | `void *` |
| 104 | 4 | `__page_3.callback_head.func` | `void (struct callback_head *) *` |
| 108 | 4 | `_hugetlb_cgroup` | `void *` |
| 108 | 4 | `__page_3.mapping` | `struct address_space *` |
| 108 | 4 | `__page_3._pp_mapping_pad` | `long unsigned int` |
| 112 | 4 | `_hugetlb_cgroup_rsvd` | `void *` |
| 112 | 4 | `__page_3.__folio_index` | `long unsigned int` |
| 112 | 4 | `__page_3.share` | `long unsigned int` |
| 112 | 4 | `__page_3.dma_addr` | `long unsigned int` |
| 116 | 4 | `_hugetlb_hwpoison` | `void *` |
| 116 | 4 | `__page_3.private` | `long unsigned int` |
| 116 | 4 | `__page_3.pp_ref_count` | `atomic_long_t` |
| 116 | 4 | `__page_3.pp_ref_count.counter` | `int` |
| 120 | 4 | `__page_3.page_type` | `unsigned int` |
| 120 | 4 | `__page_3._mapcount` | `atomic_t` |
| 120 | 4 | `__page_3._mapcount.counter` | `int` |
| 124 | 4 | `__page_3._refcount` | `atomic_t` |
| 124 | 4 | `__page_3._refcount.counter` | `int` |
<!-- bpc:end section=2 -->

## §3 Algorithms

Numbered from the system call. Steps 1 to 7 are the VFS and are the same for every file on every filesystem. Steps 8 to 12 are the filesystem's own entry point, and what is written here is the shape nearly all of them share rather than the text of any one of them. Steps 13 to 21 are the page cache loop, which is shared code again, and steps 22 and 23 are the tail after it.

1. The system call arrives with three arguments: a descriptor number, a userspace address and a count [write-path-R1]. The return value is a count of bytes and not a success flag, and every difference between this mechanism and the one a reader expects comes back to that.

2. Look up the descriptor and take the file position [write-path-R2]. The position lives in the `struct file` and not in the descriptor, so two descriptors made by `dup` share one position and two made by opening the same file twice do not. The position is read here, the write happens, and the position is written back afterwards with the number of bytes that actually went in.

3. Enter the VFS [write-path-R3]. Four things are refused here, and they are the refusals that do not need to ask the filesystem anything: the file was not opened for writing, the file has no way to be written at all, the userspace address is not readable, and the checks in the next step said no.

4. Run the position and count checks [write-path-R4]. This is also where two subsystems outside the filesystem get to refuse the write: the security modules, and the file notification machinery, which can have a watch on this file that has to be told about the access before it happens.

5. Cap the count, back in `vfs_write` [write-path-R3]. A write larger than the cap is not refused. It is shortened, and the caller finds out by comparing the return value against what it asked for. The cap is a little under two gigabytes [write-path-R6], and it is the same number on a 64-bit kernel, because the return type in the ABI is signed and 32 bits wide.

6. Dispatch through the file operations table [write-path-R8]. A file with a `write` operation is called directly. A file with only `write_iter`, which is nearly all of them, goes through an adapter that builds a `kiocb` and an `iov_iter` on the stack [write-path-R7] and calls the iterator form. Nothing is allocated to do this, which is why the adapter costs nothing worth measuring, and section 8 says why the adapter does not appear in a trace of the pinned kernel.

7. Take the filesystem's freeze protection for the whole write [write-path-R9]. This is a real lock and it is held across everything below. A filesystem being frozen for a snapshot makes writers wait here rather than fail, and a write already past this point keeps its right to finish.

8. Enter the filesystem [write-path-R10]. The generic version most filesystems use [write-path-R11] does four things in order: take the inode lock, run the checks in steps 9 and 10, do the write, drop the lock. Inside the lock [write-path-R12] there is one split worth knowing about, which is that a file opened with `O_DIRECT` leaves here for a different mechanism and never reaches the page cache loop.

9. Run the checks every buffered write goes through [write-path-R13]. Refuse a write to a file being used as swap, apply `O_APPEND` [write-path-R14], and refuse a non blocking write the filesystem cannot do without blocking. `O_APPEND` is one line [write-path-R15]: the position is set to the current end of the file, read with the inode lock held, which is the entire reason two processes appending to one file do not overwrite each other.

10. Check the size limits [write-path-R16]. There are two, the filesystem's own maximum file size and the process resource limit, and they fail differently. Going past the filesystem's limit shortens or refuses the write. Going past the resource limit also sends `SIGXFSZ` to the calling thread, which is the one signal this path can generate on its own.

11. Drop the setuid and setgid bits, because the file is being modified [write-path-R17]. This runs on every write to every file, including the overwhelming majority that have neither bit set, and on the pinned machine it costs more than every other check in this path put together, because dropping the bits means asking the filesystem for an extended attribute and that means a walk through the attribute handlers. The capture in section 5 has it at 105 microseconds of emulated time, behind only the folio allocation.

12. Update the modification timestamp [write-path-R18]. It is skipped when the clock has not moved since the last update, so whether it appears in a trace is a fact about when somebody ran the trace rather than a fact about the code.

13. Enter the loop that does the work [write-path-R19]. Everything above this was checking and everything below it is the page cache. The loop runs once per folio, so a one byte write runs it once and a one megabyte write runs it as many times as it takes.

14. At the top of each turn, ask whether this writer should be made to wait [write-path-R26]. The decision is made from a per CPU count of how many pages this CPU has dirtied since it last looked [write-path-R27], so most calls do nothing at all. The call that does not can sleep for as long as writeback needs, and the tracepoint that fires there [write-path-R37] is the only place in the kernel that reports how long a writer waited and why.

15. Look for a fatal signal [write-path-R25]. This is the only place in the loop a signal is looked at. It happens once per turn, before anything has been locked, and it is fatal signals only, so an ordinary signal does not interrupt a write that is already running.

16. Work out how much to attempt this turn [write-path-R20], and call the filesystem's `write_begin` [write-path-R21]. The chunk is the largest folio this mapping supports rather than one page, which is why a large write can need far fewer turns of the loop than its size in pages suggests. `write_begin` comes back with a folio that is locked, and that folio belongs to the caller until `write_end` hands it back. The loop then works the offset and the byte count out again from the folio it was actually given, because the folio can be smaller than the chunk that was asked for.

17. Flush the cache before the copy, but only when the same file is also mapped into somebody's address space [write-path-R23]. On a machine whose data cache is indexed by virtual address, skipping this would let the writer and the mapper see different bytes at the same offset in the same file. There is a second flush after the copy, and that one is unconditional, because the bytes have to reach the folio before anyone else looks at it.

18. Copy the bytes in [write-path-R22]. This is the one line in the path that is not allowed to sleep, and section 4c is about why.

19. Call `write_end` [write-path-R24]. This decides how much of the copy counted, and there are three answers. Counting all of it is the ordinary case. Counting some of it makes the loop rewind the iterator by the difference and carry on. Counting none of it is the interesting one: the loop halves the chunk size, and either tries the same position again with the smaller amount, or, when nothing was copied at all, tries to fault the source buffer in from here, where the folio is unlocked and faulting is safe. A buffer that cannot be faulted in even then ends the write with `EFAULT`. For the filesystem the pinned machine uses, this step is where the file grows, where the rest of a partly written folio is zeroed, where the folio is marked dirty and where it is unlocked [write-path-R31], and the order of those four is what the rest of the kernel depends on.

20. Marking it dirty [write-path-R32] is the last thing that happens to the data inside the system call, and the tracepoint that fires there [write-path-R36] is the observable event closest to the end of this path. After it, the folio is writeback's problem.

21. Go round again while the iterator still has anything in it, with a preemption point between turns so that a large write does not hold the processor against everything else. The loop returns the number of bytes that went in, and returns an error only when that number is zero, which is the code half of the promise in section 4a.

22. Drop the inode lock, and then handle `O_SYNC` outside it [write-path-R35]. This is the only path in this blueprint that reaches storage before returning, and it is a different mechanism wearing this one's return value.

23. Add the byte count to two per process counters and add one to a call counter. Where those are read back out is `/proc/<pid>/io` [write-path-R38], and section 8 says what happens to all of it on a build without the accounting.

For the filesystem the pinned machine uses, steps 16 and 19 are `shmem_write_begin` [write-path-R28] and `shmem_write_end`. The first checks the seals [write-path-R30], then finds the folio in the page cache or allocates one [write-path-R29], and refuses a folio the hardware has reported a memory error in. Its operations table [write-path-R33] has one entry that explains the whole filesystem: its `dirty_folio` does nothing, because a filesystem whose storage is memory has nowhere to write anything back to.

## §4 Invariants, locking and context

### §4a Invariants

1. The return value is the number of bytes that reached the page cache, never more. A write that returns `n` has put exactly `n` bytes where a later read will find them. [unchecked]
2. Bytes go in in order, and a write that is cut short is cut short at the end. There is no arrangement of failures that writes the second half of a request and not the first. [unchecked]
3. The position `O_APPEND` reads is the end of the file at a moment when the inode lock is held, and no other write to that inode can be between reading it and using it. [unchecked]
4. A folio handed back by `write_begin` is locked, and it is unlocked by `write_end` on every path out of it including the failing ones. [unchecked]
5. Every byte range reported as copied by the copy step is inside the folio `write_begin` returned. [unchecked]
6. A folio that reaches the end of the loop with new bytes in it is marked dirty before the folio lock is dropped. [unchecked]
7. A partly written folio that is newly allocated has the rest of it zeroed before it becomes visible to a reader, so a read never returns whatever the page previously held. [unchecked]
8. The copy step does not sleep. [checked: it is the atomic copy variant, and a fault inside it returns short rather than faulting in]
9. A folio never leaves the page cache still marked dirty [write-path-R34]. [checked: WARN_ON_ONCE in filemap_unaccount_folio]

### §4b Locking discipline

What protects each thing this mechanism touches:

| Thing | Protected by |
|---|---|
| the file position | `f_pos_lock` when the descriptor is shared, `owner` otherwise |
| the filesystem being frozen underneath the write [write-path-R9] | `sb_writers (r)`, held from step 7 to the end |
| the file size, and the position `O_APPEND` reads [write-path-R15] | `i_rwsem (w)` |
| the setuid bits and the timestamps | `i_rwsem (w)` |
| the folio between `write_begin` and `write_end` | `folio_lock` |
| the page cache tree the folio is found in | `i_pages` inside the page cache, `rcu` for a lookup |
| the per CPU dirty count [write-path-R27] | `percpu` |
| the per process byte counters | `atomic` |
| the `kiocb` and the `iov_iter` [write-path-R7] | `owner`, they are on this call's stack |

Acquisition order, written as a chain with `>` meaning taken before:

`sb_writers > i_rwsem > folio_lock > i_pages`

Three rules fall out of that chain and are worth stating on their own:

- The inode lock is held across the whole loop, so a second writer to the same file waits for the first to finish rather than interleaving with it. This is what makes a single `write` atomic against other writes to the same file, and it is a property of this code rather than a promise made by POSIX for ordinary files.
- The folio lock is taken and dropped inside each turn of the loop, so a long write does not hold any one folio for the whole call. A reader can see the first half of a large write while the second half is still being copied.
- `i_pages` is the innermost lock here and nothing in this path sleeps while holding it. The lookup that takes it is under RCU and the insert that takes it for write is the page cache's business rather than this mechanism's.

### §4c Execution context

`vfs_write` [write-path-R3] is a system call and has one answer.

| Context | Allowed | What it may do |
|---|---|---|
| `P` | yes | anything, including sleeping, allocating and waiting on writeback |
| `PP` | no | it sleeps in at least three places |
| `A` | no | same |
| `SI` | no | same |
| `HI` | no | same |
| `NMI` | no | same |

The copy step [write-path-R22] is the interesting one, and the reason this subsection is not one table.

| Context | Allowed | What it may do |
|---|---|---|
| `P` | yes | copy what is already resident, and report short when it is not |
| `PP` | yes | the same, and this is the state it actually runs in |
| `A` | no | it is called with a folio lock held, which is not a spinlock |
| `SI` | no | there is no caller |
| `HI` | no | there is no caller |
| `NMI` | no | there is no caller |

Everything in the loop runs with a folio locked, and the source buffer is a userspace address that can be paged out. Touching it can take a page fault, and resolving that fault can go into a filesystem, and the filesystem it goes into can be the one holding the folio lock this write is holding. The copy step exists to make that impossible: it disables page faults for the length of the copy, so an address that is not resident makes the copy return short instead of faulting. The loop reads a short copy as a signal to drop everything, fault the source buffer in from a context where that is safe, and start the turn again.

The `PREEMPT_RT` delta: the inode lock and the folio lock are already sleeping locks, so this path is nearly unchanged. What changes is the copy step, which runs with preemption disabled on a mainline build and does not on an RT build, and the throttle in step 14, which becomes a place a high priority thread can be made to wait for a low priority one and is one of the reasons RT builds are tuned to keep dirty limits low.

## §5 Observable behaviour

Generated, and the block below says what from. Hand editing it fails the build.

<!-- bpc:generated section=5 hash=40ee54b0a3754f22 -->
<!-- bpc:source kind=corpus path=corpora evidence=true pin=v7.2.2 arch=i386 -->

Generated by bpc 0.2 from 2 artefact(s) in `corpora/`. Every claim in this section points at a file that can be replayed, which is the difference between a specification of observable behaviour and a description of it.

### `corpora/traces/tier0/write-1byte.txt`

Tracer `function_graph`, recording one byte written to a file nothing had written to before, from the write system call down to the page being allocated and the byte copied in.

57 frame(s) in 3 call(s), nested 8 deep at the deepest, on CPU 0. No interrupt landed inside this recording.

```
mutex_unlock  22.625 us

vfs_write  516.167 us
  shmem_file_write_iter  503.875 us
    down_write  4.250 us
    generic_write_checks  22.375 us
      generic_write_checks_count  13.667 us
        generic_write_check_limits  4.666 us
    file_remove_privs  105.750 us
      file_remove_privs_flags  97.708 us
        setattr_should_drop_suidgid  3.667 us
        cap_inode_need_killpriv  79.958 us
          __vfs_getxattr  71.458 us
            strcmp  3.625 us
            strcmp  3.334 us
            xattr_resolve_name  5.125 us
            shmem_xattr_handler_get  33.834 us
              xattr_full_name  12.250 us
                strlen  3.750 us
              simple_xattr_get  3.708 us
    file_update_time  31.458 us
      file_update_time_flags  23.416 us
        current_time  14.417 us
          ktime_get_coarse_real_ts64_mg  5.083 us
    generic_perform_write  303.042 us
      balance_dirty_pages_ratelimited  19.750 us
        balance_dirty_pages_ratelimited_flags  11.500 us
          inode_to_bdi  3.375 us
      shmem_write_begin  208.791 us
        shmem_get_folio_gfp  200.042 us
          filemap_get_entry  50.583 us
            __rcu_read_lock  3.333 us
            __rcu_read_unlock  33.000 us
          shmem_allowable_huge_orders  12.333 us
            shmem_huge_global_enabled.isra.0  3.833 us
          shmem_alloc_and_add_folio.isra.0  117.833 us
            __folio_alloc_noprof  25.417 us
              __alloc_frozen_pages_noprof  17.333 us
                get_page_from_freelist  8.042 us
            shmem_add_to_page_cache  10.084 us
            shmem_inode_acct_blocks  38.791 us
              cap_vm_enough_memory  11.792 us
                cap_capable  3.750 us
              __vm_enough_memory  4.250 us
              inode_add_bytes  3.833 us
            shmem_recalc_inode  3.750 us
            folio_add_lru  12.417 us
              __folio_batch_add_and_move  4.083 us
      __copy_user_ll  3.792 us
      shmem_write_end  39.041 us
        folio_mark_dirty  19.958 us
          folio_mapping  3.542 us
          noop_dirty_folio  3.541 us
        folio_unlock  3.292 us
    up_write  3.500 us

vfs_write    (never closed)
  __copy_user_ll  3.458 us
  mutex_lock  3.542 us
```

### `corpora/traces/tier0/two-writes.txt`

Tracer `function_graph`, recording two one byte writes in one tracer window, one to a file on tmpfs and one to a pipe, so the split under vfs_write is visible in a single capture.

69 frame(s) in 4 call(s), nested 8 deep at the deepest, on CPU 0. No interrupt landed inside this recording.

```
mutex_unlock  17.250 us

vfs_write  549.333 us
  shmem_file_write_iter  535.667 us
    down_write  4.958 us
    generic_write_checks  26.042 us
      generic_write_checks_count  15.750 us
        generic_write_check_limits  5.208 us
    file_remove_privs  125.916 us
      file_remove_privs_flags  116.750 us
        setattr_should_drop_suidgid  4.291 us
        cap_inode_need_killpriv  82.583 us
          __vfs_getxattr  71.667 us
            strcmp  4.167 us
            strcmp  3.916 us
            xattr_resolve_name  5.458 us
            shmem_xattr_handler_get  32.083 us
              xattr_full_name  13.250 us
                strlen  3.916 us
              simple_xattr_get  4.125 us
    file_update_time  33.959 us
      file_update_time_flags  24.875 us
        current_time  14.833 us
          ktime_get_coarse_real_ts64_mg  4.209 us
    generic_perform_write  302.500 us
      balance_dirty_pages_ratelimited  22.500 us
        balance_dirty_pages_ratelimited_flags  13.292 us
          inode_to_bdi  3.917 us
      shmem_write_begin  203.083 us
        shmem_get_folio_gfp  192.959 us
          filemap_get_entry  23.583 us
            __rcu_read_lock  3.959 us
            __rcu_read_unlock  4.042 us
          shmem_allowable_huge_orders  14.000 us
            shmem_huge_global_enabled.isra.0  4.333 us
          shmem_alloc_and_add_folio.isra.0  134.417 us
            __folio_alloc_noprof  28.750 us
              __alloc_frozen_pages_noprof  19.416 us
                get_page_from_freelist  8.792 us
            shmem_add_to_page_cache  10.500 us
            shmem_inode_acct_blocks  44.917 us
              cap_vm_enough_memory  13.667 us
                cap_capable  4.375 us
              __vm_enough_memory  4.834 us
              inode_add_bytes  4.458 us
            shmem_recalc_inode  4.292 us
            folio_add_lru  14.208 us
              __folio_batch_add_and_move  4.542 us
      __copy_user_ll  4.083 us
      shmem_write_end  44.792 us
        folio_mark_dirty  23.125 us
          folio_mapping  4.208 us
          noop_dirty_folio  4.125 us
        folio_unlock  4.000 us
    up_write  4.208 us

vfs_write  121.875 us
  anon_pipe_write  109.458 us
    mutex_lock  4.167 us
    __alloc_pages_noprof  28.250 us
      __alloc_frozen_pages_noprof  18.833 us
        get_page_from_freelist  8.500 us
    __copy_user_ll  4.084 us
    mutex_unlock  4.000 us
    __wake_up_sync_key  23.625 us
      __wake_up_common_lock  14.291 us
        __wake_up_common  4.000 us
    kill_fasync  4.000 us

vfs_write    (never closed)
  __copy_user_ll  4.125 us
  mutex_lock  3.917 us
```
<!-- bpc:end section=5 -->

## §6 Edge cases and failure modes

- **allocation-failure.** The allocation that matters is the folio, inside `write_begin` [write-path-R21]. On a first write to a fresh file it is most of the cost of the whole call. When it fails, the loop stops, and what the caller gets depends entirely on where it stopped: a failure on the first turn returns `ENOMEM`, and a failure on any later turn returns the number of bytes that already went in and no error at all. A program that treats a short write as a transient condition and retries is doing the right thing. A program that treats it as impossible has a bug that only appears on a machine under memory pressure.

- **concurrent-entry.** Two writes to the same file at the same time do not interleave, because the inode lock is held across the loop. Two writes through the same descriptor from two threads also do not race on the position, because the position lock in step 2 covers reading it and writing it back. Two writes through two separate descriptors on the same file will happily overwrite each other, because there is no shared position to serialise them, and that is not a bug in this mechanism.

- **wrong-context.** There is no way to reach this path from an interrupt, so the interesting wrong context is inside the path rather than outside it. The copy step [write-path-R22] runs with a folio locked and faults disabled, and code that reached back into the filesystem from there would deadlock against a lock this same thread is holding. Section 4c is the whole answer.

- **signal.** A write that is already in the loop is not interrupted by an ordinary signal. It is checked once per turn of the loop, before any folio is locked, and only for fatal ones [write-path-R25]. A write that has copied part of its data and then meets a fatal signal returns the count it managed, and a write that meets one before copying anything returns `EINTR`. The other signal this path can produce is `SIGXFSZ` [write-path-R16], sent to the caller for exceeding its own file size limit.

- **object-freed.** The file cannot be closed underneath the write, because the descriptor lookup in step 2 takes a reference and the write holds it until the end. The folio cannot be freed underneath the copy, because it is locked. What can happen is that the file is truncated by another process the moment the inode lock is dropped, which makes the write return a number of bytes that are no longer in the file by the time the caller looks.

- **refcount-zero.** The dangerous window is between `write_begin` returning a folio and `write_end` giving it back. In that window this call holds a reference and a lock, and every path out has to release both. A `write_end` that returns an error still has to unlock, and a filesystem that forgets to is the classic way to hang a machine on the next write to the same file.

- **boundary-cases.** A write of zero bytes returns zero and does nothing else, which is not the same as doing nothing, because the checks in steps 4 and 9 have already run and can still refuse it. A write of exactly the cap [write-path-R6] goes through whole and a write of one byte more is shortened by one byte. A write starting exactly at the end of the file is an append and needs no special handling. A write starting past the end of the file leaves a hole, and reading that hole gives zeroes on every filesystem in the tree.

- **hostile-input.** The count, the address and the position all come from userspace and all three are fully attacker controlled. The count is capped rather than trusted, the address is checked for readability before the copy and checked again by the copy itself, and the position is checked against the file size limits. The one that is worth stating plainly is that the source buffer can be changed by another thread while the copy is running, so the bytes that land in the page cache can be different from the bytes the buffer held when the write was called, and no lock anywhere in the kernel can prevent that.

- **bug-message.** The message a reader is most likely to meet from this area is the warning that fires when a folio leaves the page cache still marked dirty [write-path-R34]. It means data was thrown away rather than written, and it means the bug is in whatever removed the folio rather than in the write that dirtied it.

## §7 Interfaces

Generated, and the block below says what from. Hand editing it fails the build.

<!-- bpc:generated section=7 hash=7d531e71ee2a37b9 -->
<!-- bpc:source kind=btf path=kxbox/kernel/build/A-full/vmlinux evidence=true pin=v7.2.2 arch=i386 -->

Generated by bpc 0.2 from `kxbox/kernel/build/A-full/vmlinux`. Signatures are what the kernel's own type information records, so a parameter with no name here is a parameter BTF has no name for rather than one the blueprint forgot.

### Functions

| Symbol | Signature |
|---|---|
| `ksys_write` | `static ssize_t ksys_write(unsigned int fd, const char *buf, size_t count)` |
| `vfs_write` | `static ssize_t vfs_write(struct file *file, const char *buf, size_t count, loff_t *pos)` |
| `rw_verify_area` | `static int rw_verify_area(int read_write, struct file *file, const loff_t *ppos, size_t count)` |
| `generic_write_checks` | `static ssize_t generic_write_checks(struct kiocb *iocb, struct iov_iter *from)` |
| `generic_write_checks_count` | `static int generic_write_checks_count(struct kiocb *iocb, loff_t *count)` |
| `file_remove_privs` | `static int file_remove_privs(struct file *file)` |
| `file_update_time` | `static int file_update_time(struct file *file)` |
| `generic_file_write_iter` | `static ssize_t generic_file_write_iter(struct kiocb *iocb, struct iov_iter *from)` |
| `__generic_file_write_iter` | `static ssize_t __generic_file_write_iter(struct kiocb *iocb, struct iov_iter *from)` |
| `generic_perform_write` | `static ssize_t generic_perform_write(struct kiocb *iocb, struct iov_iter *i)` |
| `shmem_file_write_iter` | `static ssize_t shmem_file_write_iter(struct kiocb *iocb, struct iov_iter *from)` |
| `shmem_write_begin` | `static int shmem_write_begin(const struct kiocb *iocb, struct address_space *mapping, loff_t pos, unsigned int len, struct folio **foliop, void **fsdata)` |
| `shmem_write_end` | `static int shmem_write_end(const struct kiocb *iocb, struct address_space *mapping, loff_t pos, unsigned int len, unsigned int copied, struct folio *folio, void *fsdata)` |
| `balance_dirty_pages_ratelimited` | `static void balance_dirty_pages_ratelimited(struct address_space *mapping)` |
| `folio_mark_dirty` | `static bool folio_mark_dirty(struct folio *folio)` |
| `copy_folio_from_iter_atomic` | `static size_t copy_folio_from_iter_atomic(struct folio *folio, size_t offset, size_t bytes, struct iov_iter *i)` |
| `shmem_get_folio` | `static int shmem_get_folio(struct inode *inode, long unsigned int index, loff_t write_end, struct folio **foliop, enum sgp_type sgp)` |
| `new_sync_write` | no symbol in this build, inlined or configured out |

### struct file_operations

32 operation(s) and 2 data field(s), 136 bytes.

| Offset | Operation | Signature | Filled by |
|---|---|---|---|
| 8 | `llseek` | `loff_t (*llseek)(struct file *, loff_t, int)` | no instance has been read |
| 12 | `read` | `ssize_t (*read)(struct file *, char *, size_t, loff_t *)` | no instance has been read |
| 16 | `write` | `ssize_t (*write)(struct file *, const char *, size_t, loff_t *)` | no instance has been read |
| 20 | `read_iter` | `ssize_t (*read_iter)(struct kiocb *, struct iov_iter *)` | no instance has been read |
| 24 | `write_iter` | `ssize_t (*write_iter)(struct kiocb *, struct iov_iter *)` | no instance has been read |
| 28 | `iopoll` | `int (*iopoll)(struct kiocb *, struct io_comp_batch *, unsigned int)` | no instance has been read |
| 32 | `iterate_shared` | `int (*iterate_shared)(struct file *, struct dir_context *)` | no instance has been read |
| 36 | `poll` | `__poll_t (*poll)(struct file *, struct poll_table_struct *)` | no instance has been read |
| 40 | `unlocked_ioctl` | `long int (*unlocked_ioctl)(struct file *, unsigned int, long unsigned int)` | no instance has been read |
| 44 | `compat_ioctl` | `long int (*compat_ioctl)(struct file *, unsigned int, long unsigned int)` | no instance has been read |
| 48 | `mmap` | `int (*mmap)(struct file *, struct vm_area_struct *)` | no instance has been read |
| 52 | `open` | `int (*open)(struct inode *, struct file *)` | no instance has been read |
| 56 | `flush` | `int (*flush)(struct file *, fl_owner_t)` | no instance has been read |
| 60 | `release` | `int (*release)(struct inode *, struct file *)` | no instance has been read |
| 64 | `fsync` | `int (*fsync)(struct file *, loff_t, loff_t, int)` | no instance has been read |
| 68 | `fasync` | `int (*fasync)(int, struct file *, int)` | no instance has been read |
| 72 | `lock` | `int (*lock)(struct file *, int, struct file_lock *)` | no instance has been read |
| 76 | `get_unmapped_area` | `long unsigned int (*get_unmapped_area)(struct file *, long unsigned int, long unsigned int, long unsigned int, long unsigned int)` | no instance has been read |
| 80 | `check_flags` | `int (*check_flags)(int)` | no instance has been read |
| 84 | `flock` | `int (*flock)(struct file *, int, struct file_lock *)` | no instance has been read |
| 88 | `splice_write` | `ssize_t (*splice_write)(struct pipe_inode_info *, struct file *, loff_t *, size_t, unsigned int)` | no instance has been read |
| 92 | `splice_read` | `ssize_t (*splice_read)(struct file *, loff_t *, struct pipe_inode_info *, size_t, unsigned int)` | no instance has been read |
| 96 | `splice_eof` | `void (*splice_eof)(struct file *)` | no instance has been read |
| 100 | `setlease` | `int (*setlease)(struct file *, int, struct file_lease **, void **)` | no instance has been read |
| 104 | `fallocate` | `long int (*fallocate)(struct file *, int, loff_t, loff_t)` | no instance has been read |
| 108 | `show_fdinfo` | `void (*show_fdinfo)(struct seq_file *, struct file *)` | no instance has been read |
| 112 | `copy_file_range` | `ssize_t (*copy_file_range)(struct file *, loff_t, struct file *, loff_t, size_t, unsigned int)` | no instance has been read |
| 116 | `remap_file_range` | `loff_t (*remap_file_range)(struct file *, loff_t, struct file *, loff_t, loff_t, unsigned int)` | no instance has been read |
| 120 | `fadvise` | `int (*fadvise)(struct file *, loff_t, loff_t, int)` | no instance has been read |
| 124 | `uring_cmd` | `int (*uring_cmd)(struct io_uring_cmd *, unsigned int)` | no instance has been read |
| 128 | `uring_cmd_iopoll` | `int (*uring_cmd_iopoll)(struct io_uring_cmd *, struct io_comp_batch *, unsigned int)` | no instance has been read |
| 132 | `mmap_prepare` | `int (*mmap_prepare)(struct vm_area_desc *)` | no instance has been read |

Every slot reads as empty because what a function pointer holds is a fact about a running machine and not about a type. Filling them in needs an instance read out of a kernel that is running.

### struct address_space_operations

19 operation(s) and 0 data field(s), 76 bytes.

| Offset | Operation | Signature | Filled by |
|---|---|---|---|
| 0 | `read_folio` | `int (*read_folio)(struct file *, struct folio *)` | no instance has been read |
| 4 | `writepages` | `int (*writepages)(struct address_space *, struct writeback_control *)` | no instance has been read |
| 8 | `dirty_folio` | `bool (*dirty_folio)(struct address_space *, struct folio *)` | no instance has been read |
| 12 | `readahead` | `void (*readahead)(struct readahead_control *)` | no instance has been read |
| 16 | `write_begin` | `int (*write_begin)(const struct kiocb *, struct address_space *, loff_t, unsigned int, struct folio **, void **)` | no instance has been read |
| 20 | `write_end` | `int (*write_end)(const struct kiocb *, struct address_space *, loff_t, unsigned int, unsigned int, struct folio *, void *)` | no instance has been read |
| 24 | `bmap` | `sector_t (*bmap)(struct address_space *, sector_t)` | no instance has been read |
| 28 | `invalidate_folio` | `void (*invalidate_folio)(struct folio *, size_t, size_t)` | no instance has been read |
| 32 | `release_folio` | `bool (*release_folio)(struct folio *, gfp_t)` | no instance has been read |
| 36 | `free_folio` | `void (*free_folio)(struct folio *)` | no instance has been read |
| 40 | `direct_IO` | `ssize_t (*direct_IO)(struct kiocb *, struct iov_iter *)` | no instance has been read |
| 44 | `migrate_folio` | `int (*migrate_folio)(struct address_space *, struct folio *, struct folio *, enum migrate_mode)` | no instance has been read |
| 48 | `launder_folio` | `int (*launder_folio)(struct folio *)` | no instance has been read |
| 52 | `is_partially_uptodate` | `bool (*is_partially_uptodate)(struct folio *, size_t, size_t)` | no instance has been read |
| 56 | `is_dirty_writeback` | `void (*is_dirty_writeback)(struct folio *, bool *, bool *)` | no instance has been read |
| 60 | `error_remove_folio` | `int (*error_remove_folio)(struct address_space *, struct folio *)` | no instance has been read |
| 64 | `swap_activate` | `int (*swap_activate)(struct swap_info_struct *, struct file *, sector_t *)` | no instance has been read |
| 68 | `swap_deactivate` | `void (*swap_deactivate)(struct file *)` | no instance has been read |
| 72 | `swap_rw` | `int (*swap_rw)(struct kiocb *, struct iov_iter *)` | no instance has been read |

Every slot reads as empty because what a function pointer holds is a fact about a running machine and not about a type. Filling them in needs an instance read out of a kernel that is running.
<!-- bpc:end section=7 -->

## §8 Configuration and architecture dependence

Which symbols change what is written above:

- `CONFIG_SECURITY` decides whether the security hook in step 4 [write-path-R4] is a call into a module or a stub that returns success. The pinned kernel does not set it, so the hook is a stub. Two capability functions still appear in the capture in section 5, because the capability module is built in whether or not the security framework is, and that is worth knowing before reading the trace and concluding the config was on.
- `CONFIG_FSNOTIFY` decides whether the notification hook in step 4 exists. Without it, a watch on the file cannot refuse or observe the write, and the hook compiles away to nothing. The pinned kernel does not have it.
- `CONFIG_TASK_XACCT` and `CONFIG_TASK_IO_ACCOUNTING` decide whether step 23 counts anything. Neither is set on the pinned kernel, so the byte and call counters are not incremented, and `/proc/<pid>/io` [write-path-R38] does not exist on that machine at all.
- `CONFIG_MEMCG` adds a charge against a memory control group to the folio allocation in step 16, and gives it a second way to fail that has nothing to do with the machine being short of memory. The pinned kernel does not have it, which is why the allocation in the capture has fewer frames under it than the same allocation on a distribution kernel.
- `CONFIG_FS_DAX` adds a branch before the loop for a filesystem on persistent memory, where there is no page cache and the write goes to the device's own memory. Without it that branch does not exist. The pinned kernel does not have it.
- `CONFIG_TRANSPARENT_HUGEPAGE` changes the answer step 16 gets from the chunk calculation [write-path-R20]. With large folios available, one turn of the loop can cover far more than a page, which changes the number of times the throttle in step 14 is consulted for the same amount of data. The pinned kernel does have it, and that is why `shmem_allowable_huge_orders` is in the capture in section 5. A build without it has one fewer decision in step 16 and a chunk that is always one page.
- `CONFIG_BLOCK` decides whether writeback has anywhere to go at all. The pinned kernel has it, and it still does not matter here, because the only filesystem on the machine keeps its storage in memory. The dirty flag set in step 20 is never acted on by anybody on that machine, and a reader who wants to watch the second half of this story needs a Tier 1 box with a real disk on it.
- `CONFIG_TMPFS` is what puts the filesystem in steps 16 and 19 on the machine this project boots. On any other machine those two steps are somebody else's code, and the shape rather than the text is what carries over.

Architecture dependence:

Nearly none of this path is architecture specific, which is unusual for something this close to a system call. The system call entry itself differs, and the copy step [write-path-R22] is a per architecture routine, and after that the code is the same everywhere. The cache flush in step 17 [write-path-R23] is the one place the architecture shows through in the logic rather than in an implementation, and on x86 it does nothing, because x86 caches are indexed by physical address and the problem it solves cannot happen.

Two things about the pinned kernel change what a reader sees rather than what the mechanism is. It is 32-bit, so a `loff_t` is wider than a pointer and the file size arithmetic in step 10 is doing something the machine cannot do in one instruction. It has one processor, so none of the concurrent cases in section 6 can be produced on it at all, and a reader who wants to see two writers contend on the inode lock needs a Tier 1 machine.

### The adapter in step 6 is not in the trace

Step 6 says a file with only `write_iter` goes through an adapter [write-path-R7] that builds a `kiocb` and an `iov_iter`. Look for that adapter in the capture in section 5 and it is not there. `vfs_write` calls the filesystem's `write_iter` directly, with nothing in between.

The function is `static` and it has one caller, which is the shape a compiler inlines without being asked. It is not in the kernel's own list of functions a tracer can attach to, so this is not a matter of the trace missing it. There is nothing there to attach to.

This is the second time this project has met that distinction and it will not be the last. The code runs. The work described in step 6 happens on every buffered write in the system. There is no symbol, no frame, and no way to observe it from the tracer, and the honest way to describe such a step is to say what it does and then say that it cannot be seen. A reader who goes looking for `new_sync_write` in a trace and finds nothing has not made a mistake.

There is a second reason worth knowing, because it is a different reason and it looks the same from outside. Older kernels really did put a call there that the compiler kept. Material written against those kernels shows `new_sync_write` between `vfs_write` and the filesystem, and that material is not wrong about the kernel it was written for. Which of the two explanations applies to any given build is a question only that build can answer, which is the whole argument for generating section 7 from the kernel rather than typing it.

## §9 Reimplementation notes

Forced by the syscall ABI:

- That the return value is a byte count and that a short write is a normal result rather than an error. Programs are written against this, and a kernel that always wrote everything or failed would still have to return the count.
- That the count is capped rather than refused [write-path-R6]. The cap itself could be a different number. Silently shortening rather than returning an error is the part that cannot change.
- That `O_APPEND` is atomic against other appends [write-path-R15]. Two processes appending to a log file and not losing each other's lines is a thing every piece of software on a Unix machine assumes.
- That `write` returning does not mean the data is on storage, and that `fsync` is the way to ask for that. A kernel that made `write` durable would be correct and unusably slow, and every program that was written to expect the current behaviour would be paying for a promise it never asked for.

Choices Linux made that another kernel could make differently:

- **Two calls into the filesystem per folio rather than one.** `write_begin` and `write_end` [write-path-R21] [write-path-R24] exist so the generic loop can do the copy in between while the filesystem holds the folio. A kernel could hand the whole request to the filesystem and let it do its own copying, which is what the direct path effectively does. The cost of the current arrangement is an interface with two halves that have to agree about a lock, which is the sort of interface that produces the failure in the refcount-zero case. The benefit is that the copy is written once for the whole kernel and every filesystem gets the same page cache behaviour for free.

- **Holding the inode lock across the whole loop.** This makes one `write` atomic against other writes to the same file, which POSIX does not require for ordinary files. A kernel could take the lock per folio instead and get more concurrency on large writes to one file, at the cost of two writers being able to interleave their output. Linux chose the property that surprises fewer people, and it is worth knowing that it is a choice, because a program relying on it is relying on Linux and not on the standard.

- **Throttling the writer inside the write** [write-path-R26]. A process that dirties memory faster than storage can absorb it is made to wait, inside `write`, in the middle of a loop it thinks is a memory copy. A kernel could refuse instead, or could let the dirty pages accumulate and take the pain at writeback time. Refusing would break every program. Letting them accumulate is what old kernels did and it produced machines that were responsive for a minute and then unusable for thirty seconds. Making the writer pay in proportion to what it dirtied is the design that spread the cost out, and the price is that a system call with no obvious reason to block can block for a long time.

- **Faults disabled during the copy, with a retry loop around it.** The alternative is to fault the source buffer in before taking the folio lock, which is a second pass over the same memory on every write to buy a case that nearly never happens. Linux made the common path cheap and the rare path complicated. A kernel with a different locking model, where the fault handler could not re-enter the filesystem, would not need any of this.

- **The dirty flag as the only handoff to writeback.** Marking a folio dirty [write-path-R32] is the entire message this path sends to the mechanism that will finish the job. There is no queue, no work item and no notification. A kernel could hand writeback an explicit description of what changed, which would let it be smarter about ordering and would cost an allocation on every write. The current design makes the write cheap and leaves writeback to scan for its own work.
