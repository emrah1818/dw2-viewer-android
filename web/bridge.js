// Web-Version: ersetzt die Android-Brücke (window.Android) durch einen Web Worker mit Pyodide.
// Dateien wählen = <input type=file>, Speichern = Download. Sonst dieselbe Oberfläche wie in der App.
window.DW2_BASE = '';          // Modelle kommen als blob:-Adressen
window.DW2_WEB = true;
const worker = new Worker('web/worker.js');
const blobs = new Map();       // Cache-Pfad -> blob:-URL
const MIME = { gltf: 'model/gltf+json', glb: 'model/gltf-binary', png: 'image/png', obj: 'text/plain', jpg: 'image/jpeg' };
let fatal = null;
// Ladeanzeige beim ersten Start (Python + numpy + Pillow, danach aus dem Browser-Cache)
const banner = document.createElement('div');
banner.id = 'py-banner';
banner.style.cssText = 'position:fixed;left:50%;bottom:84px;transform:translateX(-50%);z-index:50;background:#16263f;color:#dfe7f2;'
  + 'border:1px solid #2c4466;border-radius:10px;padding:8px 14px;font:13px system-ui;box-shadow:0 6px 20px #0008;max-width:90vw;text-align:center';
banner.textContent = 'Python wird geladen …';
document.addEventListener('DOMContentLoaded', () => document.body.appendChild(banner));

function blobUrl(path, bytes) {
  const old = blobs.get(path);
  if (old) URL.revokeObjectURL(old);
  const url = URL.createObjectURL(new Blob([bytes], { type: MIME[path.split('.').pop().toLowerCase()] || 'application/octet-stream' }));
  blobs.set(path, url);
  return url;
}
function rewrite(v) {
  if (typeof v === 'string') return blobs.get(v) ?? v;
  if (Array.isArray(v)) return v.map(rewrite);
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, rewrite(x)]));
  return v;
}
function answer(id, obj) { window.__resolve && window.__resolve(id, JSON.stringify(obj)); }

worker.onmessage = ev => {
  const m = ev.data;
  if (m.type === 'progress') {
    if (!banner.isConnected || banner.dataset.done) { window.__progress && window.__progress(m.text, m.pct); return; }
    banner.textContent = m.text + (m.pct >= 0 ? ` ${m.pct} %` : '');
    return;
  }
  if (m.type === 'ready') { banner.dataset.done = '1'; banner.remove(); return; }
  if (m.type === 'fatal') { fatal = m.error; banner.textContent = 'Python konnte nicht geladen werden: ' + m.error; return; }
  if (m.type === 'resolve') {
    m.files.forEach(f => blobUrl(f.url, f.bytes));
    let r; try { r = JSON.parse(m.json); } catch { r = { ok: false, error: m.json }; }
    if (r.ok) r.data = rewrite(r.data);
    answer(m.id, r);
    return;
  }
  if (m.type === 'file') {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([m.bytes])); a.download = m.name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    answer(m.id, { ok: true, data: { saved: m.name, uri: m.name } });
  }
};

function pickFile(id, kind) {
  const input = document.createElement('input');
  input.type = 'file';
  if (kind === 'image') input.accept = '.bin,.iso,.img';
  input.onchange = () => {
    const file = input.files && input.files[0];
    if (!file) { answer(id, { ok: false, error: 'Keine Datei gewählt.' }); return; }
    worker.postMessage({ type: 'pick', id, kind, file });
  };
  input.oncancel = () => answer(id, { ok: false, error: 'Keine Datei gewählt.' });
  input.click();
}

window.Android = {
  invoke(id, method, argsJson) {
    const args = JSON.parse(argsJson || '[]');
    if (fatal) { answer(id, { ok: false, error: 'Python konnte nicht geladen werden: ' + fatal }); return; }
    if (method.startsWith('pick_')) { pickFile(id, method.slice(5)); return; }
    if (method === 'app_info') { answer(id, { ok: true, data: { version: (window.DW2_VERSION || '') + ' (Web)', free_mb: null } }); return; }
    if (method === 'overwrite_original') {
      answer(id, { ok: false, error: 'Im Browser kann das Original nicht überschrieben werden. Bitte „Neues Image exportieren“ verwenden – die Datei wird dann heruntergeladen.' });
      return;
    }
    if (method === 'save_export') { worker.postMessage({ type: 'read', id, path: args[0], name: args[1] }); return; }
    worker.postMessage({ type: 'call', id, method, args: argsJson });
  },
};
