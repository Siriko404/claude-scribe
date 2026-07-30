"""Render the deco ledger at real size, in every state it can be in.

Draws through the actual tkinter canvas and screen-grabs it, so what comes out
is what the panel would look like -- not an approximation in another drawing
library with other font metrics.

    python tools/ledger-samples.py

The brief: minimal, elegant, ancient and mysterious, art deco, Times Roman, the
limits as shiny half-circle rings with the percent in the middle. Ledger on the
left, his face on the right.

One data point proves nothing about a gauge, so every run also renders the
states that break things: empty, full, near the limit, no ledger at all, and a
speech long enough to run into what sits below it. Those are what caught the
defects in the first draft.

Output lands in assets/ledger-samples/.
"""

import math
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageGrab

HERE = Path(__file__).resolve().parent
FRAMES = HERE.parent / "assets" / "frames"
OUT = HERE.parent / "assets" / "ledger-samples"

SPRITE, LEDGER_W, PAD, TRAY_H = 220, 300, 10, 46
W = PAD * 2 + SPRITE + LEDGER_W
H = PAD * 2 + SPRITE + TRAY_H

# The ledger takes the left, he takes the right, with an equal margin each side.
LEDGER_X, LEDGER_INNER = PAD, LEDGER_W - PAD
SPRITE_X = PAD * 2 + LEDGER_INNER

C_EDGE, C_PANEL, C_STONE, C_DIM = "#0f0c08", "#20190f", "#3a2f1f", "#8d7c58"

# Aged gold on near-black. Deco reads as metal, so the band needs a dark edge, a
# bright line a third of the way in, and a dark edge again -- that is what makes
# a flat arc look struck rather than coloured.
GROUND = "#0a0908"
GOLD_HI, GOLD, GOLD_LO = "#f6e6b4", "#c9a227", "#4a3a14"
BRONZE, RAY = "#241d0e", "#141109"
IVORY, DIM, GHOST = "#e8dfc8", "#8a7d5f", "#5d523c"
ALARM_HI, ALARM = "#f0a89a", "#b8402c"

TIMES = "Times New Roman"

STATES = [
    ("usual", dict(week=63, five=12, week_reset="2d", five_reset="1h",
                   speech="Sixty-three parts spent, my lord.", mood="SOBER")),
    ("empty", dict(week=0, five=0, week_reset="7d", five_reset="5h",
                   speech="Naught spent, my lord.", mood="JUBILANT")),
    ("brim", dict(week=1, five=3, week_reset="7d", five_reset="4h",
                  speech="Scarce a drop, sire.", mood="MERRY")),
    ("alarm", dict(week=87, five=91, week_reset="9h", five_reset="20m",
                   speech="A tithe remaineth. Then silence.", mood="GRIM")),
    ("full", dict(week=100, five=100, week_reset="2d", five_reset="1h",
                  speech="The coffers are bare, sire.", mood="WROTH")),
    ("noledger", dict(week=None, five=None, week_reset=None, five_reset=None,
                      speech="I have no ledger to read, sire.", mood="WATCHFUL")),
    ("longtongue", dict(week=63, five=12, week_reset="2d", five_reset="1h",
                        speech="Thou hast spent threescore and three parts of thy "
                               "seven-day treasury, and the hour groweth late "
                               "besides, my most improvident lord.",
                        mood="TROUBLED")),
]


# ------------------------------------------------------------------ helpers

def spaced(text, gap=" "):
    return gap.join(text)


def hexrgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def lerp(a, b, t):
    ra, ga, ba = hexrgb(a)
    rb, gb, bb = hexrgb(b)
    return "#%02x%02x%02x" % (int(ra + (rb - ra) * t), int(ga + (gb - ga) * t),
                              int(ba + (bb - ba) * t))


def clip(x0, y0, x1, y1, box):
    """Liang-Barsky. The canvas has no clipping region, so the sunburst has to
    be cut to the panel by hand -- without this the rays cross the whole window
    and land on his face."""
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


