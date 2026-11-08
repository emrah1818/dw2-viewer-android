import { Viewer } from './viewer.js';
import { EN } from './i18n.js';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const BASE = 'https://appassets.androidplatform.net/viewer/';

// ---------------------------------------------------------------- Sprache
let lang = localStorage.getItem('lang') || ((navigator.language || 'de').startsWith('de') ? 'de' : 'en');
const t = (key, p = {}) => {
  let s = lang === 'en' ? (EN[key] ?? key) : key;
  for (const [k, v] of Object.entries(p)) s = s.replaceAll(`{${k}}`, v);
  return s;
};
function applyLang() {
  document.documentElement.lang = lang;
  $$('[data-i18n]').forEach(e => {
    if (e.dataset.de === undefined) e.dataset.de = e.textContent;
    e.textContent = lang === 'en' ? (EN[e.dataset.i18n] ?? e.dataset.de) : e.dataset.de;
  });
  $$('[data-i18n-ph]').forEach(e => { e.placeholder = t(e.dataset.i18nPh); });
  $('#lang').value = lang;
  renderList();
  if (state.id != null && currentPage === 'page-edit') renderEdit();
  renderPending();
}

// ---------------------------------------------------------------- Brücke zu Kotlin/Python
const waiting = new Map();
let counter = 0;
window.__resolve = (id, json) => {
  const cb = waiting.get(id);
  if (!cb) return;
  waiting.delete(id);
  try { cb(JSON.parse(json)); } catch (e) { cb({ ok: false, error: String(e) }); }
};
window.__progress = (text, pct) => setOverlay(true, t(text), pct);
function native(method, ...args) {
  return new Promise((resolve, reject) => {
    const id = `c${++counter}`;
    waiting.set(id, r => (r.ok ? resolve(r.data) : reject(new Error(r.error))));
    window.Android.invoke(id, method, JSON.stringify(args));
  });
}

// ---------------------------------------------------------------- UI-Hilfen
const logLines = [];
function log(msg) { logLines.push(`${new Date().toLocaleTimeString()}  ${msg}`); $('#log').textContent = logLines.slice(-200).join('\n'); }
let toastTimer;
function toast(msg) { const el = $('#toast'); el.textContent = msg; el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, 3500); }
function setOverlay(on, text = '', pct = -1) {
  $('#overlay').hidden = !on; $('#ov-text').textContent = text;
  $('#ov-bar').style.display = pct >= 0 ? 'block' : 'none'; $('#ov-bar i').style.width = `${Math.max(0, pct)}%`;
}
async function busy(text, fn) {
  setOverlay(true, t(text));
  try { return await fn(); } finally { setOverlay(false); }
}
async function fail(e) {
  let msg = e.message || String(e);
  if (lang === 'en') { try { msg = (await native('translate', [msg], 'en'))[0]; } catch { /* Original behalten */ } }
  log(`${t('Fehler')}: ${msg}`);
  toast(`${t('Fehler')}: ${msg}`);
}
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
let closeModal = null;
function modal(build) {
  return new Promise(resolve => {
    const box = $('#modal-box'); box.innerHTML = '';
    const close = v => { $('#modal').hidden = true; closeModal = null; resolve(v); };
    closeModal = () => close(null);
    build(box, close);
    $('#modal').hidden = false;
    $('#modal').onclick = ev => { if (ev.target.id === 'modal') close(null); };
  });
}
const confirmBox = text => modal((box, close) => {
  box.innerHTML = `<h3>${esc(text)}</h3><div class="btns"><button id="m-no">${t('Abbrechen')}</button><button id="m-yes" class="primary">OK</button></div>`;
  $('#m-no', box).onclick = () => close(false); $('#m-yes', box).onclick = () => close(true);
});
const promptBox = (title, value) => modal((box, close) => {
  box.innerHTML = `<h3>${esc(title)}</h3><input id="m-in" type="text" value="${esc(value)}"><div class="btns"><button id="m-no">${t('Abbrechen')}</button><button id="m-yes" class="primary">OK</button></div>`;
  $('#m-no', box).onclick = () => close(null); $('#m-yes', box).onclick = () => close($('#m-in', box).value.trim() || null);
});
/** Auswahlliste mit Suche; items: [{value,label}] */
const pickBox = (title, items, current) => modal((box, close) => {
  box.innerHTML = `<h3>${esc(title)}</h3><input id="m-q" type="search"><div id="m-l"></div>`;
  const draw = () => {
    const q = $('#m-q', box).value.toLowerCase();
    $('#m-l', box).innerHTML = items.filter(i => i.label.toLowerCase().includes(q))
      .map(i => `<div class="opt ${i.value === current ? 'sel' : ''}" data-v="${i.value}">${esc(i.label)}</div>`).join('');
    $$('.opt', box).forEach(o => { o.onclick = () => close(Number(o.dataset.v)); });
  };
  $('#m-q', box).oninput = draw; draw();
});
const field = (label, id, value, attrs = '') =>
  `<label class="f" for="${id}">${esc(label)}</label><input id="${id}" type="number" inputmode="numeric" value="${value}" ${attrs}>`;

// ---------------------------------------------------------------- Zustand / Seiten
const state = { catalog: [], filtered: [], id: null, loaded: null, image: null, prefetch: new Set() };
const view = new Viewer($('#gl'));
window.__dw2view = view;   // für Diagnose und automatisierte Oberflächentests
view.setLight(1.2);
const nameOf = id => state.catalog.find(c => c.id === id)?.name ?? `#${id}`;

