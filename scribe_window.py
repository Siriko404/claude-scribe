"""The Scribe — a small always-on-top advisor panel for Claude Code.

Frameless, draggable, remembers where you put it. Right-click or Esc closes it.

The face:

    resting   frames 00-10, picked by the 7-day limit alone
              0% used -> broad grin ... 100% used -> stern frown
    speaking  frames 11-21, rolled once when Claude hands the turn back to you,
              or when you interrupt
    pleased   frames 22-32, rolled once on praise or a successful commit
    displeased frames 33-43, rolled once on swearing, a tool error, or a
              permission you denied

Every animation is a ping-pong roll — up through the sequence and back down to
its first frame — so the face always lands back on the resting mood. Nothing
loops; the mood face is what you see between events.

Sequence boundaries are measured, not guessed: mean frame-to-frame difference
inside a sequence is 0.4-1.8 and spikes to 6.3 / 6.3 / 7.0 at frames 11, 22, 33.

Data:
  ~/.claude/scribe-state.json   written by scribe-writer.mjs (statusline shim)
  <transcript>.jsonl            tailed directly for triggers

Run:  scribe.bat                        (detached, no console)
      python scribe_window.py --demo    (cycle every animation, no data needed)
      python scribe_window.py --once    (single frame, for screenshots)
"""

import ctypes
import json
import math
import os
import random
import re
import sys
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

from scribe_brain import OMENS, PELTED, Brain, Taunts, mockery

HERE = Path(__file__).resolve().parent
FRAMES = HERE / "assets" / "frames"
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
STATE_FILE = CLAUDE_DIR / "scribe-state.json"
POS_FILE = CLAUDE_DIR / "scribe-window.json"
LOCK_FILE = CLAUDE_DIR / "scribe.lock"
BEAT_FILE = CLAUDE_DIR / "scribe-beat"

FPS = 30
TICK_MS = 1000 // FPS
STATE_EVERY = 1.0        # seconds between state-file reads
BEAT_EVERY = 2.0         # seconds between heartbeat writes
LOCK_WAIT = 2.0          # seconds a replacement waits for the old panel to let go
STALE_AFTER = 90.0       # seconds before statusline data counts as cold
TURN_DEBOUNCE = 1.5      # quiet time before a text-only reply counts as turn end

MOOD = (0, 10)           # resting ramp: grin -> frown
SPEAK = (11, 21)
PLEASED = (22, 32)
DISPLEASED = (33, 43)

ROLL_UP = 1.0            # seconds to roll up the sequence (eased)
ROLL_HOLD = 1.15         # seconds frozen on the extreme frame
# Both are the original 1.3 / 1.5 feel run 1.3x faster; whole roll is 3.15s.

# Things to throw at him. Drawn with canvas primitives rather than sprite sheets:
# a generative model cannot hold a shape steady across frames (it returned this
# project's own sheet at 0.33x with half the grid rescaled), and an arc plus a
# splat is geometry, not art.
TRAY_H = 46
ITEM_R = 15
# Pull the tomato back and let go. A tap still lobs it straight at him.
MAX_PULL = 95            # how far back the sling stretches
MIN_PULL = 10            # below this it counts as a tap, not an aim
# 12.5 measured against the sweep in tools/: it keeps two distinct solutions --
# a flat shot and a high lob -- and lets half the sling's range reach him.
# Above about 14 the lob collapses and there is only one way to land it.
LAUNCH_POWER = 12.5      # px/s of launch speed per px of pull
LOB_TIME = 0.50          # flight time a tap solves for
MAX_FLIGHT = 2.2         # seconds before a stray tomato gives up and lands
SCREEN_HOLD = 3.5        # how long pulp clings to the glass
SCREEN_DRY = 2.0
SQUASH_TIME = 0.10       # flattened against his face before it bursts
ANGER_DELAY = 0.18       # beat of disbelief before the scowl
SHAKE_TIME = 0.30
SHAKE_AMP = 8            # pixels the whole panel jolts
RECOIL_TIME = 0.34       # his head rocks back
SPLAT_HOLD = 2.6         # seconds the pulp clings on
SPLAT_DRY = 1.2          # seconds it takes to slide off
CHUNK_LIFE = 1.4
GRAVITY = 950.0          # px/s^2 for flying pulp

TOMATO_SKIN = "#c0392b"
TOMATO_DARK = "#8e2b20"
TOMATO_LIGHT = "#e8543f"
TOMATO_SEED = "#f4d35e"
TOMATO_LEAF = "#4f7942"

C_EDGE = "#0f0c08"
C_PANEL = "#20190f"
C_STONE = "#3a2f1f"
C_PARCH = "#d9c9a1"
C_DIM = "#8d7c58"
C_GREEN = "#7fa05a"
C_AMBER = "#d8a13c"
C_RED = "#bf4b3a"

MOOD_WORDS = ["JUBILANT", "MERRY", "PLEASED", "CHEERFUL", "AGREEABLE", "WATCHFUL",
              "SOBER", "WEARY", "TROUBLED", "GRIM", "WROTH"]
ROLL_WORDS = {"speak": "READING ALOUD", "pleased": "WELL PLEASED", "displeased": "DISPLEASED"}

COMMITTED = re.compile(r"^\[[^\]\s]+ [0-9a-f]{7,}\]", re.M)

# --------------------------------------------------------------- the ledger

# Aged gold on near-black, set in Times. Deco reads as metal, so a band needs a
# dark rim, a specular line a third of the way in, and a dark rim again.
GROUND = "#0a0908"
GOLD_HI, GOLD, GOLD_LO = "#f6e6b4", "#c9a227", "#4a3a14"
RAY, IVORY, GHOST = "#141109", "#e8dfc8", "#5d523c"
ALARM_HI = "#f0a89a"

TIMES = "Times New Roman"

# The rings are drawn four times oversized and shrunk down, because Tk cannot
# anti-alias an arc: stacking create_arc calls leaves a staircase along the rim
# that no bezel hides. Off the canvas there is room for a real gradient too,
# which is what makes the band read as struck metal rather than a coloured
# stripe. Bands are built once; a value costs only a pie mask.
SS = 4
R_OUT, R_IN = 54, 40
BAND_W, BAND_H = R_OUT * 2 + 6, R_OUT + 6

METAL = {
    "gold": [(0.00, "#3d3010"), (0.16, "#a5811f"), (0.34, "#fff4c8"),
             (0.55, "#c9a227"), (0.82, "#7d6019"), (1.00, "#302509")],
    "alarm": [(0.00, "#3f120c"), (0.16, "#993526"), (0.34, "#ffd8cd"),
              (0.55, "#c04630"), (0.82, "#7a2519"), (1.00, "#2c0d08")],
    "track": [(0.00, "#14100a"), (0.30, "#2a2211"), (0.60, "#241d0e"),
              (1.00, "#100d07")],
}

