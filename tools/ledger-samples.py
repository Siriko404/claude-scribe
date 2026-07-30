"""Render candidate ledger designs at real size, for comparison.

Draws the actual panel through the actual tkinter canvas and screen-grabs it,
so what comes out is what the panel would look like -- not an approximation in
another drawing library with other font metrics.

    python tools/ledger-samples.py            all variants
    python tools/ledger-samples.py 2 4        just those

Output lands in assets/ledger-samples/.
"""

import sys
import time
import tkinter as tk
from pathlib import Path

from PIL import ImageGrab

HERE = Path(__file__).resolve().parent
FRAMES = HERE.parent / "assets" / "frames"
OUT = HERE.parent / "assets" / "ledger-samples"

SPRITE, LEDGER_W, PAD, TRAY_H = 220, 300, 10, 46
W = PAD * 2 + SPRITE + LEDGER_W
H = PAD * 2 + SPRITE + TRAY_H

# The panel's existing palette.
C_EDGE, C_PANEL, C_STONE = "#0f0c08", "#20190f", "#3a2f1f"
C_PARCH, C_DIM = "#d9c9a1", "#8d7c58"
C_GREEN, C_AMBER, C_RED = "#7fa05a", "#d8a13c", "#bf4b3a"

# Parchment palette: a page lit by candle, written in iron-gall ink.
P_PAGE, P_PAGE_2 = "#e6d8b5", "#dccaa2"
P_INK, P_INK_2 = "#332618", "#6b5738"
P_RULE, P_MARGIN = "#c3ae82", "#a8553f"
P_GILT, P_ALARM = "#9a7230", "#992f22"

SERIF = "Palatino Linotype"
MONO = "Consolas"

DATA = {
    "week": 63, "five": 12,
    "week_reset": "2d", "five_reset": "1h",
    "speech": "Sixty-three parts spent, my lord.",
    "mood": "SOBER",
}


def spaced(text):
    return " ".join(text)


def ink_for(value):
    return P_ALARM if value is not None and value >= 80 else P_INK


# --------------------------------------------------------------------- 1

def variant_current(c, x, y, w, h, d):
    """What it looks like today. The baseline to beat."""
    c.create_rectangle(x, y, x + w, y + h, fill="#2b2214", outline=C_STONE)
    c.create_text(x + 10, y + 12, anchor="w", text="THE SCRIBE'S LEDGER",
                  fill=C_PARCH, font=(MONO, 10, "bold"))
    c.create_line(x + 8, y + 24, x + w - 8, y + 24, fill=C_STONE)

    ty = y + 34
    for label, value, reset, drives in (("7 day", d["week"], d["week_reset"], True),
                                        ("5 hour", d["five"], d["five_reset"], False)):
        c.create_text(x + 10, ty + 6, anchor="w", text=("* " if drives else "  ") + label,
                      fill=C_PARCH if drives else C_DIM, font=(MONO, 9))
        c.create_rectangle(x + 74, ty, x + 178, ty + 13, fill="#171208", outline=C_STONE)
        col = C_RED if value >= 80 else C_AMBER if value >= 55 else C_GREEN
        c.create_rectangle(x + 75, ty + 1, x + 75 + int(102 * value / 100), ty + 12,
                           fill=col, outline="")
        c.create_text(x + w - 10, ty + 6, anchor="e", text=f"{value}%  {reset}",
                      fill=C_DIM, font=(MONO, 8))
        ty += 22

    ty += 6
    c.create_line(x + 8, ty, x + w - 8, ty, fill=C_STONE)
    c.create_text(x + 10, ty + 12, anchor="nw", width=w - 20, text=d["speech"],
                  fill=C_PARCH, font=(MONO, 9), justify="left")
    c.create_text(x + 10, y + h - 12, anchor="w", text=d["mood"],
                  fill=C_AMBER, font=(MONO, 12, "bold"))


# --------------------------------------------------------------------- 2

def page(c, x, y, w, h, ruled=True):
    """A parchment leaf: ruled lines and the red margin every account book has."""
    c.create_rectangle(x, y, x + w, y + h, fill=P_PAGE, outline=P_GILT)
    c.create_rectangle(x + 3, y + 3, x + w - 3, y + h - 3, fill="", outline=P_PAGE_2)
    if ruled:
        for i in range(1, 14):
            ly = y + 8 + i * 15
            if ly < y + h - 6:
                c.create_line(x + 8, ly, x + w - 8, ly, fill=P_RULE)
    c.create_line(x + 30, y + 4, x + 30, y + h - 4, fill=P_MARGIN)