let currentPage = 'start';
function show(page) {
  currentPage = page;
  $$('.page').forEach(p => p.classList.toggle('active', p.id === page));
  $$('.tab').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  if (page === 'page-view') requestAnimationFrame(() => view.resize());
  if (page === 'page-edit') renderEdit();
  if (page === 'page-changes') refreshPending();
}
$$('.tab').forEach(b => { b.onclick = () => { if (!state.image) return toast(t('Bitte zuerst ein Spiel-Image öffnen.')); show(b.dataset.page); }; });
window.__back = () => {
  if (closeModal) { closeModal(); return true; }
  if (state.image && currentPage !== 'page-list') { show('page-list'); return true; }
  return false;
};

// ---------------------------------------------------------------- Image öffnen
async function openImage() {
  try {
    const info = await native('pick_image');
    if (!info) return;
    state.image = info; state.id = null; state.loaded = null; state.prefetch.clear(); view.clear();
    state.catalog = await native('catalog');
    $('#subtitle').textContent = `${info.name} · ${info.count} Digimon`;
    log(`Image: ${info.name}, ${info.count} Digimon, ${info.cached ? 'Index aus Cache' : 'neu analysiert'} (${info.seconds} s)`);
    if (info.name_error) log('Namenstabelle: ' + info.name_error);
    $('#search').value = ''; renderList(); show('page-list'); refreshPending();
  } catch (e) { await fail(e); } finally { setOverlay(false); }
}
$('#btn-open').onclick = openImage; $('#btn-open2').onclick = openImage;

// ---------------------------------------------------------------- Liste
function renderList() {
  const q = $('#search').value.toLowerCase().trim();
  state.filtered = state.catalog.filter(c => `${String(c.id).padStart(3, '0')} ${c.code} ${c.name}`.toLowerCase().includes(q));
  $('#list').innerHTML = state.filtered.map(c =>
    `<div class="item ${c.id === state.id ? 'sel' : ''}" data-id="${c.id}"><span class="id">#${String(c.id).padStart(3, '0')}</span><span class="nm">${esc(c.name)}</span><span class="cd">${esc(c.code)}</span></div>`).join('');
  $$('#list .item').forEach(el => { el.onclick = () => selectDigimon(Number(el.dataset.id), true); });
}
$('#search').oninput = renderList;

function selectDigimon(id, openView) {
  state.id = id;
  $$('#list .item').forEach(el => el.classList.toggle('sel', Number(el.dataset.id) === id));
  $('#v-name').textContent = nameOf(id);
  if (openView) show('page-view');
  return loadModel(id);
}
function neighbour(step) {
  const i = state.filtered.findIndex(c => c.id === state.id);
  const n = state.filtered[i + step];
  if (n) selectDigimon(n.id, false);
}
$('#v-prev').onclick = () => neighbour(-1);
$('#v-next').onclick = () => neighbour(1);

// ---------------------------------------------------------------- 3D-Modell
let loadSeq = 0;
async function loadModel(id) {
  const seq = ++loadSeq;
  $('#stage-msg').textContent = t('Modell wird vorbereitet …');
  try {
    const info = await native('prepare_model', id, state.showOriginal);
    if (seq !== loadSeq) return;
    const r = await view.load(BASE + info.url);
    if (seq !== loadSeq) return;
    state.loaded = { id, info };
    $('#stage-msg').textContent = '';
    $('#v-name').textContent = info.name;
    showEditState(info);
    $('#anim').innerHTML = r.animations.length
      ? r.animations.map((n, i) => `<option value="${i}">${esc(n)}</option>`).join('')
      : `<option>${t('Keine Animationen')}</option>`;
    if (r.animations.length) view.play(0);
    renderDiag(info);
    log(`${info.name}: ${t('geladen')} (${info.seconds} s)`);
    prefetchNeighbours(id);
  } catch (e) {
    if (seq !== loadSeq) return;
    $('#stage-msg').textContent = '';
    await fail(e);
  }
}
async function prefetchNeighbours(id) {
  if (!$('#o-prefetch').checked) return;
  const i = state.filtered.findIndex(c => c.id === id);
  for (const n of [state.filtered[i + 1], state.filtered[i - 1]]) {
    if (!n || state.prefetch.has(n.id) || state.id !== id) continue;
    state.prefetch.add(n.id);
    try { await native('prepare_model', n.id); } catch { /* nicht kritisch */ }
  }
}
$('#anim').onchange = e => view.play(Number(e.target.value));
$('#play').onclick = () => {
  if (view.playing && view.restartIfFinished()) return;
  view.playing = !view.playing; $('#play').textContent = view.playing ? '⏸' : '▶';
};
$('#o-smooth').onchange = e => { view.smooth = e.target.checked; };
$('#o-repeat').onchange = e => { view.repeatOnce = e.target.checked; };
for (const [id, ch] of [['#c-bones', 'bones'], ['#c-cycles', 'cycles'], ['#c-extended', 'extended'], ['#c-blend', 'blend'], ['#c-cull', 'cull']]) {
  $(id).onchange = e => view.setChannel(ch, e.target.checked);
}
function animStatus() {
  const s = view.status();
  const el = $('#anim-info');
  if (!s) { el.textContent = view.native === null && view.actions.length ? t('Wiedergabe über glTF (keine nativen Spieldaten)') : ''; return; }
  const parts = [`${t('Spiel-ID')} ${s.id}`, `${t('Bild')} ${s.frame}/${s.rows}`];
  parts.push(s.loopRow ? t('Schleife ab Bild {n}', { n: s.loopRow }) : (s.finished ? t('einmalig · beendet (▶ startet neu)') : t('einmalig')));
  if (s.blink.startsWith('zu')) parts.push(t('Augen geschlossen (Spielregel)'));
  if (!view.playing) parts.push(t('pausiert'));
  el.textContent = parts.join(' · ');
}
setInterval(animStatus, 250);
function renderDiag(info) {
  const c = view.channelsInfo();
  const el = $('#diag-info');
  if (!c) { el.textContent = t('Keine nativen Animationsdaten (Import oder älterer Cache).'); return; }
  const src = info?.anim_source;
  const shared = src ? Object.entries(src.slots || {}).filter(([, v]) => v.shared).map(([k, v]) => `${k}=${v.file}`) : [];
  const rows = [
    [t('Knochen'), c.bones], [t('Animationsdateien'), c.files], [t('Clips'), `${c.clips} (${t('Schleifen')} ${c.loops}, ${t('einmalig')} ${c.holds})`],
    [t('Zuordnung'), src?.source === 'MODELDT' ? t('Spieltabelle MODELDT') : t('Dateiname')],
    [t('Geteilte Animationen'), shared.join(', ') || '–'],
    [t('Augen'), c.eyes], [t('Texturzyklen'), c.cycles], [t('Erweiterte Texturanimation'), c.extended],
    [t('Palettenzeilen betroffen'), c.palette ? t('ja') : t('nein')], [t('Halbtransparenz'), c.semi], [t('Rückseiten'), c.culling],
  ];
  if (c.legacy) rows.push([t('Hinweis'), t('{n} Clips nur tolerant lesbar', { n: c.legacy })]);
  el.innerHTML = rows.map(([k, v]) => `<div><b>${esc(k)}:</b> ${esc(String(v))}</div>`).join('') +
    [...c.warnings, ...(src?.notes || [])].map(w => `<div class="warn">${esc(w)}</div>`).join('');
}
$('#b-native-zip').onclick = async () => {
  if (!needDigimon()) return;
  try { await exportFile(busy('Rohdaten werden gepackt …', () => native('native_files_export', state.id))); } catch (e) { await fail(e); }
};
$('#speed').oninput = e => { view.speed = Number(e.target.value); };
$('#reset').onclick = () => view.resetCamera();
$('#o-blink').onchange = e => { view.blink = e.target.checked; };
$('#o-grid').onchange = e => { view.grid.visible = e.target.checked; };
$('#o-wire').onchange = e => { view.wire = e.target.checked; view.applyMaterial(); };
$('#o-nearest').onchange = e => { view.nearest = e.target.checked; view.applyMaterial(); };
$('#o-light').oninput = e => view.setLight(Number(e.target.value));
$('#o-bg').oninput = e => view.setBackground(e.target.value);

