---
description: Open or close the Scribe — the Stronghold advisor panel showing this session's rate limits
argument-hint: [open | close]
---

Open or close the Scribe desktop panel. Action requested: $ARGUMENTS (empty means
open).

Only `open` and `close` exist. Anything else: say so in one line and run nothing.
Run the matching PowerShell command, then report the result in one line. Do not
explain the panel unless asked.

He is opened automatically at session start by the `scribe-launch.mjs` hook, so
these are for forcing the issue. The same hook records where the checkout lives
in `~/.claude/scribe-home`, which is what `$Root` below reads — nothing here
hardcodes a path. If that file is missing the hook is not installed, and the fix
is the `SessionStart` entry described in the README, not a path typed in by hand.

Both commands identify him with `Get-CimInstance`. `Get-Process` does **not**
expose `CommandLine` on Windows PowerShell 5.1 — it comes back empty, so
filtering on it matches nothing, and killing without it takes every `pythonw` on
the machine. A new panel waits two seconds for the old one's lock, so the kill
and the start need no sleep between them.

**open** (also the default) — replaces any running instance:

```powershell
$Root = (Get-Content "$env:USERPROFILE\.claude\scribe-home" -Raw -ErrorAction SilentlyContinue)
if (-not $Root) { "the launch hook is not installed - add the SessionStart entry from the README, then restart Claude Code"; return }
$Root = $Root.Trim()
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*scribe_window*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Process -FilePath (Get-Command pythonw).Source -ArgumentList "$Root\scribe_window.py" -WorkingDirectory $Root -WindowStyle Hidden
Start-Sleep -Seconds 4
"pid: " + (@(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*scribe_window*' }).ProcessId -join ",")
```

**close** — dismiss him until the next session start:

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*scribe_window*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500
"remaining: " + (@(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*scribe_window*' }).Count)
```

Notes for you, not for the user:

- `close` only lasts until the next session start, when the hook opens him
  again. To keep him away, remove the `scribe-launch.mjs` entry from
  `SessionStart` in `~/.claude/settings.json`.
- The panel reads `~/.claude/scribe-state.json`, which the statusline shim writes
  on every redraw. If the ledger says "stale", the shim is not wired — check that
  `statusLine.command` in `~/.claude/settings.json` runs `scribe-writer.mjs`.
- The demo strip and the launch log are still there for development, but they are
  not commands: run `python scribe_window.py --demo` directly, and read
  `~/.claude/scribe-launch.log` if he never appears.
- It remembers its own position, including on a second monitor. Never pass
  `SCRIBE_POS` unless the user asks for a specific spot.
- Sprites are decoded from the user's own game install and are not in the repo.
  If the panel reports missing sprites, regenerate them with
  `tools/export-frames.mjs` pointed at their `scribe.gm1`, then
  `tools/upscale-frames.py`. The README has the exact commands.