def variant_parchment(c, x, y, w, h, d):
    """The page, read as a page. Ink bars, a heading, his words below the rule."""
    page(c, x, y, w, h)
    tx = x + 38

    c.create_text(tx, y + 16, anchor="w", text="The Ledger",
                  fill=P_INK, font=(SERIF, 13, "bold"))
    c.create_line(tx, y + 27, x + w - 10, y + 27, fill=P_INK_2)
    c.create_line(tx, y + 29, x + w - 10, y + 29, fill=P_INK_2)

    ty = y + 42
    for label, value, reset in (("Seven days", d["week"], d["week_reset"]),
                                ("Five hours", d["five"], d["five_reset"])):
        ink = ink_for(value)
        c.create_text(tx, ty + 7, anchor="w", text=label, fill=P_INK, font=(SERIF, 10))
        bx = tx + 84
        c.create_rectangle(bx, ty, bx + 96, ty + 14, fill="", outline=P_INK_2)
        c.create_rectangle(bx + 1, ty + 1, bx + 1 + int(94 * value / 100), ty + 13,
                           fill=ink, outline="")
        c.create_text(x + w - 10, ty + 7, anchor="e", text=f"{value}%",
                      fill=ink, font=(SERIF, 11, "bold"))
        c.create_text(x + w - 10, ty + 22, anchor="e", text=f"anew in {reset}",
                      fill=P_INK_2, font=(SERIF, 8))
        ty += 38

    c.create_line(tx, ty + 2, x + w - 10, ty + 2, fill=P_RULE)
    c.create_text(tx, ty + 12, anchor="nw", width=w - 48, text=d["speech"],
                  fill=P_INK, font=(SERIF, 11), justify="left")
    c.create_text(tx, y + h - 14, anchor="w", text=spaced(d["mood"]),
                  fill=P_GILT, font=(SERIF, 10, "bold"))


# --------------------------------------------------------------------- 3