/** Datei aus dem App-Ordner über den Android-Speichern-Dialog ablegen. */
async function exportFile(promise) {
  const f = await promise;
  const saved = await native('save_export', f.path, f.name);
  toast(saved ? `${t('Gespeichert')}: ${f.name}` : t('Nicht gespeichert'));
  setOverlay(false);
}
// ---------------------------------------------------------------- Original / Bearbeitet, Rückgängig
state.showOriginal = false;
function showEditState(info) {
  const b = $('#b-compare');
  b.textContent = t(state.showOriginal ? 'Original' : 'Bearbeitet');
  b.classList.toggle('orig', state.showOriginal);
  $('#edit-state').textContent = info?.foreign ? t('Nur Ansicht (Import)') : info?.edited ? t('geändert · vorgemerkt') : t('unverändert');
}
$('#b-compare').onclick = () => {
  state.showOriginal = !state.showOriginal;
  if (state.id != null) loadModel(state.id); else showEditState(null);
};
async function afterChange(message) {
  state.showOriginal = false;
  state.prefetch.clear();
  try { state.catalog = await native('catalog'); renderList(); } catch { /* Anzeige */ }
  await refreshPending();
  if (state.id != null) await loadModel(state.id);
  if (message) toast(message);
}
async function historyStep(kind) {
  try { await native(kind); await afterChange(t(kind === 'undo' ? 'Rückgängig gemacht' : 'Wiederhergestellt')); }
  catch (e) { await fail(e); }
}
$('#b-undo').onclick = () => historyStep('undo');
$('#b-redo').onclick = () => historyStep('redo');
$('#b-undo2').onclick = () => historyStep('undo');
$('#b-redo2').onclick = () => historyStep('redo');
async function refreshHistory() {
  try {
    const h = await native('history');
    for (const id of ['#b-undo', '#b-undo2']) $(id).disabled = !h.undo;
    for (const id of ['#b-redo', '#b-redo2']) $(id).disabled = !h.redo;
  } catch { /* ohne Image */ }
}

