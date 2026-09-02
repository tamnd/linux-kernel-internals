// The kill criterion, measured, in a browser, by one command.
//
//     node kxbox/web/measure.js
//     node kxbox/web/measure.js --show               a real visible window instead of headless
//     node kxbox/web/measure.js --profile A-gzip     time one of the other builds
//     KXBOX_BROWSER=/path/to/chrome node kxbox/web/measure.js
//
// M0 asks whether the pinned kernel boots in a browser tab in under thirty seconds. Every number
// this project had before this was node, and node is not a tab: no page to fetch the image over,
// a different JIT, no compositor, and none of the memory pressure a real browser is under. So
// this starts the server, starts a browser, opens the harness page, waits for it to finish, and
// prints what it found.
//
// It drives the browser over the DevTools protocol directly rather than through a driver library.
// That is one fewer dependency to pin, it is about eighty lines, and the whole of what it needs is
// open a tab, evaluate an expression and read the answer back.
//
// The number it prints is for the machine it ran on. That is the point of the table in RESULTS.md
// having a machine column: thirty seconds on a developer's laptop and thirty seconds on a five
// year old Chromebook are different claims, and only one of them is the claim this project needs.

import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");

// Where Chrome lives, in the order worth looking. Chromium and Edge work too, because all three
// speak the same protocol, and Firefox does not, which is why the browser table has a column for
// it that this script cannot fill in.
const BROWSERS = [
  process.env.KXBOX_BROWSER,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].filter(Boolean);

const PORT = 8123;
const DEBUG_PORT = 9333;

function sleep(ms) {
  return new Promise((done) => setTimeout(done, ms));
}

async function waitFor(what, url, seconds = 30) {
  const until = Date.now() + seconds * 1000;
  while (Date.now() < until) {
    try {
      const answer = await fetch(url);
      if (answer.ok) return answer;
    } catch {
      // Not up yet. There is no way to ask other than to try.
    }
    await sleep(200);
  }
  throw new Error(`${what} did not come up within ${seconds}s`);
}

// One DevTools connection, with the one call this needs. `awaitPromise` is off because the page
// is polled rather than awaited: a boot that hangs should time out here with a message, not sit
// on an unresolved promise until somebody presses control C.
class Tab {
  constructor(socket) {
    this.socket = socket;
    this.next = 0;
    this.waiting = new Map();
    socket.addEventListener("message", (event) => {
      const reply = JSON.parse(event.data);
      const pending = this.waiting.get(reply.id);
      if (!pending) return;
      this.waiting.delete(reply.id);
      pending(reply);
    });
  }

  static async open(wsUrl) {
    const socket = new WebSocket(wsUrl);
    await new Promise((ok, bad) => {
      socket.addEventListener("open", ok, { once: true });
      socket.addEventListener("error", () => bad(new Error(`cannot connect to ${wsUrl}`)), { once: true });
    });
    return new Tab(socket);
  }

