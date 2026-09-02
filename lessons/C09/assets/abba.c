// SPDX-License-Identifier: GPL-2.0
/*
 * abba, a module that cannot deadlock and gets reported for deadlocking.
 *
 * Two mutexes and two kernel threads. The first thread takes lock_a and then lock_b. The second
 * thread takes lock_b and then lock_a, which is the opposite order, and that is the bug.
 *
 * The second thread does not start until the first one has finished and released both locks. There
 * is no instant at which two threads hold anything at the same time, so nothing can wait on
 * anything, so this module cannot hang. Run it a million times and it will not hang.
 *
 * Load it once with CONFIG_PROVE_LOCKING on and lockdep reports a circular locking dependency.
 * That is the lesson. The report is about the order the locks were taken in, and the order is
 * wrong whether or not the timing ever lines up.
 *
 * Build it against a kernel you do not mind annoying. It is safe in the sense that it does not
 * hang and does not corrupt anything, and it does turn the lock checker off for the rest of that
 * boot, which is the other half of what C09 is about.
 */

#include <linux/completion.h>
#include <linux/init.h>
#include <linux/kthread.h>
#include <linux/module.h>
#include <linux/mutex.h>

static DEFINE_MUTEX(lock_a);
static DEFINE_MUTEX(lock_b);

static DECLARE_COMPLETION(first_finished);
static DECLARE_COMPLETION(second_finished);

/* a then b. This is the order the rest of the module is supposed to follow. */
static int abba_first_thread(void *unused)
{
	mutex_lock(&lock_a);
	mutex_lock(&lock_b);
	pr_info("abba: first thread holds both, in the order a then b\n");
	mutex_unlock(&lock_b);
	mutex_unlock(&lock_a);

	complete(&first_finished);
	return 0;
}

/* b then a. Nothing is held by anybody else by the time this runs. */
static int abba_second_thread(void *unused)
{
	wait_for_completion(&first_finished);

	mutex_lock(&lock_b);
	/* The report comes out of the next line. Nothing blocks on it. */
	mutex_lock(&lock_a);
	pr_info("abba: second thread holds both, in the order b then a\n");
	mutex_unlock(&lock_a);
	mutex_unlock(&lock_b);

	complete(&second_finished);
	return 0;
}

static int __init abba_init(void)
{
	struct task_struct *first, *second;

	first = kthread_run(abba_first_thread, NULL, "abba_first");
	if (IS_ERR(first))
		return PTR_ERR(first);

	second = kthread_run(abba_second_thread, NULL, "abba_second");
	if (IS_ERR(second)) {
		wait_for_completion(&first_finished);
		return PTR_ERR(second);
	}

	/* Both threads are done before init returns, so nothing outlives the module. */
	wait_for_completion(&second_finished);
	pr_info("abba: both threads finished, nothing waited for anything\n");
	return 0;
}

static void __exit abba_exit(void)
{
	pr_info("abba: unloaded\n");
}

module_init(abba_init);
module_exit(abba_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Two locks taken in two orders, with no overlap in time");
