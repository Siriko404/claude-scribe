"""Super-resolves the sprite frames locally with EDSR x4.

Why not a chat model: a generative model rebuilds an image rather than
resampling it. Asked for 5x it returned 0.33x of the input, with the right half
of the grid rendered at a different scale — and the 44 near-identical faces are
exactly what it tends to homogenise. EDSR is a deterministic convolutional
network: same input, same output, no invented content, no drifting identity.

Transparency needs care. The network only sees RGB, so a transparent background
would bleed black into the sprite outline. Instead the background is flooded
with the sprite's own mean colour before upscaling, and the alpha channel is
enlarged separately, then re-applied.

Usage:
  python tools/upscale-frames.py --model path/to/EDSR_x4.pb [--scale 4] [--dry-run]
"""

import argparse
import shutil
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
FRAMES = HERE.parent / "assets" / "frames"
BACKUP = HERE.parent / "assets" / "frames-original"


def upscale(path, sr, scale):
    src = Image.open(path).convert("RGBA")
    rgba = np.asarray(src)
    rgb, alpha = rgba[:, :, :3], rgba[:, :, 3]

    # Flood the transparent area with the sprite's own average colour so the
    # network never sees a hard edge against black.
    opaque = alpha > 0
    if opaque.any():
        fill = rgb[opaque].mean(axis=0).astype(np.uint8)
        flooded = np.where(opaque[:, :, None], rgb, fill)
    else:
        flooded = rgb

    big_rgb = sr.upsample(cv2.cvtColor(flooded.astype(np.uint8), cv2.COLOR_RGB2BGR))
    big_rgb = cv2.cvtColor(big_rgb, cv2.COLOR_BGR2RGB)

    # Alpha is a hard-edged mask; enlarging it with Lanczos keeps the silhouette
    # smooth without the network inventing translucency.
    big_alpha = np.asarray(
        Image.fromarray(alpha).resize(
            (src.width * scale, src.height * scale), Image.LANCZOS)
    )

    out = np.dstack([big_rgb[:big_alpha.shape[0], :big_alpha.shape[1]], big_alpha])
    return Image.fromarray(out, "RGBA")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sr = cv2.dnn_superres.DnnSuperResImpl_create()
    sr.readModel(args.model)
    sr.setModel("edsr", args.scale)

    frames = sorted(FRAMES.glob("frame-*.png"))
    if not frames:
        raise SystemExit(f"no frames in {FRAMES}")

    if not args.dry_run and not BACKUP.exists():
        shutil.copytree(FRAMES, BACKUP)
        print(f"originals kept in {BACKUP.name}")

    for i, path in enumerate(frames):
        big = upscale(path, sr, args.scale)
        if not args.dry_run:
            big.save(path)
        if i % 11 == 0 or i == len(frames) - 1:
            print(f"  {path.name}  ->  {big.width}x{big.height}")

    print(f"{'would upscale' if args.dry_run else 'upscaled'} {len(frames)} frames "
          f"{args.scale}x with EDSR")


if __name__ == "__main__":
    main()