def variant_tally(c, x, y, w, h, d):
    """No bars at all. A scribe counts in strokes, five to a gate."""
    page(c, x, y, w, h, ruled=False)
    tx = x + 38

    c.create_text(tx, y + 16, anchor="w", text="Tally of the Week",
                  fill=P_INK, font=(SERIF, 13, "bold"))
    c.create_line(tx, y + 28, x + w - 10, y + 28, fill=P_INK_2)

    ty = y + 44
    for label, value, reset in (("Seven days", d["week"], d["week_reset"]),
                                ("Five hours", d["five"], d["five_reset"])):
        ink = ink_for(value)
        c.create_text(tx, ty, anchor="w", text=label, fill=P_INK, font=(SERIF, 10))
        c.create_text(x + w - 10, ty, anchor="e", text=f"{value}%  ({reset})",
                      fill=ink, font=(SERIF, 10, "bold"))
        # One stroke per tenth, struck through in gates of five.
        marks = int(round(value / 10.0))
        sx, sy = tx + 2, ty + 14
        for i in range(10):
            gx = sx + (i // 5) * 12 + (i % 5) * 9
            col = ink if i < marks else P_RULE
            c.create_line(gx, sy, gx + 3, sy + 18, fill=col, width=2)
        for gate in range(2):
            if marks >= (gate + 1) * 5:
                gx = sx + gate * 12
                c.create_line(gx - 3, sy + 15, gx + 39, sy + 3, fill=ink, width=2)
        ty += 46

    c.create_line(tx, ty - 4, x + w - 10, ty - 4, fill=P_RULE)
    c.create_text(tx, ty + 4, anchor="nw", width=w - 48, text=d["speech"],
                  fill=P_INK, font=(SERIF, 11), justify="left")
    c.create_text(tx, y + h - 14, anchor="w", text=spaced(d["mood"]),
                  fill=P_GILT, font=(SERIF, 10, "bold"))


# --------------------------------------------------------------------- 4

def variant_coffers(c, x, y, w, h, d):
    """His own metaphor, drawn: coin spent is coin gone from the coffer."""
    page(c, x, y, w, h, ruled=False)
    tx = x + 38

    c.create_text(tx, y + 16, anchor="w", text="The Coffers",
                  fill=P_INK, font=(SERIF, 13, "bold"))
    c.create_line(tx, y + 28, x + w - 10, y + 28, fill=P_INK_2)

    ty = y + 46
    for label, value, reset in (("Week", d["week"], d["week_reset"]),
                                ("Day", d["five"], d["five_reset"])):
        ink = ink_for(value)
        left = 10 - int(round(value / 10.0))
        c.create_text(tx, ty, anchor="w", text=label, fill=P_INK, font=(SERIF, 10))
        c.create_text(x + w - 10, ty, anchor="e", text=f"{left} of 10 remain",
                      fill=ink, font=(SERIF, 9))
        cy = ty + 18
        for i in range(10):
            cx = tx + 4 + i * 23
            if i < left:
                c.create_oval(cx, cy, cx + 17, cy + 17, fill=P_GILT, outline=P_INK)
                c.create_oval(cx + 4, cy + 4, cx + 13, cy + 13, fill="", outline="#c9a24c")
            else:
                c.create_oval(cx, cy, cx + 17, cy + 17, fill="", outline=P_RULE, dash=(2, 2))
        ty += 50

    c.create_line(tx, ty - 6, x + w - 10, ty - 6, fill=P_RULE)
    c.create_text(tx, ty + 2, anchor="nw", width=w - 48, text=d["speech"],
                  fill=P_INK, font=(SERIF, 11), justify="left")
    c.create_text(tx, y + h - 14, anchor="w", text=spaced(d["mood"]),
                  fill=P_GILT, font=(SERIF, 10, "bold"))


# --------------------------------------------------------------------- 5

def variant_dark(c, x, y, w, h, d):
    """Stay dark, but fix what is actually wrong: no wasted title, gilt rules,
    the numbers big, and his words given the room they deserve."""
    c.create_rectangle(x, y, x + w, y + h, fill="#241c11", outline=P_GILT)
    c.create_rectangle(x + 3, y + 3, x + w - 3, y + h - 3, fill="", outline="#332818")
    tx = x + 12

    ty = y + 14
    for label, value, reset in (("SEVEN DAYS", d["week"], d["week_reset"]),
                                ("FIVE HOURS", d["five"], d["five_reset"])):
        col = C_RED if value >= 80 else C_AMBER if value >= 55 else C_GREEN
        c.create_text(tx, ty + 10, anchor="w", text=label, fill=C_DIM, font=(MONO, 8))
        c.create_text(x + w - 12, ty + 8, anchor="e", text=f"{value}%",
                      fill=col, font=(SERIF, 20, "bold"))
        c.create_text(x + w - 12, ty + 26, anchor="e", text=f"anew in {reset}",
                      fill=C_DIM, font=(MONO, 7))
        # A thin rule that fills rather than a boxed bar.
        c.create_line(tx, ty + 32, x + w - 12, ty + 32, fill="#332818", width=3)
        c.create_line(tx, ty + 32, tx + int((w - 24) * value / 100), ty + 32,
                      fill=col, width=3)
        ty += 48

    c.create_line(tx, ty + 2, x + w - 12, ty + 2, fill=P_GILT)
    c.create_text(tx, ty + 12, anchor="nw", width=w - 24, text=d["speech"],
                  fill=C_PARCH, font=(SERIF, 12), justify="left")
    c.create_text(tx, y + h - 14, anchor="w", text=spaced(d["mood"]),
                  fill=P_GILT, font=(MONO, 9, "bold"))


VARIANTS = [
    ("1-current", variant_current),
    ("2-parchment", variant_parchment),
    ("3-tally", variant_tally),
    ("4-coffers", variant_coffers),
    ("5-dark-refined", variant_dark),
]


def render(name, draw, root, canvas, sprite):
    canvas.delete("all")
    canvas.create_rectangle(0, 0, W - 1, H - 1, fill=C_PANEL, outline=C_STONE)
    canvas.create_rectangle(2, 2, W - 3, H - 3, outline="#4b3c26")
    canvas.create_rectangle(PAD - 1, PAD - 1, PAD + SPRITE, PAD + SPRITE,
                            fill="#171208", outline=C_STONE)
    canvas.create_image(PAD, PAD, anchor="nw", image=sprite)

    draw(canvas, PAD * 2 + SPRITE, PAD, LEDGER_W - PAD, SPRITE, DATA)

    # The tray is not what is being redesigned; it is here so the panel reads whole.
    tray_y = PAD * 2 + SPRITE
    canvas.create_oval(PAD + 6, tray_y + 8, PAD + 36, tray_y + 38,
                       fill="#c0392b", outline="#8e2b20")
    canvas.create_rectangle(PAD + 46, tray_y + 10, W - PAD, tray_y + 36,
                            fill="#171208", outline=C_STONE)
    canvas.create_text(PAD + 54, tray_y + 23, anchor="w", text="speak to him...",
                       fill=C_DIM, font=(MONO, 9))

    root.update()
    time.sleep(0.25)
    bx, by = root.winfo_rootx(), root.winfo_rooty()
    img = ImageGrab.grab(bbox=(bx, by, bx + W, by + H))
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / f"{name}.png")
    print(f"  {name}.png")


def main():
    wanted = sys.argv[1:]
    picks = [(n, f) for n, f in VARIANTS if not wanted or n[0] in wanted]

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry(f"{W}x{H}+80+80")
    root.configure(bg=C_EDGE)
    canvas = tk.Canvas(root, width=W, height=H, bg=C_EDGE, highlightthickness=0, bd=0)
    canvas.pack()
    sprite = tk.PhotoImage(file=str(FRAMES / "frame-06.png"))
    root.update()

    print(f"rendering {len(picks)} into {OUT}")
    for name, draw in picks:
        render(name, draw, root, canvas, sprite)
    root.destroy()


if __name__ == "__main__":
    main()