try:
    from PIL import Image, ImageChops, ImageDraw, ImageTk
    HAVE_PIL = True
except ImportError:          # the panel still runs, the rings are just flat
    HAVE_PIL = False

_bands, _rings = {}, {}


def hexrgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def lerp(a, b, t):
    ra, ga, ba = hexrgb(a)
    rb, gb, bb = hexrgb(b)
    return "#%02x%02x%02x" % (int(ra + (rb - ra) * t), int(ga + (gb - ga) * t),
                              int(ba + (bb - ba) * t))


def gradient(stops, t):
    for i in range(len(stops) - 1):
        (s0, c0), (s1, c1) = stops[i], stops[i + 1]
        if s0 <= t <= s1:
            return lerp(c0, c1, (t - s0) / (s1 - s0) if s1 > s0 else 0.0)
    return stops[-1][1]


def band(key):
    if key not in _bands:
        big = Image.new("RGBA", (BAND_W * SS, BAND_H * SS), (0, 0, 0, 0))
        pen = ImageDraw.Draw(big)
        cx, cy = BAND_W * SS // 2, (R_OUT + 3) * SS
        steps = (R_OUT - R_IN) * SS
        for i in range(steps):
            r = R_OUT * SS - i
            pen.arc([cx - r, cy - r, cx + r, cy + r], 180, 360,
                    fill=hexrgb(gradient(METAL[key], i / float(steps - 1))) + (255,),
                    width=2)
        _bands[key] = big.resize((BAND_W, BAND_H), Image.LANCZOS)
    return _bands[key]


def ring_image(value, key):
    slot = (value, key)
    if slot not in _rings:
        img = band("track").copy()
        if value:
            sweep = max(2.5, 180.0 * value / 100.0)   # one percent still reads
            mask = Image.new("L", (BAND_W * SS, BAND_H * SS), 0)
            far = (R_OUT + 3) * SS + R_OUT * SS
            ImageDraw.Draw(mask).pieslice([3 * SS, 3 * SS, far, far],
                                          180, 180 + sweep, fill=255)
            mask = mask.resize((BAND_W, BAND_H), Image.LANCZOS)
            lit = band(key)
            img.paste(lit, (0, 0), ImageChops.multiply(lit.split()[3], mask))
        _rings[slot] = ImageTk.PhotoImage(img)        # the dict keeps it alive
    return _rings[slot]


def clip_line(x0, y0, x1, y1, box):
    """Liang-Barsky. The canvas has no clipping region, so the sunburst has to
    be cut to the panel by hand, or its rays cross the window onto his face."""
    xmin, ymin, xmax, ymax = box
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - xmin), (dx, xmax - x0), (-dy, y0 - ymin), (dy, ymax - y0)):
        if p == 0:
            if q < 0:
                return None
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return None
                t0 = max(t0, r)
            else:
                if r < t0:
                    return None
                t1 = min(t1, r)
    return x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy


def spaced(text, gap=" "):
    return gap.join(text)


