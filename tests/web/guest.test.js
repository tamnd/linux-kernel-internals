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
    `\n${MARK}:BEG:${id}\n${stdout}\n${MARK}:ERR:${id}\n${stderr}\n${MARK}:END:${id}:${status}\n`;

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

  it("waits for the status even though the marker before it has arrived", () => {
    // The bug: the end marker was matched as soon as `__kx:END:abc:` was on the wire, which is one
    // byte before the status is. The status parsed as empty, empty became 0, and every command
    // that failed came back looking like it had worked. A real serial line delivers a byte at a
    // time, so this is not a corner case, it is what always happens.
    const whole = stream("abc", { stdout: "one\n", status: 7 });
    const early = whole.slice(0, whole.indexOf(`${MARK}:END:abc:`) + `${MARK}:END:abc:`.length);
    assert.equal(parseReply("abc", early), null);
    assert.equal(parseReply("abc", `${early}7`), null); // still no newline, still not finished
    assert.equal(parseReply("abc", `${early}7\n`).status, 7);
  });

  it("gives the same answer byte by byte as it does all at once", () => {
    // Feeding the stream the way the emulator does, one byte at a time, and parsing after each
    // one. There is exactly one point at which an answer may appear and it has to be the right one.
    const whole = stream("abc", { stdout: "one\ntwo\n", stderr: "bad\n", status: 3 });
    const replies = [];
    for (let at = 1; at <= whole.length; at += 1) {
      const reply = parseReply("abc", whole.slice(0, at));
      if (reply) replies.push(reply);
    }
    assert.equal(replies.length, 1, `answered ${replies.length} times`);
    assert.deepEqual(replies[0], { status: 3, stdout: "one\ntwo\n", stderr: "bad\n" });
  });

  it("throws rather than guessing when the status is not a number", () => {
    const broken = `\n${MARK}:BEG:abc\n\n${MARK}:ERR:abc\n\n${MARK}:END:abc:huh\n`;
    assert.throws(() => parseReply("abc", broken), /without a status/);
  });

  it("keeps a multi line answer whole", () => {
    const reply = parseReply("abc", stream("abc", { stdout: "one\ntwo\nthree\n" }));
    assert.equal(reply.stdout, "one\ntwo\nthree\n");
  });
});

describe("writing a file", () => {
  it("clears the staging file, appends, decodes, and copies once into the target", () => {
    const lines = writeCommands("/sys/kernel/tracing/current_tracer", "function_graph");
    assert.equal(lines[0], `: > ${STAGING}`);
    assert.match(lines.at(-1), /^cat .* > '\/sys\/kernel\/tracing\/current_tracer'$/);
  });

  it("never decodes straight into the target, because base64 writes with writev", () => {
    // Found by tracing the syscalls inside the box. base64 -d into a tracer file gets EINVAL from
    // the kernel, exits 0 anyway, and leaves the old value in place, which is the worst shape a
    // failure can have.
    const lines = writeCommands("/sys/kernel/tracing/current_tracer", "function_graph");
    const decode = lines.find((one) => one.startsWith("base64 -d"));
    assert.ok(!decode.includes("current_tracer"), decode);
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
