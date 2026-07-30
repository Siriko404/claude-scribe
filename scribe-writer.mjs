#!/usr/bin/env node
// Statusline shim. It dumps the payload Claude Code hands the statusline (rate
// limits, context window, cost, model) to a state file the Scribe window polls.
// That payload is the only place rate limits are exposed at all, which is the
// whole reason this exists.
//
// It then delegates to claude-hud so the terminal footer stays byte-identical,
// or draws a plain line itself if there is nothing to delegate to.
//
// env: SCRIBE_HUD_DIR — claude-hud install dir, resolved by the statusLine prologue

import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const CLAUDE_DIR = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude');
const STATE = path.join(CLAUDE_DIR, 'scribe-state.json');

const chunks = [];
for await (const c of process.stdin) chunks.push(c);
const raw = Buffer.concat(chunks).toString('utf8');

let data = null;
try { data = JSON.parse(raw); } catch { /* not JSON: nothing to record */ }

if (data) {
  try {
    fs.writeFileSync(STATE, JSON.stringify({
      updated_at: Date.now(),
      transcript_path: data.transcript_path ?? null,
      cwd: data.workspace?.current_dir ?? data.cwd ?? null,
      model: data.model ?? null,
      effort: typeof data.effort === 'string' ? data.effort : data.effort?.level ?? null,
      rate_limits: data.rate_limits ?? null,
      context_window: data.context_window ?? null,
      cost: data.cost ?? null,
    }));
  } catch { /* best effort — never break the statusline over a failed write */ }
}

const hudDir = process.env.SCRIBE_HUD_DIR;
if (hudDir) {
  const { main } = await import(pathToFileURL(path.join(hudDir, 'dist', 'index.js')).href);
  await main(data ? { readStdin: async () => data } : {});
} else if (data) {
  // No statusline to defer to. Printing nothing would leave the footer blank,
  // so this draws the same numbers the scribe is reading.
  const pct = (v) => (typeof v === 'number' ? `${Math.round(v)}%` : null);
  const line = [
    data.model?.display_name,
    path.basename(data.workspace?.current_dir ?? data.cwd ?? '') || null,
    pct(data.rate_limits?.five_hour?.used_percentage) &&
      `5h ${pct(data.rate_limits.five_hour.used_percentage)}`,
    pct(data.rate_limits?.seven_day?.used_percentage) &&
      `7d ${pct(data.rate_limits.seven_day.used_percentage)}`,
  ].filter(Boolean).join('  ');
  if (line) process.stdout.write(line);
}
