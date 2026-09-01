// The page side, driven against a guest that answers like a shell but is not a kernel.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { Answerer, MORE, makeChannel } from "../../kxbox/web/channel.js";
import { STAGING } from "../../kxbox/web/guest.js";
import { Guest, Host } from "../../kxbox/web/host.js";
import { FakeGuest } from "./fakeguest.js";

const TRACE = "# tracer: function_graph\n 0)   1.250 us    |  vfs_write();\n";

function host(answers = {}, options = {}) {
  const serial = new FakeGuest(answers, options);
  const channel = makeChannel();
  const answerer = new Answerer(channel);
  return { serial, answerer, host: new Host(new Guest(serial, options), answerer) };
}

describe("running a command", () => {
  it("gives back what it printed and what it exited with", async () => {
    const { host: page } = host({ "echo hi": { stdout: "hi\n" } });
    assert.deepEqual(await page.sh("echo hi"), { status: 0, stdout: "hi\n", stderr: "" });
  });

  it("treats a non zero exit as an answer rather than as a failure", async () => {
    const { host: page } = host({ "insmod /tmp/bad.ko": { status: 1, stderr: "invalid module\n" } });
    const reply = await page.sh("insmod /tmp/bad.ko");
    assert.equal(reply.status, 1);
    assert.equal(reply.stderr, "invalid module\n");
  });

  it("keeps the two streams apart, even though they share one serial line", async () => {
    const { host: page } = host({ dmesg: { stdout: "out\n", stderr: "err\n", status: 0 } });
    const reply = await page.sh("dmesg");
    assert.equal(reply.stdout, "out\n");
    assert.equal(reply.stderr, "err\n");
  });
});

describe("one command at a time", () => {
  it("does not let two commands interleave on the one shell", async () => {
    const { host: page } = host(
      { first: { stdout: "one\n" }, second: { stdout: "two\n" } },
      { delay: 5 },
    );
    const [one, two] = await Promise.all([page.sh("first"), page.sh("second")]);
    assert.equal(one.stdout, "one\n");
    assert.equal(two.stdout, "two\n");
  });

  it("keeps going after a command that timed out", async () => {
    const serial = new FakeGuest({ ok: { stdout: "fine\n" } });
    const quiet = { send() {}, listen: (fn) => serial.listen(fn) };
    const page = new Host(new Guest(quiet, { timeout: 20 }), null);
    await assert.rejects(() => page.sh("wedged"), /did not finish/);

    const talkative = new Host(new Guest(serial, { timeout: 200 }), null);
    assert.equal((await talkative.sh("ok")).stdout, "fine\n");
  });
});

describe("reading a file", () => {
  it("gives back the contents", async () => {
    const { serial, host: page } = host();
    serial.files["/sys/kernel/tracing/trace"] = TRACE;
    assert.equal(await page.read("/sys/kernel/tracing/trace"), TRACE);
  });

  it("fails with the words the guest used, not with words of ours", async () => {
    const { host: page } = host();
    await assert.rejects(() => page.read("/sys/kernel/tracing/trace"), /No such file or directory/);
  });
});

describe("writing a file", () => {
  it("arrives whole, however many commands it took", async () => {
    const { serial, host: page } = host();
    await page.write("/sys/kernel/tracing/set_ftrace_filter", "vfs_write\ngeneric_perform_write");
    assert.equal(serial.files["/sys/kernel/tracing/set_ftrace_filter"], "vfs_write\ngeneric_perform_write");
  });

  it("survives text that would break quoting", async () => {
    const { serial, host: page } = host();
    const awkward = `it's "quoted" $(and) \`worse\`\n`;
    await page.write("/tmp/awkward", awkward);
    assert.equal(serial.files["/tmp/awkward"], awkward);
  });

  it("stages the whole thing before touching the target", async () => {
    const { serial, host: page } = host();
    await page.write("/tmp/target", "x".repeat(2000));
    const order = serial.sent.map((one) => (one.includes(STAGING) ? "staging" : "other"));
    assert.equal(order.at(-1), "staging", "the decode into the target reads the staging file");
    assert.equal(serial.files["/tmp/target"], "x".repeat(2000));
  });
});

describe("answering the worker", () => {
  it("answers once, even when the call blew up", async () => {
    const { answerer, host: page } = host();
    let answered = 0;
    answerer.answer = (reply) => {
      answered += 1;
      assert.equal(reply.ok, false);
    };
    await page.handle({ call: "read", args: ["/gone"] });
    assert.equal(answered, 1);
  });

  it("refuses a call that is not in the protocol", async () => {
    const { answerer, host: page } = host();
    const said = [];
    answerer.answer = (reply) => said.push(reply);
    await page.handle({ call: "constructor", args: [] });
    assert.match(said[0].error, /no such call/);
  });

  it("treats a request for the rest of an answer as bookkeeping, not as a call", async () => {
    const { answerer, host: page } = host();
    let flushed = 0;
    answerer.flush = () => (flushed += 1);
    await page.handle({ call: MORE, args: [] });
    assert.equal(flushed, 1);
  });
});