// ---------------------------------------------------------------- Texturen
const needDigimon = () => { if (state.id == null) { toast(t('Digimon wählen')); return false; } return true; };
$('#b-png-export').onclick = async () => {
  if (!needDigimon()) return;
  const factor = await pickBox(t('Arbeitsauflösung (Spiel bleibt 128×256)'),
    [1, 2, 3, 4].map(k => ({ value: k, label: `${k}× · ${128 * k}×${256 * k}` })), 1);
  if (factor == null) return;
  try { await exportFile(busy('PNG wird erstellt …', () => native('png_export', state.id, true, factor))); }
  catch (e) { await fail(e); }
};
async function pngImport(eyesOnly) {
  if (!needDigimon()) return;
  try {
    const file = await native('pick_file');
    if (!file) return;
    if (!/\.png$/i.test(file.name)) throw new Error(t('Bitte eine PNG-Datei wählen.'));
    const prev = await busy('PS1-Farben werden berechnet …', () =>
      native('png_preview', state.id, file.path, $('#o-palette').value, eyesOnly, $('#o-resize').value));
    const accepted = await modal((box, close) => {
      const q = prev.quality;
      const img = (k, label) => prev.images[k] ? `<div><img src="${BASE + prev.images[k]}" alt=""><br>${esc(t(label))}</div>` : '';
      box.innerHTML = `<h3>${t('Vorschau vor dem Vormerken')}</h3>
        <div class="cmp">${img('original', 'Original im Spiel')}${img('desired', 'Deine PNG')}${img('result', 'Erwartetes Ergebnis im Spiel')}</div>
        ${prev.factor > 1 ? `<p class="warn">${t('PNG {w}×{h} wurde auf 128×256 verkleinert ({f}×).', { w: prev.size[0], h: prev.size[1], f: prev.factor })}</p>` : ''}
        ${q ? `<p class="hint">${t('Mittlerer Farbfehler')}: ${q.mean_rgb_error}/255 · ${t('Starke Abweichungen')}: ${(q.bad_pixel_fraction * 100).toFixed(1)} % · ${t('Geänderte Paletten')}: ${q.palettes_rewritten} · ${t('Neue Palettenfarben')}: ${q.colors_rewritten}</p>
             <p class="hint">${t('Bearbeitete Pixel')}: ${q.edited_pixels_checked} · ${t('Farbfehler dort')}: ${q.edited_mean_rgb_error}/255</p>` : ''}
        ${prev.reserved_ignored || prev.unmapped_ignored ? `<p class="warn">${t('{a} Pixel in den Palettenzeilen und {b} Pixel außerhalb der Modellflächen werden ignoriert.', { a: prev.reserved_ignored, b: prev.unmapped_ignored })}</p>` : ''}
        ${prev.warn ? `<p class="warn">${t('Einzelne bearbeitete Bereiche weichen deutlich ab. Bei entfärbten Augen den Modus Farbschutz wählen.')}</p>` : ''}
        ${prev.eye_frames ? `<p class="hint">${t('Augenposen werden mitgeschrieben.')}</p>` : ''}
        <p class="hint">${t('Nur fortfahren, wenn das rechte Bild deinen Farben entspricht. Die Original-BIN bleibt unverändert.')}</p>
        <div class="btns"><button id="m-no">${t('Abbrechen')}</button><button id="m-yes" class="primary">${t('Farben stimmen – vormerken')}</button></div>`;
      $('#m-no', box).onclick = () => close(false); $('#m-yes', box).onclick = () => close(true);
    });
    if (!accepted) { native('cancel', prev.token).catch(() => {}); return; }
    const r = await busy('Textur wird vorgemerkt …', () => native('png_apply', prev.token));
    await afterChange(r.changed ? t('Textur vorgemerkt · Vorschau aktualisiert') : t('PNG enthält keine wirksame Änderung.'));
  } catch (e) { await fail(e); } finally { setOverlay(false); }
}
$('#b-png-import').onclick = () => pngImport(false);
$('#b-eyes-import').onclick = () => pngImport(true);

