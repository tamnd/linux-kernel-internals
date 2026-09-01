// The page side: turn a request from the Python worker into shell, wait for the guest, answer.
//
// Two things here that are not obvious.
//
// One command at a time. There is one shell and one serial line, so two commands in flight would
// interleave their output and both answers would be wrong. Requests queue.
//
// Every command has a deadline. A guest that has wedged looks exactly like a guest that is being
// slow, and a lesson cell that never returns is worse than one that fails, because the reader has
// no way to tell which of the two happened.

import { MORE } from "./channel.js";
import { commandFor, insmodCommand, nextId, parseReply, readCommand, writeCommands } from "./guest.js";

export const TIMEOUT = 20000;

// The protocol, and nothing else. Same four names as `CALLS` in kxbox/bridge.py.
export const CALLS = ["sh", "read", "write", "insmod"];

export class Guest {
  // `serial` is anything with `send(text)` and `listen(fn)`. In the page that is v86's serial
  // adapter. In the tests it is an object that replies with canned output. The emulator is never
  // imported here, which is what makes this file testable at all.
  constructor(serial, { timeout = TIMEOUT } = {}) {
    this.serial = serial;
    this.timeout = timeout;
    this.waiting = null;
    this.queue = Promise.resolve();
    serial.listen((text) => this.arrived(text));
  }

  run(line) {
    // Chain on the previous command rather than starting now, and keep the chain alive when one
    // of them fails, or a single bad command would poison every command after it.
    const next = this.queue.then(
      () => this.send(line),
      () => this.send(line),
    );
    this.queue = next.catch(() => {});
    return next;
  }

  send(line) {
    const id = nextId();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.waiting = null;
        reject(new Error(`the guest did not finish ${JSON.stringify(line)} within ${this.timeout}ms`));
      }, this.timeout);

      this.waiting = {
        id,
        stream: "",
        done: (reply) => {
          clearTimeout(timer);
          this.waiting = null;
          resolve(reply);
        },
      };
      this.serial.send(commandFor(id, line));
    });
  }

  arrived(text) {
    const waiting = this.waiting;
    if (!waiting) return; // console noise between commands, which there is plenty of
    waiting.stream += text;
    const reply = parseReply(waiting.id, waiting.stream);
    if (reply) waiting.done(reply);
  }
}

// A command that was supposed to work and did not. The message carries the guest's own words,
// because "read failed" tells a reader nothing and "cat: /sys/kernel/tracing/trace: No such file
// or directory" tells them the tracer is not mounted.
function insist(reply, what) {
  if (reply.status !== 0) {
    const said = reply.stderr.trim() || reply.stdout.trim() || `exit ${reply.status}`;
    throw new Error(`${what}: ${said}`);
  }
  return reply;
}

export class Host {
  constructor(guest, answerer) {
    this.guest = guest;
    this.answerer = answerer;
  }

  async sh(line) {
    const reply = await this.guest.run(line);
    return { status: reply.status, stdout: reply.stdout, stderr: reply.stderr };
  }

  async read(path) {
    const reply = await this.guest.run(readCommand(path));
    return insist(reply, `reading ${path}`).stdout;
  }

  async write(path, text) {
    for (const line of writeCommands(path, text)) {
      insist(await this.guest.run(line), `writing ${path}`);
    }
    return null;
  }

  async insmod(path) {
    const reply = await this.guest.run(insmodCommand(path));
    return { status: reply.status, stdout: reply.stdout, stderr: reply.stderr };
  }

  // One request from the worker. Answers exactly once, whatever happens, because the worker is
  // blocked on that answer and an exception that only reaches the console leaves it blocked
  // forever.
  async handle(request) {
    if (request.call === MORE) {
      this.answerer.flush();
      return;
    }
    try {
      // An allow list rather than a lookup on `this`, so a request naming any other method of this
      // object gets an error instead of a surprise.
      if (!CALLS.includes(request.call)) throw new Error(`no such call: ${request.call}`);
      this.answerer.value(await this[request.call].apply(this, request.args || []));
    } catch (error) {
      this.answerer.failed(error);
    }
  }
}
