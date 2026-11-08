// JS-Gegenstück zu tests/test_native_anim.py: prüft Player, Texturanimation und Dekodierung
// mit der vom Python-Konverter erzeugten Nutzlast. Aufruf (nach dem Python-Test):
//   node tests/test_native_anim.mjs
import { readFileSync } from 'node:fs';
import { AnimFile, BonePlayer, TexAnimator, decodeRect, fromBase64, glMatrix, faceOrientation, VRAM_W } from '../app/src/main/assets/www/native_anim.js';

const fx = JSON.parse(readFileSync(new URL('./_fixture_payload.json', import.meta.url)));
const p = fx.payload;
let fails = 0;
const check = (c, label) => { console.log((c ? 'OK   ' : 'FEHL ') + label); if (!c) fails++; };
const eq = (a, b) => JSON.stringify([...a]) === JSON.stringify([...b]);

// ---- Knochen: Schleife ab Zwischenbild und Halten wie Anim_StepModelAnim
const file = new AnimFile(fromBase64(p.files.A), p.bones);
check(eq(file.table, [0, 28, 37]), 'Clip-Tabelle bis Abschluss 1 (Lücke an Index 0)');
const pl = new BonePlayer(p.bones);
const a1 = p.anims.find(a => a.name === 'anim_A1');
pl.set(file, a1.offset);
const seq = [[...pl.keys]];
for (let i = 0; i < 5; i++) { pl.tick(2); seq.push([...pl.keys]); }
check(JSON.stringify(seq) === JSON.stringify([[0, 0], [1, 0], [0, 1], [1, 0], [0, 1], [1, 0]]), 'Schleife springt auf Zeile 1 (nicht 0)');
check(pl.loops >= 2 && !pl.finished, 'Loop-Zähler, kein Ende');
pl.set(file, p.anims.find(a => a.name === 'anim_A2').offset);
pl.tick(2); pl.tick(10);
check(eq(pl.keys, [1, 1]) && pl.finished && pl.frame === 1, 'Einmal-Clip hält letztes Bild');
pl.restart();
check(eq(pl.keys, [0, 0]) && !pl.finished, 'Neustart setzt korrekt zurück');
pl.set(file, a1.offset); pl.tick(1);
check(eq(pl.keys, [0, 0]), 'Halbe Zeile (1 VBlank) ändert nichts – 30 Hz');
pl.tick(1);
check(eq(pl.keys, [1, 0]), 'Nach 2 VBlanks nächste Zeile');

// ---- Matrix-Konvertierung D·M·D
const m = glMatrix(file.key(0, 1));
check(Math.abs(m[1] - 1) < 1e-9 && Math.abs(m[4] + 1) < 1e-9 && m[3] === 5 && m[7] === 0, 'Matrix D·M·D und Translation D·t');
const sheared = glMatrix(file.key(1, 1));
check(Math.abs(sheared[1] + 0.5) < 1e-9 && sheared[7] === 20, 'Scherung bleibt erhalten (keine TRS-Zerlegung)');

// ---- Dekodierung identisch zum Python-Konverter
const vram = fromBase64(p.vram);
const tex = new TexAnimator(fromBase64(p.texanim.region), vram, () => 0);
fx.materials.forEach((mat, i) => {
  const rgba = new Uint8Array(128 * 256 * 4);
  decodeRect(tex.vram, mat.clut, mat.semi_transparent, rgba);
  const ref = fromBase64(fx.images[i]);
  let diff = 0;
  for (let k = 0; k < ref.length; k++) {
    if (k % 4 === 3) { if ((ref[k] > 0) !== (rgba[k] > 0) || (ref[k] === 255) !== (rgba[k] === 255)) diff++; }
    else if (ref[k] !== rgba[k]) diff++;
  }
  check(diff === 0, `Material ${i}: Dekodierung wie Python (${diff} Abweichungen)`);
});

