// Prüft den WebAssembly-DW3-Konverter der Web-Version gegen das native Programm
// (gleiche Quelle third_party/dw3_converter) mit dem selbst erstellten Mini-Modell.
//   node tests/test_dw3conv_wasm.mjs build/dw3conv/dw3conv.js build/dw3conv/dw3_converter
import { createRequire } from 'module';
import { execFileSync, spawnSync } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';
import assert from 'assert/strict';
const require = createRequire(import.meta.url);
const [wasmJs, native] = process.argv.slice(2).map(p => path.resolve(p));
const create = require(wasmJs);
const { dw3convRun } = require(path.resolve('web/dw3conv_run.js'));

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'dw3w-'));
execFileSync('python3', ['tests/studio_extra/fixture_dw3.py', path.join(tmp, 'mini.bin')]);
const model = fs.readFileSync(path.join(tmp, 'mini.bin'));

const inst = create({});
assert.ok(inst && inst.FS && typeof inst.callMain === 'function', 'Fabrik liefert die Instanz synchron');
const src = inst.FS;                       // steht für das Pyodide-Dateisystem
src.mkdirTree('/files/viewer/dw3/tmp');
src.writeFile('/files/viewer/dw3/tmp/source.bin', model);

// 1) Umwandlung
const r = dw3convRun(create, src, ['/files/viewer/dw3/tmp/source.bin', '/files/viewer/dw3/tmp/out']);
assert.equal(r.returncode, 0, r.stderr);
assert.match(r.stdout, /2 bones, 1 meshes, 0 motions/);
const n = spawnSync(native, [path.join(tmp, 'mini.bin'), path.join(tmp, 'out')]);
assert.equal(n.status, 0);
// Gleich bis auf Rundung im letzten Bit (anderer Compiler: Emscripten/clang gegen g++)
function close(x, y, where) {
  if (typeof x === 'number') { assert.ok(Math.abs(x - y) <= 1e-4 * Math.max(1, Math.abs(x)), `${where}: ${x} vs ${y}`); return; }
  if (Array.isArray(x)) { assert.equal(x.length, y.length, where); x.forEach((v, i) => close(v, y[i], where + '/' + i)); return; }
  if (x && typeof x === 'object') { assert.deepEqual(Object.keys(x).sort(), Object.keys(y).sort(), where); for (const k in x) close(x[k], y[k], where + '/' + k); return; }
  assert.equal(x, y, where);
}
function glb(buf) {
  const json = JSON.parse(buf.subarray(20, 20 + buf.readUInt32LE(12)).toString());
  const at = 20 + buf.readUInt32LE(12);
  const bin = buf.subarray(at + 8, at + 8 + buf.readUInt32LE(at));
  return { json, bin };
}
const out = f => [Buffer.from(src.readFile('/files/viewer/dw3/tmp/out/' + f)), fs.readFileSync(path.join(tmp, 'out', f))];
{
  const [a, b] = out('tex0.png'); assert.ok(a.equals(b), 'tex0.png identisch');
  const [ja, jb] = out('native_source.json'); close(JSON.parse(ja), JSON.parse(jb), 'native_source.json');
  const [ga, gb] = out('model.glb').map(glb);
  close(ga.json, gb.json, 'model.glb JSON');
  assert.equal(ga.bin.length, gb.bin.length, 'model.glb Binärteil gleich lang');
  const fa = new Float32Array(ga.bin.buffer, ga.bin.byteOffset, ga.bin.length >> 2), fb = new Float32Array(gb.bin.buffer, gb.bin.byteOffset, gb.bin.length >> 2);
  let worst = 0; for (let i = 0; i < fa.length; i++) if (Number.isFinite(fa[i]) && Number.isFinite(fb[i])) worst = Math.max(worst, Math.abs(fa[i] - fb[i]) / Math.max(1, Math.abs(fa[i])));
  assert.ok(worst < 1e-4, 'model.glb Binärdaten gleich bis auf Rundung: ' + worst);
}
// 2) Fehlerfall (kein Modell): gleicher Rückgabewert und gleiche Meldung
src.writeFile('/files/bad.bin', new Uint8Array(64));
const bad = dw3convRun(create, src, ['/files/bad.bin', '/files/badout']);
fs.writeFileSync(path.join(tmp, 'bad.bin'), Buffer.alloc(64));
const nb = spawnSync(native, [path.join(tmp, 'bad.bin'), path.join(tmp, 'badout')], { encoding: 'utf8' });
assert.equal(bad.returncode, nb.status);
assert.equal(bad.stderr.trim(), nb.stderr.trim());
// 3) --scripts mit ungültigem Eintrag: gleicher Code
const s = dw3convRun(create, src, ['--scripts', '/files/viewer/dw3/tmp/source.bin', '7']);
const ns = spawnSync(native, ['--scripts', path.join(tmp, 'mini.bin'), '7']);
assert.equal(s.returncode, ns.status);
// 4) zweiter Lauf in frischer Instanz liefert dasselbe
const r2 = dw3convRun(create, src, ['/files/viewer/dw3/tmp/source.bin', '/files/viewer/dw3/tmp/out2']);
assert.equal(r2.returncode, 0);
assert.ok(Buffer.from(src.readFile('/files/viewer/dw3/tmp/out2/model.glb')).equals(Buffer.from(src.readFile('/files/viewer/dw3/tmp/out/model.glb'))), 'zweiter Lauf identisch');
console.log('WebAssembly-DW3-Konverter: 4 Prüfungen bestanden (gleich wie das native Programm).');
