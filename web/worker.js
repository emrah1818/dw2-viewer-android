// Web-Version: Python-Kern (dieselben Module wie in der Android-App) in Pyodide.
// Das Spiel-Image wird nicht kopiert: WORKERFS liest die gewählte Datei stückweise.
const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.28.3/full/';
importScripts(PYODIDE + 'pyodide.js');

let py = null;
const ready = (async () => {
  post({ type: 'progress', text: 'Python wird geladen …', pct: 10 });
  py = await loadPyodide({ indexURL: PYODIDE });
  post({ type: 'progress', text: 'Bibliotheken werden geladen …', pct: 45 });
  await py.loadPackage(['numpy', 'pillow']);
  post({ type: 'progress', text: 'App wird vorbereitet …', pct: 80 });
  const zr = await fetch(new URL('../py.zip', self.location.href), { cache: 'no-cache' }); if (!zr.ok) throw new Error('py.zip: HTTP ' + zr.status); const zip = await zr.arrayBuffer();
  py.unpackArchive(zip, 'zip', { extractDir: '/app' });
  py.FS.mkdirTree('/files'); py.FS.mkdirTree('/input'); py.FS.mkdirTree('/imports');
  py.runPython(`
import sys, shutil, collections
sys.path.insert(0, '/app')
# Im Browser gibt es keine echte Datenträgerabfrage: großzügigen Wert melden.
shutil.disk_usage = lambda p: collections.namedtuple('usage', 'total used free')(1 << 40, 0, 1 << 40)
import android_api
android_api.configure('/files', None, '/app/data')
`);
  post({ type: 'ready' });
})().catch(e => post({ type: 'fatal', error: String(e && e.message || e) }));

function post(msg, transfer) { self.postMessage(msg, transfer || []); }

/** Dateien aus dem Cache (glTF/PNG/GLB/OBJ), die im Ergebnis genannt werden, an die Seite geben. */
function collectFiles(data, out) {
  if (typeof data === 'string') {
    if (/\.(gltf|glb|png|obj|jpg)$/i.test(data) && !data.startsWith('/')) {
      const p = '/files/viewer/' + data;
      try { if (py.FS.analyzePath(p).exists && !out.has(data)) out.set(data, py.FS.readFile(p)); } catch { /* kein Cache-Pfad */ }
    }
  } else if (Array.isArray(data)) data.forEach(v => collectFiles(v, out));
  else if (data && typeof data === 'object') Object.values(data).forEach(v => collectFiles(v, out));
}

function call(method, argsJson) {
  const api = py.pyimport('android_api');
  const text = api.call(method, argsJson);
  api.destroy();
  return text;
}

function resolve(id, text) {
  let files = new Map();
  try { const r = JSON.parse(text); if (r.ok) collectFiles(r.data, files); } catch { /* Fehlertext */ }
  const list = [...files].map(([url, bytes]) => ({ url, bytes }));
  post({ type: 'resolve', id, json: text, files: list }, list.map(f => f.bytes.buffer));
}

self.onmessage = async ev => {
  const m = ev.data;
  try {
    await ready;
    if (!py) throw new Error('Python konnte nicht geladen werden.');
    if (m.type === 'call') { resolve(m.id, call(m.method, m.args)); return; }
    if (m.type === 'pick') {
      const name = m.file.name.replace(/[^A-Za-z0-9._ -]/g, '_') || 'datei';
      let path;
      if (m.kind === 'image') {
        // Nur lesend einbinden – kein Kopieren des (großen) Images in den Speicher.
        try { py.FS.unmount('/input'); } catch { /* noch nicht eingebunden */ }
        py.FS.mount(py.FS.filesystems.WORKERFS, { files: [new File([m.file], name, { lastModified: m.file.lastModified })] }, '/input');
        path = '/input/' + name;
      } else {
        path = '/imports/' + name;
        py.FS.writeFile(path, new Uint8Array(await m.file.arrayBuffer()));
      }
      if (m.kind === 'file') { post({ type: 'resolve', id: m.id, json: JSON.stringify({ ok: true, data: { path, name } }), files: [] }); return; }
      const method = { image: 'open_image', roster: 'roster_open', project: 'load_project' }[m.kind];
      post({ type: 'progress', text: m.kind === 'image' ? 'Image wird analysiert …' : 'Datei wird gelesen …', pct: -1 });
      resolve(m.id, call(method, JSON.stringify([path])));
      return;
    }
    if (m.type === 'read') {
      const bytes = py.FS.readFile(m.path);
      post({ type: 'file', id: m.id, bytes, name: m.name }, [bytes.buffer]);
      try { if (m.path.startsWith('/files/')) py.FS.unlink(m.path); } catch { /* bleibt */ }
      return;
    }
  } catch (e) {
    post({ type: 'resolve', id: m.id, json: JSON.stringify({ ok: false, error: String(e && e.message || e) }), files: [] });
  }
};
