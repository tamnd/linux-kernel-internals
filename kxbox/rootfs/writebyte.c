/* Write exactly one byte, with the tracer running for exactly that write.
 *
 *     /bin/writebyte            one byte into a fresh file on /tmp
 *     /bin/writebyte --quiet    the same, without the line on stdout
 *
 * The same problem as `touchpage` and the same answer. `dd if=/dev/zero of=/tmp/one bs=1 count=1`
 * looks like one write and is not: the shell writes its prompt, dd writes its two lines of summary
 * to stderr, and busybox writes whatever it feels like on the way past. Filtering to `vfs_write`
 * does not help, because every one of those is a `vfs_write` too, and a beginner's first trace
 * should not open with the question of which of the nine identical frames is theirs.
 *
 *     write(on, "1")               tracing starts here
 *     write(target, "x", 1)        the write
 *     write(on, "0")               tracing stops here
 *
 * Everything else happens outside that window. The file is opened before it, so no `open` lands in
 * the trace. It is closed after it, so no `close` does. And the whole sequence runs once against a
 * throwaway file first, so every page of code and stack this needs is already resident.
 *
 * The one thing left inside the window on purpose is that the target is a file nothing has written
 * to yet. A first write has to find a page for the data and a second one finds it already there,
 * and the first is the interesting one, because the allocation is where the time goes and where
 * the tree of calls underneath `vfs_write` gets deep enough to be worth drawing.
 */

#include "tiny.h"

#define WARM "/tmp/.writebyte-warmup"
#define TARGET "/tmp/one-byte"

/* The three instructions the whole program exists for. Both descriptors are already open, because
 * an open inside the window is a system call nobody asked to see. */
static void write_one(int on, int target)
{
	if (on >= 0)
		call3(SYS_WRITE, (ulong)on, (ulong) "1\n", 2);
	call3(SYS_WRITE, (ulong)target, (ulong) "x", 1);
	if (on >= 0)
		call3(SYS_WRITE, (ulong)on, (ulong) "0\n", 2);
}

static int make(const char *path)
{
	return (int)call3(SYS_OPEN, (ulong)path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
}

int main(int argc, char **argv)
{
	int quiet = argc > 1 && same(argv[1], "--quiet");
	int warm, target, on;

	/* The dry run. Same calls, same code, on a file that gets deleted afterwards so that the
	 * real one is still a file nothing has written to. */
	warm = make(WARM);
	if (warm < 0) {
		say("writebyte: cannot create " WARM ", is /tmp writable\n");
		return 1;
	}
	write_one(-1, warm);
	call1(SYS_CLOSE, (ulong)warm);
	call1(SYS_UNLINK, (ulong)WARM);

	target = make(TARGET);
	if (target < 0) {
		say("writebyte: cannot create " TARGET "\n");
		return 1;
	}

	/* Opened before the window. A machine with no tracing filesystem still does the write, it
	 * just does not record it, which is the right behaviour for a program somebody runs to see
	 * what happens. */
	on = (int)call3(SYS_OPEN, (ulong)TRACING_ON, O_WRONLY, 0);

	write_one(on, target);

	if (on >= 0)
		call1(SYS_CLOSE, (ulong)on);
	call1(SYS_CLOSE, (ulong)target);

	if (!quiet)
		say("wrote 1 byte to " TARGET "\n");
	return 0;
}
