// A guest that is not a kernel: enough busybox to answer the four calls.
//
// It understands the handful of shell forms `guest.js` actually emits, and looks everything else
// up in a table. That is not a simulation of a shell and is not meant to be. What it is for is
// checking that what we send and what we parse fit together, including the awkward parts: the
// echo of the command coming back at us, carriage returns from the terminal, stderr arriving
// after stdout, and a write arriving in pieces and having to end up as one file.

import { DECODED, MARK, STAGING } from "../../kxbox/web/guest.js";

export function unquote(text) {
  const inner = text.replace(/^'/, "").replace(/'$/, "");
  return inner.split(`'\\''`).join("'");
}

export class FakeGuest {
  // `answers` maps a command line to { status, stdout, stderr }. Anything not in it exits 127,
  // the same way a shell answers a command it cannot find.
  // `bytes` delivers the answer one character at a time instead of in one lump, which is what the
  // emulator's serial listener actually does. A double that hands over the whole reply at once is
  // a double that never asks the parser whether a half arrived marker looks finished, and that is
  // the shape of every parser bug this protocol has had.
  constructor(answers = {}, { delay = 0, echo = true, bytes = false } = {}) {
    this.answers = answers;
    this.delay = delay;
    this.echo = echo;
    this.bytes = bytes;
    this.files = { [STAGING]: "", [DECODED]: "" };
    this.sent = [];
    this.listeners = [];
  }

  listen(fn) {
    this.listeners.push(fn);
  }

  emit(text) {
    for (const fn of this.listeners) fn(text);
  }

  send(text) {
    this.sent.push(text);
    const id = /__kx:BEG:([^\\]+)\\n/.exec(text)[1];
    const line = /\{ ([\s\S]*?)\n\} 2>/.exec(text)[1];
    const reply = this.run(line);

    // The terminal ends its lines with a carriage return, and echoes what we typed. Both are
    // things the parser has to cope with, so both are here.
    const crlf = (one) => one.split("\n").join("\r\n");
    // Every marker starts on a line of its own, the same way the printfs in `commandFor` do. That
    // leading newline is not decoration: it is what lets a command whose output did not end in one
    // still have its marker on a fresh line, and a double that leaves it out is a double that
    // makes the parser look right when it is off by exactly one newline.
    const stream =
      (this.echo ? crlf(text) : "") +
      crlf(`\n${MARK}:BEG:${id}\n${reply.stdout}\n${MARK}:ERR:${id}\n${reply.stderr}`) +
      crlf(`\n${MARK}:END:${id}:${reply.status}\n`);

    const hand = () => {
      if (!this.bytes) return this.emit(stream);
      for (const one of stream) this.emit(one);
    };

    if (this.delay) setTimeout(hand, this.delay);
    else hand();
  }

  run(line) {
    const ok = (stdout = "") => ({ status: 0, stdout, stderr: "" });

    if (line === `: > ${STAGING}`) {
      this.files[STAGING] = "";
      return ok();
    }

    const appending = new RegExp(`^printf '%s' (.*) >> ${STAGING}$`).exec(line);
    if (appending) {
      this.files[STAGING] += unquote(appending[1]);
      return ok();
    }

    const decoding = new RegExp(`^base64 -d < ${STAGING} > (.*)$`).exec(line);
    if (decoding) {
      this.files[unquote(decoding[1])] = Buffer.from(this.files[STAGING], "base64").toString();
      return ok();
    }

    // The last step of a write is a copy rather than a read, because the decode cannot go
    // straight into a tracer file. It has to be matched before the plain cat below it.
    const copying = new RegExp(`^cat ${DECODED} > (.*)$`).exec(line);
    if (copying) {
      this.files[unquote(copying[1])] = this.files[DECODED];
      return ok();
    }

    const reading = /^cat (.*)$/.exec(line);
    if (reading) {
      const path = unquote(reading[1]);
      if (path in this.files) return ok(this.files[path]);
      return { status: 1, stdout: "", stderr: `cat: ${path}: No such file or directory\n` };
    }

    const answer = this.answers[line];
    if (!answer) return { status: 127, stdout: "", stderr: `sh: ${line}: not found\n` };
    return { status: 0, stdout: "", stderr: "", ...answer };
  }
}
