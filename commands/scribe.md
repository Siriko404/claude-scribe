---
description: Summon, dismiss or demo the Scribe — the Stronghold advisor panel showing this session's rate limits
argument-hint: [stop | demo | status]
---

Manage the Scribe desktop panel. Action requested: $ARGUMENTS (empty means summon).

The panel lives at `C:/Users/sinas/OneDrive/Desktop/Projects/ClaudeSidePanel`. Run
the matching PowerShell command, then report the result in one line. Do not
explain the panel unless asked.

**summon** (no arguments, or `start`) — replaces any running instance:

```powershell
Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*scribe_window*' } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Process -FilePath (Get-Command pythonw).Source -ArgumentList "C:/Users/sinas/OneDrive/Desktop/Projects/ClaudeSidePanel/scribe_window.py" -WorkingDirectory "C:/Users/sinas/OneDrive/Desktop/Projects/ClaudeSidePanel" -WindowStyle Hidden
```

**stop** — dismiss it:

```powershell
Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
```

**demo** — same panel plus the control strip: one button per animation, a
7-day / mood-step slider pair, and live roll/hold timing sliders. Useful for
checking the animations without waiting for real events:

```powershell
Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Process -FilePath (Get-Command pythonw).Source -ArgumentList "C:/Users/sinas/OneDrive/Desktop/Projects/ClaudeSidePanel/scribe_window.py","--demo" -WorkingDirectory "C:/Users/sinas/OneDrive/Desktop/Projects/ClaudeSidePanel" -WindowStyle Hidden
```

**status** — report whether it is running and whether its data is fresh:

```powershell
$p = Get-Process pythonw -ErrorAction SilentlyContinue
if ($p) { "running (pid $($p.Id))" } else { "not running" }
$s = Get-Content "$env:USERPROFILE\.claude\scribe-state.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
if ($s) { "state age {0:N0}s, 7-day {1}%" -f (([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - $s.updated_at)/1000), $s.rate_limits.seven_day.used_percentage } else { "no state file yet" }
```

Notes for you, not for the user:

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
