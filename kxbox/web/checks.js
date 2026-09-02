// The things a lesson stops working without.
//
// One list, used by the node smoke run and by the page, because a check that passes under node and
// is never run in a tab is a check for the wrong machine. The kill criterion is about a browser,
// and a browser is the place where the answer is allowed to be different.
//
// Every entry says what it is for. A red line in a list of names tells you nothing about what just
// became impossible, and the person reading it is usually not the person who wrote it.

export const CHECKS = [
  { name: "shell", what: "the protocol reaches a shell at all", run: (box) => box.sh("echo hello") },
  { name: "proc", what: "everything /proc based", run: (box) => box.read("/proc/version") },
  { name: "kallsyms", what: "names in a trace instead of addresses", run: (box) => box.sh("wc -l < /proc/kallsyms") },
  { name: "tracefs", what: "Z02 and every trace in the book", run: (box) => box.sh("ls /sys/kernel/tracing/current_tracer") },
  { name: "tracers", what: "function_graph, which is what a tape is made of", run: (box) => box.read("/sys/kernel/tracing/available_tracers") },
  { name: "dmesg", what: "C09 and every oops lesson", run: (box) => box.sh("dmesg | tail -1") },
  { name: "write", what: "turning a tracer on, which is a single redirect", run: (box) => box.write("/tmp/probe", "one\ntwo\n") },
  { name: "readback", what: "the write above actually landing", run: (box) => box.read("/tmp/probe") },
  { name: "modules", what: "every part that ends in a change", run: (box) => box.sh("test -d /sys/module") },
  { name: "touchpage", what: "a page fault trace with one fault in it instead of thirty", run: (box) => box.sh("/bin/touchpage") },
];

// A reply is a string from `read` and an object from `sh`, and nothing above cares which.
export function summarise(answer) {
  const shown = typeof answer === "string" ? answer : (answer && answer.stdout) || "";
  const status = typeof answer === "object" && answer ? answer.status : 0;
  return { status: status || 0, first: (shown.trim().split("\n")[0] || "").slice(0, 60) };
}

// Run all of them and report, without throwing. The caller decides what a failure looks like,
// because on a page it is a red row and under node it is an exit code.
export async function runChecks(box, checks = CHECKS) {
  const out = [];
  for (const check of checks) {
    try {
      const { status, first } = summarise(await check.run(box));
      if (status !== 0) throw new Error(`exit ${status}`);
      out.push({ name: check.name, what: check.what, ok: true, detail: first });
    } catch (error) {
      out.push({ name: check.name, what: check.what, ok: false, detail: error.message.split("\n")[0] });
    }
  }
  return out;
}