// ---------------------------------------------------------------- 3D-Modelle
async function exportModel(fmt) {
  if (!needDigimon()) return;
  try {
    const f = await busy('Modell wird exportiert …', () => native('model_export', state.id, fmt, null));
    if (!f.native) log(t('Hinweis: Animationen dieses Modells sind nicht als Spieldaten eingebettet (nur Ansicht).'));
    await exportFile(Promise.resolve(f));
  } catch (e) { await fail(e); }
}
$('#b-glb').onclick = () => exportModel('glb');
$('#b-gltf').onclick = () => exportModel('gltf');
$('#b-restore').onclick = async () => {
  if (!needDigimon() || !(await confirmBox(t('Modell- und Animationsänderungen dieses Digimon verwerfen?')))) return;
  try { const r = await native('restore_original', state.id); await afterChange(`${r.removed} ${t('Datei(en) zurückgesetzt')}`); }
  catch (e) { await fail(e); }
};
async function showImport(ins) {
  state.loaded = { id: null, info: { foreign: true } };
  $('#v-name').textContent = ins.name;
  showEditState({ foreign: true });
  try {
    const r = await view.load(BASE + ins.view);
    renderDiag(null);
    $('#anim').innerHTML = r.animations.length ? r.animations.map((n, i) => `<option value="${i}">${esc(n)}</option>`).join('') : `<option>${t('Keine Animationen')}</option>`;
    if (r.animations.length) view.play(0);
  } catch (e) { await fail(e); }
}
$('#b-3d-import').onclick = async () => {
  try {
    const file = await native('pick_file');
    if (!file) return;
    const ins = await busy('3D-Datei wird geprüft …', () => native('inspect_3d', file.path, state.id));
    const target = state.id != null ? nameOf(state.id) : null;
    const choice = await modal((box, close) => {
      let body = `<h3>${esc(ins.name)}</h3>`;
      if (ins.kind === 'transfer') {
        const p = ins.plan;
        body += `<p>${t('DW2-Austauschmodell')}: <b>${esc(ins.source.name)}</b> · ${t('Knochen')} ${p ? `${p.source_bones} → ${p.target_bones}` : ''}</p>`;
        if (p) body += `<table class="plan">${p.rows.map(r => `<tr><td>${esc(r[0])}</td><td>${r[1]} / ${r[2]} B</td><td>${esc(r[3])}</td></tr>`).join('')}</table>` +
          (p.errors.length ? `<p class="bad">${p.errors.map(esc).join('<br>')}</p>` : '');
      } else if (ins.kind === 'foreign') {
        body += `<p>${t('Fremdes 3D-Modell. Zum Einbau ins Spiel werden seine Teile den Knochen des Ziel-Digimon zugeordnet.')}</p>`;
      } else {
        body += `<p>${t('Native Modell-BIN (muss genau so groß sein wie das Ziel).')}</p>`;
      }
      const canReplace = target && (ins.kind !== 'transfer' || (ins.plan && !ins.plan.errors.length));
      body += `<div class="btns">
        ${ins.view ? `<button data-c="view">${t('Nur ansehen')}</button>` : ''}
        ${canReplace ? `<button data-c="replace" class="primary">${t('{name} ersetzen', { name: esc(target) })}</button>` : ''}
        <button data-c="">${t('Abbrechen')}</button></div>
        ${!target ? `<p class="hint">${t('Zum Ersetzen zuerst in der Liste ein Ziel-Digimon wählen.')}</p>` : ''}`;
      box.innerHTML = body;
      $$('button[data-c]', box).forEach(b => { b.onclick = () => close(b.dataset.c || null); });
    });
    if (!choice) { native('cancel', ins.token).catch(() => {}); return; }
    if (choice === 'view') { show('page-view'); await showImport(ins); return; }
    if (ins.kind === 'transfer') {
      await busy('Digimon wird ersetzt …', () => native('transfer_apply', ins.token, state.id));
      await afterChange(t('Digimon ersetzt · Vorschau aktualisiert'));
    } else if (ins.kind === 'native_bin') {
      await busy('Modell wird ersetzt …', () => native('bin_apply', ins.token, state.id));
      await afterChange(t('Modell-BIN vorgemerkt'));
    } else {
      await rigFlow(ins);
    }
    show('page-view');
  } catch (e) { await fail(e); } finally { setOverlay(false); }
};
async function rigFlow(ins) {
  const rig = await busy('Knochen werden zugeordnet …', () => native('rig_prepare', ins.token, state.id));
  const bones = Array.from({ length: rig.bones }, (_, i) => i);
  const result = await modal((box, close) => {
    box.innerHTML = `<h3>${t('Knochenzuordnung')}</h3>
      <p class="hint">${t('{f} Dreiecke · {b} Knochen im Ziel · Platzbedarf mind. {m} von {g} Bytes', { f: rig.faces, b: rig.bones, m: rig.minimum, g: rig.budget })}</p>
      ${rig.minimum > rig.budget ? `<p class="bad">${t('Das Modell hat zu viele Dreiecke für diesen Modellplatz. Vorher reduzieren.')}</p>` : ''}
      ${rig.groups.map((g, i) => `<label class="f">${esc(g.group)} · ${g.faces} ${t('Dreiecke')} · ${t('Vorschlag')}: ${esc(t(g.how))}</label>
        <select data-g="${i}">${bones.map(b => `<option value="${b}" ${b === g.bone ? 'selected' : ''}>${t('Knochen')} ${String(b).padStart(2, '0')}${rig.parents[b] < 0 ? ' · ' + t('Wurzel') : ' ← ' + String(rig.parents[b]).padStart(2, '0')}</option>`).join('')}</select>`).join('')}
      <label class="row"><span>${t('Größe')} (×)</span><input type="range" id="r-scale" min="0.25" max="4" step="0.05" value="1"><b id="r-sv">1.00</b></label>
      ${rig.has_texture ? `<label class="row"><input type="checkbox" id="r-tex" checked> <span>${t('Textur des Modells übernehmen (auf 14 Farben reduziert)')}</span></label>` : ''}
      <p class="hint">${t('Das Modell wird automatisch eingepasst. Vorhandene Animationen bleiben erhalten.')}</p>
      <div class="btns"><button id="m-no">${t('Abbrechen')}</button><button id="m-yes" class="primary">${t('Prüfen und vormerken')}</button></div>`;
    $('#r-scale', box).oninput = e => { $('#r-sv', box).textContent = Number(e.target.value).toFixed(2); };
    $('#m-no', box).onclick = () => close(null);
    $('#m-yes', box).onclick = () => {
      const mapping = {};
      $$('select[data-g]', box).forEach(sel => { mapping[rig.groups[Number(sel.dataset.g)].group] = Number(sel.value); });
      close({ mapping, texture: $('#r-tex', box)?.checked ?? false, scale: Number($('#r-scale', box).value) });
    };
  });
  if (!result) { native('cancel', ins.token).catch(() => {}); return; }
  const r = await busy('Modell wird gebaut und geprüft …', () =>
    native('rig_apply', ins.token, state.id, result.mapping, result.texture, $('#o-palette').value, result.scale));
  r.warnings.forEach(w => log(w));
  await afterChange(t('Formatprüfung bestanden: {u}/{b} Geometriebytes · Vorschau aktualisiert', { u: r.report.geometry_used, b: r.report.geometry_budget }));
  if (r.warnings.length) toast(r.warnings[0]);
}

// ---------------------------------------------------------------- Bearbeiten
function renderEdit() {
  const id = state.id;
  const boxes = ['#f-name', '#f-type', '#f-attacks', '#f-enemy', '#f-roster'];
  if (id == null || !state.image) { $('#edit-name').textContent = t('Digimon wählen'); $('#edit-sub').textContent = ''; boxes.forEach(s => { $(s).innerHTML = ''; }); return; }
  const c = state.catalog.find(x => x.id === id);
  $('#edit-name').textContent = `#${String(id).padStart(3, '0')} ${c.name}`; $('#edit-sub').textContent = ` · ${c.code}`;
  renderName(id); renderType(id); renderAttacks(id); renderEnemy(id); renderRoster(id);
}
const errBox = (box, e) => { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; };

