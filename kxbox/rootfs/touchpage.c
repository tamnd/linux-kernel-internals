/* Cause exactly one page fault, with the tracer running for exactly that fault.
 *
 *     /bin/touchpage            one anonymous page, written to for the first time
 *     /bin/touchpage --quiet    the same, without the line on stdout
 *
 * Every other way of triggering a fault from a shell traces thirty of them. Running `true` under
 * busybox faults thirty times before it gets anywhere near your code, because a fork copies on
 * write and an exec pages a binary in, and none of that is the thing you wanted to look at. A
 * trace with thirty faults in it is a trace where the reader has to be told which one to read,
 * and being told which one to read is the opposite of observing something.
 *
 * So this turns the tracer on itself, in between the two instructions that matter:
 *
 *     write(on, "1")     tracing starts here
 *     *page = 1          the fault
 *     write(on, "0")     tracing stops here
 *
 * The whole trick is that nothing else may fault inside that window. Two things make that true.
 * There is no C library in here at all, which `tiny.h` explains, so there is no loader, no startup
 * code and no library page to fault in on a first call. And it does the entire sequence once
 * against /dev/null before it opens the tracer, which walks every line of code and every stack
 * page this will touch, so that by the time tracing is on there is nothing left to fault on except
 * the page we mean.
 *
 * It writes the address it touched to stdout, so a reader can find their fault in the trace by
 * matching the address rather than by trusting that the only one there is theirs.
 */

#include "tiny.h"

/* The three instructions the whole program exists for. `on` is a file descriptor that is already
 * open, because opening one inside the window would be a syscall we did not ask to see. */
static void touch(int on, volatile char *page)
{
	if (on >= 0)
		call3(SYS_WRITE, (ulong)on, (ulong) "1\n", 2);
	*page = 1;
	if (on >= 0)
		call3(SYS_WRITE, (ulong)on, (ulong) "0\n", 2);
}

int main(int argc, char **argv)
{
	int quiet = argc > 1 && same(argv[1], "--quiet");
	volatile char *warm, *page;
	int sink, on;

	/* The dry run. Same calls, same code, with the two writes going to /dev/null instead of to
	 * the tracer. Everything the real run is about to do is resident by the time it matters. */
	warm = map_one_page();
	if (!warm) {
		say("touchpage: no memory for the warm up page\n");
		return 1;
	}
	sink = (int)call3(SYS_OPEN, (ulong) "/dev/null", O_WRONLY, 0);
	touch(sink, warm);
	if (sink >= 0)
		call1(SYS_CLOSE, (ulong)sink);
	call2(SYS_MUNMAP, (ulong)warm, PAGE);

	page = map_one_page();
	if (!page) {
		say("touchpage: no memory for the page to touch\n");
		return 1;
	}

	/* Opened before the window, so the open does not land in the trace. A machine with no
	 * tracing filesystem still runs the fault, it just does not record it, which is the right
	 * behaviour for a program somebody runs to see what happens. */
	on = (int)call3(SYS_OPEN, (ulong)TRACING_ON, O_WRONLY, 0);

	touch(on, page);

	if (on >= 0)
		call1(SYS_CLOSE, (ulong)on);

	if (!quiet) {
		say("touched ");
		say_pointer((const void *)page);
		say("\n");
	}
	return 0;
}
