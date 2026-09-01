// The shell protocol: what we send, and what we can get back out of what returns.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MARK,
  STAGING,
  commandFor,
  nextId,
  parseReply,
  quote,
  readCommand,
  writeCommands,
} from "../../kxbox/web/guest.js";

describe("quoting", () => {
  it("wraps a path in single quotes", () => {
    assert.equal(quote("/sys/kernel/tracing/trace"), "'/sys/kernel/tracing/trace'");
  });

  it("survives the one character a single quoted string cannot hold", () => {
    assert.equal(quote("it's"), `'it'\\''s'`);
  });
});

describe("the command we send", () => {
  it("carries the command inside the markers", () => {
    const line = commandFor("abc", "echo hi");
    assert.match(line, /__kx:BEG:abc/);
    assert.match(line, /echo hi/);
    assert.match(line, /__kx:END:abc/);
  });

  it("closes the group on a line of its own, so a trailing semicolon is still valid shell", () => {
    assert.match(commandFor("abc", "echo hi;"), /echo hi;\n\} 2>/);
  });

  it("gives every call a different id", () => {
    assert.notEqual(nextId(), nextId());
  });
});

describe("reading the answer back", () => {
  const stream = (id, { stdout = "", stderr = "", status = 0 } = {}) =>
    `\n${MARK}:BEG:${id}\n${stdout}${MARK}:ERR:${id}\n${stderr}${MARK}:END:${id}:${status}\n`;

  it("says nothing until the command has finished", () => {
    assert.equal(parseReply("abc", `\n${MARK}:BEG:abc\nhalf a line`), null);
  });

  it("splits the two streams and the status", () => {
    const reply = parseReply("abc", stream("abc", { stdout: "one\n", stderr: "bad\n", status: 2 }));
    assert.deepEqual(reply, { status: 2, stdout: "one\n", stderr: "bad\n", });
  });

  it("returns empty rather than a blank line when a command printed nothing", () => {
    assert.deepEqual(parseReply("abc", stream("abc")), { status: 0, stdout: "", stderr: "" });
  });

  it("drops the prompt and the echo of what we typed", () => {
    const noise = `~ # ${commandFor("abc", "echo hi")}`;
    const reply = parseReply("abc", noise + stream("abc", { stdout: "hi\n" }));
    assert.equal(reply.stdout, "hi\n");
  });

  it("strips the carriage returns the terminal adds", () => {
    const reply = parseReply("abc", stream("abc", { stdout: "one\n" }).split("\n").join("\r\n"));
    assert.equal(reply.stdout, "one\n");
  });

  it("ignores an answer belonging to another call", () => {
    assert.equal(parseReply("abc", stream("xyz", { stdout: "hi\n" })), null);
  });

  it("keeps a multi line answer whole", () => {
    const reply = parseReply("abc", stream("abc", { stdout: "one\ntwo\nthree\n" }));
    assert.equal(reply.stdout, "one\ntwo\nthree\n");
  });
});

describe("writing a file", () => {
  it("clears the staging file, appends, and decodes once into the target", () => {
    const lines = writeCommands("/sys/kernel/tracing/current_tracer", "function_graph");
    assert.equal(lines[0], `: > ${STAGING}`);
    assert.match(lines.at(-1), /^base64 -d < .* > '\/sys\/kernel\/tracing\/current_tracer'$/);
  });

  it("splits a long file into pieces, because the command line has a length", () => {
    const lines = writeCommands("/tmp/big", "x".repeat(4096), 512);
    assert.ok(lines.length > 4, "a four kilobyte file should not be one command");
    for (const line of lines) assert.ok(line.length < 1024, `too long: ${line.slice(0, 40)}`);
  });

  it("writes the target with one redirect, because two writes to a tracer file are two writes", () => {
    const lines = writeCommands("/sys/kernel/tracing/set_ftrace_filter", "a\nb\nc", 4);
    const touching = lines.filter((one) => one.includes("set_ftrace_filter"));
    assert.equal(touching.length, 1);
  });
});

describe("the other two calls", () => {
  it("reads with cat", () => {
    assert.equal(readCommand("/proc/self/status"), "cat '/proc/self/status'");
  });
});
