#!/usr/bin/env node
/**
 * Summons the Scribe on SessionStart, so he is never opened by hand.
 *
 * SessionStart fires on startup, resume, clear and compact alike, so this runs
 * several times per session and must be cheap and idempotent. The panel writes
 * a heartbeat every two seconds; a fresh one means it is already up and this
 * exits without spawning. That is only the fast path — two sessions starting
 * together will both see the same stale beat, and the panel's own file lock is
 * what actually keeps there being one of him.
 *
 * Nothing is printed: SessionStart stdout is injected into the session context.
 * Failures go to ~/.claude/scribe-launch.log, because a detached spawn with its
 * output discarded is otherwise invisible when it does not work.
 */

import { spawn } from "node:child_process";
import {
  appendFileSync, existsSync, readFileSync, statSync, truncateSync, writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.join(HERE, "..", "scribe_window.py");
const CLAUDE_DIR = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
const BEAT_FILE = path.join(CLAUDE_DIR, "scribe-beat");
const HOME_FILE = path.join(CLAUDE_DIR, "scribe-home");
const LOG_FILE = path.join(CLAUDE_DIR, "scribe-launch.log");

const BEAT_FRESH_MS = 6000;   // three missed beats
const LOG_MAX = 64 * 1024;

// The hook's environment is not the interactive shell's, so PATH may not carry
// pythonw. Absolute paths are tried first and bare `pythonw` is the fallback,
// which keeps a Python upgrade from silently breaking this.
const CANDIDATES = [
  "C:/Program Files/Python313/pythonw.exe",
  "C:/Program Files/Python312/pythonw.exe",
];

function note(line) {
  try {
    if (statSync(LOG_FILE).size > LOG_MAX) truncateSync(LOG_FILE, 0);
  } catch { /* no log yet */ }
  try {
    appendFileSync(LOG_FILE, `${new Date().toISOString()} ${line}\n`);
  } catch { /* nothing to be done about it here */ }
}

function panelIsUp() {
  try {
    const beat = Number(readFileSync(BEAT_FILE, "utf8").trim());
    return Number.isFinite(beat) && Date.now() - beat < BEAT_FRESH_MS;
  } catch {
    return false;
  }
}

// Where the checkout lives, so nothing downstream has to hardcode it. The hook
// is the one piece that knows by construction, and it runs before anyone can
// type /scribe. Written even when the panel is already up, so moving the
// checkout is picked up on the next session start.
try {
  writeFileSync(HOME_FILE, path.resolve(HERE, ".."));
} catch (err) {
  note(`could not record home: ${err.message}`);
}

// Every run leaves a dated line, not just the failures. Whether this hook fires
// under a real session start is otherwise unobservable from inside the session:
// the only trace was a file's mtime, and reasoning from that is guesswork.
if (panelIsUp()) {
  note("ran; panel already up");
  process.exit(0);
}
note("ran; no heartbeat, summoning him");

const exe = CANDIDATES.find(existsSync) || "pythonw";
try {
  const child = spawn(exe, [PANEL], {
    cwd: path.dirname(PANEL),
    detached: true,
    stdio: "ignore",
    windowsHide: true,
  });
  child.on("error", (err) => note(`spawn failed (${exe}): ${err.message}`));
  child.unref();
  // An unref'd child does not hold the loop open, and a spawn error arrives on
  // a later tick. A quarter second buys enough time to record one.
  setTimeout(() => process.exit(0), 250);
} catch (err) {
  note(`spawn threw (${exe}): ${err.message}`);
}
