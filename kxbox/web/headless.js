// Tier 0 without a browser.
//
//     node kxbox/web/headless.js boot     boot the box and print how long it took
//     node kxbox/web/headless.js smoke    boot it and check the things a lesson needs
//     node kxbox/web/headless.js sh 'ls /proc'
//
// v86 runs in node as well as in a tab, which is worth a lot more than it sounds. It means the
// kernel, the rootfs and the whole four call protocol can be exercised by a script, in CI, on a
// machine with no display, and that a boot that broke can be bisected without anybody clicking
// anything.
//
// It is not the same thing as the page. There is no worker here and no shared buffer, because
// nothing is blocking: this side is allowed to await. The page needs those and has them in
// channel.js. What is shared is everything below that, which is the part that talks to the kernel.
//
// A boot here is also not a boot measurement for the kill criterion. Node is not a browser tab and
// this laptop is not a reader's machine. What it settles is whether the kernel boots at all, which
// is the question that was open for the whole of M0.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Guest, Host } from "./host.js";
import { READY, serialFor, waitForBoot } from "./page.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");

export const IMAGES = {
  wasm: resolve(HERE, "vendor/v86/v86.wasm"),
  bios: resolve(HERE, "vendor/v86/seabios.bin"),
  vgabios: resolve(HERE, "vendor/v86/vgabios.bin"),
  bzimage: resolve(ROOT, "kxbox/kernel/build/A-full/bzImage"),
  initrd: resolve(ROOT, "kxbox/rootfs/build/initrd.gz"),
};

// Quiet, because the console is the same wire the protocol talks over, and every line the kernel
// prints while a command is running is a line the reply parser has to step over. printk still
// records everything, so `dmesg` in a lesson shows the whole boot.
export const CMDLINE = "console=ttyS0 quiet nokaslr";

function missing(images) {
  return Object.entries(images)
    .filter(([, path]) => {
      try {
        readFileSync(path, { flag: "r" });
        return false;
      } catch {
        return true;
      }
    })
    .map(([name, path]) => `${name}: ${path}`);
}

export async function boot(options = {}) {
  const images = { ...IMAGES, ...options.images };
  const gone = missing(images);
  if (gone.length) {
    throw new Error(
      `nothing to boot, these are not built yet:\n  ${gone.join("\n  ")}\n` +
        "  kxbox/kernel/build.sh builds the kernel, kxbox/rootfs/build.sh builds the rootfs",
    );
  }

  const { V86 } = await import("./vendor/v86/libv86.mjs");
  const emulator = new V86({
    wasm_path: images.wasm,
    bios: { url: images.bios },
    vga_bios: { url: images.vgabios },
    bzimage: { url: images.bzimage },
    initrd: { url: images.initrd },
    cmdline: options.cmdline || CMDLINE,
    memory_size: (options.memory || 128) * 1024 * 1024,
    autostart: true,
    disable_speaker: true,
  });

  // Everything the guest says, kept from the first byte. A boot that never reaches the ready line
  // is the failure that matters most here, and the only useful thing to print when it happens is
  // what the kernel did say.
  let log = "";
  const decoder = new TextDecoder();
  emulator.add_listener("serial0-output-byte", (byte) => {
    log += decoder.decode(new Uint8Array([byte]), { stream: true });
  });

  const serial = serialFor(emulator);
  try {
    const seconds = await waitForBoot(serial, options.seconds || 90);
    return { emulator, host: new Host(new Guest(serial), null), seconds, log: () => log };
  } catch (error) {
    emulator.stop();
    throw new Error(`${error.message}\n\nwhat the guest said:\n${log}`);
  }
}

// The checks. Each one is a thing some lesson stops working without, and each says what it is for,
// because a red line in a list of names tells you nothing about what just became impossible.
const CHECKS = [
  { name: "shell", what: "the protocol reaches a shell at all", run: (box) => box.sh("echo hello") },
  { name: "proc", what: "everything /proc based", run: (box) => box.read("/proc/version") },
  { name: "kallsyms", what: "names in a trace instead of addresses", run: (box) => box.sh("wc -l < /proc/kallsyms") },
  { name: "tracefs", what: "Z02 and every trace in the book", run: (box) => box.sh("ls /sys/kernel/tracing/current_tracer") },
  { name: "tracers", what: "function_graph, which is what a tape is made of", run: (box) => box.read("/sys/kernel/tracing/available_tracers") },
  { name: "dmesg", what: "C09 and every oops lesson", run: (box) => box.sh("dmesg | tail -1") },
  { name: "write", what: "turning a tracer on, which is a single redirect", run: (box) => box.write("/tmp/probe", "one\ntwo\n") },
  { name: "readback", what: "the write above actually landing", run: (box) => box.read("/tmp/probe") },
  { name: "modules", what: "every part that ends in a change", run: (box) => box.sh("test -d /sys/module") },
  { name: "touchpage", what: "a page fault trace with one fault in it instead of thirty", run: (box) => box.sh("/bin/touchpage") },
];

async function smoke() {
  const box = await boot();
  console.log(`booted in ${box.seconds.toFixed(1)}s`);

  let bad = 0;
  for (const check of CHECKS) {
    try {
      const answer = await check.run(box.host);
      const shown = typeof answer === "string" ? answer : (answer && answer.stdout) || "";
      const status = typeof answer === "object" && answer ? answer.status : 0;
      const first = shown.trim().split("\n")[0] || "";
      if (status !== 0) throw new Error(`exit ${status}`);
      console.log(`  pass  ${check.name.padEnd(9)} ${first.slice(0, 60)}`);
    } catch (error) {
      bad += 1;
      console.log(`  FAIL  ${check.name.padEnd(9)} ${error.message.split("\n")[0]}`);
      console.log(`        without it: ${check.what}`);
    }
  }

  box.emulator.stop();
  console.log(bad === 0 ? `\nall ${CHECKS.length} checks passed` : `\n${bad} check(s) failed`);
  return bad === 0 ? 0 : 1;
}

async function main(argv) {
  const [what, ...rest] = argv;
  if (what === "smoke") return smoke();

  if (what === "boot") {
    const box = await boot();
    console.log(`booted in ${box.seconds.toFixed(1)}s, waiting for ${READY} took that long`);
    box.emulator.stop();
    return 0;
  }

  if (what === "sh") {
    const box = await boot();
    const reply = await box.host.sh(rest.join(" "));
    process.stdout.write(reply.stdout);
    process.stderr.write(reply.stderr);
    box.emulator.stop();
    return reply.status;
  }

  console.error("usage: headless.js boot | smoke | sh COMMAND");
  return 2;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2))
    .then((code) => process.exit(code))
    .catch((error) => {
      console.error(error.message);
      process.exit(1);
    });
}
