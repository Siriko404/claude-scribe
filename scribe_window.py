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

HERE = Path(__file__).resolve().parent
FRAMES = HERE / "assets" / "frames"
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
STATE_FILE = CLAUDE_DIR / "scribe-state.json"
POS_FILE = CLAUDE_DIR / "scribe-window.json"

FPS = 30
TICK_MS = 1000 // FPS
STATE_EVERY = 1.0        # seconds between state-file reads
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
WINDUP = 0.14            # he gets a moment to see it coming
THROW_TIME = 0.40        # seconds from tray to face
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
    LEDGER_W = 268
    PAD = 10
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
        self.canvas.create_rectangle(self.PAD - 1, self.PAD - 1,
                                     self.PAD + self.SPRITE, self.PAD + self.SPRITE,
                                     fill="#120d07", outline=C_STONE)
        self.sprite = self.canvas.create_image(self.PAD, self.PAD, anchor="nw")
        if not self.images:
            self.canvas.create_text(self.PAD + self.SPRITE / 2, self.PAD + self.SPRITE / 2,
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

    def draw_tomato(self, x, y, r, tag, tilt=0.0, squash=1.0):
        """One tomato, from primitives, so it can spin and squash for free."""
        c = self.canvas
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
        self.slots["tomato"] = (34, mid)
        self.draw_tomato(34, mid, ITEM_R, "tray")
        c.create_text(60, mid, anchor="w", text="pelt the scribe",
                      fill=C_DIM, font=("Consolas", 8))

    def throw(self, _name="tomato"):
        """Wind up, arc, then burst. The scowl lands a beat after the tomato."""
        if "tomato" not in self.slots or self.flight:
            return
        self.flight = {"t0": time.time(),
                       "src": self.slots["tomato"],
                       "dst": (self.PAD + 96 + random.randint(-16, 16),
                               self.PAD + 90 + random.randint(-16, 16))}

    def impact(self, x, y):
        now = time.time()
        self.squash_until = now + SQUASH_TIME
        self.squash_at = (x, y)
        self.shake_t0 = now
        self.recoil_t0 = now
        self.anger_at = now + ANGER_DELAY          # comic beat before the scowl
        self.base_pos = (self.root.winfo_x(), self.root.winfo_y())
        self.pelted_at = now

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

    def draw_items(self, now):
        c = self.canvas
        for tag in ("fly", "splat", "chunk"):
            c.delete(tag)

        if self.flight:
            e = now - self.flight["t0"]
            sx, sy = self.flight["src"]
            dx, dy = self.flight["dst"]
            if e < WINDUP:                          # anticipation: rear back
                w = e / WINDUP
                self.draw_tomato(sx - 6 * w + random.uniform(-1, 1),
                                 sy - 4 * w + random.uniform(-1, 1),
                                 ITEM_R * (1 + 0.35 * w), "fly", tilt=-30 * w)
            else:
                p = (e - WINDUP) / THROW_TIME
                if p >= 1.0:
                    self.impact(dx, dy)
                    self.flight = None
                else:
                    x = sx + (dx - sx) * p
                    y = sy + (dy - sy) * p - 80 * math.sin(math.pi * p)
                    stretch = 1.0 + 0.25 * math.sin(math.pi * p)
                    self.draw_tomato(x, y, ITEM_R, "fly", tilt=p * 1080,
                                     squash=stretch)

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

    def item_at(self, x, y):
        for name, (ix, iy) in self.slots.items():
            if abs(x - ix) <= ITEM_R + 5 and abs(y - iy) <= ITEM_R + 5:
                return name
        return None

    # ----------------------------------------------------------------- window

    def grab(self, event):
        self.drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
        self.pressed_at = (event.x_root, event.y_root)
        self.pressed_face = (event.x < self.PAD + self.SPRITE and event.y < self.PAD + self.SPRITE)
        self.armed = self.item_at(event.x, event.y)

    def move(self, event):
        if self.drag:
            self.root.geometry(f"+{event.x_root - self.drag[0]}+{event.y_root - self.drag[1]}")

    def release(self, event):
        moved = max(abs(event.x_root - self.pressed_at[0]),
                    abs(event.y_root - self.pressed_at[1])) if self.pressed_at else 99
        if self.armed and moved < 6:
            self.throw(self.armed)
        elif self.pressed_face and moved < 4:
            self.start("displeased")    # poked in the face
        self.armed = None
        self.drag = None
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

    def bar(self, x, y, w, h, value, stale):
        self.canvas.create_rectangle(x, y, x + w, y + h, fill="#171208",
                                     outline=C_STONE, tags="ledger")
        if value is None:
            self.canvas.create_text(x + w / 2, y + h / 2, text="no data",
                                    fill=C_DIM, font=("Consolas", 7), tags="ledger")
            return
        color = C_DIM if stale else C_RED if value >= 80 else C_AMBER if value >= 55 else C_GREEN
        fill_w = int((w - 2) * value / 100)
        if fill_w > 0:
            self.canvas.create_rectangle(x + 1, y + 1, x + 1 + fill_w, y + h - 1,
                                         fill=color, outline="", tags="ledger")

    def draw_ledger(self):
        c = self.canvas
        c.delete("ledger")
        d = self.data
        lx = self.PAD * 2 + self.SPRITE
        ly = self.PAD
        lw = self.LEDGER_W - self.PAD
        stale = not d.get("fresh")

        c.create_rectangle(lx, ly, lx + lw, ly + self.SPRITE, fill="#2b2214",
                           outline=C_STONE, tags="ledger")
        c.create_text(lx + 10, ly + 12, anchor="w", text="THE SCRIBE'S LEDGER",
                      fill=C_PARCH, font=("Consolas", 10, "bold"), tags="ledger")
        c.create_line(lx + 8, ly + 24, lx + lw - 8, ly + 24, fill=C_STONE, tags="ledger")

        y = ly + 36
        for label, value, reset, drives in (
            ("7 day", d.get("week"), d.get("week_reset"), True),
            ("5 hour", d.get("five"), d.get("five_reset"), False),
            ("context", d.get("ctx"), "", False),
        ):
            c.create_text(lx + 10, y + 6, anchor="w", text=("* " if drives else "  ") + label,
                          fill=C_PARCH if drives else C_DIM, font=("Consolas", 9), tags="ledger")
            self.bar(lx + 74, y, 110, 13, value, stale)
            right = f"{value}%" if value is not None else "--"
            if reset:
                right += f"  {reset}"
            c.create_text(lx + lw - 10, y + 6, anchor="e", text=right,
                          fill=C_DIM, font=("Consolas", 8), tags="ledger")
            y += 24

        y += 4
        c.create_line(lx + 8, y, lx + lw - 8, y, fill=C_STONE, tags="ledger")
        y += 12
        cost = f"${d['cost']:.2f}" if isinstance(d.get("cost"), (int, float)) else "$--"
        meta = f"{cost}   {d.get('model', '-')}" + (f"   {d['effort']}" if d.get("effort") else "")
        c.create_text(lx + 10, y, anchor="w", text=meta, fill=C_DIM,
                      font=("Consolas", 8), tags="ledger")
        c.create_text(lx + 10, y + 15, anchor="w", text=f"project  {d.get('cwd', '-')}",
                      fill=C_DIM, font=("Consolas", 8), tags="ledger")

        step = self.mood_step()
        word = ROLL_WORDS[self.roll.name] if self.roll else MOOD_WORDS[step]
        if time.time() - self.pelted_at < 2.0:
            word = "PELTED"
        ratio = step / (len(MOOD_WORDS) - 1)
        color = C_PARCH if self.roll else (
            C_GREEN if ratio < 0.35 else C_PARCH if ratio < 0.6 else C_AMBER if ratio < 0.85 else C_RED)
        c.create_text(lx + 10, ly + self.SPRITE - 30, anchor="w", text=word,
                      fill=color, font=("Consolas", 13, "bold"), tags="ledger")
        c.create_text(lx + 10, ly + self.SPRITE - 12, anchor="w",
                      text="demo - right-click to close" if self.demo else
                           ("drag to move - right-click to close" if d.get("fresh")
                            else "statusline stale - restart Claude Code"),
                      fill=C_DIM, font=("Consolas", 7), tags="ledger")

    def tick(self):
        try:
            now = time.time()
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

            if self.anger_at and now >= self.anger_at:
                self.start("displeased")
                self.anger_at = None

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
                    self.canvas.coords(self.sprite, self.PAD, self.PAD)
                    self.recoil_t0 = None
                else:
                    k = (1.0 - e / RECOIL_TIME) ** 2
                    self.canvas.coords(self.sprite,
                                       self.PAD + 7 * k, self.PAD + 4 * k)

            if frame != self.shown and self.images:
                self.canvas.itemconfig(self.sprite, image=self.images[frame])
                self.shown = frame
            self.draw_ledger()
        except Exception as exc:
            self.canvas.delete("ledger")
            self.canvas.create_text(self.PAD * 2 + self.SPRITE + 10, 20, anchor="nw",
                                    text=f"scribe error:\n{exc}", fill=C_RED,
                                    font=("Consolas", 8), tags="ledger")
        if not self.once:
            self.root.after(TICK_MS, self.tick)


def main():
    root = tk.Tk()
    root.title("The Scribe")
    ScribePanel(root, demo="--demo" in sys.argv, once="--once" in sys.argv)
    if "--once" in sys.argv:
        root.update()
        root.after(2500, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