def fit_text(c, cx, top, width, max_h, text, fill, font, tags=""):
    """Drop words until the block fits its band.

    A centred text item grows both ways as it wraps, so a long line walked
    straight into the mood word below it. Measuring is the only honest fix --
    the wrap point depends on the font, not on a character count.
    """
    words = " ".join(text.split()).split(" ")
    for n in range(len(words), 0, -1):
        body = " ".join(words[:n]) + ("" if n == len(words) else " ...")
        item = c.create_text(cx, top, anchor="n", width=width, text=body,
                             fill=fill, font=font, justify="center", tags=tags)
        x0, y0, x1, y1 = c.bbox(item)
        if y1 - y0 <= max_h:
            return item
        c.delete(item)
    return None


# The rings are drawn four times oversized and shrunk down, because Tk cannot
# anti-alias an arc: stacking `create_arc` calls leaves a staircase along the
# rim, and no bezel hides it. Off the canvas there is room for a real gradient
# too, which is what makes the band read as struck metal instead of a coloured
# stripe. Bands are built once; a value only costs a pie mask.
SS = 4
R_OUT, R_IN = 54, 40
BAND_W, BAND_H = R_OUT * 2 + 6, R_OUT + 6

# stop, colour -- dark rim, specular line a third of the way in, dark rim again
METAL = {
    "gold": [(0.00, "#3d3010"), (0.16, "#a5811f"), (0.34, "#fff4c8"),
             (0.55, "#c9a227"), (0.82, "#7d6019"), (1.00, "#302509")],
    "alarm": [(0.00, "#3f120c"), (0.16, "#993526"), (0.34, "#ffd8cd"),
              (0.55, "#c04630"), (0.82, "#7a2519"), (1.00, "#2c0d08")],
    "track": [(0.00, "#14100a"), (0.30, "#2a2211"), (0.60, "#241d0e"),
              (1.00, "#100d07")],
}

_bands = {}
_rings = {}


def _grad(stops, t):
    for i in range(len(stops) - 1):
        (s0, c0), (s1, c1) = stops[i], stops[i + 1]
        if s0 <= t <= s1:
            return lerp(c0, c1, (t - s0) / (s1 - s0) if s1 > s0 else 0.0)
    return stops[-1][1]


def _band(key):
    if key not in _bands:
        from PIL import ImageDraw
        big = Image.new("RGBA", (BAND_W * SS, BAND_H * SS), (0, 0, 0, 0))
        pen = ImageDraw.Draw(big)
        cx, cy = BAND_W * SS // 2, (R_OUT + 3) * SS
        steps = (R_OUT - R_IN) * SS
        for i in range(steps):
            r = R_OUT * SS - i
            colour = _grad(METAL[key], i / float(steps - 1))
            pen.arc([cx - r, cy - r, cx + r, cy + r], 180, 360,
                    fill=hexrgb(colour) + (255,), width=2)
        _bands[key] = big.resize((BAND_W, BAND_H), Image.LANCZOS)
    return _bands[key]


def ring(c, cx, cy, value, key, tags=""):
    """A half-circle gauge, struck like metal. Anchored so its centre lands on
    (cx, cy) -- the flat side of the band sits three pixels off the image foot."""
    from PIL import ImageChops, ImageDraw, ImageTk
    pct = None if value is None else max(0, min(100, int(round(value))))
    slot = (pct, key)
    if slot not in _rings:
        img = _band("track").copy()
        if pct:
            sweep = max(2.5, 180.0 * pct / 100.0)   # one percent still reads
            mask = Image.new("L", (BAND_W * SS, BAND_H * SS), 0)
            edge = (R_OUT + 3) * SS
            ImageDraw.Draw(mask).pieslice(
                [3 * SS, 3 * SS, edge + R_OUT * SS, edge + R_OUT * SS],
                180, 180 + sweep, fill=255)
            mask = mask.resize((BAND_W, BAND_H), Image.LANCZOS)
            band = _band(key)
            img.paste(band, (0, 0), ImageChops.multiply(band.split()[3], mask))
        _rings[slot] = ImageTk.PhotoImage(img)     # the dict keeps it alive
    c.create_image(cx, cy + 3, anchor="s", image=_rings[slot], tags=tags)


