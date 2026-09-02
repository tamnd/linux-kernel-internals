# Experiments

A capture says what the kernel did. An experiment says what it cost.

The difference matters here because of how Tier 0 works. The pinned kernel runs under v86, which has no real clock, so every duration in a Tier 0 trace is a number about the emulator. The order of events is true, the nesting is true, and the microseconds are not. That is written into every Tier 0 `.meta.toml` and no claim rests on them.

So when a lesson wants to say something costs time, the measurement has to come off a real machine, and this is where those measurements live. Same rules as everywhere else in `corpora/`: the output is committed exactly as it came out, a `.meta.toml` beside it says which machine and how to do it again, and nothing gets edited to match the prose.

## tracer-cost.txt

The same one byte write, timed three ways: with the tracer off, with `function_graph` filtered to `vfs_write`, and with `function_graph` tracing every function in the kernel.

About a quarter of a microsecond untraced, about six and a half with the tracer on. That is roughly twenty five times, on a machine where a write is already one of the cheaper things you can ask the kernel to do.

It is worth knowing before you measure anything else. If you turn the tracer on to find out why something is slow, you have made it about twenty five times slower in the act of looking, and any number you read while it is on is a number about the tracer. Tracing tells you what happened and in what order. It does not tell you how long it took.

The filter turned out to be almost free here, which is only true because the workload is nothing but writes and filtering to `vfs_write` therefore filters nothing. On a machine doing anything else the filter is the difference between a trace you can read and a ring buffer that has thrown away everything you wanted, which is what `../../proc/tier0/ring-overrun.txt` shows happening in seven milliseconds.
