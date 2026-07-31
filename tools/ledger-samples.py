"""Render the ledger at real size, in every state it can be in.

This drives the *actual panel* -- it builds a ScribePanel, sets its data by hand
and screen-grabs it. The first version of this tool kept its own copy of the
drawing code, which meant a redesign had to be written twice and the samples
could quietly stop being the truth. Now there is one ledger, and this is a
camera pointed at it.

    python tools/ledger-samples.py

One data point proves nothing about a gauge, so every run also renders the
states that break things: empty, full, near the limit, no ledger at all, and a
speech long enough to run into what sits below it. Those are what caught the
defects in the first draft.

It takes no lock and does not disturb a running panel. Output lands in
assets/ledger-samples/.
"""

import os
import sys
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageGrab

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "assets" / "ledger-samples"

# Somewhere out of the way, and never the remembered position: the live panel
# is usually sitting there.
os.environ["SCRIBE_POS"] = "80,80"
sys.path.insert(0, str(HERE.parent))

from scribe_window import TRAY_H, ScribePanel   # noqa: E402

PAD, SPRITE = ScribePanel.PAD, ScribePanel.SPRITE
W = PAD * 2 + SPRITE + ScribePanel.LEDGER_W
H = PAD * 2 + SPRITE + TRAY_H

# week and five are percent *spent*, resets are minutes away, as the panel holds
# them. mood follows from week, so it is not set here.
STATES = [
    ("usual", dict(week=27, five=12, week_reset=3100, five_reset=64,
                   speech="Sixty-three parts spent, my lord.")),
    ("empty", dict(week=0, five=0, week_reset=10080, five_reset=300,
                   speech="Naught spent, my lord.")),
    ("brim", dict(week=1, five=3, week_reset=9900, five_reset=240,
                  speech="Scarce a drop, sire.")),
    ("alarm", dict(week=87, five=91, week_reset=540, five_reset=20,
                   speech="A tithe remaineth. Then silence.")),
    ("full", dict(week=100, five=100, week_reset=2900, five_reset=61,
                  speech="The coffers are bare, sire.")),
    ("noledger", dict(week=None, five=None, week_reset=None, five_reset=None,
                      speech="I have no ledger to read, sire.", fresh=False)),
    # The worst case is both at once: the widest numeral a column can hold and
    # a speech tall enough to fill its band. Set apart they never meet, and the
    # gutter between them is only five pixels wide.
    ("longtongue", dict(week=12, five=12, week_reset=179, five_reset=179,
                        speech="Thou hast spent threescore and three parts of thy "
                               "seven-day treasury, and the hour groweth late "
                               "besides, my most improvident lord.")),
]


def paint(panel, over):
    """Set the panel's state by hand and redraw the ledger alone.

    The roll and the pelting are cleared each time so a stray animation left
    over from construction cannot creep into the mood word.
    """
    panel.data = dict(week=None, five=None, ctx=None, week_reset=None,
                      five_reset=None, model="haiku", cwd="scribe", fresh=True)
    panel.data.update({k: v for k, v in over.items() if k != "speech"})
    panel.speech = over["speech"]
    panel.roll = None
    panel.pelted_at = 0.0
    panel.draw_ledger()
    panel.root.update()
    time.sleep(0.18)


def grab(root):
    bx, by = root.winfo_rootx(), root.winfo_rooty()
    return ImageGrab.grab(bbox=(bx, by, bx + W, by + H))


def motion_gif(panel, name):
    """The brief asked for smooth text changes, which a still cannot show. The
    coins go out one at a time and his words cross over rather than snapping."""
    frames = []
    for i in range(34):
        p = i / 33.0
        eased = p * p * (3 - 2 * p)
        d = dict(STATES[0][1])
        d["week"] = round(12 + (87 - 12) * eased)
        d["speech"] = ("Twelve parts spent, my lord." if eased < 0.45
                       else "A tithe remaineth. Then silence.")
        paint(panel, d)
        frames.append(grab(panel.root).convert("P", palette=1))
    frames += [frames[-1]] * 14
    frames[0].save(OUT / f"{name}.gif", save_all=True, append_images=frames[1:],
                   duration=55, loop=0, optimize=True)
    print(f"  {name}.gif")


def main():
    root = tk.Tk()
    root.title("The Scribe")
    # once=True: the panel ticks a single time and never reschedules, so nothing
    # it reads from disk can overwrite the state set here.
    panel = ScribePanel(root, once=True)
    root.update()
    OUT.mkdir(parents=True, exist_ok=True)

    shots = []
    for name, over in STATES:
        paint(panel, over)
        img = grab(root)
        img.save(OUT / f"luxe-{name}.png")
        shots.append(img)
        print(f"  luxe-{name}.png")

    # Every state on one sheet, so nothing gets checked in isolation again.
    sheet = Image.new("RGB", (W, H * len(shots)), "#000000")
    for i, img in enumerate(shots):
        sheet.paste(img, (0, i * H))
    sheet.save(OUT / "luxe-states.png")
    print("  luxe-states.png")

    motion_gif(panel, "luxe-motion")
    root.destroy()


if __name__ == "__main__":
    main()