async function renderName(id) {
  const box = $('#f-name');
  try {
    const n = await native('name_info', id);
    box.innerHTML = `<label class="f" for="in-name">${t('Name (max. {n} Zeichen)', { n: n.max_length })}</label>
      <input id="in-name" type="text" maxlength="${n.max_length}" value="${esc(n.current)}">
      <p class="hint">${t('Original')}: ${esc(n.original)}</p>
      <div class="btns"><button id="b-name-ok" class="primary">${t('Übernehmen')}</button><button id="b-name-orig">${t('Original')}</button></div>`;
    const apply = async text => {
      try {
        await native('rename', id, text);
        state.catalog = await native('catalog');
        toast(t('Name vorgemerkt')); renderList(); renderEdit(); refreshPending();
      } catch (e) { await fail(e); }
    };
    $('#b-name-ok').onclick = () => apply($('#in-name').value);
    $('#b-name-orig').onclick = () => apply(n.original);
  } catch (e) { errBox(box, e); }
}

async function renderType(id) {
  const box = $('#f-type');
  try {
    const [ty, sp] = await Promise.all([native('type_info', id), native('specialty_info', id)]);
    const opts = (list, cur) => list.map(o => `<option value="${o.code}" ${o.code === cur ? 'selected' : ''}>${esc(o.name)}</option>`).join('');
    box.innerHTML = `<label class="f">${t('Typ')} <span class="pill">${t('Original')}: ${esc(ty.original_name)}</span></label><select id="sel-type">${opts(ty.choices, ty.code)}</select>
      <label class="f">${t('Specialty')} <span class="pill">${t('Original')}: ${esc(sp.original_name)}</span></label><select id="sel-spec">${opts(sp.choices, sp.code)}</select>
      <div class="btns"><button id="b-type-ok" class="primary">${t('Übernehmen')}</button></div>`;
    $('#b-type-ok').onclick = async () => {
      try {
        await native('set_type', id, Number($('#sel-type').value));
        await native('set_specialty', id, Number($('#sel-spec').value));
        toast(t('Typ/Specialty vorgemerkt')); refreshPending(); renderType(id);
      } catch (e) { await fail(e); }
    };
  } catch (e) { errBox(box, e); }
}

async function renderAttacks(id) {
  const box = $('#f-attacks');
  try {
    const info = await native('attack_info', id);
    const items = [{ value: 0, label: `— ${t('keine')} —` }, ...info.skills.map(s => ({ value: s.id, label: s.label }))];
    const label = v => items.find(i => i.value === v)?.label ?? `${v}`;
    const draft = { default: info.default, enc: Object.fromEntries(info.encounters.map(e => [e.key.join(','), [...e.skills]])) };
    const draw = () => {
      box.innerHTML = `<label class="f">${t('Standard-Attacke')} ${info.original_default != null ? `<span class="pill">${t('Original')}: ${esc(label(info.original_default))}</span>` : ''}</label>
        <button class="slot" id="s-def">${esc(label(draft.default))}</button>
        ${info.encounters.map(e => {
          const k = e.key.join(',');
          return `<label class="f">${t('Gegner-Begegnung')} ${e.key[0]}/${e.key[1]} · Lv ${e.level}</label>` +
            draft.enc[k].map((s, i) => `<button class="slot" data-k="${k}" data-i="${i}">${t('Technik {n}', { n: i + 1 })}: ${esc(label(s))}</button>`).join('');
        }).join('')}
        <div class="btns"><button id="b-att-ok" class="primary">${t('Übernehmen')}</button></div>
        <label class="f">${t('Technikwerte (global)')}</label><button class="slot" id="s-tech">${t('Technik wählen')} …</button>`;
      $('#s-def').onclick = async () => { const v = await pickBox(t('Standard-Attacke'), items.slice(1), draft.default); if (v != null) { draft.default = v; draw(); } };
      $$('button[data-k]', box).forEach(b => {
        b.onclick = async () => {
          const k = b.dataset.k, i = Number(b.dataset.i);
          const v = await pickBox(t('Technik {n}', { n: i + 1 }), items, draft.enc[k][i]);
          if (v != null) { draft.enc[k][i] = v; draw(); }
        };
      });
      $('#b-att-ok').onclick = async () => {
        try { await native('apply_attacks', id, draft.default, draft.enc, {}); toast(t('Attacken vorgemerkt')); refreshPending(); renderAttacks(id); }
        catch (e) { await fail(e); }
      };
      $('#s-tech').onclick = async () => {
        const sid = await pickBox(t('Technik wählen'), items.slice(1), null);
        if (sid == null) return;
        const s = info.skills.find(x => x.id === sid);
        await modal((m, close) => {
          m.innerHTML = `<h3>${esc(s.label)}</h3>${field('MP', 'tv-mp', s.mp, 'min="0" max="255"')}${field(t('Power (nativ)'), 'tv-pw', s.power, 'min="-32768" max="32767"')}
            <div class="btns"><button id="m-no">${t('Abbrechen')}</button><button id="m-yes" class="primary">${t('Übernehmen')}</button></div>`;
          $('#m-no', m).onclick = () => close(null);
          $('#m-yes', m).onclick = async () => {
            try {
              await native('apply_attacks', id, null, {}, { [sid]: { mp: Number($('#tv-mp', m).value), power: Number($('#tv-pw', m).value) } });
              close(true); toast(t('Attacken vorgemerkt')); refreshPending(); renderAttacks(id);
            } catch (e) { await fail(e); }
          };
        });
      };
    };
    draw();
  } catch (e) { errBox(box, e); }
}

