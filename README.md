# The Scribe

A small always-on-top desktop panel for Claude Code: the game's own hooded
scribe on the left, his ledger on the right. Frameless, draggable, remembers
where you put it (including on a second monitor). Right-click or Esc closes it.

```
+--------------------------------------------------+
|                      | THE SCRIBE'S LEDGER       |
|   [ 220x220 sprite ] | * 7 day  [####----] 52% 2d|
|                      |   5 hour [###-----] 40%   |
|                      |   context[###-----] 42%   |
|                      | $4.87  Opus 5  high       |
|                      | WATCHFUL                  |
+--------------------------------------------------+
```

## The face

**Resting mood** is the 7-day limit and nothing else — 11 frames, linear:

```
step = round(seven_day_used_% / 10)      0 = broad grin ... 10 = stern frown
```

**Three animations**, each played once and never looped:

| Roll | Frames | Fires on |
|---|---|---|
| speaking | 11→21→11 | Claude hands the turn back to you, or you interrupt |
| pleased | 22→32→22 | you send a message, or a `git commit` succeeds |
| displeased | 33→43→33 | you poke his face, a tomato lands, or a tool errors |

Every trigger is an event that either happened or it didn't. Message *sentiment*
was tried and cut: rules for it have unbounded surface area, and three live tests
in a row each needed a new rule afterwards. That is not a classifier converging,
it is a list of misses.

## The tomato

The tray under him holds one tomato. Click it:

| Beat | |
|---|---|
| 0.00s | wind-up — rears back, swells 35%, jitters |
| 0.14s | launches, three full tumbles, stretching over the arc |
| 0.54s | flattens against his face for 0.1s, then bursts |
| | 15 blobs stick, 9 chunks fly off under gravity, the panel jolts 8px, his head rocks back |
| 0.72s | *then* the scowl — the beat of disbelief is what makes it land |
| 0.7–3.8s | pulp creeps down his face, stretching into drips, then dries off |

Drawn from canvas primitives, not sprites. A spinning arc and a splat pattern are
geometry; they never drift and cost nothing.

Each roll is eased up the sequence, frozen on the extreme frame, then eased back
down onto the resting face:

```
1.00s roll up (eased)  +  1.15s hold  +  1.00s roll back  =  3.15s
```

Easing is smoothstep, so the ends are slow and the middle is quick — 6 ticks per
frame at the extremes, 3 through the middle at 30fps.

One trap worth knowing: the roll deliberately spans every frame *except* the
extreme, which belongs to the hold alone. Without that, easing parks on the
extreme ~0.18s early at each end and a 1.15s hold renders as ~1.5s.

## The sequences

`scribe.gm1` holds four 11-frame sequences. The boundaries are measured, not
guessed — mean frame-to-frame difference is 0.4–1.8 inside a sequence and spikes
to 6.3 / 6.3 / 7.0 at exactly frames 11, 22 and 33.

```
00-10  mood ramp        grin -> stern frown   (monotonic, no internal jumps)
11-21  speaking         mouth closed -> open
22-32  positive         calm -> beaming
33-43  negative         calm -> grimace
```

`assets/sequences-labelled.png` shows all four rows if you want to re-check.

## Layout

| File | Role |
|---|---|
| `scribe_window.py` | the panel — tkinter, stdlib only |
| `commands/scribe.md` | the `/scribe` slash command, the only way to launch it |
| `scribe-writer.mjs` | statusline shim: records limits, then renders claude-hud unchanged |
| `tools/gm1.mjs` | GM1/TGX reader + PNG writer, no dependencies |
| `tools/export-frames.mjs` | dumps all 44 frames out of `scribe.gm1` |
| `tools/upscale-frames.py` | EDSR x4 super-resolution over the frames |
| `tools/make-sheet.mjs` | contact sheet for an external upscaler, plus `import-sheet.ps1` to cut it back |

## Where the numbers come from

| Value | Source |
|---|---|
| 7-day, 5-hour, context %, cost, model, effort | `~/.claude/scribe-state.json`, written by the statusline shim on every redraw |
| every animation trigger | the session transcript `.jsonl`, tailed directly |

Rate limits reach the desktop no other way — they exist only in the JSON payload
Claude Code hands its statusline. The shim prints claude-hud's line byte-for-byte
and records the payload on the side.

When Claude Code isn't running, that state goes stale; after 90s the bars grey
out and the panel says so rather than showing a confidently wrong face.

Turn-end detection debounces for 1.5s: Claude sometimes splits text and tool
calls across messages mid-turn, and without the wait that reads as a false
"turn handed back".

## Running it

The panel is summoned from inside Claude Code and nowhere else:

```
/scribe           summon him
/scribe stop      dismiss him
/scribe demo      control strip: one button per roll, mood and timing sliders
/scribe status    running? data fresh?
```

The command lives in `commands/scribe.md` and is installed to
`~/.claude/commands/scribe.md`, so it works from any project. There is no
double-clickable launcher on purpose.

For development there is still `python scribe_window.py [--demo|--once]`, and
`SCRIBE_POS=60,60` pins it somewhere fixed for screenshots.

Re-extract sprites from the local game install:

```
node tools/export-frames.mjs "C:/Non Windows Data/SCE/gm/scribe.gm1" 2
```

**Restart Claude Code** once, so the statusline shim starts writing state.

## Notes

- `assets/frames/*.png` are decoded from your own installed copy of the game.
  They stay local — don't publish them.
- Compaction is **not** detected: no `compact_boundary` record was ever observed
  in a real transcript, so there's no regex guessing at one.
- No "5-hour reset" trigger either — the state file only updates while the
  terminal is redrawing, so a reset can't be observed reliably.
- A remembered window position is trusted as-is rather than clamped to the
  primary screen, which is what lets it live on a second monitor.
- The panel survives a missing state file, missing transcript and missing
  sprites; a render error prints inside the panel instead of killing it.
- On startup the transcript reader seeks to end of file. A panel launched
  mid-session must never replay the backlog as a burst of animations — that is
  covered by the pipeline test, not just by a timestamp guard.
