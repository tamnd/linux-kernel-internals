// The page. Boots the emulator, starts the Python worker, and carries messages between them.
//
// Nothing in this file has been run, because there is no built kernel and v86 is not vendored yet.
// It is the shortest thing that could work, written down so that the first person with a kernel
// image has something to run rather than something to design. Everything here that could be
// tested without an emulator has been moved into channel.js, guest.js and host.js, which is why
// this file is mostly wiring.

import { makeChannel } from "./channel.js";
import { Answerer } from "./channel.js";
import { Guest, Host } from "./host.js";

// Printed by the guest's init once the shell is up and the tracer is mounted. Waiting for a
// specific line rather than for a prompt, because a prompt is whatever the rootfs says it is and
// this is a fact we control.
export const READY = "__kx:READY";

export const DEFAULTS = {
  wasm: "vendor/v86/v86.wasm",
  bios: "vendor/v86/seabios.bin",
  vgabios: "vendor/v86/vgabios.bin",
  bzimage: "kernel/bzImage",
  initrd: "rootfs/initrd.gz",
  cmdline: "console=ttyS0 quiet nokaslr",
};

// v86 speaks bytes. Everything above here speaks strings.
export function serialFor(emulator) {
  const decoder = new TextDecoder();
  return {
    send(text) {
      emulator.serial0_send(text);
    },
    listen(fn) {
      emulator.add_listener("serial0-output-byte", (byte) => {
        fn(decoder.decode(new Uint8Array([byte]), { stream: true }));
      });
    },
  };
}

export function waitForBoot(serial, seconds = 60) {
  return new Promise((resolve, reject) => {
    let seen = "";
    const started = Date.now();
    const timer = setTimeout(
      () => reject(new Error(`no ${READY} from the guest within ${seconds}s`)),
      seconds * 1000,
    );
    serial.listen((text) => {
      seen += text;
      if (seen.includes(READY)) {
        clearTimeout(timer);
        resolve((Date.now() - started) / 1000);
      }
    });
  });
}

export async function start(options = {}) {
  const settings = { ...DEFAULTS, ...options };

  const emulator = new window.V86({
    wasm_path: settings.wasm,
    bios: { url: settings.bios },
    vga_bios: { url: settings.vgabios },
    bzimage: { url: settings.bzimage },
    initrd: { url: settings.initrd },
    cmdline: settings.cmdline,
    memory_size: 128 * 1024 * 1024,
    autostart: true,
  });

  const serial = serialFor(emulator);
  const booted = await waitForBoot(serial);

  const channel = makeChannel();
  const host = new Host(new Guest(serial), new Answerer(channel));

  const worker = new Worker("worker.js", { type: "module" });
  // The worker sends two kinds of message: requests, which have a `call`, and news about itself,
  // which does not. Only the first kind is the protocol.
  worker.addEventListener("message", (event) => {
    if (event.data && event.data.call) host.handle(event.data);
  });
  worker.postMessage({ channel });

  return { emulator, worker, host, booted };
}
