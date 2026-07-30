// Exports every frame of the local scribe.gm1 as a PNG the window loads.
//
// scribe.gm1 holds four 11-frame sequences. The boundaries are not a guess:
// mean frame-to-frame difference inside a sequence is 0.4-1.8, and it spikes to
// 6.3 / 6.3 / 7.0 exactly at frames 11, 22 and 33.
//
//   00-10  mood ramp, broad grin -> stern frown (monotonic, no internal jumps)
//   11-21  mouth opening, speaking
//   22-32  positive reaction, calm -> beaming
//   33-43  negative reaction, calm -> grimace
//
// Usage: node tools/export-frames.mjs [path-to-scribe.gm1] [scale]

import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readGm1, writePng } from './gm1.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, '..', 'assets', 'frames');
const GM1 = process.argv[2] || 'C:/Non Windows Data/SCE/gm/scribe.gm1';
const SCALE = Number(process.argv[3] || 2);

function upscale(img, z) {
  const W = img.width * z, H = img.height * z;
  const out = Buffer.alloc(W * H * 4);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const s = (Math.floor(x / z) + Math.floor(y / z) * img.width) * 4;
      const d = (x + y * W) * 4;
      out[d] = img.px[s]; out[d + 1] = img.px[s + 1];
      out[d + 2] = img.px[s + 2]; out[d + 3] = img.px[s + 3];
    }
  }
  return { width: W, height: H, px: out };
}

const gm1 = readGm1(GM1);
if (gm1.count !== 44) {
  console.error(`expected 44 frames in ${GM1}, found ${gm1.count}`);
  process.exit(1);
}

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

for (let i = 0; i < gm1.count; i++) {
  const src = gm1.frames[i]?.image;
  if (!src) {
    console.error(`frame ${i} failed to decode`);
    process.exit(1);
  }
  const up = upscale(src, SCALE);
  writePng(path.join(OUT, `frame-${String(i).padStart(2, '0')}.png`), up.width, up.height, up.px);
}
console.log(`wrote ${gm1.count} frames at ${SCALE}x (${gm1.frames[0].width * SCALE}px) to assets/frames`);