class Splatter:
    """A sheet of glass over the whole desktop, for tomatoes that miss him.

    The window is keyed transparent so only the pulp is visible, and the
    extended style is set explicitly rather than relying on the key alone:
    a full-screen topmost window that is *not* click-through would lock the
    desktop out, so WS_EX_TRANSPARENT is asked for by name. It is withdrawn
    whenever there is nothing to draw, so even a mistake here cannot outlive
    the last splat.

    Bounds come from the virtual screen, not the primary one -- on this machine
    that is 3000x1920 starting at y=-104, and a primary-only rect would put half
    the desktop out of reach.
    """

    KEY = "#ff00fe"          # a magenta nobody paints a tomato with

    def __init__(self, root):
        self.root = root
        self.win = None
        self.canvas = None
        self.origin = (0, 0)

    def bounds(self):
        try:
            user32 = ctypes.windll.user32
            return tuple(user32.GetSystemMetrics(m) for m in (76, 77, 78, 79))
        except Exception:
            return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def build(self):
        x, y, w, h = self.bounds()
        self.origin = (x, y)
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=self.KEY)
        win.attributes("-transparentcolor", self.KEY)
        win.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas = tk.Canvas(win, width=w, height=h, bg=self.KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        win.update_idletasks()
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetAncestor(win.winfo_id(), 2)     # GA_ROOT
            style = user32.GetWindowLongW(hwnd, -20)         # GWL_EXSTYLE
            user32.SetWindowLongW(hwnd, -20, style
                                  | 0x00080000      # LAYERED
                                  | 0x00000020      # TRANSPARENT -- clicks pass through
                                  | 0x08000000      # NOACTIVATE  -- never takes focus
                                  | 0x00000080)     # TOOLWINDOW  -- stays out of alt-tab
        except Exception:
            pass
        self.win = win

    def sheet(self):
        if self.win is None:
            self.build()
        self.win.deiconify()
        self.win.lift()
        return self.canvas

    def to_local(self, x, y):
        return x - self.origin[0], y - self.origin[1]

    def idle(self):
        if self.win is not None:
            self.canvas.delete("all")
            self.win.withdraw()

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def pct(v):
    if isinstance(v, (int, float)) and math.isfinite(v):
        return int(clamp(round(v), 0, 100))
    return None


def epoch(ts):
    if not isinstance(ts, (int, float)):
        return None
    return ts / 1000.0 if ts > 1e12 else float(ts)


def until(ts):
    secs = epoch(ts)
    if secs is None:
        return ""
    left = secs - time.time()
    if left <= 0:
        return ""
    mins = int(left // 60)
    if mins < 60:
        return f"{mins}m"
    if mins < 60 * 48:
        return f"{mins // 60}h{mins % 60:02d}"
    return f"{mins // 1440}d"


def pingpong(span):
    """Frame order up the sequence and back down, landing on the first frame."""
    first, last = span
    return list(range(first, last + 1)) + list(range(last - 1, first - 1, -1))


def smoothstep(p):
    """Ease in and out: slow off the mark, quick through the middle, slow to rest."""
    p = clamp(p, 0.0, 1.0)
    return p * p * (3.0 - 2.0 * p)


class Roll:
    """A one-shot animation: eased roll up the sequence, hold at the extreme
    pose, eased roll back down. Frame is a pure function of elapsed time."""

    def __init__(self, name, span, up=ROLL_UP, hold=ROLL_HOLD, down=None):
        self.name = name
        self.frames = list(range(span[0], span[1] + 1))
        self.up = up
        self.hold = hold
        self.down = up if down is None else down
        self.started = time.time()

    @property
    def duration(self):
        return self.up + self.hold + self.down

    def at(self, progress):
        # Spans every frame but the last. The extreme pose belongs to the hold
        # phase alone, otherwise easing parks on it early and the hold overruns.
        last = len(self.frames) - 2
        return self.frames[int(round(smoothstep(progress) * last))]

    def frame(self, now=None):
        t = (now or time.time()) - self.started
        if t < self.up:
            return self.at(t / self.up)
        if t < self.up + self.hold:
            return self.frames[-1]
        t -= self.up + self.hold
        if t < self.down:
            return self.at(1.0 - t / self.down)
        return None


class Transcript:
    """Incremental reader over a session .jsonl that emits animation triggers."""

    def __init__(self):
        self.path = None
        self.offset = 0
        self.primed = False           # skip the backlog on the first read
        self.pending_turn_at = None   # text-only reply awaiting the debounce
        self.triggers = []            # names ready to play
        self.started = time.time()

    def follow(self, path):
        if path != self.path:
            self.path = path
            self.offset = 0
            self.primed = False
            self.pending_turn_at = None

    def take(self):
        out, self.triggers = self.triggers, []
        return out

    def fire(self, name, when):
        # Never replay history: only lines newer than startup animate.
        if when >= self.started - 2:
            self.triggers.append(name)

    def poll(self):
        if self.path and os.path.exists(self.path):
            try:
                size = os.path.getsize(self.path)
                if size < self.offset:
                    self.offset = 0
                if not self.primed:
                    # Start at the end of the file. A panel launched mid-session
                    # must not replay the backlog as a burst of animations.
                    self.offset = size
                    self.primed = True
                    return
                if size > self.offset:
                    with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(self.offset)
                        block = fh.read()
                        self.offset = fh.tell()
                    for line in block.splitlines():
                        if line.strip():
                            try:
                                self.ingest(json.loads(line))
                            except Exception:
                                continue
            except Exception:
                pass

        # A text-only reply only counts as "turn handed back" once it stays quiet.
        if self.pending_turn_at and (time.time() - self.pending_turn_at) > TURN_DEBOUNCE:
            self.fire("speak", self.pending_turn_at)
            self.pending_turn_at = None

    @staticmethod
    def stamp_of(obj):
        raw = obj.get("timestamp")
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
            except Exception:
                pass
        return time.time()

    @staticmethod
    def parts(obj):
        content = (obj.get("message") or {}).get("content")
        return content if isinstance(content, list) else []

    @staticmethod
    def text_of(obj):
        content = (obj.get("message") or {}).get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        return ""

    def ingest(self, obj):
        kind = obj.get("type")
        when = self.stamp_of(obj)

        if kind == "assistant":
            parts = self.parts(obj)
            if any(p.get("type") == "tool_use" for p in parts):
                self.pending_turn_at = None      # still working
            elif parts:
                self.pending_turn_at = when      # maybe the end of the turn
            return

        if kind != "user":
            return

        self.pending_turn_at = None

        if obj.get("interruptedMessageId"):
            self.fire("speak", when)
            return

        results = [p for p in self.parts(obj) if p.get("type") == "tool_result"]
        if results:
            for part in results:
                body = part.get("content")
                if not isinstance(body, str):
                    body = json.dumps(body) if body is not None else ""
                if part.get("is_error") is True:
                    self.fire("displeased", when)
                elif COMMITTED.search(body):
                    self.fire("pleased", when)
            return

        if obj.get("isMeta"):
            return
        text = self.text_of(obj)
        if not text or text.lstrip().startswith("<"):
            return
        self.fire("pleased", when)      # you spoke to him; he is glad of it


class ScribePanel:
    SPRITE = 220
    LEDGER_W = 300
    PAD = 10
    # The ledger takes the left, he takes the right, with an equal margin either side.
    LEDGER_INNER = LEDGER_W - PAD
    LEDGER_X = PAD
    SPRITE_X = PAD * 2 + LEDGER_INNER
    CONTROL_H = 116

    def __init__(self, root, demo=False, once=False):
        self.root = root
        self.demo = demo
        self.once = once
        self.transcript = Transcript()
        self.roll = None
        self.drag = None
        self.pressed_at = None
        self.pressed_face = False
        self.shown = None
        self.data = {}
        self.next_state_at = 0.0
        self.next_beat_at = 0.0
        self.numeral = None      # measured once, on the first draw
        self.pull = None         # the sling, while you are drawing it back
        self.screen_splats = []  # pulp that never reached him
        self.splatter = Splatter(root)
        self.taunts = Taunts()
        self.misses = 0          # consecutive; he gets crueller as it climbs
        self.roll_up = ROLL_UP
        self.roll_hold = ROLL_HOLD
        self.slots = {}          # item name -> tray position
        self.flight = None       # item currently in the air
        self.splats = []         # tomato pulp stuck to him
        self.chunks = []         # bits that fly off and drop
        self.armed = None        # item under the cursor when the press began
        self.squash_until = 0.0  # tomato flattened against his face
        self.squash_at = (0, 0)
        self.shake_t0 = None     # panel jolt
        self.recoil_t0 = None    # his head rocks back
        self.anger_at = None     # scowl scheduled a beat after impact
        self.pelted_at = 0.0
        self.base_pos = None
        self.brain = Brain()
        self.speech = "At your service, my lord."
        self.waiting_since = None    # he is writing
        self.omens_seen = set()      # thresholds already remarked upon

        w = self.PAD * 2 + self.SPRITE + self.LEDGER_W
        h = self.PAD * 2 + self.SPRITE + TRAY_H + (self.CONTROL_H if demo else 0)
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=C_EDGE)

        pos = read_json(POS_FILE) or {}
        x, y = pos.get("x"), pos.get("y")
        if os.environ.get("SCRIBE_POS"):
            try:
                x, y = (int(v) for v in os.environ["SCRIBE_POS"].split(",", 1))
            except Exception:
                pass
        if isinstance(x, int) and isinstance(y, int):
            # A remembered position may sit on another monitor, so it is trusted
            # as-is; winfo_screenwidth() only knows the primary screen and would
            # drag the panel back off it.
            x = clamp(x, -20000, 20000)
            y = clamp(y, -20000, 20000)
        else:
            x = root.winfo_screenwidth() - w - 40
            y = root.winfo_screenheight() - h - 120
        root.geometry(f"{w}x{h}+{x}+{y}")

        canvas_h = self.PAD * 2 + self.SPRITE + TRAY_H
        self.canvas = tk.Canvas(root, width=w, height=canvas_h, bg=C_EDGE,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="x")
        if demo:
            self.data = {"week": 50, "model": "demo", "cwd": "demo", "fresh": True}
            self.build_controls(root, w)

        self.images = []
        i = 0
        while (FRAMES / f"frame-{i:02d}.png").exists():
            self.images.append(tk.PhotoImage(file=str(FRAMES / f"frame-{i:02d}.png")))
            i += 1

        self.canvas.create_rectangle(0, 0, w - 1, h - 1, fill=C_PANEL, outline=C_STONE)
        self.canvas.create_rectangle(2, 2, w - 3, h - 3, outline="#4b3c26")
        self.canvas.create_rectangle(self.SPRITE_X - 1, self.PAD - 1,
                                     self.SPRITE_X + self.SPRITE, self.PAD + self.SPRITE,
                                     fill="#120d07", outline=C_STONE)
        self.sprite = self.canvas.create_image(self.SPRITE_X, self.PAD, anchor="nw")
        if not self.images:
            self.canvas.create_text(self.SPRITE_X + self.SPRITE / 2,
                                    self.PAD + self.SPRITE / 2,
                                    text="sprites missing\nrun tools/export-frames.mjs",
                                    fill=C_RED, font=("Consolas", 9), justify="center")

        self.build_tray(w, self.PAD * 2 + self.SPRITE)

        self.canvas.bind("<Button-1>", self.grab)
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Button-3>", lambda _e: self.root.destroy())
        root.bind("<Escape>", lambda _e: self.root.destroy())

        self.tick()

    # ---------------------------------------------------------------- window

    # ------------------------------------------------------------------ items

    def draw_tomato(self, x, y, r, tag, tilt=0.0, squash=1.0, canvas=None):
        """One tomato, from primitives, so it can spin and squash for free.

        Takes a canvas because a missed throw is drawn on the overlay, not here.
        """
        c = canvas or self.canvas
        rx, ry = r * squash, r / squash
        c.create_oval(x - rx, y - ry, x + rx, y + ry, fill=TOMATO_SKIN,
                      outline=TOMATO_DARK, width=1, tags=tag)
        # highlight rides around the skin as it tumbles
        hx = x + math.cos(math.radians(tilt - 120)) * r * 0.35
        hy = y + math.sin(math.radians(tilt - 120)) * r * 0.35
        c.create_oval(hx - r * 0.26, hy - r * 0.22, hx + r * 0.26, hy + r * 0.22,
                      fill=TOMATO_LIGHT, outline="", tags=tag)
        leaf = r * 0.45
        lx = x + math.cos(math.radians(tilt - 90)) * r * 0.85
        ly = y + math.sin(math.radians(tilt - 90)) * r * 0.85
        c.create_polygon(lx, ly, lx - leaf, ly - leaf * 0.6,
                         lx, ly - leaf * 0.35, lx + leaf, ly - leaf * 0.6,
                         fill=TOMATO_LEAF, outline="", tags=tag)

    def build_tray(self, width, top):
        c = self.canvas
        c.create_rectangle(0, top, width, top + TRAY_H, fill="#171208",
                           outline=C_STONE)
        mid = top + TRAY_H / 2
        self.slots["tomato"] = (28, mid)   # drawn per frame: it moves when aimed

        self.entry = tk.Entry(self.canvas, bg="#241c11", fg=C_PARCH,
                              insertbackground=C_PARCH, relief="flat", bd=0,
                              font=("Consolas", 9), highlightthickness=1,
                              highlightbackground=C_STONE, highlightcolor=C_DIM)
        c.create_window(52, mid, anchor="w", window=self.entry,
                        width=width - 66, height=24)
        self.entry.insert(0, "speak to the scribe...")
        self.entry.bind("<Return>", self.speak_to_him)
        self.entry.bind("<FocusIn>", self.clear_placeholder)
        self.entry.bind("<Button-1>", lambda _e: (self.root.focus_force(),
                                                  self.entry.focus_set()))

    def face_rect(self):
        """His head, in screen coordinates -- what the tomato has to hit."""
        ox, oy = self.root.winfo_x(), self.root.winfo_y()
        return (ox + self.SPRITE_X + 22, oy + self.PAD + 12,
                ox + self.SPRITE_X + self.SPRITE - 22, oy + self.PAD + self.SPRITE - 20)

    def lob_velocity(self):
        """Solve the arc that drops a tap straight onto his face."""
        ax, ay = self.slots["tomato"]
        ox, oy = self.root.winfo_x(), self.root.winfo_y()
        fx0, fy0, fx1, fy1 = self.face_rect()
        dx = (fx0 + fx1) / 2 - (ox + ax) + random.uniform(-14, 14)
        dy = (fy0 + fy1) / 2 - (oy + ay) + random.uniform(-12, 12)
        return dx / LOB_TIME, (dy - 0.5 * GRAVITY * LOB_TIME ** 2) / LOB_TIME

    def throw(self, velocity=None):
        """Let it go. Gravity does the rest, and it lands where it lands."""
        if "tomato" not in self.slots or self.flight:
            return
        ax, ay = self.slots["tomato"]
        vx, vy = velocity if velocity else self.lob_velocity()
        self.flight = {"x": self.root.winfo_x() + ax, "y": self.root.winfo_y() + ay,
                       "vx": vx, "vy": vy, "t0": time.time(), "last": time.time(),
                       "spin": 0.0}

    def path_of(self, vx, vy, span=0.9, step=0.055):
        """Where a shot would go, sampled for the aiming dots."""
        ax, ay = self.slots["tomato"]
        out, x, y, t = [], ax, ay, 0.0
        while t < span:
            x += vx * step
            y += vy * step
            vy += GRAVITY * step
            t += step
            out.append((x, y))
        return out

    def missed(self, x, y):
        """It hit the glass instead of him, and he enjoyed that."""
        now = time.time()
        for _ in range(13):
            self.screen_splats.append({
                "x": x + random.uniform(-30, 30),
                "y": y + random.uniform(-24, 26),
                "r": random.uniform(5, 17),
                "colour": random.choice((TOMATO_SKIN, TOMATO_DARK, TOMATO_LIGHT)),
                "born": now})
        self.misses += 1
        # Not say(): that starts the speaking roll, and the point is the smirk.
        self.speech = self.taunts.pick(mockery(self.misses))
        self.waiting_since = None
        self.start("pleased")           # your failure is the best of his day

    def impact(self, x, y):
        now = time.time()
        self.squash_until = now + SQUASH_TIME
        self.squash_at = (x, y)
        self.shake_t0 = now
        self.recoil_t0 = now
        self.anger_at = now + ANGER_DELAY          # comic beat before the scowl
        self.base_pos = (self.root.winfo_x(), self.root.winfo_y())
        self.pelted_at = now
        self.misses = 0            # you landed one; the ridicule starts over

        for _ in range(11):                        # pulp stuck to his face
            self.splats.append({
                "x": x + random.uniform(-36, 36),
                "y": y + random.uniform(-28, 32),
                "r": random.uniform(5, 16),
                "colour": random.choice((TOMATO_SKIN, TOMATO_DARK, TOMATO_LIGHT)),
                "born": now})
        for _ in range(4):                         # seeds
            self.splats.append({
                "x": x + random.uniform(-22, 22),
                "y": y + random.uniform(-16, 16),
                "r": random.uniform(1.5, 2.6),
                "colour": TOMATO_SEED, "born": now})
        for _ in range(9):                         # bits that fly off and drop
            angle = random.uniform(math.pi, 2 * math.pi)
            speed = random.uniform(90, 260)
            self.chunks.append({
                "x": x, "y": y,
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed,
                "r": random.uniform(2.5, 6),
                "colour": random.choice((TOMATO_SKIN, TOMATO_DARK, TOMATO_LIGHT)),
                "born": now, "last": now})

    def draw_aim(self):
        """The sling, on the overlay rather than the panel.

        Pulling back goes down and left, away from his face -- straight off a
        540x286 window. Drawn in the panel it was invisible the moment it
        mattered, so it goes on the same sheet of glass the throw uses.
        """
        sheet = self.splatter.sheet()
        sheet.delete("aim")
        ox, oy = self.root.winfo_x(), self.root.winfo_y()
        ax, ay = self.slots["tomato"]
        dx, dy = self.pull

        for i, (px, py) in enumerate(self.path_of(-dx * LAUNCH_POWER, -dy * LAUNCH_POWER)):
            r = 3.4 - i * 0.14
            if r > 0.7:
                sx, sy = self.splatter.to_local(ox + px, oy + py)
                sheet.create_oval(sx - r, sy - r, sx + r, sy + r,
                                  fill=GOLD_LO if i % 2 else GOLD, outline="",
                                  tags="aim")
        bx, by = self.splatter.to_local(ox + ax, oy + ay)
        sheet.create_line(bx, by, bx + dx, by + dy, fill=TOMATO_DARK, width=2,
                          tags="aim")
        reach = math.hypot(dx, dy) / MAX_PULL
        self.draw_tomato(bx + dx, by + dy, ITEM_R * (1 + 0.12 * reach), "aim",
                         tilt=reach * 40, squash=1.0 + 0.18 * reach, canvas=sheet)

    def step_flight(self, now):
        """Advance the tomato through the air and decide what it hit.

        Everything is in screen coordinates, because the throw does not respect
        the edge of the panel -- a bad one leaves the window entirely.
        """
        f = self.flight
        dt = max(0.0, min(0.05, now - f["last"]))
        f["last"] = now
        f["vy"] += GRAVITY * dt
        f["x"] += f["vx"] * dt
        f["y"] += f["vy"] * dt
        f["spin"] += dt * 900

        fx0, fy0, fx1, fy1 = self.face_rect()
        if fx0 <= f["x"] <= fx1 and fy0 <= f["y"] <= fy1:
            self.flight = None
            self.splatter.idle()
            self.impact(f["x"] - self.root.winfo_x(), f["y"] - self.root.winfo_y())
            return

        ox, oy, ow, oh = self.splatter.bounds()
        gone = not (ox <= f["x"] <= ox + ow and f["y"] <= oy + oh)
        if gone or now - f["t0"] > MAX_FLIGHT:
            self.flight = None
            self.missed(min(max(f["x"], ox + 20), ox + ow - 20),
                        min(max(f["y"], oy + 20), oy + oh - 20))
            return

        sheet = self.splatter.sheet()
        sheet.delete("fly")
        px, py = self.splatter.to_local(f["x"], f["y"])
        self.draw_tomato(px, py, ITEM_R, "fly", tilt=f["spin"], squash=1.15,
                         canvas=sheet)

    def draw_screen_splats(self, now):
        """Pulp on the glass. It clings, sags, then dries off."""
        if not self.screen_splats:
            # The sheet also carries the sling and the shot; only put it away
            # when none of the three want it.
            if not self.flight and self.pull is None:
                self.splatter.idle()
            return
        sheet = self.splatter.sheet()
        sheet.delete("glass")
        for blob in list(self.screen_splats):
            age = now - blob["born"]
            if age > SCREEN_HOLD + SCREEN_DRY:
                self.screen_splats.remove(blob)
                continue
            drying = max(0.0, (age - SCREEN_HOLD) / SCREEN_DRY)
            r = blob["r"] * (1.0 - drying)
            sag = min(11.0, age * 3.4)
            drip = 1.0 + min(1.7, age * 0.45)
            bx, by = self.splatter.to_local(blob["x"], blob["y"] + sag)
            sheet.create_oval(bx - r, by - r * drip, bx + r, by + r * drip,
                              fill=blob["colour"], outline="", tags="glass")

    def draw_items(self, now):
        c = self.canvas
        for tag in ("fly", "splat", "chunk"):
            c.delete(tag)

        c.delete("tray")
        if self.pull is None and not self.flight:
            self.draw_tomato(*self.slots.get("tomato", (0, 0)), ITEM_R, "tray")
        elif self.pull is not None:
            self.draw_aim()

        if self.flight:
            self.step_flight(now)

        if now < self.squash_until:                 # flattened on his face
            x, y = self.squash_at
            k = 1 - (self.squash_until - now) / SQUASH_TIME
            self.draw_tomato(x, y, ITEM_R * (1 + 0.5 * k), "fly",
                             squash=1.9 + k)

        for chunk in list(self.chunks):
            age = now - chunk["born"]
            if age > CHUNK_LIFE or chunk["y"] > 4000:
                self.chunks.remove(chunk)
                continue
            dt = max(0.0, min(0.1, now - chunk["last"]))
            chunk["last"] = now
            chunk["vy"] += GRAVITY * dt
            chunk["x"] += chunk["vx"] * dt
            chunk["y"] += chunk["vy"] * dt
            r = chunk["r"]
            c.create_oval(chunk["x"] - r, chunk["y"] - r,
                          chunk["x"] + r, chunk["y"] + r,
                          fill=chunk["colour"], outline="", tags="chunk")

        for blob in list(self.splats):
            age = now - blob["born"]
            if age > SPLAT_HOLD + SPLAT_DRY:
                self.splats.remove(blob)
                continue
            drying = max(0.0, (age - SPLAT_HOLD) / SPLAT_DRY)
            r = blob["r"] * (1.0 - drying)
            sag = min(9.0, age * 3.0)               # pulp creeps down his face
            drip = 1.0 + min(1.6, age * 0.5)        # and stretches as it goes
            c.create_oval(blob["x"] - r, blob["y"] - r * drip + sag,
                          blob["x"] + r, blob["y"] + r * drip + sag,
                          fill=blob["colour"], outline="", tags="splat")

    def clear_placeholder(self, _event=None):
        if self.entry.get().startswith("speak to the scribe"):
            self.entry.delete(0, "end")

    def speak_to_him(self, _event=None):
        question = self.entry.get().strip()
        if not question or question.startswith("speak to the scribe"):
            return
        if not self.brain.ask(question, self.data):
            self.speech = "One thing at a time, my lord."
            return
        self.entry.delete(0, "end")
        self.waiting_since = time.time()

    def say(self, text):
        """Put words in his mouth and let him deliver them."""
        self.speech = text
        self.waiting_since = None
        self.start("speak")

    def check_omens(self, now):
        """Unprompted remarks, but only when something actually changed."""
        week = self.data.get("week")
        if week is None:
            return
        for mark in (90, 75, 50):
            if week >= mark and f"treasury_{mark}" not in self.omens_seen:
                self.omens_seen.add(f"treasury_{mark}")
                self.say(random.choice(OMENS[f"treasury_{mark}"]))
                return
        # the week rolled over; he is willing to be surprised again
        if week < 45:
            self.omens_seen.difference_update({"treasury_50", "treasury_75", "treasury_90"})

    def item_at(self, x, y):
        for name, (ix, iy) in self.slots.items():
            if abs(x - ix) <= ITEM_R + 5 and abs(y - iy) <= ITEM_R + 5:
                return name
        return None

    # ----------------------------------------------------------------- window

    def grab(self, event):
        self.pressed_at = (event.x_root, event.y_root)
        self.pressed_face = (self.SPRITE_X <= event.x < self.SPRITE_X + self.SPRITE
                             and event.y < self.PAD + self.SPRITE)
        self.armed = self.item_at(event.x, event.y)
        # Pressing the tomato draws the sling; pressing anywhere else drags the
        # panel. Doing both at once would move the window as you took aim.
        self.pull = (0.0, 0.0) if self.armed else None
        self.drag = None if self.armed else (event.x_root - self.root.winfo_x(),
                                             event.y_root - self.root.winfo_y())

    def move(self, event):
        if self.pull is not None:
            ax, ay = self.slots["tomato"]
            dx, dy = event.x - ax, event.y - ay
            reach = math.hypot(dx, dy)
            if reach > MAX_PULL:                    # the sling only stretches so far
                dx, dy = dx * MAX_PULL / reach, dy * MAX_PULL / reach
            self.pull = (dx, dy)
        elif self.drag:
            self.root.geometry(f"+{event.x_root - self.drag[0]}+{event.y_root - self.drag[1]}")

    def release(self, event):
        moved = max(abs(event.x_root - self.pressed_at[0]),
                    abs(event.y_root - self.pressed_at[1])) if self.pressed_at else 99
        if self.pull is not None:
            dx, dy = self.pull
            if math.hypot(dx, dy) >= MIN_PULL:
                self.throw((-dx * LAUNCH_POWER, -dy * LAUNCH_POWER))
            else:
                self.throw()                # a tap still lobs it straight at him
        elif self.pressed_face and moved < 4:
            self.start("displeased")        # poked in the face
        self.armed = None
        self.pull = None
        self.drag = None
        if self.splatter.canvas is not None:
            self.splatter.canvas.delete("aim")
        try:
            POS_FILE.write_text(json.dumps({"x": self.root.winfo_x(), "y": self.root.winfo_y()}))
        except Exception:
            pass

    # ----------------------------------------------------------------- state

    def read_state(self):
        state = read_json(STATE_FILE) or {}
        stamped = epoch(state.get("updated_at"))
        if state.get("transcript_path"):
            self.transcript.follow(state["transcript_path"])

        rl = state.get("rate_limits") or {}
        cw = state.get("context_window") or {}
        ctx = pct(cw.get("used_percentage"))
        if ctx is None and pct(cw.get("remaining_percentage")) is not None:
            ctx = 100 - pct(cw.get("remaining_percentage"))

        self.data = {
            "fresh": stamped is not None and (time.time() - stamped) < STALE_AFTER,
            "week": pct((rl.get("seven_day") or {}).get("used_percentage")),
            "five": pct((rl.get("five_hour") or {}).get("used_percentage")),
            "ctx": ctx,
            "week_reset": until((rl.get("seven_day") or {}).get("resets_at")),
            "five_reset": until((rl.get("five_hour") or {}).get("resets_at")),
            "model": (state.get("model") or {}).get("display_name")
                     or (state.get("model") or {}).get("id") or "no session",
            "effort": state.get("effort"),
            "cost": (state.get("cost") or {}).get("total_cost_usd"),
            "cwd": os.path.basename(state.get("cwd") or "") or "-",
        }

    def mood_step(self):
        week = self.data.get("week")
        if week is None:
            return len(MOOD_WORDS) // 2
        return int(round(week / 100.0 * (MOOD[1] - MOOD[0])))

    def start(self, name):
        span = {"speak": SPEAK, "pleased": PLEASED, "displeased": DISPLEASED}[name]
        self.roll = Roll(name, span, up=self.roll_up, hold=self.roll_hold)

    def build_controls(self, parent, width):
        """Demo-only strip: play each roll on demand, set the mood by hand.

        The two sliders are two views of one number — 7-day percent and the mood
        step it maps to — so dragging either keeps the face and the ledger honest.
        """
        bar = tk.Frame(parent, bg=C_PANEL, height=self.CONTROL_H, width=width)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        row1 = tk.Frame(bar, bg=C_PANEL)
        row1.pack(fill="x")
        row2 = tk.Frame(bar, bg=C_PANEL)
        row2.pack(fill="x")

        def button(label, command, color):
            tk.Button(row1, text=label, command=command, bg="#2b2214", fg=color,
                      activebackground=C_STONE, activeforeground=C_PARCH,
                      relief="flat", bd=1, font=("Consolas", 8, "bold"),
                      highlightthickness=0, padx=5, cursor="hand2"
                      ).pack(side="left", padx=(6, 0), pady=(6, 2))

        button("SPEAK  11-21", lambda: self.start("speak"), "#9ec5e8")
        button("PLEASED  22-32", lambda: self.start("pleased"), C_GREEN)
        button("DISPLEASED  33-43", lambda: self.start("displeased"), C_RED)
        button("CLOSE", self.root.destroy, C_DIM)

        def slider(parent_row, label, hi, handler):
            tk.Label(parent_row, text=label, bg=C_PANEL, fg=C_DIM,
                     font=("Consolas", 8)).pack(side="left", padx=(8, 2))
            s = tk.Scale(parent_row, from_=0, to=hi, orient="horizontal", length=140,
                         bg=C_PANEL, fg=C_PARCH, troughcolor="#171208",
                         highlightthickness=0, bd=0, sliderrelief="flat",
                         font=("Consolas", 7), width=9, command=handler)
            s.pack(side="left")
            return s

        self.syncing = False

        def set_week(v):
            if self.syncing:
                return
            week = int(v)
            self.data["week"] = week
            self.syncing = True
            self.mood_slider.set(int(round(week / 100.0 * (MOOD[1] - MOOD[0]))))
            self.syncing = False

        def set_step(v):
            if self.syncing:
                return
            step = int(v)
            week = int(round(step / float(MOOD[1] - MOOD[0]) * 100))
            self.data["week"] = week
            self.syncing = True
            self.week_slider.set(week)
            self.syncing = False

        self.week_slider = slider(row2, "7 day %", 100, set_week)
        self.mood_slider = slider(row2, "mood step", MOOD[1] - MOOD[0], set_step)
        self.week_slider.set(50)

        row3 = tk.Frame(bar, bg=C_PANEL)
        row3.pack(fill="x")

        def timing(label, lo, hi, initial, setter):
            tk.Label(row3, text=label, bg=C_PANEL, fg=C_DIM,
                     font=("Consolas", 8)).pack(side="left", padx=(8, 2))
            s = tk.Scale(row3, from_=lo, to=hi, resolution=0.1, orient="horizontal",
                         length=140, bg=C_PANEL, fg=C_PARCH, troughcolor="#171208",
                         highlightthickness=0, bd=0, sliderrelief="flat",
                         font=("Consolas", 7), width=9,
                         command=lambda v: setter(float(v)))
            s.set(initial)
            s.pack(side="left")

        timing("roll s", 0.3, 3.0, ROLL_UP, lambda v: setattr(self, "roll_up", v))
        timing("hold s", 0.0, 3.0, ROLL_HOLD, lambda v: setattr(self, "roll_hold", v))

    # ---------------------------------------------------------------- render

    def dial(self, cx, cy, value, alarmed):
        """A half-circle gauge. Falls back to a flat arc without Pillow rather
        than refusing to draw -- the panel is still readable, just not struck."""
        c = self.canvas
        pct = None if value is None else max(0, min(100, int(round(value))))
        if HAVE_PIL:
            c.create_image(cx, cy + 3, anchor="s", tags="ledger",
                           image=ring_image(pct, "alarm" if alarmed else "gold"))
            return
        for r in range(R_OUT, R_IN, -1):
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=180, extent=-180,
                         style="arc", outline="#241d0e", width=3, tags="ledger")
        if pct:
            sweep = min(-2.5, -180.0 * pct / 100.0)
            for r in range(R_OUT, R_IN, -1):
                c.create_arc(cx - r, cy - r, cx + r, cy + r, start=180, extent=sweep,
                             style="arc", outline=C_RED if alarmed else GOLD,
                             width=3, tags="ledger")

    def numeral_fit(self, sample="100%"):
        """Largest Times size whose corners still clear the ring's inner circle.

        The room inside a half ring is not its inner diameter -- it narrows as
        you climb, so the block's top corners bind, not its width. Fitted once
        against the widest reading and cached, then used for both dials so they
        never disagree.
        """
        if self.numeral is None:
            c = self.canvas
            self.numeral = (12, 12)
            for size in range(24, 11, -1):
                probe = c.create_text(-900, -900, text=sample, anchor="center",
                                      font=(TIMES, size, "bold"))
                x0, y0, x1, y1 = c.bbox(probe)
                c.delete(probe)
                half_w, half_h = (x1 - x0) / 2.0, (y1 - y0) / 2.0
                rise = half_h + 2
                if math.hypot(half_w, rise + half_h) <= R_IN - 3:
                    self.numeral = (size, rise)
                    break
        return self.numeral

    def fit_text(self, cx, top, width, max_h, text, fill, font):
        """Drop words until the measured block fits its band.

        A centred text item grows both ways as it wraps, so a long line walked
        straight into the mood word below. Where it wraps depends on the font,
        not on a character count, so it has to be measured.
        """
        c = self.canvas
        words = " ".join(text.split()).split(" ")
        for n in range(len(words), 0, -1):
            body = " ".join(words[:n]) + ("" if n == len(words) else " ...")
            item = c.create_text(cx, top, anchor="n", width=width, text=body,
                                 fill=fill, font=font, justify="center", tags="ledger")
            x0, y0, x1, y1 = c.bbox(item)
            if y1 - y0 <= max_h:
                return
            c.delete(item)

    def draw_ledger(self):
        c = self.canvas
        c.delete("ledger")
        d = self.data
        x, y, w, h = self.LEDGER_X, self.PAD, self.LEDGER_INNER, self.SPRITE
        c.create_rectangle(x, y, x + w, y + h, fill=GROUND, outline=GOLD_LO,
                           tags="ledger")

        # A sunburst, barely there. Deco's one indulgence -- clipped to the panel.
        cx0, cy0 = x + w / 2, y + h + 26
        for k in range(-9, 10):
            a = math.radians(90 + k * 6.5)
            seg = clip_line(cx0, cy0, cx0 + math.cos(a) * 340, cy0 - math.sin(a) * 340,
                            (x + 1, y + 1, x + w - 1, y + h - 1))
            if seg:
                c.create_line(*seg, fill=RAY, tags="ledger")

        for yy, col in ((y + 8, GOLD_LO), (y + 11, GOLD),
                        (y + h - 11, GOLD), (y + h - 8, GOLD_LO)):
            c.create_line(x + 10, yy, x + w - 10, yy, fill=col, tags="ledger")
        # Chevrons at the head only. The foot belongs to the mood word, and
        # "READING ALOUD" letterspaced is wide enough to sit right on them.
        for sx, sgn in ((x + 10, 1), (x + w - 10, -1)):
            for step in range(3):
                run = 6 + step * 5
                c.create_line(sx, y + 15 + step * 4, sx + sgn * run,
                              y + 15 + step * 4, fill=GOLD_LO, tags="ledger")

        c.create_text(x + w / 2, y + 27, anchor="center", text=spaced("THE LEDGER", "  "),
                      fill=GOLD, font=(TIMES, 10, "bold"), tags="ledger")
        c.create_line(x + w / 2 - 54, y + 39, x + w / 2 + 54, y + 39, fill=GOLD_LO,
                      tags="ledger")

        size, rise = self.numeral_fit()
        for frac, key, label, reset in ((0.29, "week", "VII DAYS", "week_reset"),
                                        (0.71, "five", "V HOURS", "five_reset")):
            v = d.get(key)
            alarmed = v is not None and v >= 80
            cx, cy = x + w * frac, y + 104
            self.dial(cx, cy, v, alarmed)
            # "--" rather than the raw absence: a blank dial is a state, not a fault.
            c.create_text(cx, cy - rise, anchor="center",
                          text=f"{v}%" if v is not None else "--",
                          fill=(ALARM_HI if alarmed else GOLD_HI) if v is not None else GHOST,
                          font=(TIMES, size, "bold"), tags="ledger")
            c.create_text(cx, cy + 13, anchor="center", text=spaced(label),
                          fill=C_DIM, font=(TIMES, 7), tags="ledger")
            anew = d.get(reset)
            c.create_text(cx, cy + 26, anchor="center",
                          text=f"anew in {anew}" if anew else "no reckoning",
                          fill=GHOST, font=(TIMES, 8, "italic"), tags="ledger")

        # His last words, and nothing older. A speech screen, not a log.
        self.fit_text(x + w / 2, y + 148, w - 40, 46, self.speech, IVORY,
                      (TIMES, 12, "italic"))

        step = self.mood_step()
        word = ROLL_WORDS[self.roll.name] if self.roll else MOOD_WORDS[step]
        if time.time() - self.pelted_at < 2.0:
            word = "PELTED"
        c.create_text(x + w / 2, y + h - 20, anchor="center", text=spaced(word),
                      fill=C_DIM, font=(TIMES, 9), tags="ledger")
        if not d.get("fresh"):
            c.create_text(x + w - 14, y + h - 20, anchor="e", text="stale",
                          fill=GHOST, font=(TIMES, 8, "italic"), tags="ledger")

    def tick(self):
        try:
            now = time.time()
            if now >= self.next_beat_at:
                # The launch hook reads this instead of enumerating processes.
                try:
                    BEAT_FILE.write_text(str(int(now * 1000)))
                except Exception:
                    pass
                self.next_beat_at = now + BEAT_EVERY
            if not self.demo:
                if now >= self.next_state_at:
                    self.read_state()
                    self.next_state_at = now + STATE_EVERY
                self.transcript.poll()
                for name in self.transcript.take():
                    # A reaction outranks the speaking roll.
                    if self.roll is None or name != "speak":
                        self.start(name)

            frame = self.roll.frame(now) if self.roll else None
            if frame is None:
                self.roll = None
                frame = MOOD[0] + self.mood_step()

            self.draw_items(now)
            self.draw_screen_splats(now)

            if self.anger_at and now >= self.anger_at:
                self.start("displeased")
                self.anger_at = None
                self.speech = self.taunts.pick(PELTED)

            reply = self.brain.take()
            if reply:
                self.say(reply)
            elif self.waiting_since:
                dots = "." * (1 + int((now - self.waiting_since) * 2) % 3)
                self.speech = "the scribe dips his quill" + dots
            self.check_omens(now)

            # The whole panel jolts, then his head rocks back and settles.
            if self.shake_t0 is not None and self.base_pos:
                e = now - self.shake_t0
                if e > SHAKE_TIME:
                    self.root.geometry("+%d+%d" % self.base_pos)
                    self.shake_t0 = None
                else:
                    decay = 1.0 - e / SHAKE_TIME
                    ox = int(SHAKE_AMP * decay * math.sin(e * 58))
                    oy = int(SHAKE_AMP * 0.6 * decay * math.cos(e * 47))
                    self.root.geometry("+%d+%d" % (self.base_pos[0] + ox,
                                                   self.base_pos[1] + oy))
            if self.recoil_t0 is not None:
                e = now - self.recoil_t0
                if e > RECOIL_TIME:
                    self.canvas.coords(self.sprite, self.SPRITE_X, self.PAD)
                    self.recoil_t0 = None
                else:
                    k = (1.0 - e / RECOIL_TIME) ** 2
                    self.canvas.coords(self.sprite,
                                       self.SPRITE_X + 7 * k, self.PAD + 4 * k)

            if frame != self.shown and self.images:
                self.canvas.itemconfig(self.sprite, image=self.images[frame])
                self.shown = frame
            self.draw_ledger()
        except Exception as exc:
            self.canvas.delete("ledger")
            self.canvas.create_text(self.LEDGER_X + 10, 20, anchor="nw",
                                    text=f"scribe error:\n{exc}", fill=C_RED,
                                    font=("Consolas", 8), tags="ledger")
        if not self.once:
            self.root.after(TICK_MS, self.tick)


