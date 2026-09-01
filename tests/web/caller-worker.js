// The blocking side, in a real thread, for the one test that has to prove it really blocks.

import { parentPort, workerData } from "node:worker_threads";

import { Caller } from "../../kxbox/web/channel.js";

const caller = new Caller(workerData.channel, (request) => parentPort.postMessage({ request }));

try {
  parentPort.postMessage({ value: caller.call(workerData.call, workerData.args) });
} catch (error) {
  parentPort.postMessage({ error: error.message });
}
