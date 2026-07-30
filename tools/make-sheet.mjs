// Builds one contact sheet of all 44 frames for an external upscaler, and the
// matching slicer input. Frames sit in a tight 8x6 grid, row-major, on a flat
// magenta key (the same key the game itself uses for transparency), so the
// result can be cut back apart and the background removed deterministically.
//
// 8x6 rather than 11x4: a 4:3-ish sheet survives image models that quietly
// re-frame extreme aspect ratios. The last four cells stay empty.
//
// Usage: node tools/make-sheet.mjs [path-to-scribe.gm1] [cell-scale]

import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readGm1, writePng } from './gm1.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, '..', 'assets', 'upscale');
const GM1 = process.argv[2];
const SCALE = Number(process.argv[3] || 1);

if (!GM1) {
  console.error('usage: node tools/make-sheet.mjs <path to gm/scribe.gm1> [scale]');
  process.exit(1);
}

const COLS = 8;
const ROWS = 6;
const KEY = [255, 0, 255];

const gm1 = readGm1(GM1);
const cell = gm1.frames[0].width * SCALE;      // frames are square and uniform
const W = cell * COLS;
const H = cell * ROWS;
const sheet = Buffer.alloc(W * H * 4);

for (let i = 0; i < W * H; i++) {
  sheet[i * 4] = KEY[0];
  sheet[i * 4 + 1] = KEY[1];
  sheet[i * 4 + 2] = KEY[2];
  sheet[i * 4 + 3] = 255;
}

gm1.frames.forEach((f, n) => {
  if (!f.image) return;
  const ox = (n % COLS) * cell;
  const oy = Math.floor(n / COLS) * cell;
  for (let y = 0; y < cell; y++) {
    for (let x = 0; x < cell; x++) {
      const s = (Math.floor(x / SCALE) + Math.floor(y / SCALE) * f.width) * 4;
      if (!f.image.px[s + 3]) continue;          // leave the key showing
      const d = (ox + x + (oy + y) * W) * 4;
      sheet[d] = f.image.px[s];
      sheet[d + 1] = f.image.px[s + 1];
      sheet[d + 2] = f.image.px[s + 2];
    }
  }
});

fs.mkdirSync(OUT, { recursive: true });
const file = path.join(OUT, SCALE > 1 ? `scribe-sheet-${SCALE}x.png` : 'scribe-sheet.png');
writePng(file, W, H, sheet);

fs.writeFileSync(path.join(OUT, 'LAYOUT.txt'),
  `grid    ${COLS} x ${ROWS}, row-major\n` +
  `cell    ${cell}px\n` +
  `sheet   ${W} x ${H}\n` +
  `frames  0-${gm1.count - 1} in order; cells ${gm1.count}-${COLS * ROWS - 1} are empty\n` +
  `key     magenta ${KEY.join(',')} = transparent\n` +
  `rows    0-10 mood ramp | 11-21 speaking | 22-32 positive | 33-43 negative\n` +
  `slice   powershell -File tools/import-sheet.ps1 -Sheet <upscaled.png>\n`);

console.log(`${file}\n${W} x ${H}, ${COLS}x${ROWS} grid, ${cell}px cells, ${gm1.count} frames`);