// ---- Texturanimation wie Gfx_AnimateModelTex
const word = (x, y) => tex.vram[y * VRAM_W + x];
check(tex.active && tex.anim.cycles.length === 1 && tex.anim.extended.length === 1, 'texAnimParts gelesen');
let dirty = [];
for (let i = 0; i < 8; i++) dirty = dirty.concat(tex.frame(1, 0));
check(word(10, 40) === 0x2222 && dirty.some(r => r[0] === 40 && r[1] === 40 && r[2] === 56 && r[3] === 48), 'Zyklus: Bild 2 nach 8 VBlanks, Rechteck als geändert gemeldet');
for (let i = 0; i < 8; i++) tex.frame(1, 0);
check(word(10, 40) === 0x3333, 'Zyklus: Bild 3 nach 16 VBlanks');
for (let i = 0; i < 8; i++) tex.frame(1, 0);
check(word(10, 40) === 0x1111, 'Zyklus: zurück zu Bild 1 nach 24 VBlanks');

// Blinzeln: Zufall 0 → Zähler 60, abwärts; Zähler 13–10 halb, 9–6 zu, 5–2 halb (Gfx_AnimateModelTex)
const t2 = new TexAnimator(fromBase64(p.texanim.region), vram, () => 0);
const states = [];
for (let i = 0; i < 80; i++) { t2.frame(1, 0); states.push(t2.vram[10 * VRAM_W + 2]); }
const firstHalf = states.indexOf(0x2222), firstClosed = states.indexOf(0x3333);
check(firstHalf === 47 && firstClosed === 51 && states[79] === 0x1111, `Blinzeln: offen → halb → zu → offen (halb bei ${firstHalf}, zu bei ${firstClosed})`);
const t3 = new TexAnimator(fromBase64(p.texanim.region), vram, () => 0);
t3.frame(1, 10);
check(t3.vram[10 * VRAM_W + 2] === 0x3333, 'Animation 10 (B0): Augen geschlossen wie Gfx_AnimAllowsBlink');
t3.enabled.blink = false; t3.frame(1, 0);
check(t3.vram[10 * VRAM_W + 2] === 0x1111, 'Blinzeln aus: Augen offen');

// Erweitert: Periode 6, Startphase 3, Takt +1 je VBlank (frameDelta 1) bzw. +2
const t4 = new TexAnimator(fromBase64(p.texanim.region), vram, () => 0);
t4.frame(1, 0);
check(t4.anim.extended[0].timer === 4, 'Erweitert: Phase 3 + 1 = 4');
t4.frame(2, 0);
check(t4.anim.extended[0].timer === 0, 'Erweitert: (4 + 2) mod 6 = 0');
t4.reset();
check(t4.anim.extended[0].timer === 3 && t4.vram.every((v, i) => v === t4.original[i]), 'Reset stellt Textur und Phase her');

// ---- Vorderseite: Umlaufsinn gegen Lichtnormale (Grundlage für das PS1-Backface-Culling)
const tri = (pts, nz) => ({ geometry: { attributes: { position: { array: new Float32Array(pts) }, normal: { array: new Float32Array([0, 0, nz, 0, 0, nz, 0, 0, nz]) } } } });
const ccw = [0, 0, 0, 1, 0, 0, 0, 1, 0];   // Normale des Umlaufs: +z
check(JSON.stringify(faceOrientation([tri(ccw, 1)])) === '{"agree":1,"disagree":0}', 'Umlauf passt zur Normale → Vorderseite');
check(JSON.stringify(faceOrientation([tri(ccw, -1), tri(ccw, -1), tri(ccw, 1)])) === '{"agree":1,"disagree":2}', 'Gespiegelter Umlauf wird erkannt');
// Konverter-Ausgabe (Fixture-Quad: PS1-Normale +z, nach D → −z) ist stimmig
const conv = [0, 20, 0, 20, 0, 0, 0, 0, 0];   // Reihenfolge (2,1,0) wie native_gltf
check(faceOrientation([tri(conv, -1)]).agree === 1, 'Konverter-Umlauf (2,1,0) + D passt zur PS1-Normale');

if (fails) { console.error(`${fails} Prüfungen fehlgeschlagen`); process.exit(1); }
console.log('Alle JS-Animationstests bestanden');