def tone(value):
    return (ALARM_HI, ALARM) if value is not None and value >= 80 else (GOLD_HI, GOLD)


def numeral_fit(c, r_in, sample="100%"):
    """Largest Times size whose corners still clear the ring's inner circle.

    The room inside a half ring is not its inner diameter -- it narrows as you
    go up, so the block's top corners are what actually bind. "100%" set to fit
    the width alone lands squarely on the gold band. Fitted once against the
    widest reading and then used for both dials, so they never disagree.
    """
    for size in range(24, 11, -1):
        probe = c.create_text(-900, -900, text=sample, anchor="center",
                              font=(TIMES, size, "bold"))
        x0, y0, x1, y1 = c.bbox(probe)
        c.delete(probe)
        half_w, half_h = (x1 - x0) / 2.0, (y1 - y0) / 2.0
        rise = half_h + 2                       # sit the block just off the base
        if math.hypot(half_w, rise + half_h) <= r_in - 3:
            return size, rise
    return 12, 12


# ------------------------------------------------------------------- ledger

def draw_ledger(c, x, y, w, h, d, tags=""):
    box = (x + 1, y + 1, x + w - 1, y + h - 1)
    c.create_rectangle(x, y, x + w, y + h, fill=GROUND, outline=GOLD_LO, tags=tags)

    # A sunburst, barely there. Deco's one indulgence -- clipped to the panel.
    cx0, cy0 = x + w / 2, y + h + 26
    for k in range(-9, 10):
        a = math.radians(90 + k * 6.5)
        seg = clip(cx0, cy0, cx0 + math.cos(a) * 340, cy0 - math.sin(a) * 340, box)
        if seg:
            c.create_line(*seg, fill=RAY, tags=tags)

    for yy, col in ((y + 8, GOLD_LO), (y + 11, GOLD),
                    (y + h - 11, GOLD), (y + h - 8, GOLD_LO)):
        c.create_line(x + 10, yy, x + w - 10, yy, fill=col, tags=tags)
    for sx, sgn in ((x + 10, 1), (x + w - 10, -1)):
        for step in range(3):
            run = 6 + step * 5
            c.create_line(sx, y + 15 + step * 4, sx + sgn * run, y + 15 + step * 4,
                          fill=GOLD_LO, tags=tags)
            c.create_line(sx, y + h - 16 - step * 4, sx + sgn * run,
                          y + h - 16 - step * 4, fill=GOLD_LO, tags=tags)

    c.create_text(x + w / 2, y + 27, anchor="center", text=spaced("THE LEDGER", "  "),
                  fill=GOLD, font=(TIMES, 10, "bold"), tags=tags)
    c.create_line(x + w / 2 - 54, y + 39, x + w / 2 + 54, y + 39, fill=GOLD_LO, tags=tags)

    size, rise = numeral_fit(c, R_IN)
    for frac, key, label, reset in ((0.29, "week", "VII DAYS", "week_reset"),
                                    (0.71, "five", "V HOURS", "five_reset")):
        v = d.get(key)
        hi, mid = tone(v)
        cx, cy = x + w * frac, y + 104
        ring(c, cx, cy, v, "alarm" if v is not None and v >= 80 else "gold", tags=tags)
        # "--" rather than the raw absence: a blank dial is a state, not a fault.
        c.create_text(cx, cy - rise, anchor="center",
                      text=f"{v}%" if v is not None else "--",
                      fill=hi if v is not None else GHOST,
                      font=(TIMES, size, "bold"), tags=tags)
        c.create_text(cx, cy + 13, anchor="center", text=spaced(label),
                      fill=DIM, font=(TIMES, 7), tags=tags)
        anew = d.get(reset)
        c.create_text(cx, cy + 26, anchor="center",
                      text=f"anew in {anew}" if anew else "no reckoning",
                      fill=GHOST, font=(TIMES, 8, "italic"), tags=tags)

    fit_text(c, x + w / 2, y + 148, w - 40, 46, d["speech"], IVORY,
             (TIMES, 12, "italic"), tags)
    c.create_text(x + w / 2, y + h - 20, anchor="center", text=spaced(d["mood"]),
                  fill=DIM, font=(TIMES, 9), tags=tags)


