# Where this stands

The Scribe is finished and running. Everything below is verified, not assumed.

## What it is

Stronghold Crusader's scribe as an always-on-top desktop panel for Claude Code.
His resting face tracks the 7-day rate limit, session events animate him, you can
type to him and he answers in the old tongue, and you can throw a tomato at him.

Launched only from inside Claude Code: `/scribe` (start / stop / demo / status).

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