  send(method, params = {}) {
    const id = (this.next += 1);
    return new Promise((done) => {
      this.waiting.set(id, done);
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async value(expression) {
    const reply = await this.send("Runtime.evaluate", { expression, returnByValue: true });
    const thrown = reply.result && reply.result.exceptionDetails;
    if (thrown) throw new Error(thrown.exception ? thrown.exception.description : "evaluate threw");
    return reply.result.result.value;
  }
}

async function main(argv) {
  const show = argv.includes("--show");
  const at = argv.indexOf("--profile");
  const profile = at < 0 ? "A-full" : argv[at + 1];
  const patience = Number(process.env.KXBOX_PATIENCE || 300);

  const browser = BROWSERS.find((path) => {
    try {
      return spawn(path, ["--version"]).pid > 0;
    } catch {
      return false;
    }
  });
  if (!browser) {
    console.error("no Chrome found. Set KXBOX_BROWSER to the binary and run this again.");
    return 2;
  }

  const server = spawn("python3", [join(ROOT, "kxbox/web/serve.py"), "--port", String(PORT)], {
    cwd: ROOT,
    stdio: "ignore",
  });
  const scratch = mkdtempSync(join(tmpdir(), "kxbox-"));
  // A throwaway profile every time, so this measures a first visit rather than whatever a warm
  // cache happened to be holding, and so it cannot collide with a browser somebody has open.
  const chrome = spawn(browser, [
    // Headless is the default because this is meant to be runnable in a terminal over ssh. It is
    // not quite the same machine though: there is no compositor and no window to paint into, so
    // `--show` is here for the run that goes in the table as a tab somebody could have watched.
    ...(show ? [] : ["--headless=new"]),
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${scratch}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    `http://127.0.0.1:${PORT}/web/?profile=${encodeURIComponent(profile)}`,
  ], { stdio: "ignore" });

  const stop = () => {
    chrome.kill();
    server.kill();
    // Chrome is still flushing its profile as this runs, so a first delete hits a directory that
    // is not empty yet. Retrying is the whole fix and it is cheaper than waiting a fixed second.
    rmSync(scratch, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  };

  try {
    await waitFor("the server", `http://127.0.0.1:${PORT}/web/`);
    const version = await (await waitFor("the browser", `http://127.0.0.1:${DEBUG_PORT}/json/version`)).json();

    // The tab Chrome opened for the URL on the command line. Waiting for it rather than opening
    // another, because the one on the command line is the one that got a cold start.
    let target = null;
    const until = Date.now() + 30000;
    while (!target && Date.now() < until) {
      const targets = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`)).json();
      target = targets.find((t) => t.type === "page" && t.url.includes("/web/"));
      if (!target) await sleep(200);
    }
    if (!target) throw new Error("the browser never opened the harness page");

    const tab = await Tab.open(target.webSocketDebuggerUrl);
    console.log(`${version.Browser}, cold profile, booting ${profile}${show ? "" : ", headless"}`);
    console.log(`waiting up to ${patience}s for it to finish`);

    const deadline = Date.now() + patience * 1000;
    let results = null;
    while (Date.now() < deadline) {
      results = await tab.value("JSON.stringify(window.kxResults || null)");
      const parsed = results ? JSON.parse(results) : null;
      if (parsed && parsed.done) {
        results = parsed;
        break;
      }
      results = null;
      await sleep(500);
    }
    if (!results) throw new Error(`the page did not finish within ${patience}s`);

    report(results);
    const disagreed = (results.both_ways?.recipes || []).some((one) => !one.same);
    const bad =
      results.error || results.python_error || results.trace_error || results.both_ways_error;
    return bad || disagreed ? 1 : 0;
  } finally {
    stop();
  }
}

function report(r) {
  console.log("");
  if (r.error) {
    console.log(`  did not get going: ${r.error}`);
    return;
  }
  console.log(`  boot to ready       ${r.booted}s`);
  console.log(`  fetch and boot      ${r.fetch_and_boot}s`);
  console.log(`  checks passed       ${r.checks_passed} of ${r.checks.length}`);
  for (const check of r.checks.filter((c) => !c.ok)) console.log(`    FAIL ${check.name}: ${check.detail}`);
  console.log(`  python up           ${r.python_error ? r.python_error : `${r.python} in ${r.python_seconds}s`}`);
  if (r.tape) console.log(`  one traced recipe   ${r.tape.frames} calls in ${r.trace_seconds}s, ${r.tape.recipe || "?"}`);
  if (r.trace_error) console.log(`  one traced recipe   ${r.trace_error}`);
  if (r.both_ways_error) console.log(`  emulator on and off ${r.both_ways_error}`);
  if (r.both_ways) {
    const all = r.both_ways.recipes;
    const agreed = all.filter((one) => one.same).length;
    console.log(`  emulator on and off ${agreed} of ${all.length} recipes agree, in ${r.both_ways_seconds}s`);
    for (const one of all.filter((o) => !o.same)) {
      console.log(`    DIFFERENT ${one.recipe}: ${one.error || one.differences.join("; ")}`);
    }
  }
  console.log("");
  console.log(`  ${r.booted <= 30 ? "under" : "over"} the thirty second bar`);
  console.log("");
  console.log(JSON.stringify({ ...r, checks: undefined }, null, 2));
}

main(process.argv.slice(2))
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