# ------------------------------------------------------------------- render

def paint(canvas, sprite, d):
    canvas.delete("all")
    canvas.create_rectangle(0, 0, W - 1, H - 1, fill=C_PANEL, outline=C_STONE)
    canvas.create_rectangle(2, 2, W - 3, H - 3, outline="#4b3c26")

    draw_ledger(canvas, LEDGER_X, PAD, LEDGER_INNER, SPRITE, d)

    canvas.create_rectangle(SPRITE_X - 1, PAD - 1, SPRITE_X + SPRITE, PAD + SPRITE,
                            fill="#171208", outline=C_STONE)
    canvas.create_image(SPRITE_X, PAD, anchor="nw", image=sprite)

    tray_y = PAD * 2 + SPRITE
    canvas.create_oval(PAD + 6, tray_y + 8, PAD + 36, tray_y + 38,
                       fill="#c0392b", outline="#8e2b20")
    canvas.create_rectangle(PAD + 46, tray_y + 10, W - PAD, tray_y + 36,
                            fill="#171208", outline=C_STONE)
    canvas.create_text(PAD + 54, tray_y + 23, anchor="w", text="speak to him...",
                       fill=C_DIM, font=("Consolas", 9))


def grab(root):
    root.update()
    time.sleep(0.18)
    bx, by = root.winfo_rootx(), root.winfo_rooty()
    return ImageGrab.grab(bbox=(bx, by, bx + W, by + H))


def motion_gif(root, canvas, sprite, name):
    """The brief asked for smooth text changes, which a still cannot show. The
    needle eases from one reading to the next and his words cross over rather
    than snapping."""
    frames, lo, hi = [], 12, 87
    for i in range(34):
        p = i / 33.0
        eased = p * p * (3 - 2 * p)
        d = dict(STATES[0][1])
        d["week"] = round(lo + (hi - lo) * eased)
        d["speech"] = ("Twelve parts spent, my lord." if eased < 0.45
                       else "A tithe remaineth. Then silence.")
        d["mood"] = "MERRY" if eased < 0.45 else "GRIM"
        paint(canvas, sprite, d)
        frames.append(grab(root).convert("P", palette=1))
    frames += [frames[-1]] * 14
    frames[0].save(OUT / f"{name}.gif", save_all=True, append_images=frames[1:],
                   duration=55, loop=0, optimize=True)
    print(f"  {name}.gif")


def main():
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry(f"{W}x{H}+80+80")
    root.configure(bg=C_EDGE)
    canvas = tk.Canvas(root, width=W, height=H, bg=C_EDGE, highlightthickness=0, bd=0)
    canvas.pack()
    sprite = tk.PhotoImage(file=str(FRAMES / "frame-06.png"))
    root.update()
    OUT.mkdir(parents=True, exist_ok=True)

    shots = []
    for name, over in STATES:
        d = dict(STATES[0][1])
        d.update(over)
        paint(canvas, sprite, d)
        img = grab(root)
        img.save(OUT / f"luxe-{name}.png")
        shots.append((name, img))
        print(f"  luxe-{name}.png")

    # Every state on one sheet, so nothing gets checked in isolation again.
    sheet = Image.new("RGB", (W, H * len(shots)), "#000000")
    for i, (_, img) in enumerate(shots):
        sheet.paste(img, (0, i * H))
    sheet.save(OUT / "luxe-states.png")
    print("  luxe-states.png")

    motion_gif(root, canvas, sprite, "luxe-motion")
    root.destroy()


if __name__ == "__main__":
    main()
