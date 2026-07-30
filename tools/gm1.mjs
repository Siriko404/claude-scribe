// Minimal GM1/TGX reader + PNG writer. No dependencies.
//
// Format facts from the Stronghold Wiki (GM1 / TGX file format pages) and the
// sourcehold project's Gm1-file notes:
//   header      88 bytes; u32 @12 = image count, u32 @20 = data type, u32 @80 = data size
//   palettes    10 x 256 x u16 (RGB555) immediately after the header
//   then        count x u32 offsets, count x u32 sizes, count x 16-byte image headers
//   image data  starts after the header table; each offset is relative to that point
//   TGX tokens  high 3 bits = kind (0 stream, 4 repeat, 2 transparent, 4+2.. see below),
//               low 5 bits = length - 1
//
// Data types: 1 interface, 2 animation (palette-indexed), 3 tiles, 4 font,
//             5 uncompressed, 6 compressed, 7 mixed.

import * as fs from 'node:fs';
import * as zlib from 'node:zlib';

const T_STREAM = 0x00;
const T_TRANSPARENT = 0x20;
const T_REPEAT = 0x40;
const T_NEWLINE = 0x80;

export function rgb555(n) {
  return {
    r: (n & 0x7c00) >> 7,
    g: (n & 0x03e0) >> 2,
    b: (n & 0x001f) << 3,
  };
}

// Decodes a TGX stream into RGBA. Untouched pixels stay fully transparent.
export function decodeTgx(buf, width, height, palette = null) {
  const px = Buffer.alloc(width * height * 4);
  let off = 0, x = 0, y = 0;

  const put = c => {
    if (x >= 0 && x < width && y >= 0 && y < height) {
      const i = (x + y * width) * 4;
      px[i] = c.r; px[i + 1] = c.g; px[i + 2] = c.b; px[i + 3] = 255;
    }
    x++;
  };
  const readColor = () => {
    if (palette) {
      const c = palette[buf[off]]; off += 1; return c;
    }
    const c = rgb555(buf.readUInt16LE(off)); off += 2; return c;
  };

  while (off < buf.length) {
    const token = buf[off++];
    const kind = token & 0xe0;
    const len = (token & 0x1f) + 1;

    if (kind === T_STREAM) {
      for (let i = 0; i < len && off < buf.length; i++) put(readColor());
    } else if (kind === T_NEWLINE) {
      y++; x = 0;
    } else if (kind === T_REPEAT) {
      if (off >= buf.length) break;
      const c = readColor();
      for (let i = 0; i < len; i++) put(c);
    } else if (kind === T_TRANSPARENT) {
      x += len;
    } else {
      break; // unknown token: stop rather than emit garbage
    }
    if (y >= height) break;
  }
  return { width, height, px };
}

export function readGm1(file) {
  const d = fs.readFileSync(file);
  const count = d.readUInt32LE(12);
  const type = d.readUInt32LE(20);

  const pOff = 88;
  const offList = pOff + 5120;
  const sizeList = offList + count * 4;
  const hdrList = sizeList + count * 4;
  const dataStart = hdrList + count * 16;

  const palettes = [];
  for (let p = 0; p < 10; p++) {
    const pal = [];
    for (let i = 0; i < 256; i++) pal.push(rgb555(d.readUInt16LE(pOff + p * 512 + i * 2)));
    palettes.push(pal);
  }

  const frames = [];
  for (let i = 0; i < count; i++) {
    const h = hdrList + i * 16;
    const meta = {
      index: i,
      width: d.readUInt16LE(h),
      height: d.readUInt16LE(h + 2),
      xOffset: d.readUInt16LE(h + 4),
      yOffset: d.readUInt16LE(h + 6),
      part: d.readUInt8(h + 8),
      subParts: d.readUInt8(h + 9),
      colorIndex: d.readUInt8(h + 15),
      offset: d.readUInt32LE(offList + i * 4),
      size: d.readUInt32LE(sizeList + i * 4),
    };
    let image = null;
    if (meta.width > 0 && meta.height > 0 && meta.width < 4096 && meta.height < 4096) {
      const slice = d.subarray(dataStart + meta.offset, dataStart + meta.offset + meta.size);
      const pal = type === 2 ? palettes[meta.colorIndex] ?? palettes[0] : null;
      try { image = decodeTgx(slice, meta.width, meta.height, pal); } catch { image = null; }
    }
    frames.push({ ...meta, image });
  }
  return { type, count, palettes, frames };
}

// ------------------------------------------------------------------ PNG out

function crc32(buf) {
  let c, crc = 0xffffffff;
  for (const byte of buf) {
    c = (crc ^ byte) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crc = c ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'latin1'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

export function writePng(file, width, height, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;  // bit depth
  ihdr[9] = 6;  // RGBA
  const raw = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (width * 4 + 1)] = 0; // filter: none
    rgba.copy(raw, y * (width * 4 + 1) + 1, y * width * 4, (y + 1) * width * 4);
  }
  fs.writeFileSync(file, Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]));
}

// Lays frames out in a grid on a checkerboard so transparency is visible.
export function contactSheet(file, frames, cols = 8, pad = 4) {
  const drawn = frames.filter(f => f.image);
  const cw = Math.max(...drawn.map(f => f.width)) + pad;
  const ch = Math.max(...drawn.map(f => f.height)) + pad;
  const rows = Math.ceil(drawn.length / cols);
  const W = cw * cols, H = ch * rows;
  const out = Buffer.alloc(W * H * 4);

  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const dark = (Math.floor(x / 8) + Math.floor(y / 8)) % 2 === 0;
      const v = dark ? 40 : 60;
      const i = (x + y * W) * 4;
      out[i] = v; out[i + 1] = v; out[i + 2] = v; out[i + 3] = 255;
    }
  }
  drawn.forEach((f, n) => {
    const ox = (n % cols) * cw + pad / 2;
    const oy = Math.floor(n / cols) * ch + pad / 2;
    for (let y = 0; y < f.height; y++) {
      for (let x = 0; x < f.width; x++) {
        const s = (x + y * f.width) * 4;
        if (!f.image.px[s + 3]) continue;
        const dI = (ox + x + (oy + y) * W) * 4;
        out[dI] = f.image.px[s]; out[dI + 1] = f.image.px[s + 1];
        out[dI + 2] = f.image.px[s + 2]; out[dI + 3] = 255;
      }
    }
  });
  writePng(file, W, H, out);
  return { cols, cellW: cw, cellH: ch, count: drawn.length };
}
