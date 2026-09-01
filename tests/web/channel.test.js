// The shared buffer: one answer, however long it turns out to be.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { Answerer, Caller, HEADER, MORE, makeChannel } from "../../kxbox/web/channel.js";

// A page that answers the moment it is asked. The worker's `Atomics.wait` then returns straight
// away with "not-equal", which is the same path a real answer takes, minus the waiting.
function wired(bytes) {
  const channel = makeChannel(bytes);
  const answerer = new Answerer(channel);
  const answers = [];
  const asked = [];
  const caller = new Caller(channel, (request) => {
    asked.push(request.call);
    if (request.call === MORE) answerer.flush();
    else answers.shift()(answerer, request);
  });
  return { caller, answerer, asked, expect: (fn) => answers.push(fn) };
}

describe("a call and its answer", () => {
  it("carries a value back", () => {
    const { caller, expect } = wired();
    expect((answerer) => answerer.value({ status: 0, stdout: "hi\n" }));
    assert.deepEqual(caller.call("sh", ["echo hi"]), { status: 0, stdout: "hi\n" });
  });

  it("passes the arguments along", () => {
    const { caller, expect } = wired();
    expect((answerer, request) => answerer.value(request.args));
    assert.deepEqual(caller.call("write", ["/sys/kernel/tracing/tracing_on", "1"]), [
      "/sys/kernel/tracing/tracing_on",
      "1",
    ]);
  });

  it("turns a failure on the page into an exception in Python's thread", () => {
    const { caller, expect } = wired();
    expect((answerer) => answerer.failed(new Error("the tracer is not mounted")));
    assert.throws(() => caller.call("read", ["/sys/kernel/tracing/trace"]), /not mounted/);
  });
});

describe("an answer too big for the buffer", () => {
  it("comes back in pieces and arrives whole", () => {
    // Sixty four bytes of payload, against a trace of a few kilobytes.
    const { caller, expect } = wired(64);
    const trace = "vfs_write() {\n".repeat(400);
    expect((answerer) => answerer.value(trace));
    assert.equal(caller.call("read", ["/sys/kernel/tracing/trace"]), trace);
  });

  it("asks for the rest rather than truncating", () => {
    const { caller, asked, expect } = wired(16);
    expect((answerer) => answerer.value("x".repeat(200)));
    assert.equal(caller.call("read", ["/tmp/x"]).length, 200);
    assert.equal(asked[0], "read");
    assert.ok(asked.length > 10, "two hundred bytes through sixteen takes several turns");
    assert.ok(asked.slice(1).every((one) => one === MORE));
  });

  it("survives a value with characters that are more than one byte", () => {
    const { caller, expect } = wired(8);
    expect((answerer) => answerer.value("stack depth → 7 frames"));
    assert.equal(caller.call("read", ["/tmp/x"]), "stack depth → 7 frames");
  });
});

describe("the buffer itself", () => {
  it("is the header plus what was asked for", () => {
    assert.equal(makeChannel(1024).byteLength, HEADER * 4 + 1024);
  });
});
