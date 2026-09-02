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
const BOTH_WAYS = "both-ways.py";

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

// How much of what the guest has said is kept on screen. Everything before this is dropped, and
// dropping it is the point rather than a tidiness measure. See below.
const KEPT = 40000;

// Show the guest's serial output without making the page slower the longer it runs.
//
// This used to append to `textContent` once per byte and read `scrollHeight` once per byte, which
// is two mistakes that compound. Every append re-serialises the whole text node, so the cost of a
// byte grows with everything said before it, and every read of `scrollHeight` forces the browser
// to lay the element out synchronously before it can answer. A trace is a few thousand bytes and
// the comparison below reads three of them plus every command it takes to set the tracer up, so
// by the end of a run the element held hundreds of kilobytes and each byte cost a full layout of
// it. The emulator shares the main thread with all of that.
//
// Nothing about it looked like a rendering problem. It looked like the guest getting slower and
// slower until a `cat` of the trace file went past the twenty second deadline in host.js and the
// page failed on a command that had been fine two minutes earlier. Buffering into a string and
// flushing once a frame, with a cap on what is kept, holds the cost of a byte flat.
function showConsole(box) {
  const decoder = new TextDecoder();
  const element = el("console");
  let pending = "";
  let queued = false;

  const flush = () => {
    queued = false;
    if (!pending) return;
    const text = element.textContent + pending;
    pending = "";
    element.textContent = text.length > KEPT ? text.slice(text.length - KEPT) : text;
    element.scrollTop = element.scrollHeight;
  };

  box.emulator.add_listener("serial0-output-byte", (byte) => {
    pending += decoder.decode(new Uint8Array([byte]), { stream: true });
    if (queued) return;
    queued = true;
    requestAnimationFrame(flush);
  });
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

  showConsole(box);

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

  // One recipe, then a reload for the next one. `bothWays` navigates away and never returns when
  // there is another to do, so nothing below here runs until the last of them.
  await bothWays(box, results);

  say("state", "Taking one trace through the whole bridge, for the picture.");
  const traceClock = performance.now();
  try {
    const source = await (await fetch(PROGRAM)).text();
    const setting = `import os; os.environ[${JSON.stringify("KXBOX_PROFILE")}] = ${JSON.stringify(PROFILE)}\n`;
    const answer = JSON.parse(await box.python.run(setting + source));
    results.trace_seconds = seconds(traceClock);
    results.tape = { recipe: answer.recipe, frames: answer.frames, roots: answer.roots, root_count: answer.root_count, unparsed: answer.unparsed };
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

// The other M0 criterion, which is the one that cannot be checked anywhere but here. Off a browser
// there is no emulator to find, so both halves of the comparison come back as the recording and
// every recipe matches itself. That reads as a pass and is not one.
//
// One recipe per page load, with a reload in between, which is why this is a loop spread across
// several visits to this file rather than a `for`. Every recording in the corpus was taken as the
// first thing a freshly booted guest did, so comparing against it fairly means being that guest.
// Three recipes in one boot is not, and the ways it shows up are mostly not obvious ones. The
// obvious one is that a second write to the same file finds the page already there and skips the
// subtree the first one showed. The one that took much longer to find is that `two-writes` grew an
// `inode_update_time` subtree on exactly the runs where `write-1byte` had gone first, because
// whether a write updates the timestamp depends on whether anything has looked at it since.
//
// It runs before the trace below it for the same reason, and the trace below has to be of a recipe
// that does not care, which is written down as `repeatable` in the recipe list rather than left as
// something to remember here. A test holds `first-tape.py` to naming one, because getting it wrong
// fails minutes into a run in a browser and the reason is three files away from the symptom.
async function bothWays(box, results) {
  const done = carried();
  const next = done.length;
  say("state", `Running recipe ${next + 1} against its recording.`);
  const clock = performance.now();
  let answer;
  try {
    const source = await (await fetch(BOTH_WAYS)).text();
    const setting = `import os; os.environ[${JSON.stringify("KXBOX_RECIPE_INDEX")}] = ${JSON.stringify(String(next))}\n`;
    answer = JSON.parse(await box.python.run(setting + source));
  } catch (error) {
    say("bothstate", `Did not compare: ${error.message}`);
    results.both_ways_error = error.message;
    return;
  }

  const all = [...done, ...answer.recipes];
  const seconds_ = (carriedSeconds() + (performance.now() - clock) / 1000);

  if (answer.live && all.length < answer.names.length) {
    // More to do, and the next one needs a guest that has just booted rather than this one. A
    // reload is the cheapest honest way to get that: it throws away the emulator, the shell and
    // Pyodide and starts again, which is what the recording it will be compared against was taken
    // against. Carrying the results across in sessionStorage rather than in a variable is the
    // whole cost, and sessionStorage is right because this belongs to the tab and not the browser.
    keep(all, seconds_);
    say("state", `Reloading for recipe ${all.length + 1} of ${answer.names.length}, on a guest that has just booted.`);
    location.reload();
    // The reload is not instant and everything after this call would run against a page that is
    // going away, which is a confusing way to fail. Never returning is the intent.
    await new Promise(() => {});
  }

  clear();
  results.both_ways_seconds = Math.round(seconds_ * 10) / 10;
  results.both_ways = { same: answer.live ? all.every((one) => one.same && !one.error) : null, live: answer.live, recipes: all };

  const table = el("bothways");
  for (const one of all) {
    const detail = one.error || one.differences.join("; ") || `${one.calls} calls, both ways`;
    table.appendChild(row([one.same ? "same" : "DIFFERENT", one.recipe, detail], one.same));
  }

  if (!answer.live) {
    // Should be unreachable on this page, and worth saying rather than swallowing if it happens,
    // because it means Python could not see the emulator that the trace above just used.
    say("bothstate", `Nothing was compared: ${answer.why}`);
    return;
  }
  const agreed = all.filter((one) => one.same).length;
  say("bothstate", `${agreed} of ${all.length} recipes give the same answer both ways, each on a guest that had just booted, in ${results.both_ways_seconds.toFixed(1)} seconds of comparing.`);
}

// What survives a reload. sessionStorage and not localStorage, because this belongs to the tab:
// two tabs measuring at once must not pour their results into each other, and nothing here should
// outlive the window it was measured in.
const CARRIED = "kxBothWays";

function carried() {
  try {
    return JSON.parse(sessionStorage.getItem(CARRIED))?.recipes || [];
  } catch {
    return [];
  }
}

function carriedSeconds() {
  try {
    return JSON.parse(sessionStorage.getItem(CARRIED))?.seconds || 0;
  } catch {
    return 0;
  }
}

function keep(recipes, seconds_) {
  sessionStorage.setItem(CARRIED, JSON.stringify({ recipes, seconds: seconds_ }));
}

function clear() {
  sessionStorage.removeItem(CARRIED);
}

main();
