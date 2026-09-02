// The page. Boots the emulator, starts the Python worker, and carries messages between them.
//
// Everything here that could be tested without an emulator has been moved into channel.js,
// guest.js and host.js, which is why this file is mostly wiring. What is left is the wiring, and
// `serialFor` and `waitForBoot` are shared with headless.js so that a boot under node and a boot
// in a tab go through the same code and can disagree about the machine rather than about us.

import { makeChannel } from "./channel.js";
import { Answerer } from "./channel.js";
import { Guest, Host } from "./host.js";

// Printed by the guest's init once the shell is up and the tracer is mounted. Waiting for a
// specific line rather than for a prompt, because a prompt is whatever the rootfs says it is and
// this is a fact we control.
export const READY = "__kx:READY";

// Absolute from the root `serve.py` hands out, which is `kxbox`, not `kxbox/web`. The images are
// where the two build scripts put them, so there is nothing to copy before opening the page.
export const DEFAULTS = {
  wasm: "/web/vendor/v86/v86.wasm",
  bios: "/web/vendor/v86/seabios.bin",
  vgabios: "/web/vendor/v86/vgabios.bin",
  bzimage: "/kernel/build/A-full/bzImage",
  initrd: "/rootfs/build/initrd.gz",
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

  const { V86 } = await import("./vendor/v86/libv86.mjs");
  const emulator = new V86({
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
