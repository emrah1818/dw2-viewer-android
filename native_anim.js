/**
 * Originalgetreue Wiedergabe der DW2-Modellanimationen (ohne three.js, in Node testbar).
 *
 * Nachbau aus der Decompilation Wyrelade/DW2-PC (CC0):
 *  - BonePlayer      = src/main/anim.c Anim_SetModelAnim / Anim_StepModelAnim
 *  - TexAnimator     = src/main/anim.c Gfx_AnimateModelTex (+ Gfx_AnimAllowsBlink),
 *                      Strukturen include/main/156C.h GfxTexAnimPart / GfxModelTexAnim
 *  - decode()        = 4-Bit-Textur mit CLUT aus den Zeilen 224–255 der Modelltextur
 * Zeitbasis: VBlanks (60 Hz NTSC). Eine Animationszeile gilt 2 VBlanks (30 Bilder/s).
 */

export const SLOTS = 'ABCDEFGHIJK';
export const NO_BLINK = new Set([0x64, 0x0A, 0x14, 0x15, 0x16]);
export const MAX_DELTA = 6;   // Sys_State.frameDelta wird im Spiel auf 6 begrenzt

export function fromBase64(text) {
  if (!text) return new Uint8Array(0);
  if (typeof atob === 'function') {
    const bin = atob(text); const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  return new Uint8Array(Buffer.from(text, 'base64'));
}

// ------------------------------------------------------------------ Knochen
/** Eine A–K-Animationsdatei, gelesen wie Anim_StepModelAnim (Clip-Tabelle bis 1). */
export class AnimFile {
  constructor(bytes, bones) {
    this.bytes = bytes; this.bones = bones;
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    this.dv = dv;
    this.poses = [];
    for (let i = 0; i < bones; i++) this.poses.push(dv.getUint32(4 + 4 * i, true));
    this.table = [];
    let pos = 4 + 4 * bones;
    while (pos + 4 <= bytes.length && this.table.length <= 64) {
      const v = dv.getUint32(pos, true); pos += 4;
      if (v === 1) break;
      this.table.push(v);
    }
  }
  /** Rohschlüssel: 9 Matrixwerte (zeilenweise, /4096) + 3 Translationen. */
  key(bone, k) {
    const at = this.poses[bone] + k * 24;
    const out = new Array(12);
    if (at < 0 || at + 24 > this.bytes.length) { out.fill(0); out[0] = out[4] = out[8] = 4096; return out; }
    for (let i = 0; i < 12; i++) out[i] = this.dv.getInt16(at + 2 * i, true);
    return out;
  }
}

/** Zustandsautomat wie ActorModel.animPos/animTimer/animDone. */
export class BonePlayer {
  constructor(bones) {
    this.bones = bones;
    this.keys = new Uint8Array(bones);
    this.file = null; this.clip = 0; this.pos = 0; this.timer = 1; this.done = 0;
    this.rowStart = 0; this.finished = false; this.loops = 0;
  }
  /** Clip-Beginn = animTable[index]; Anzeige der ersten Zeile sofort (Spiel: nach 1 VBlank). */
  set(file, offset) {
    this.file = file; this.clip = offset; this.pos = 0; this.timer = 1; this.done = 0;
    this.finished = false; this.loops = 0;
    this.tick(1);
  }
  restart() { if (this.file) this.set(this.file, this.clip); }
  _byte(i) { return this.file.bytes[this.clip + i]; }
  /** n VBlanks weiter. Gibt true zurück, wenn sich die Schlüssel geändert haben. */
  tick(n) {
    if (!this.file) return false;
    let changed = false;
    this.timer += n;
    while (this.timer >= 2) {
      this.timer -= 2;
      const start = this.pos;
      if (this.clip + start + this.bones > this.file.bytes.length) { this.finished = true; break; }
      for (let i = 0; i < this.bones; i++) {
        const k = this._byte(this.pos++);
        if (this.keys[i] !== k) { this.keys[i] = k; changed = true; }
      }
      this.rowStart = start;
      const q = this._byte(this.pos);
      if (q & 0x80) {
        if (q === 0xFF) { this.done = -1; this.pos = start; this.finished = true; break; }
        if (q === 0xFE) { this.pos = this._byte(this.pos + 1) | (this._byte(this.pos + 2) << 8); this.done = -1; this.loops++; }
      }
    }
    return changed;
  }
  /** Schlüssel der als Nächstes gelesenen Zeile (für optionale Glättung). */
  peekNext() {
    if (!this.file || this.finished) return this.keys;
    const out = new Uint8Array(this.bones);
    if (this.clip + this.pos + this.bones > this.file.bytes.length) return this.keys;
    for (let i = 0; i < this.bones; i++) out[i] = this._byte(this.pos + i);
    return out;
  }
  get frame() { return Math.floor(this.rowStart / this.bones); }
}

/** Lokale Matrix im glTF-Raum: D·M·D, D·t mit D = diag(1,-1,-1). Ergebnis zeilenweise 4×4. */
export function glMatrix(raw, out = new Array(16)) {
  const s = 1 / 4096;
  const d = [1, -1, -1];
  for (let r = 0; r < 3; r++) {
    for (let c = 0; c < 3; c++) out[r * 4 + c] = raw[r * 3 + c] * s * d[r] * d[c];
    out[r * 4 + 3] = raw[9 + r] * d[r];
  }
  out[12] = out[13] = out[14] = 0; out[15] = 1;
  return out;
}

// ------------------------------------------------------------------ Texturen
export const VRAM_W = 32, VRAM_H = 256;   // 128×256 4-Bit-Pixel = 32×256 16-Bit-Wörter

/** texAnimParts-Block wie Gfx_AnimateModelTex. */
export function parseTexAnim(region) {
  const out = { eyes: [null, null], hasEye0: false, cycles: [], extended: [], warnings: [] };
  const at = i => (i * 10 + 10 <= region.length ? region.subarray(i * 10, i * 10 + 10) : null);
  for (let i = 0; i < 2; i++) {
    const r = at(i);
    if (!r) { out.warnings.push('Augenblock unvollständig'); return out; }
    if (i === 0) out.hasEye0 = r[0] !== 0xFF;
    if (r[0] !== 0xFF) out.eyes[i] = { dx: r[0], dy: r[1], w: r[2], h: r[3], uv: [...r.subarray(4, 10)] };
  }
  let i = 2, marker = -1;
  for (;;) {
    const o = i * 10;
    if (o >= region.length) break;
    if (region[o] === 0xFF || region[o] === 0xFE) { marker = region[o]; break; }
    if (i >= 10) break;
    const r = at(i); if (!r) break;
    out.cycles.push({ dx: r[0], dy: r[1], w: r[2], h: r[3], uv: [...r.subarray(4, 10)] });
    i++;
  }
  if (marker === 0xFE) {
    let q = i * 10 + 1;
    for (let c = 0; c < 10; c++) {
      if (q >= region.length || region[q] === 0xFF) break;
      if (q + 42 > region.length) break;
      const r = region.subarray(q, q + 42);
      out.extended.push({ dx: r[0], dy: r[1], w: r[2], h: r[3], dx2: r[4], dy2: r[5], w2: r[6], h2: r[7],
        period: r[8], timer: r[9], uv: [...r.subarray(10, 42)] });
      q += 42;
    }
  }
  return out;
}

export class TexAnimator {
  /** region: texAnimParts-Bytes, vram: 0x4000 Bytes Texturdaten (wird kopiert). */
  constructor(region, vramBytes, random = Math.random) {
    this.anim = parseTexAnim(region);
    this.vram = new Uint16Array(VRAM_W * VRAM_H);
    const dv = new DataView(vramBytes.buffer, vramBytes.byteOffset, vramBytes.byteLength);
    for (let i = 0; i < this.vram.length && 2 * i + 1 < vramBytes.length; i++) this.vram[i] = dv.getUint16(2 * i, true);
    this.original = this.vram.slice();
    this.blinkTimer = 0; this.texTimer = 0; this.random = random;
    this.outside = 0;
    this.enabled = { blink: true, cycles: true, extended: true };
  }
  get active() { return !!(this.anim.eyes[0] || this.anim.eyes[1] || this.anim.cycles.length || this.anim.extended.length); }
  reset() {
    this.vram.set(this.original); this.blinkTimer = 0; this.texTimer = 0;
    this.anim.extended.forEach(e => { e.timer = e.timer0 ?? e.timer; });
  }
  /** Ein Spiel-Frame mit delta VBlanks. Rückgabe: Liste geänderter Pixelrechtecke [x0,y0,x1,y1]. */
  frame(delta, animId) {
    const a = this.anim; const moves = [];
    let k = 0;
    if (a.hasEye0) {
      if (!this.enabled.blink) { k = 0; this.blinkTimer = 0; }
      else if (!NO_BLINK.has(animId)) {
        switch (this.blinkTimer >> 1) {
          case 0: this.blinkTimer = (Math.floor(this.random() * 128) & 0x7F) + 0x3C; k = 0; break;
          case 1: case 2: case 5: case 6: k = 2; break;
          case 3: case 4: k = 4; break;
          default: k = 0;
        }
        this.blinkTimer -= delta; if (this.blinkTimer < 0) this.blinkTimer = 0;
      } else { k = 4; this.blinkTimer = 0; }
    }
    this.texTimer += delta;
    while (this.texTimer >= 0x18) this.texTimer -= 0x18;
    const j = Math.floor(this.texTimer / 8) * 2;
    for (let i = 0; i < 2; i++) {
      const e = a.eyes[i]; if (!e) continue;
      moves.push([e.uv[k], e.uv[k + 1], e.w, e.h, e.dx, e.dy]);
    }
    if (this.enabled.cycles) for (const e of a.cycles) moves.push([e.uv[j], e.uv[j + 1], e.w, e.h, e.dx, e.dy]);
    for (const q of a.extended) {
      if (q.timer0 === undefined) q.timer0 = q.timer;
      if (!q.period) continue;                       // Periode 0 würde das Spiel aufhängen
      q.timer = (q.timer + (delta === 1 ? 1 : 2)) & 0xFF;
      while (q.timer >= q.period) q.timer -= q.period;
      const m = (q.timer >> 1) * 4;
      if (!this.enabled.extended || m + 3 >= q.uv.length) continue;
      moves.push([q.uv[m], q.uv[m + 1], q.w, q.h, q.dx, q.dy]);
      moves.push([q.uv[m + 2], q.uv[m + 3], q.w2, q.h2, q.dx2, q.dy2]);
    }
    // AddPrim hängt vorn an die Ordnungstabelle an: Ausführung in umgekehrter Reihenfolge.
    const dirty = [];
    for (let i = moves.length - 1; i >= 0; i--) {
      const r = this.move(...moves[i]);
      if (r) dirty.push(r);
    }
    return dirty;
  }
  /** DR_MOVE innerhalb der Modelltextur (Wortkoordinaten). */
  move(sx, sy, w, h, dx, dy) {
    if (!w || !h) return null;
    if (sx + w > VRAM_W || sy + h > VRAM_H || dx + w > VRAM_W || dy + h > VRAM_H) { this.outside++; }
    const W = Math.min(w, VRAM_W - sx, VRAM_W - dx), H = Math.min(h, VRAM_H - sy, VRAM_H - dy);
    if (W <= 0 || H <= 0) return null;
    const tmp = new Uint16Array(W * H);
    for (let y = 0; y < H; y++) tmp.set(this.vram.subarray((sy + y) * VRAM_W + sx, (sy + y) * VRAM_W + sx + W), y * W);
    let changed = false;
    for (let y = 0; y < H; y++) {
      const row = (dy + y) * VRAM_W + dx;
      for (let x = 0; x < W; x++) {
        const v = tmp[y * W + x];
        if (this.vram[row + x] !== v) { this.vram[row + x] = v; changed = true; }
      }
    }
    return changed ? [dx * 4, dy, (dx + W) * 4, dy + H] : null;
  }
}

/** Material-Dekodierung exakt wie native_gltf.texture_images (Alpha 0 / 128 halbtransparent / 255). */
export function decodeRect(vram, clut, stp, rgba, x0 = 0, y0 = 0, x1 = 128, y1 = 256) {
  const px = (clut & 63) * 16, py = (clut >> 6) & 1023;
  if ((px !== 0 && px !== 16) || py < 224 || py > 255) return false;
  const pal = py * VRAM_W + px;
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const w = vram[y * VRAM_W + (x >> 2)];
      const c = vram[pal + ((w >> ((x & 3) * 4)) & 15)];
      const r = (c & 31) * 8, g = ((c >> 5) & 31) * 8, b = ((c >> 10) & 31) * 8;
      const flag = (c & 0x8000) !== 0;
      const o = (y * 128 + x) * 4;
      rgba[o] = r; rgba[o + 1] = g; rgba[o + 2] = b;
      rgba[o + 3] = flag && stp ? 128 : ((r | g | b) === 0 && !flag ? 0 : 255);   // 0x8000 auf halbtransparenter Fläche: gemischt
    }
  }
  return true;
}

/** Zählt Dreiecke, deren Umlaufsinn zur Lichtnormale passt (Vorderseite = Normale zeigt nach außen). */
export function faceOrientation(meshes) {
  let agree = 0, disagree = 0;
  for (const o of meshes) {
    const pos = o.geometry?.attributes?.position, nor = o.geometry?.attributes?.normal;
    if (!pos || !nor || o.geometry.index) continue;
    const p = pos.array, q = nor.array;
    for (let i = 0; i + 8 < p.length; i += 9) {
      const ax = p[i + 3] - p[i], ay = p[i + 4] - p[i + 1], az = p[i + 5] - p[i + 2];
      const bx = p[i + 6] - p[i], by = p[i + 7] - p[i + 1], bz = p[i + 8] - p[i + 2];
      const cx = ay * bz - az * by, cy = az * bx - ax * bz, cz = ax * by - ay * bx;
      const d = cx * (q[i] + q[i + 3] + q[i + 6]) + cy * (q[i + 1] + q[i + 4] + q[i + 7]) + cz * (q[i + 2] + q[i + 5] + q[i + 8]);
      if (d > 0) agree++; else if (d < 0) disagree++;
    }
  }
  return { agree, disagree };
}
