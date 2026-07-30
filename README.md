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
| pleased | 22→32→22 | a message with real positive heat, or a successful `git commit` |
| displeased | 33→43→33 | a message with real negative heat, or a tool error |

## What counts as "heat"

Not a keyword list — a list can't tell `good work` from `THIS IS BRILIANT!!`,
and it will never contain every spelling of every insult. `sentiment.py` scores
**arousal**: how strongly something was said, not merely what it means.

```
arousal = valence x emphasis

valence   VADER's 7,506-term rated lexicon, scored clause by clause so negation
          cannot leak across punctuation, plus one fuzzy pass so typos land
emphasis  1 + 0.35 x exclamations + 0.6 x CAPS ratio + 0.25 x elongation

fires     scorn at <= -2.5
          praise at >= 3.5, or >= 2.8 when emphasis clears 1.5
```

Polarity alone is the wrong signal: VADER's own normalised score ranks a flat
`great` (+0.63) above a shouted `THANK YOU!!!` (+0.52). And the thresholds are
asymmetric on purpose — praise words turn up in ordinary politeness, insults
never do.

| | arousal | |
|---|---|---|
| `YOU MOTHERFUCKER!` | −7.02 | displeased |
| `wtf is this garbage` | −2.80 | displeased |
| `THIS IS BRILIANT!!` | +6.44 | pleased, typo and all |
| `thank you!!!` | +3.07 | pleased |
| `great` | +3.10 | silent |
| `i said i want THAT EXACTLY` | +0.39 | silent |

`great` and `thank you!!!` sit 0.03 apart in arousal, so no single threshold ever
separates them; the emphasis gate is what does.

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
| `sentiment.py` | the arousal classifier |
| `scribe-writer.mjs` | statusline shim: records limits, then renders claude-hud unchanged |
| `tools/gm1.mjs` | GM1/TGX reader + PNG writer, no dependencies |
| `tools/export-frames.mjs` | dumps all 44 frames out of `scribe.gm1` |
| `scribe.bat` | spawns the panel detached via `pythonw` |

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

```
scribe.bat                        # detached, no console
python scribe_window.py --demo    # buttons + sliders to drive it by hand
python scribe_window.py --once    # single frame, for screenshots
SCRIBE_POS=60,60 python scribe_window.py   # fixed position
```

Demo mode adds a control strip: one button per roll, a 7-day / mood-step slider
pair (two views of the same number), and live `roll s` / `hold s` timing sliders.

One dependency, for the lexicon:

```
python -m pip install vaderSentiment
```

If it is missing the panel still runs — it just stops reacting to what you type.

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
- The panel survives a missing state file, missing transcript, missing sprites
  and a missing classifier; a render error prints inside the panel instead of
  killing it.
- On startup the transcript reader seeks to end of file. A panel launched
  mid-session must never replay the backlog as a burst of animations — that is
  covered by the pipeline test, not just by a timestamp guard.
