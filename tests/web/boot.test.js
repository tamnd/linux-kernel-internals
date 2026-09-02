// The one test that needs a kernel.
//
// Everything else in this directory is checked against a stand in, on purpose, because that is what
// runs in CI on a machine with no images on it. This file is the other half of that trade: it runs
// the four calls against a real kernel when there is one, and skips when there is not.
//
// Skipping rather than failing is a deliberate choice and it has a cost. A test that skips is a
// test nobody notices going quiet, so it prints why it skipped and which command builds the missing
// piece, and the skip is loud enough to read in the output.
//
// What this catches that the stand ins cannot: both protocol bugs found the first time the box was
// booted were in code with passing tests, and in both cases the double was wrong in the same way
// the code was. A double can only disagree with you about things you thought of.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { before, after, describe, it } from "node:test";

import { IMAGES, boot } from "../../kxbox/web/headless.js";

function whatIsMissing() {
  const gone = [];
  for (const [name, path] of Object.entries(IMAGES)) {
    try {
      readFileSync(path, { flag: "r" });
    } catch {
      gone.push(name);
    }
  }
  return gone;
}

const gone = whatIsMissing();
const why =
  `no images: ${gone.join(", ")}. ` +
  "python3 -m tools.vendor, sh kxbox/rootfs/build.sh, sh kxbox/kernel/build.sh A-full";

describe("a real kernel", { skip: gone.length ? why : false }, () => {
  let box;

  before(async () => {
    box = await boot({ seconds: 120 });
  });

  after(() => {
    if (box) box.emulator.stop();
  });

  it("reaches a shell that runs commands and reports status", async () => {
    const hello = await box.host.sh("echo hello");
    assert.equal(hello.status, 0);
    assert.equal(hello.stdout, "hello\n");

    // A non zero exit is an answer, not an exception. A lesson about error paths needs to see it.
    const bad = await box.host.sh("false");
    assert.equal(bad.status, 1);
  });

  it("keeps stdout and stderr apart on the one serial line", async () => {
    const both = await box.host.sh("echo out; echo err >&2");
    assert.equal(both.stdout, "out\n");
    assert.equal(both.stderr, "err\n");
  });

  it("reads a file back exactly, with no newline added or lost", async () => {
    // The bug this pins down: the markers each start on a line of their own, and joining the lines
    // back together with a trailing newline added returns one more newline than the file has. It
    // looked right in every test because the double put the same extra newline in.
    await box.host.sh("printf 'one\\ntwo\\n' > /tmp/withnl");
    await box.host.sh("printf 'nonl' > /tmp/nonl");
    assert.equal(await box.host.read("/tmp/withnl"), "one\ntwo\n");
    assert.equal(await box.host.read("/tmp/nonl"), "nonl");
  });

  it("writes a file of a few kilobytes in one piece", async () => {
    const text = `${Array.from({ length: 400 }, (_, at) => `line ${at}`).join("\n")}\n`;
    await box.host.write("/tmp/big", text);
    assert.equal(await box.host.read("/tmp/big"), text);
  });

  it("writes to a tracefs file, which an ordinary write does not manage", async () => {
    // Decoding base64 straight into the target here does nothing at all and reports success:
    // busybox base64 uses writev, the tracer's write handler answers EINVAL, and base64 exits 0
    // anyway. This is the check that says the extra hop through a scratch file is still there.
    const path = "/sys/kernel/tracing/current_tracer";
    await box.host.write(path, "function_graph");
    assert.equal((await box.host.read(path)).trim(), "function_graph");
    await box.host.write(path, "nop");
    assert.equal((await box.host.read(path)).trim(), "nop");
  });

  it("has the kernel facilities every lesson leans on", async () => {
    const version = await box.host.read("/proc/version");
    assert.match(version, /Linux version 7\.2\.2/);

    const tracers = await box.host.read("/sys/kernel/tracing/available_tracers");
    assert.match(tracers, /function_graph/);

    const symbols = await box.host.sh("wc -l < /proc/kallsyms");
    assert.ok(Number(symbols.stdout.trim()) > 10000, `only ${symbols.stdout.trim()} symbols`);

    const modules = await box.host.sh("test -d /sys/module");
    assert.equal(modules.status, 0);
  });
});
