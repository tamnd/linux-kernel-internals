/* Linux, i386, with nothing between you and the system calls.
 *
 * Every program in this directory does the same small trick: turn the tracer on, do exactly one
 * thing, turn the tracer off. Anything else that runs inside that window lands in the trace and
 * has to be explained away, and the explaining is what makes a beginner's first trace unreadable.
 *
 * So there is no C library here. A static glibc binary with one `printf` in it is seven hundred
 * kilobytes, and the rootfs is a thing a browser downloads and decompresses before a lesson
 * starts. Going straight to the syscalls makes it about ten, and it removes the last place a
 * fault or a call could come from that nobody asked for: no loader, no startup code, no library
 * page to fault in on a first call.
 *
 * The calling convention on 32-bit x86 is the number in eax, the arguments in ebx, ecx, edx, esi
 * and edi in that order, `int $0x80`, and the result back in eax. A negative result is an errno
 * with the sign flipped. That is the whole interface, and it is the boundary this book is about,
 * which makes writing it out by hand less of an indulgence than it looks.
 *
 * A program that includes this writes `int main(int argc, char **argv)` and nothing else. The
 * entry point at the bottom is the whole of what a C library would have done first.
 */

#ifndef KXBOX_TINY_H
#define KXBOX_TINY_H

#define PAGE 4096

#define SYS_EXIT 1
#define SYS_WRITE 4
#define SYS_OPEN 5
#define SYS_CLOSE 6
#define SYS_UNLINK 10
/* On 32-bit x86 this is the one that takes a pointer to two ints and returns zero. The variant
 * that hands both descriptors back in registers is an Alpha and MIPS thing and is not this. */
#define SYS_PIPE 42
#define SYS_MMAP 90
#define SYS_MUNMAP 91

#define O_WRONLY 1
#define O_CREAT 0100
#define O_TRUNC 01000

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
 * frame, and none of these programs has an opinion about which mmap it gets. */
static inline void *map_one_page(void)
{
	ulong args[6] = { 0, PAGE, PROT_READ | PROT_WRITE,
			  MAP_PRIVATE | MAP_ANONYMOUS, (ulong)-1, 0 };
	long out = call1(SYS_MMAP, (ulong)args);

	return out < 0 && out > -4096 ? 0 : (void *)out;
}

static inline int same(const char *a, const char *b)
{
	while (*a && *a == *b) {
		a++;
		b++;
	}
	return *a == *b;
}

static inline void say(const char *text)
{
	const char *end = text;

	while (*end)
		end++;
	call3(SYS_WRITE, 1, (ulong)text, (ulong)(end - text));
}

/* A number in the same 0x form the kernel prints one in, so it can be matched by eye. */
static inline void say_pointer(const void *value)
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

#endif /* KXBOX_TINY_H */