def claim_lock(wait=LOCK_WAIT):
    """One panel at a time, decided by the OS rather than by a timestamp.

    The launch hook checks the heartbeat first, but two sessions starting
    together both read the same stale beat and both spawn. This is what
    actually settles it. Windows releases the lock even on a hard kill, so
    there is no staleness to reason about.

    It waits rather than failing at once, because `/scribe` replaces the panel
    by killing the old one and starting a new one, and the kill is not
    instantaneous. Giving up immediately would leave that command killing the
    scribe and silently declining to bring him back.

    Returns the open file -- the caller must hold it, since closing it releases
    the lock -- or None if someone else already has it.
    """
    handle = open(LOCK_FILE, "w")
    try:
        import msvcrt
    except ImportError:
        return handle                     # not Windows; nothing to guard
    deadline = time.time() + wait
    while True:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return handle
        except OSError:
            if time.time() >= deadline:
                handle.close()
                return None
            time.sleep(0.1)


def main():
    # A screenshot run is a one-off and never contends with a live panel.
    if "--once" not in sys.argv:
        lock = claim_lock()      # kept in scope: closing it releases the lock
        if lock is None:
            return
    root = tk.Tk()
    root.title("The Scribe")
    ScribePanel(root, demo="--demo" in sys.argv, once="--once" in sys.argv)
    if "--once" in sys.argv:
        root.update()
        root.after(2500, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
