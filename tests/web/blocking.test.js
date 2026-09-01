// The claim the whole design rests on, in two real threads.
//
// A lesson cell says `box.sh("dd ...")` and reads the answer on the next line. For that to be
// true, the thread Python is on has to stop until the emulator has finished, and the thread the
// emulator is on has to keep running while it is stopped. Everything else in this directory is
// arrangement. This is the part that is either true or not.
//
// Node's worker threads are not a browser, but `Atomics.wait`, `SharedArrayBuffer` and
// `postMessage` are the same three things in both, so what is being checked here is the part that
// is ours.

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Worker } from "node:worker_threads";

import { Answerer, MORE, makeChannel } from "../../kxbox/web/channel.js";

const WORKER = new URL("./caller-worker.js", import.meta.url);

// Every answer is deliberately late. If the caller were not really blocking it would read the
// buffer before anything had been put in it and come back with nothing.
function ask(call, args, answer, { bytes = 64, wait = 10 } = {}) {
  const channel = makeChannel(bytes);
  const answerer = new Answerer(channel);
  const asked = [];

  return new Promise((resolve, reject) => {
    const worker = new Worker(WORKER, { workerData: { channel, call, args } });
    worker.on("error", reject);
    worker.on("message", (message) => {
      if (!message.request) {
        worker.terminate();
        resolve({ ...message, asked });
        return;
      }
      asked.push(message.request);
      setTimeout(() => {
        if (message.request.call === MORE) answerer.flush();
        else answer(answerer, message.request);
      }, wait);
    });
  });
}

describe("a call that crosses a thread", () => {
  it("waits for the answer instead of racing it", async () => {
    const got = await ask("sh", ["echo hi"], (answerer) =>
      answerer.value({ status: 0, stdout: "hi\n", stderr: "" }),
    );
    assert.deepEqual(got.value, { status: 0, stdout: "hi\n", stderr: "" });
  });

  it("arrives with the arguments the caller sent", async () => {
    const got = await ask("write", ["/sys/kernel/tracing/tracing_on", "1"], (answerer, request) =>
      answerer.value(request.args),
    );
    assert.deepEqual(got.value, ["/sys/kernel/tracing/tracing_on", "1"]);
  });

  it("brings a long answer back in pieces without losing any of it", async () => {
    const trace = "vfs_write() {\n".repeat(500);
    const got = await ask("read", ["/sys/kernel/tracing/trace"], (a) => a.value(trace), {
      bytes: 128,
      wait: 0,
    });
    assert.equal(got.value, trace);
    assert.ok(got.asked.length > 1, "it should have asked for the rest");
  });

  it("raises on the Python side when the page could not do it", async () => {
    const got = await ask("read", ["/gone"], (answerer) =>
      answerer.failed(new Error("cat: /gone: No such file or directory")),
    );
    assert.match(got.error, /No such file or directory/);
  });
});
