# Event formats

Each of these is one file copied out of `/sys/kernel/tracing/events/<group>/<event>/format` on the pinned kernel. They are the kernel describing the shape of its own records, and they are here so that the event reader never has to guess one.

That sounds like a small thing and it is not. The layout of a trace event is decided by the compiler that built the kernel, from a struct the kernel assembled out of a macro, for the architecture it was built for, with the config it was built with. Nothing about it is stable across machines. This is `sched_switch` on the box this project pins, which is 32 bit x86:

```
	field:long prev_state;	offset:32;	size:4;	signed:1;
	field:char next_comm[16];	offset:36;	size:16;	signed:0;
```

On the machine you are probably reading this on, `long` is eight bytes, `prev_state` is eight bytes, `next_comm` starts at 40, and every field after that has moved as well. A parser that wrote those numbers down once would read the wrong bytes on one of the two machines and would report nothing wrong while doing it. Reading the file is not being careful, it is the only correct thing to do.

## What is in a format file

Four lines of header and then the fields. Every event begins with the same four common fields, which is what lets the kernel work out which event a record is before it knows how to read the rest of it, and after those come the fields the event declares for itself.

The last line is `print fmt`, and it is worth reading and is not worth parsing. It is a C expression, and for something like `kmem:kmalloc` it is several thousand characters of nested macro expansion that resolves GFP flags into names. `kxray/trace/formats.py` keeps it as text and stops there, because evaluating it properly means being a C compiler.

It is also the answer to a question that comes up as soon as you read a trace next to a format. The format says `prev_state` is a signed integer. The trace says `prev_state=S`. Both are right, and `print fmt` is what happened in between: it ran the number through `__print_flags` before the text was ever written. So the field list tells you what is in the record and the printed line tells you what the kernel decided to show you, and a reader that assumes those are the same thing will be wrong about roughly one field per event.

## The four here

`sched_switch.format` is the one to read first, for the `prev_state` reasons above and because it is the event that the capture next door is mostly made of.

`sched_wakeup.format` is here because of `comm`, a `char[16]` copied into the record at the moment the event fired. That copy is the reason `corpora/traces/tier0/events-exec.txt` has a line whose header says `sleep` and whose payload says `sh` for the same pid, and the payload is the one that was true at the time.

`sched_process_exec.format` has the only field shape in this corpus that does not hold its own value. `filename` is a `__data_loc char[]`, which is four bytes in the record holding an offset and a length, with the string itself sitting further along. That is how a value of any length fits in a record of a fixed size, and it is why the size column says 4 for a field that prints as `/bin/true`.

`sys_enter.format` has the only array that is not a string: `unsigned long args[6]`, one field of 24 bytes rather than six fields of four. It is not in any capture here. It is kept anyway, because a corpus of formats that only holds the shapes one capture happened to use is a corpus that tests one code path.

## Taking one again

```
node kxbox/web/headless.js sh 'cat /sys/kernel/tracing/events/sched/sched_switch/format'
```

No setup, no tracer, and no need to turn anything on. A format file is there whether or not the event is enabled, which makes these the cheapest artefacts in the whole corpus to refresh after a kernel bump. They are also the ones most likely to change, which is the point.
