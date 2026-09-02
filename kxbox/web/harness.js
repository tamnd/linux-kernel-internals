// What the page does, kept out of index.html so that index.html is markup.
//
// The page has one job that node cannot do for it. The kill criterion in M0 is about a browser
// tab on somebody's own machine, and every number this project has so far came off node on one
// laptop. So this boots, times the boot, runs the same checks the smoke run does, brings Python
// up in the worker, and takes one real trace through the whole bridge.
//
// It leaves everything it learned on `window.kxResults`, and prints the same thing into the page
// as JSON. That is so a measurement can be copied out of a browser on a machine that has none of
// this checked out, which is most of the machines the answer is wanted for.

import { runChecks } from "./checks.js";
import { imagesFor, start } from "./page.js";

const PROGRAM = "first-tape.py";

// `?profile=A-gzip` boots that build instead. The browser table has a row per profile and they are
// the three answers to the kill criterion failing, so there has to be a way to time them.
const PROFILE = new URLSearchParams(location.search).get("profile") || "A-full";

function el(id) {
  return document.getElementById(id);
}

function say(id, text) {
  el(id).textContent = text;
}

function row(cells, ok) {
  const tr = document.createElement("tr");
  if (ok === false) tr.className = "bad";
  for (const cell of cells) {
    const td = document.createElement("td");
    td.textContent = cell;
    tr.appendChild(td);
  }
  return tr;
}

// Rounded to a tenth of a second everywhere, because the difference between 4.16 and 4.2 seconds
// is not a difference anybody is going to act on and printing it suggests otherwise.
function seconds(from) {
  return Math.round((performance.now() - from) / 100) / 10;
}

async function main() {
  const results = {
    profile: PROFILE,
    agent: navigator.userAgent,
    cores: navigator.hardwareConcurrency || null,
    isolated: crossOriginIsolated,
    started: new Date().toISOString(),
  };
  window.kxResults = results;

  if (!crossOriginIsolated) {
    // Worth catching early and by name. Without the two headers the boot works, the checks work,
    // and then Python hangs forever on a call that can never be answered, which looks like the
    // emulator being slow.
    say("state", "This page is not cross origin isolated, so the worker cannot block on the emulator. Serve it with kxbox/web/serve.py rather than with python3 -m http.server.");
    results.error = "not cross origin isolated";
    results.done = true;
    return;
  }

  say("state", `Booting the ${PROFILE} kernel.`);
  const clock = performance.now();
  let box;
  try {
    box = await start(imagesFor(PROFILE));
  } catch (error) {
    // Almost always one of three things: v86 not fetched, the kernel not built, or the rootfs not
    // built. serve.py prints which one when it starts, so say to look there.
    say("state", `Did not boot: ${error.message}. Check what serve.py printed when it started.`);
    results.error = error.message;
    results.done = true;
    return;
  }

  // Pyodide starts fetching the moment the worker has the shared buffer, which is here, and the
  // checks below run while it does. So this clock is started now rather than where Python is
  // waited on, because otherwise a download that finished during the checks reads as zero seconds.
  const pythonClock = performance.now();
  results.booted = Math.round(box.booted * 10) / 10;
  results.fetch_and_boot = seconds(clock);
  say("state", `Booted in ${results.booted.toFixed(1)} seconds.`);
  say("boot", `${results.booted.toFixed(1)}s from the emulator starting to the guest printing its ready marker. ${results.fetch_and_boot.toFixed(1)}s counting the fetch of the kernel image and the emulator as well.`);

  const decoder = new TextDecoder();
  const console_ = el("console");
  box.emulator.add_listener("serial0-output-byte", (byte) => {
    console_.textContent += decoder.decode(new Uint8Array([byte]), { stream: true });
    console_.scrollTop = console_.scrollHeight;
  });

  say("state", "Running the checks.");
  const checks = await runChecks(box.host);
  const table = el("checks");
  for (const check of checks) {
    table.appendChild(row([check.ok ? "pass" : "FAIL", check.name, check.ok ? check.detail : `${check.detail}, so no ${check.what}`], check.ok));
  }
  results.checks = checks.map(({ name, ok, detail }) => ({ name, ok, detail }));
  results.checks_passed = checks.filter((c) => c.ok).length;

  say("state", "Waiting for Python. It has been fetching Pyodide since the boot finished.");
  try {
    results.python = await box.python.up;
    results.python_seconds = seconds(pythonClock);
    say("pystate", `Python ${results.python} came up in ${results.python_seconds.toFixed(1)} seconds, and it can see the emulator.`);
  } catch (error) {
    say("pystate", `Python did not come up: ${error.message}`);
    results.python_error = error.message;
    results.done = true;
    say("state", "Booted, checked, and stopped at Python.");
    return;
  }

  say("state", "Taking a trace through the whole bridge.");
  const traceClock = performance.now();
  try {
    const source = await (await fetch(PROGRAM)).text();
    const setting = `import os; os.environ[${JSON.stringify("KXBOX_PROFILE")}] = ${JSON.stringify(PROFILE)}\n`;
    const answer = JSON.parse(await box.python.run(setting + source));
    results.trace_seconds = seconds(traceClock);
    results.tape = { frames: answer.frames, roots: answer.roots, root_count: answer.root_count, unparsed: answer.unparsed };
    results.kernel = answer.kernel;
    // The widget's own markup, from `kxwidgets`, not something this file draws. If it looks right
    // here it looks right in a notebook, because it is the same string.
    el("tape").innerHTML = answer.html;
    say("tapestate", `${answer.frames} calls in ${answer.root_count} outermost frames, ${answer.unparsed} lines the parser could not read, back in ${results.trace_seconds.toFixed(1)} seconds.`);
  } catch (error) {
    say("tapestate", `No trace: ${error.message}`);
    results.trace_error = error.message;
  }

  results.done = true;
  say("state", "Done. The block at the bottom is what to paste into RESULTS.md.");
  say("results", JSON.stringify(results, null, 2));
}

main();
