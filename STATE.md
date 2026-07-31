# Where this stands

The Scribe is running and committed. Everything below is verified unless the
"Open" section says otherwise.

## Live right now

Panel, sprites, mood ramp, the three animations, the deco ledger, the aimed
tomato and its screen splats, the fifty taunts, the `/scribe` command and the
statusline shim -- all wired and seen working.

He now launches himself from a `SessionStart` hook. Measured, not assumed:
a cold run spawns exactly one panel and writes a heartbeat; four runs against a
live panel spawn nothing; two hooks fired simultaneously from cold leave exactly
one survivor; `/scribe` replaces a live panel with a new pid and no sleep between
the kill and the start; and a spawn failure does reach the log (`ENOENT` caught
inside the 250ms the hook stays alive for).

## Open, not yet confirmed

- **The hook fires under a real session start, on strong evidence rather than
  observation.** `~/.claude/scribe-home` is written by nothing but the hook, and
  it was updated at 20:22 on 2026-07-30, between two commits, at a time when no
  invocation was made by hand -- the last of those was three hours earlier. That
  is inference, not a sighting.
  It is now self-proving: the hook writes a dated line to
  `~/.claude/scribe-launch.log` on *every* run, not only on failure. Read that
  file at the start of the next session. A line whose timestamp matches the
  session opening settles it; an empty file means the entry in
  `~/.claude/settings.json` is not firing.
- **The chat path has only been tested headless.** `Brain.ask()` was exercised
  directly and answers correctly in voice within seven words, but nobody has yet
  typed into the panel entry and watched a reply land on the speech screen. Two
  things could bite there and neither has been observed: keyboard focus on an
  `overrideredirect` window (the entry calls `focus_force()` on click, untested),
  and the reply crossing from the worker thread to the canvas.
- The three "ideas not yet built" below are untouched.

## What it is

Stronghold Crusader's scribe as an always-on-top desktop panel for Claude Code.
His resting face tracks the 7-day rate limit, session events animate him, you can
type to him and he answers in the old tongue, and you can throw a tomato at him.

Opened by a SessionStart hook. `/scribe open` and `/scribe close` force the
issue; those two are the whole command.

## Architecture

```
scribe-writer.mjs     statusline shim -> ~/.claude/scribe-state.json, then renders
                      claude-hud byte-for-byte unchanged
scribe_window.py      the panel: tkinter, 30fps, reads the state file and tails the
                      session transcript for triggers
scribe_brain.py       his mind: `claude -p --model haiku` in a worker thread
tools/gm1.mjs         GM1/TGX decoder written from the format spec, no dependencies
tools/export-frames   dumps all 44 sprite frames
tools/upscale-frames  EDSR x4 super-resolution
commands/scribe.md    the slash command, installed to ~/.claude/commands/
```

## Decisions that cost something to learn

- **Rate limits exist only in the statusline payload.** Not in the transcript, not
  in any CLI command. That is the whole reason the shim exists.
- **scribe.gm1 is four 11-frame sequences**, boundaries at 11 / 22 / 33. Measured:
  frame-to-frame difference is 0.4-1.8 inside a sequence and 6.3-7.0 at the seams.
  0-10 mood ramp, 11-21 speaking, 22-32 pleased, 33-43 displeased.
- **Generative upscaling failed.** Asked for 5x, ChatGPT returned 0.33x with the
  grid's right half at a different scale. EDSR x4 is deterministic: scaled back
  down it differs from the source by 2.37/255 per pixel.
- **Sentiment analysis was built and then deleted.** Lexicon plus emphasis
  multipliers, passing 42 cases -- but the suite grew one case at a time after
  each live miss, which makes it a record of misses rather than evidence of
  convergence. Triggers are events only now.
- **Animations are one-shot ping-pongs**: eased 1.0s up, 1.15s hold on the extreme
  frame, 1.0s back. The roll deliberately spans every frame *except* the extreme,
  or easing parks there early and a 1.15s hold renders as 1.5s.
- **The transcript reader seeks to EOF on its first read**, or a panel launched
  mid-session replays the whole backlog as a burst of animations.
- **A remembered window position is not clamped** to the primary screen.
  `winfo_screenwidth()` only knows the primary monitor and would drag it back off
  the second one.
- **A heartbeat cannot make the launch hook idempotent by itself.** Two sessions
  starting together read the same stale beat and both spawn. The panel takes an
  exclusive lock on `~/.claude/scribe.lock` and exits if it cannot get it; the
  heartbeat is only the cheap path that avoids spawning four processes a session
  to have them die. It waits two seconds for the lock rather than failing at
  once, because `/scribe` replaces the panel by killing the old one and starting
  a new one -- giving up immediately would make that command kill the scribe and
  silently decline to bring him back, which is worse than the bug it replaced.
