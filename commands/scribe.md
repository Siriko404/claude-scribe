---
description: Summon, dismiss or demo the Scribe — the Stronghold advisor panel showing this session's rate limits
argument-hint: [stop | demo | status]
---

Manage the Scribe desktop panel. Action requested: $ARGUMENTS (empty means summon).

The panel lives at `C:/Users/sinas/OneDrive/Desktop/Projects/ClaudeSidePanel`. Run
the matching PowerShell command, then report the result in one line. Do not
explain the panel unless asked.

He is summoned automatically at session start by the `scribe-launch.mjs` hook,
so these are for when you want to force the issue.

The new panel waits up to two seconds for the old one to release its lock, so
the kill and the start need no sleep between them.

Every command below identifies him with `Get-CimInstance`. `Get-Process` does
**not** expose `CommandLine` on Windows PowerShell 5.1 — it comes back empty, so
filtering on it matches nothing and killing without it kills every `pythonw` on
the machine.

**summon** (no arguments, or `start`) — replaces any running instance:

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*scribe_window*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Process -FilePath (Get-Command pythonw).Source -ArgumentList "C:/Users/sinas/OneDrive/Desktop/Projects/ClaudeSidePanel/scribe_window.py" -WorkingDirectory "C:/Users/sinas/OneDrive/Desktop/Projects/ClaudeSidePanel" -WindowStyle Hidden
```

**stop** — dismiss him until the next session start:

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*scribe_window*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
```

**demo** — same panel plus the control strip: one button per animation, a
7-day / mood-step slider pair, and live roll/hold timing sliders. Useful for
checking the animations without waiting for real events:

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*scribe_window*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Process -FilePath (Get-Command pythonw).Source -ArgumentList "C:/Users/sinas/OneDrive/Desktop/Projects/ClaudeSidePanel/scribe_window.py","--demo" -WorkingDirectory "C:/Users/sinas/OneDrive/Desktop/Projects/ClaudeSidePanel" -WindowStyle Hidden
```

**status** — report whether he is up, whether his data is fresh, and whether the
launch hook has logged any trouble:

```powershell
$b = (Get-Content "$env:USERPROFILE\.claude\scribe-beat" -Raw -ErrorAction SilentlyContinue)
if ($b) { "heartbeat {0:N1}s ago" -f (([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - [double]$b)/1000) } else { "no heartbeat (never started)" }
$s = Get-Content "$env:USERPROFILE\.claude\scribe-state.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
if ($s) { "state age {0:N0}s, 7-day {1}%" -f (([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - $s.updated_at)/1000), $s.rate_limits.seven_day.used_percentage } else { "no state file yet" }
Get-Content "$env:USERPROFILE\.claude\scribe-launch.log" -Tail 3 -ErrorAction SilentlyContinue
```

A heartbeat older than about six seconds means he is not running.

Notes for you, not for the user:

- `stop` only lasts until the next session start, when the hook summons him
  again. To keep him away, remove the `scribe-launch.mjs` entry from
  `SessionStart` in `~/.claude/settings.json`.
- The panel reads `~/.claude/scribe-state.json`, which the statusline shim writes
  on every redraw. If status reports a stale state, the shim is not wired — check
  that `statusLine.command` in `~/.claude/settings.json` points at
  `scribe-writer.mjs`.
- It remembers its own position, including on a second monitor. Never pass
  `SCRIBE_POS` unless the user asks for a specific spot.
- Sprites are decoded from the user's own game install and are not in the repo.
  If the panel reports missing sprites, regenerate them:
  `node tools/export-frames.mjs "C:/Non Windows Data/SCE/gm/scribe.gm1" 1`
  then `python tools/upscale-frames.py --model <EDSR_x4.pb> --scale 4`.