const ENEMY_LABELS = { hp: 'HP', mp: 'MP', attack: 'Angriff', defense: 'Verteidigung', speed: 'Tempo', exp: 'EXP' };
async function renderEnemy(id) {
  const box = $('#f-enemy');
  try {
    const d = await native('enemy_values', id);
    if (!d.rows.length) { box.innerHTML = `<p class="hint">${t('Keine Gegnerwerte für dieses Digimon gefunden.')}</p>`; return; }
    box.innerHTML = d.rows.map(r => {
      const k = r.key.join(',');
      return `<div class="pend"><b>${t('Gegner-Begegnung')} ${r.key[0]}/${r.key[1]} · Lv ${r.level}</b><div class="grid2">` +
        Object.keys(ENEMY_LABELS).map(f => `<div>${field(t(ENEMY_LABELS[f]) + (r.values[f] !== r.original[f] ? ` (${r.original[f]})` : ''),
          `ev-${k.replace(',', '-')}-${f}`, r.values[f], `min="${d.fields[f].min}" max="${d.fields[f].max}" data-k="${k}" data-f="${f}"`)}</div>`).join('') +
        '</div></div>';
    }).join('') + `<div class="btns"><button id="b-enemy-ok" class="primary">${t('Übernehmen')}</button></div>`;
    $('#b-enemy-ok').onclick = async () => {
      const changes = {};
      $$('input[data-k]', box).forEach(i => { (changes[i.dataset.k] ||= {})[i.dataset.f] = Number(i.value); });
      try { await native('set_enemy_values', id, changes); toast(t('Werte vorgemerkt')); refreshPending(); renderEnemy(id); }
      catch (e) { await fail(e); }
    };
  } catch (e) { errBox(box, e); }
}

let rosterOpen = false;
const ROSTER_FIELDS = [['hp', 'HP'], ['max_hp', 'Max. HP'], ['mp', 'MP'], ['max_mp', 'Max. MP'], ['attack', 'Angriff'], ['defense', 'Verteidigung'], ['speed', 'Tempo'], ['exp', 'EXP']];
async function renderRoster(id) {
  const box = $('#f-roster');
  let html = `<div class="btns"><button id="b-roster-open">${t('Memorycard/Spielstand öffnen')}</button></div>`;
  if (rosterOpen) {
    try {
      const rows = await native('roster_records', id);
      html += rows.length ? rows.map(r => {
        const k = r.key.join('-');
        return `<div class="pend" data-key="${r.key.join(',')}"><b>${esc(r.name || nameOf(r.id))}</b> · Lv ${r.level}/${r.max_level}<span class="pill"></span><div class="grid2">` +
          ROSTER_FIELDS.map(([f, l]) => `<div>${field(t(l), `rf-${k}-${f}`, r[f], `data-f="${f}"`)}</div>`).join('') +
          `<div>${field(`${t('Elternteil 1')} (${nameOf(r.parent1)})`, `rf-${k}-p1`, r.parent1, 'data-f="parent1" min="0" max="255"')}</div>` +
          `<div>${field(`${t('Elternteil 2')} (${nameOf(r.parent2)})`, `rf-${k}-p2`, r.parent2, 'data-f="parent2" min="0" max="255"')}</div></div>` +
          `<div class="btns"><button class="primary" data-apply="1">${t('Übernehmen')}</button><button data-restore="1">${t('Zurücksetzen')}</button></div></div>`;
      }).join('') : `<p class="hint">${t('Keine Einträge dieses Digimon im Spielstand.')}</p>`;
    } catch (e) { html += `<p class="bad">${esc(e.message)}</p>`; }
  }
  box.innerHTML = html;
  $('#b-roster-open').onclick = async () => {
    try {
      const r = await native('pick_roster');
      if (r) { rosterOpen = true; log('Spielstand: ' + r.name); renderRoster(id); }
    } catch (e) { await fail(e); } finally { setOverlay(false); }
  };
  $$('.pend[data-key]', box).forEach(card => {
    const key = card.dataset.key.split(',').map(Number);
    $('[data-apply]', card).onclick = async () => {
      const fields = {};
      $$('input[data-f]', card).forEach(i => { fields[i.dataset.f] = Number(i.value); });
      try {
        const r = await native('roster_change', key, fields);
        toast(t('Spielstand-Werte vorgemerkt'));
        $('.pill', card).textContent = `${t('Nächstes Level in')} ${r.next_exp}`;
        refreshPending();
      } catch (e) { await fail(e); }
    };
    $('[data-restore]', card).onclick = async () => {
      try { await native('roster_restore', key); refreshPending(); renderRoster(id); } catch (e) { await fail(e); }
    };
  });
}

