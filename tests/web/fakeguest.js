// A guest that is not a kernel: enough busybox to answer the four calls.
//
// It understands the handful of shell forms `guest.js` actually emits, and looks everything else
// up in a table. That is not a simulation of a shell and is not meant to be. What it is for is
// checking that what we send and what we parse fit together, including the awkward parts: the
// echo of the command coming back at us, carriage returns from the terminal, stderr arriving
// after stdout, and a write arriving in pieces and having to end up as one file.

import { MARK, STAGING } from "../../kxbox/web/guest.js";

export function unquote(text) {
  const inner = text.replace(/^'/, "").replace(/'$/, "");
  return inner.split(`'\\''`).join("'");
}

export class FakeGuest {
  // `answers` maps a command line to { status, stdout, stderr }. Anything not in it exits 127,
  // the same way a shell answers a command it cannot find.
  constructor(answers = {}, { delay = 0, echo = true } = {}) {
    this.answers = answers;
    this.delay = delay;
    this.echo = echo;
    this.files = { [STAGING]: "" };
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
    const stream =
      (this.echo ? crlf(text) : "") +
      crlf(`\n${MARK}:BEG:${id}\n${reply.stdout}${MARK}:ERR:${id}\n${reply.stderr}`) +
      crlf(`${MARK}:END:${id}:${reply.status}\n`);

    if (this.delay) setTimeout(() => this.emit(stream), this.delay);
    else this.emit(stream);
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
