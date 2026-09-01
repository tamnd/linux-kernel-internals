// One synchronous call, across two threads that do not share an event loop.
//
// Python runs in a worker under Pyodide. The emulator runs on the page. A lesson cell says
// `box.sh("dd ...")` and expects an answer on the next line, so the worker has to stop and wait
// for the page to finish, and stopping is the whole difficulty. A worker is allowed to block on
// `Atomics.wait`. The page is not, which is why the sides are arranged this way round and not the
// other. That is the one thing about this file worth remembering.
//
// The request goes over `postMessage`, which is queued before the worker blocks and so arrives
// even though the worker is asleep. The answer comes back through the shared buffer, because the
// worker cannot receive a message while it is blocked.
//
// The buffer is a fixed size and a trace is not, so a long answer comes back in pieces. That is
// worth the small amount of bookkeeping below, because the alternative is a buffer big enough for
// the biggest trace anybody ever takes, chosen by guessing.

// Three integers of header, then the bytes.
export const HEADER = 3;
export const STATE = 0;
export const LENGTH = 1;
export const REMAINING = 2;

// What the state word says. The worker sets it to WAITING before it asks, and blocks until the
// page sets it to DONE. There is no ERROR state: a failure is an answer that says it failed.
export const WAITING = 0;
export const DONE = 1;

// A megabyte of payload per turn. Big enough that an ordinary trace arrives in one piece, small
// enough that a page holding several channels open is not holding much.
export const CHUNK = 1 << 20;

// The request the worker sends to ask for the rest of an answer that did not fit.
export const MORE = "_more";

const encoder = new TextEncoder();
const decoder = new TextDecoder();

export function makeChannel(bytes = CHUNK) {
  return new SharedArrayBuffer(HEADER * 4 + bytes);
}

export function views(channel) {
  return {
    control: new Int32Array(channel, 0, HEADER),
    payload: new Uint8Array(channel, HEADER * 4),
  };
}

// The worker side. Blocks.
export class Caller {
  // `send` is whatever gets a message to the page, which is `postMessage` in the browser and a
  // function in the tests. It is passed in rather than looked up so this file has no globals in it.
  constructor(channel, send) {
    const { control, payload } = views(channel);
    this.control = control;
    this.payload = payload;
    this.send = send;
  }

  call(name, args = []) {
    const pieces = [];
    let total = 0;
    let request = { call: name, args };

    for (;;) {
      Atomics.store(this.control, STATE, WAITING);
      this.send(request);
      Atomics.wait(this.control, STATE, WAITING);

      const length = Atomics.load(this.control, LENGTH);
      // Copy out of the shared buffer before saying anything, because the next turn overwrites it.
      pieces.push(this.payload.slice(0, length));
      total += length;

      if (Atomics.load(this.control, REMAINING) === 0) break;
      request = { call: MORE, args: [] };
    }

    const whole = new Uint8Array(total);
    let at = 0;
    for (const piece of pieces) {
      whole.set(piece, at);
      at += piece.length;
    }

    const reply = JSON.parse(decoder.decode(whole));
    if (!reply.ok) throw new Error(reply.error);
    return reply.value;
  }
}

// The page side. Never blocks.
export class Answerer {
  constructor(channel) {
    const { control, payload } = views(channel);
    this.control = control;
    this.payload = payload;
    this.tail = new Uint8Array(0);
  }

  value(value) {
    this.answer({ ok: true, value });
  }

  failed(error) {
    this.answer({ ok: false, error: String(error && error.message ? error.message : error) });
  }

  answer(reply) {
    this.tail = encoder.encode(JSON.stringify(reply));
    this.flush();
  }

  // Called again for each MORE request, until there is nothing left over.
  flush() {
    const length = Math.min(this.tail.length, this.payload.length);
    this.payload.set(this.tail.subarray(0, length));
    this.tail = this.tail.subarray(length);

    Atomics.store(this.control, LENGTH, length);
    Atomics.store(this.control, REMAINING, this.tail.length);
    Atomics.store(this.control, STATE, DONE);
    Atomics.notify(this.control, STATE);
  }
}
