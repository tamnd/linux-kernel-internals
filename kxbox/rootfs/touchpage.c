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
 * There is no C library in here at all, so there is no loader, no startup code and no library
 * page to fault in on a first call. And it does the entire sequence once against /dev/null before
 * it opens the tracer, which walks every line of code and every stack page this will touch, so
 * that by the time tracing is on there is nothing left to fault on except the page we mean.
 *
 * It writes the address it touched to stdout, so a reader can find their fault in the trace by
 * matching the address rather than by trusting that the only one there is theirs.
 *
 * ## Why there is no libc
 *
 * A static glibc binary with one `printf` in it is seven hundred kilobytes, and the rootfs is a
 * thing a browser downloads and decompresses before a lesson starts. Going straight to the
 * syscalls makes it about ten, and it removes the last place a fault could come from that we did
 * not ask for. The cost is thirty lines of i386 assembly, which is a fair trade in a book whose
 * whole subject is the boundary these instructions cross.
 *
 * The calling convention on 32-bit x86 is the number in eax, the arguments in ebx, ecx, edx, esi
 * and edi in that order, `int $0x80`, and the result back in eax. A negative result is an errno
 * with the sign flipped. That is the whole interface.
 */

#define PAGE 4096

#define SYS_EXIT 1
#define SYS_WRITE 4
#define SYS_OPEN 5
#define SYS_CLOSE 6
#define SYS_MMAP 90
#define SYS_MUNMAP 91

#define O_WRONLY 1

#define PROT_READ 0x1
#define PROT_WRITE 0x2
#define MAP_PRIVATE 0x02
#define MAP_ANONYMOUS 0x20

#define TRACING_ON "/sys/kernel/tracing/tracing_on"

typedef unsigned long ulong;

static inline long call1(long number, ulong a)
{
	long out;
	__asm__ volatile("int $0x80" : "=a"(out) : "a"(number), "b"(a) : "memory");
	return out;
}

static inline long call2(long number, ulong a, ulong b)
{
	long out;
	__asm__ volatile("int $0x80" : "=a"(out) : "a"(number), "b"(a), "c"(b) : "memory");
	return out;
}

static inline long call3(long number, ulong a, ulong b, ulong c)
{
	long out;
	__asm__ volatile("int $0x80"
			 : "=a"(out)
			 : "a"(number), "b"(a), "c"(b), "d"(c)
			 : "memory");
	return out;
}

/* The oldest of the three mmap syscalls, and the only one that takes its arguments through memory
 * rather than through six registers. Six would need ebp, which the compiler is using for the
 * frame, and this program has no opinion about which mmap it gets. */
static void *map_one_page(void)
{
	ulong args[6] = { 0, PAGE, PROT_READ | PROT_WRITE,
			  MAP_PRIVATE | MAP_ANONYMOUS, (ulong)-1, 0 };
	long out = call1(SYS_MMAP, (ulong)args);

	return out < 0 && out > -4096 ? 0 : (void *)out;
}

static int same(const char *a, const char *b)
{
	while (*a && *a == *b) {
		a++;
		b++;
	}
	return *a == *b;
}

static void say(const char *text)
{
	const char *end = text;

	while (*end)
		end++;
	call3(SYS_WRITE, 1, (ulong)text, (ulong)(end - text));
}

/* The address, in the same 0x form the kernel prints one in, so it can be matched by eye. */
static void say_pointer(const void *value)
{
	static const char digits[] = "0123456789abcdef";
	ulong number = (ulong)value;
	char out[2 + 2 * sizeof(number)];
	int at = (int)sizeof(out);

	do {
		out[--at] = digits[number & 0xf];
		number >>= 4;
	} while (number);
	out[--at] = 'x';
	out[--at] = '0';
	call3(SYS_WRITE, 1, (ulong)(out + at), sizeof(out) - (ulong)at);
}

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

/* Where the kernel puts us. There is no libc to set anything up, so this is the whole of it: argc
 * is on top of the stack and argv starts one word above it, exactly as `execve` left them. */
__asm__(".globl _start\n"
	"_start:\n"
	"	movl (%esp), %eax\n"
	"	leal 4(%esp), %edx\n"
	"	pushl %edx\n"
	"	pushl %eax\n"
	"	call main\n"
	"	movl %eax, %ebx\n"
	"	movl $1, %eax\n"
	"	int $0x80\n");
