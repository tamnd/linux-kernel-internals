// Talking to the kernel through the one thing it gives you: a shell on a serial line.
//
// There is no system call interface from JavaScript into v86. There is a byte stream in and a
// byte stream out, and a busybox shell at the other end of it. So every call in the protocol
// turns into a line of shell, and the whole problem becomes knowing when the line finished and
// what it printed. That is what this file is: building the line, and reading the answer back out
// of a stream that also contains the prompt, the echo of what we typed and whatever the kernel
// decided to print to the console while we were waiting.
//
// Nothing here touches the emulator, so all of it is testable, which is the reason it is a file of
// its own.

// Every marker carries the id of the call it belongs to, so an answer that arrives late cannot be
// mistaken for the answer to the next question.
export const MARK = "__kx";

// Where the shell parks stderr while a command runs. One file, reused, because the guest has no
// mktemp worth relying on and a fixed name is easier to explain in a lesson than a random one.
export const STDERR = "/tmp/.kx.err";
export const STAGING = "/tmp/.kx.b64";

let counter = 0;

export function nextId() {
  counter += 1;
  return `${Date.now().toString(36)}${counter.toString(36)}`;
}

// Single quotes, with the one escape a single quoted string cannot contain.
export function quote(text) {
  return `'${String(text).split("'").join(`'\\''`)}'`;
}

// The line we actually send.
//
// The three markers split the output into the two halves we want and the status. Everything
// before BEG is the prompt and the echo of this command, and gets dropped. Between BEG and ERR is
// what the command printed. Between ERR and END is what it printed to stderr, which was parked in
// a file because both streams share one serial line and interleaving them would be a lie.
//
// The command goes inside a group ending on its own line rather than after a semicolon, so that a
// line already ending in a semicolon, or in a comment, is still valid shell.
export function commandFor(id, line) {
  const beg = `printf '\\n${MARK}:BEG:${id}\\n'`;
  const err = `printf '\\n${MARK}:ERR:${id}\\n'`;
  const end = `printf '\\n${MARK}:END:${id}:%d\\n' "$__kx_status"`;
  return `${beg}; { ${line}\n} 2>${STDERR}; __kx_status=$?; ${err}; cat ${STDERR} 2>/dev/null; ${end}\n`;
}

// What came back, or null when the command has not finished yet.
//
// Called on the whole accumulated stream every time more of it arrives, which is the simplest
// thing that works and is fine at the sizes involved. The status marker is what says the command
// is over, so a partly arrived answer returns null and the caller waits for more bytes.
export function parseReply(id, stream) {
  const lines = String(stream).split("\n").map((one) => one.replace(/\r+$/, ""));

  const beg = lines.indexOf(`${MARK}:BEG:${id}`);
  const err = lines.indexOf(`${MARK}:ERR:${id}`);
  const end = lines.findIndex((one) => one.startsWith(`${MARK}:END:${id}:`));
  if (beg < 0 || err < beg || end < err) return null;

  const status = Number.parseInt(lines[end].slice(`${MARK}:END:${id}:`.length), 10);
  return {
    status: Number.isNaN(status) ? 0 : status,
    stdout: join(lines.slice(beg + 1, err)),
    stderr: join(lines.slice(err + 1, end)),
  };
}

function join(lines) {
  return lines.length === 0 ? "" : `${lines.join("\n")}\n`;
}

export function readCommand(path) {
  return `cat ${quote(path)}`;
}

export function insmodCommand(path) {
  return `insmod ${quote(path)}`;
}

// Writing a file, in as many lines of shell as it takes.
//
// Base64 rather than quoting, because the text being written is sometimes a list of function names
// with newlines in it and quoting rules are the wrong thing to be debugging from inside a browser.
//
// The staging file is why this is a list and not one command. The target has to be written by a
// single redirect, because writing to `current_tracer` twice is two writes and the kernel reads
// each one separately. So the base64 is appended in pieces, and then decoded into the target once.
export function writeCommands(path, text, chunk = 512) {
  const encoded = base64(text);
  const lines = [`: > ${STAGING}`];
  for (let at = 0; at < encoded.length; at += chunk) {
    lines.push(`printf '%s' ${quote(encoded.slice(at, at + chunk))} >> ${STAGING}`);
  }
  lines.push(`base64 -d < ${STAGING} > ${quote(path)}`);
  return lines;
}

// Node and the browser spell this differently and neither spelling is available in both.
export function base64(text) {
  const bytes = new TextEncoder().encode(text);
  if (typeof Buffer !== "undefined") return Buffer.from(bytes).toString("base64");
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}
