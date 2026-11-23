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
for (const f of ['model.glb', 'native_source.json', 'tex0.png']) {
  const a = Buffer.from(src.readFile('/files/viewer/dw3/tmp/out/' + f));
  const b = fs.readFileSync(path.join(tmp, 'out', f));
  assert.ok(a.equals(b), f + ' identisch mit dem nativen Konverter');
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
assert.ok(Buffer.from(src.readFile('/files/viewer/dw3/tmp/out2/model.glb')).equals(fs.readFileSync(path.join(tmp, 'out', 'model.glb'))));
console.log('WebAssembly-DW3-Konverter: 4 Prüfungen bestanden (identisch zum nativen Programm).');