- **`Get-Process` returns an empty `CommandLine` on PowerShell 5.1.** `/scribe`
  summon filtered on it and so matched nothing -- it never replaced the running
  panel -- while `stop` had no filter at all and killed every `pythonw` on the
  machine. Both now go through `Get-CimInstance Win32_Process`.
- **Two open sessions make him twitchy.** He follows whichever session wrote the
  statusline last and re-primes the transcript reader on every switch, so
  triggers land wherever redrew most recently. It degrades to silence, not a
  crash. Auto-launch makes it the normal case; not fixed.
- **Tk cannot anti-alias an arc.** The gauges are drawn four times oversized
  with a real gradient and shrunk with Lanczos, because stacked `create_arc`
  calls leave a staircase along the rim that no bezel hides. Bands are built
  once; a value costs only a pie mask. 4.2ms cached, 6.7ms when the value moves
  every frame, against a 33.3ms budget. This is why the panel now wants Pillow.
- **The room inside a half ring is not its inner diameter.** It narrows as you
  climb, so a numeral's top corners bind, not its width -- "100%" fitted on
  width alone lands squarely on the band.
- **A centred text block grows both ways as it wraps**, so a long line walked
  into the mood word below it. Words are dropped until the *measured* block
  fits; where it wraps depends on the font, not on a character count.
- **A full-screen overlay must ask for click-through by name.** The colour key
  alone is not a guarantee, and a topmost sheet that swallows clicks locks the
  desktop out. `WS_EX_TRANSPARENT | NOACTIVATE | TOOLWINDOW` are set explicitly
  and the window is withdrawn whenever nothing is drawn on it, so a mistake
  cannot outlive the last splat. Bounds come from the virtual screen: this
  machine's is 3000x1920 at y=-104, so primary-only metrics would be wrong.
- **The sling had to move off the panel.** Pulling back goes down and left, away
  from his face and straight off a 540x286 window -- drawn in the panel it was
  invisible exactly when it mattered. It shares the overlay with the throw.
- **Launch power was measured, not chosen.** Swept every angle and strength:
  9.5 needs a 65px pull minimum, 14.0 collapses the high lob into a single
  solution. 12.5 keeps both arcs and opens up half the sling's range.
- **Worked examples in a system prompt become a lookup table.** Five literal
  ones and he answered with them verbatim. Labelling them as strokes rather
  than words fixed it -- and took the bite with it, because the examples had
  been carrying the tone. The test now asserts he never returns one.
- **Being helpful is the failure mode, not being rude.** With the parroting
  gone he reverted to "Where hath it broken?" and "Lay bare thy code" --
  assistant reflexes in costume. Asking for the tone never produced it; only
  forbidding counsel outright did. No asking what he needs, no requesting
  detail, no instruction he could act upon.
- **A new persona section can quietly overturn an old binding.** "fix the bug"
  got "I shall mend it" once the humble manner was added, because humility read
  as a reason to agree. The bindings now say in the prompt that they stand above
  the manner, and refusing is shown as one of the strokes.
- **Named bans beat gestured ones.** "Speak never of tools, files, permissions"
  still produced "bid artificer read file". The forbidden words are listed.
- **A fifty-line pool still repeats.** Plain random.choice says the same thing
  twice in a row often enough to spoil a taunt, which is the one thing a taunt
  cannot do. Draws avoid the last twelve; measured 0 repeats over 40.
- **The brain gets no tools.** Without that he goes and reads the repo when asked
  to fix something; one such question took 45s and timed out mid-tool-call. His
  refusal then leaked the plumbing, so the persona gives him no hands and no
  knowledge of files or permissions.

## Known limits

- 6-9s per answer, tail to 20s. `--bare` would be faster but demands an
  `ANTHROPIC_API_KEY`; this machine uses subscription auth.
- Compaction is not detected: no `compact_boundary` record was ever observed in a
  real transcript, so nothing guesses at one.
- `assets/` is gitignored -- those frames are decoded from the local game install.
  Regenerate with `tools/export-frames.mjs` then `tools/upscale-frames.py`.
- The EDSR model (`EDSR_x4.pb`, 37MB) lives in the session scratchpad, not the
  repo. Re-download from `Saafke/EDSR_Tensorflow` if the frames need rebuilding.

## Ideas not yet built

- Painted item art to replace the primitive-drawn tomato. `draw_tomato()` is the
  seam: swap primitives for PNGs and nothing else changes.
- More things to throw.
- Unprompted remarks currently fire on three thresholds only; there are more
  events available in the transcript.
- More things to throw, now that the sling and the screen splats exist.