// ---------------------------------------------------------------- Änderungen
let pendingItems = [];
async function refreshPending() {
  try { pendingItems = state.image ? await native('pending') : []; } catch { pendingItems = []; }
  renderPending();
  refreshHistory();
}
function renderPending() {
  const n = pendingItems.length;
  $('#badge').hidden = n === 0; $('#badge').textContent = n;
  $('#pending-count').textContent = n ? `${n} ${t('vorgemerkt')}` : t('Keine Änderungen vorgemerkt.');
  $('#pending-list').innerHTML = pendingItems.map((p, i) =>
    `<div class="pend"><b>${esc(p.file)}</b><br>${esc(p.label)}<small>${esc(p.detail || '')}${p.shared ? '\n' + esc(t('Gemeinsame Tabelle: Verwerfen setzt alle Änderungen dieser Datei zurück.')) : ''}</small><div class="btns"><button data-i="${i}">${t('Verwerfen')}</button></div></div>`).join('');
  $$('#pending-list button[data-i]').forEach(b => {
    b.onclick = async () => {
      const p = pendingItems[Number(b.dataset.i)];
      if (!(await confirmBox(t('Diese Änderung verwerfen?')))) return;
      try {
        await native('discard', p.kind, p.path ?? null, p.lba ?? null);
        state.catalog = await native('catalog'); state.prefetch.clear(); renderList(); await refreshPending();
        if (state.id != null) loadModel(state.id);
      } catch (e) { await fail(e); }
    };
  });
}
$('#b-saveimg').onclick = async () => {
  if (!pendingItems.some(p => p.kind === 'file')) return toast(t('Keine Änderungen vorgemerkt.'));
  const stem = (state.image?.name || 'dw2').replace(/\.[^.]+$/, '');
  const name = await promptBox(t('Dateiname'), `${stem}_bearbeitet`);
  if (!name) return;
  try {
    const f = await busy('Image wird geprüft und gespeichert …', () => native('save_image', name));
    log(`Image geschrieben: ${f.name} (${(f.size / 1048576).toFixed(0)} MB)`);
    await exportFile(Promise.resolve(f));
  } catch (e) { await fail(e); } finally { setOverlay(false); }
};
$('#b-saveproj').onclick = async () => {
  try { await exportFile(native('save_project', 'dw2_viewer.dw2mod')); } catch (e) { await fail(e); }
};
$('#b-loadproj').onclick = async () => {
  try {
    const r = await native('pick_project');
    if (r) {
      state.catalog = await native('catalog'); state.prefetch.clear(); renderList(); await refreshPending();
      toast(`${r.edits} ${t('vorgemerkt')}`);
      if (state.id != null) loadModel(state.id);
    }
  } catch (e) { await fail(e); } finally { setOverlay(false); }
};
$('#b-overwrite').onclick = async () => {
  if (!pendingItems.some(p => p.kind === 'file')) return toast(t('Keine Änderungen vorgemerkt.'));
  if (!(await confirmBox(t('Dein Original-Image „{n}“ wirklich überschreiben? Die bisherige Fassung bleibt als Sicherung in der App.', { n: state.image?.name || '' })))) return;
  try {
    const f = await busy('Image wird geprüft und gespeichert …', () => native('save_image', 'overwrite'));
    const info = await busy('Original wird überschrieben …', () => native('overwrite_original', f.path));
    state.backup = info.backup;
    $('#b-backup').hidden = !info.backup;
    state.catalog = await native('catalog'); renderList();
    await afterChange(t('Original-Image überschrieben. Bitte im Emulator testen.'));
  } catch (e) { await fail(e); } finally { setOverlay(false); }
};
$('#b-backup').onclick = async () => {
  if (!state.backup) return;
  try { await native('save_export', state.backup, state.backup.split('/').pop()); toast(t('Sicherung gespeichert')); }
  catch (e) { await fail(e); }
};
$('#b-saveroster').onclick = async () => {
  if (!pendingItems.some(p => p.kind === 'roster')) return toast(t('Keine Änderungen vorgemerkt.'));
  try { await exportFile(native('roster_export', '')); } catch (e) { await fail(e); }
};

// ---------------------------------------------------------------- Mehr
$('#lang').onchange = e => { lang = e.target.value; localStorage.setItem('lang', lang); applyLang(); };
$('#b-audit').onclick = async () => {
  try {
    const r = await busy('Alle Modelle werden geprüft …', () => native('animation_audit'));
    const s = r.summary;
    const ok = await modal((box, close) => {
      const line = (k, v) => `<div><b>${esc(t(k))}:</b> ${v}</div>`;
      box.innerHTML = `<h3>${t('Animationsprüfung')}</h3>` +
        line('Modelle', s.models) + line('Fehler', s.errors) + line('Zuordnung über Spieltabelle', s.anim_source_table) +
        line('Mit Augenanimation', s.with_eyes) + line('Mit Texturzyklus', s.with_tex_cycles) +
        line('Mit erweiterter Texturanimation', s.with_tex_extended) + line('Mit Palettenkopie', s.with_palette_copy) +
        line('Mit Halbtransparenz', s.with_semi_faces) + line('Mit Mischmodus ≠ 50 %', s.with_abr_non_average) +
        line('Mit geteilten Animationen', s.with_shared_anims) + line('Ohne Animationen', s.without_anims) +
        line('Mit Tabellenlücken', s.with_table_gaps) + line('Schleife ab Zwischenbild', s.with_loop_offset) +
        line('Mit Scherung/Skalierung', s.with_sheared_keys) + line('Dauer (s)', s.seconds) +
        `<p class="hint">${r.highlight.slice(0, 40).map(h => esc(`#${h.id} ${h.name}: ${h.missing.join(', ')}`)).join('<br>')}</p>` +
        `<div class="btns"><button id="m-no">${t('Schließen')}</button><button id="m-yes" class="primary">${t('Bericht exportieren')}</button></div>`;
      $('#m-no', box).onclick = () => close(false); $('#m-yes', box).onclick = () => close(true);
    });
    log(`${t('Animationsprüfung')}: ${s.models} ${t('Modelle')}, ${s.errors} ${t('Fehler')}`);
    if (ok) {
      await exportFile(Promise.resolve({ path: r.path, name: r.name }));
      await exportFile(Promise.resolve({ path: r.csv, name: r.csv_name }));
    }
  } catch (e) { await fail(e); } finally { setOverlay(false); }
};
$('#b-clear').onclick = async () => {
  try { await native('clear_cache'); state.prefetch.clear(); toast(t('Zwischenspeicher geleert.')); } catch (e) { await fail(e); }
};

(async function init() {
  applyLang();
  try {
    const a = await native('app_info');
    $('#about').textContent = `v${a.version} · ${t('Nur eigene Spiel-Images verwenden. Die App enthält keine Spieldaten.')}`;
    $('#space-hint').textContent = `${t('Freier Speicher')}: ${a.free_mb} MB · ${t('Das Image wird in den App-Speicher kopiert.')}`;
  } catch { /* nur Anzeige */ }
})();
