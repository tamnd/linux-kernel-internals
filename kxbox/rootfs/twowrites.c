/* Two writes of one byte each, to two different kinds of file, in one tracer window.
 *
 *     /bin/twowrites            one byte to a file on /tmp, then one byte to a pipe
 *     /bin/twowrites --quiet    the same, without the line on stdout
 *
 * This is `writebyte` done twice with the second destination swapped, and the swap is the point.
 * Both writes are the same system call with the same count, both go through the same `vfs_write`,
 * and underneath that they run completely different kernel code. Which code is not decided by
 * `vfs_write` and is not decided by anything in the call. It was decided when the file was opened,
 * by whatever was written into `file->f_op`.
 *
 *     write(on, "1")               tracing starts here
 *     write(target, "x", 1)        into a file on tmpfs
 *     write(pipe, "x", 1)          into a pipe
 *     write(on, "0")               tracing stops here
 *
 * Two writes in one window and not two windows with one write each, which would have been tidier
 * to read. A capture is only evidence that the same code went two ways if the two ways are in the
 * same capture: two separate traces taken a second apart could differ because something else on
 * the machine changed, and nobody could rule it out from the files.
 *
 * Everything else is `writebyte`'s arrangement for the same reasons. Both descriptors are open
 * before the window, both destinations are warmed up on throwaways first so no page of code faults
 * inside it, and the two real destinations are both untouched, so each one shows the first write
 * rather than the cheap second one.
 */

#include "tiny.h"

#define WARM "/tmp/.twowrites-warmup"
#define TARGET "/tmp/two-writes"

/* The four instructions the whole program exists for. */
static void write_both(int on, int target, int pipe)
{
	if (on >= 0)
		call3(SYS_WRITE, (ulong)on, (ulong) "1\n", 2);
	call3(SYS_WRITE, (ulong)target, (ulong) "x", 1);
	call3(SYS_WRITE, (ulong)pipe, (ulong) "x", 1);
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
	int warm_pipe[2], pipe[2];

	/* The dry run. Same calls on a file and a pipe that both get thrown away, so that the two
	 * real destinations below are still ones nothing has written to. */
	warm = make(WARM);
	if (warm < 0) {
		say("twowrites: cannot create " WARM ", is /tmp writable\n");
		return 1;
	}
	if (call1(SYS_PIPE, (ulong)warm_pipe) < 0) {
		say("twowrites: cannot make a pipe\n");
		return 1;
	}
	write_both(-1, warm, warm_pipe[1]);
	call1(SYS_CLOSE, (ulong)warm_pipe[0]);
	call1(SYS_CLOSE, (ulong)warm_pipe[1]);
	call1(SYS_CLOSE, (ulong)warm);
	call1(SYS_UNLINK, (ulong)WARM);

	target = make(TARGET);
	if (target < 0) {
		say("twowrites: cannot create " TARGET "\n");
		return 1;
	}
	if (call1(SYS_PIPE, (ulong)pipe) < 0) {
		say("twowrites: cannot make a pipe\n");
		return 1;
	}

	/* Opened before the window. A machine with no tracing filesystem still does both writes, it
	 * just does not record them. */
	on = (int)call3(SYS_OPEN, (ulong)TRACING_ON, O_WRONLY, 0);

	write_both(on, target, pipe[1]);

	if (on >= 0)
		call1(SYS_CLOSE, (ulong)on);
	call1(SYS_CLOSE, (ulong)pipe[0]);
	call1(SYS_CLOSE, (ulong)pipe[1]);
	call1(SYS_CLOSE, (ulong)target);

	if (!quiet)
		say("wrote 1 byte to " TARGET " and 1 byte to a pipe\n");
	return 0;
}
