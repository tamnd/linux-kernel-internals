// The two pieces the page and the node smoke run share, driven without either.
//
// Neither of these needs a kernel, which is the point. What they do need is to behave the same
// whichever side calls them, because the whole reason `checks.js` exists as one file is that a
// check passing under node and never running in a tab is a check for the wrong machine.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { CHECKS, runChecks, summarise } from "../../kxbox/web/checks.js";
import { Python, imagesFor } from "../../kxbox/web/page.js";

describe("the shared check list", () => {
  it("says what every check is for, so a red line means something", () => {
    for (const check of CHECKS) {
      assert.ok(check.name, "a check with no name");
      assert.ok(check.what, `${check.name} does not say what it is for`);
      assert.equal(typeof check.run, "function");
    }
  });

  it("reads a string answer and an object answer the same way", () => {
    assert.deepEqual(summarise("one\ntwo\n"), { status: 0, first: "one" });
    assert.deepEqual(summarise({ status: 0, stdout: "hello\n" }), { status: 0, first: "hello" });
  });

  it("treats a non zero exit as a failure even though the call returned", () => {
    assert.equal(summarise({ status: 1, stdout: "" }).status, 1);
  });

  it("reports a check that threw instead of stopping at it", async () => {
    const results = await runChecks(null, [
      { name: "fine", what: "nothing", run: () => "ok\n" },
      { name: "broken", what: "nothing", run: () => { throw new Error("no shell\nand a second line"); } },
      { name: "after", what: "nothing", run: () => "still ran\n" },
    ]);
    assert.deepEqual(results.map((r) => [r.name, r.ok]), [["fine", true], ["broken", false], ["after", true]]);
    // One line, because the second line of a stack trace in a table cell helps nobody.
    assert.equal(results[1].detail, "no shell");
  });

  it("reports a check that came back with an exit code", async () => {
    const results = await runChecks(null, [
      { name: "missing", what: "nothing", run: () => ({ status: 127, stdout: "" }) },
    ]);
    assert.equal(results[0].ok, false);
    assert.equal(results[0].detail, "exit 127");
  });
});

describe("which kernel the page boots", () => {
  it("leaves the defaults alone for the profile the book uses", () => {
    assert.deepEqual(imagesFor("A-full"), {});
    assert.deepEqual(imagesFor(""), {});
  });

  it("points at the other build for any other profile", () => {
    assert.deepEqual(imagesFor("A-gzip"), { bzimage: "/kernel/build/A-gzip/bzImage" });
  });
});

// A stand in for the worker. Everything `Python` does is postMessage out and receive back, so the
// worker being a real thread adds nothing to what these say.
function fakeWorker() {
  const sent = [];
  return { sent, postMessage: (message) => sent.push(message) };
}

describe("Python in the worker", () => {
  it("comes up when the worker says it did, with the version it found", async () => {
    const python = new Python(fakeWorker());
    python.receive({ ready: true, version: "3.13.2" });
    assert.equal(await python.up, "3.13.2");
  });

  it("fails with the worker's own reason rather than with a timeout", async () => {
    const python = new Python(fakeWorker());
    python.receive({ ready: false, error: "cannot fetch the wheel" });
    await assert.rejects(python.up, /cannot fetch the wheel/);
  });

  it("matches an answer to the cell that asked for it", async () => {
    const worker = fakeWorker();
    const python = new Python(worker);
    const first = python.run("1 + 1");
    const second = python.run("2 + 2");
    assert.deepEqual(worker.sent.map((m) => m.cell), [1, 2]);

    // Deliberately out of order. Two cells can be in flight and nothing promises the second one
    // takes longer than the first.
    python.receive({ cell: 2, value: "4" });
    python.receive({ cell: 1, value: "2" });
    assert.equal(await first, "2");
    assert.equal(await second, "4");
  });

  it("turns an error from a cell into a rejection of that cell", async () => {
    const python = new Python(fakeWorker());
    const cell = python.run("1 / 0");
    python.receive({ cell: 1, error: "ZeroDivisionError: division by zero" });
    await assert.rejects(cell, /ZeroDivisionError/);
  });

  it("ignores an answer to a cell nobody is waiting for", () => {
    const python = new Python(fakeWorker());
    assert.doesNotThrow(() => python.receive({ cell: 99, value: "late" }));
  });
});
