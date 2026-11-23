import { Viewer } from './viewer.js';
import { EN, EN_PATTERNS } from './i18n.js';
import { makeTranslator, installDomTranslator } from './domtr.js';
import { initAnimEditor } from './animeditor.js';
import { dw3Matches, dw3Rank } from './dw3_search.js';
import { chooseMotion, motionEndText } from './dw3_assignment.js';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const BASE = window.DW2_BASE ?? 'https://appassets.androidplatform.net/viewer/';   // Web-Version: '' (blob:-Adressen)

// ---------------------------------------------------------------- Sprache
let lang = localStorage.getItem('lang') || ((navigator.language || 'de').startsWith('de') ? 'de' : 'en');
const t = (key, p = {}) => {
  let s = lang === 'en' ? (EN[key] ?? key) : key;
  for (const [k, v] of Object.entries(p)) s = s.replaceAll(`{${k}}`, v);
  return s;
};
const trDom = makeTranslator(EN, EN_PATTERNS);
let retranslate = () => {};
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
  retranslate();
  if (window.DW2_DESKTOP && window.__desktopReady) window.__desktopReady.then(() => native('set_language', lang)).catch(() => {});
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

// ---------------------------------------------------------------- Android-App / Web-Version (6.0)
// Mobile Fassung: bearbeitet nur das PS1-Image (BIN/ISO, Modus B). PC-Port-Teile (Mods-Ordner,
// HD-Texturpacks, freie DNA-Regeln, Digitationslevel, Kampfkameras des Ports) gibt es nur am PC.
const MOBILE = !window.DW2_DESKTOP;

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
window.__dw2 = { view, native, get state() { return state; } };   // Testzugang (integration/uitest)
window.__dw2view = view;   // für Diagnose und automatisierte Oberflächentests
view.setLight(1.2);
const nameOf = id => state.catalog.find(c => c.id === id)?.name ?? `#${id}`;

let currentPage = 'start';
function show(page) {
  if (MOBILE) requestAnimationFrame(() => document.querySelector(`.tab[data-page="${page}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' }));
  currentPage = page;
  $$('.page').forEach(p => p.classList.toggle('active', p.id === page));
  $$('.tab').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  layoutDesktopTools();
  if (page === 'page-view' || window.DW2_DESKTOP) requestAnimationFrame(() => view.resize());
  if (page === 'page-edit') renderEdit();
  if (page === 'page-changes') refreshPending();
  if (window.__onPage) window.__onPage(page);
}
$$('.tab').forEach(b => { b.onclick = () => { if (!state.image) return toast(t('Bitte zuerst ein Spiel-Image öffnen.')); show(b.dataset.page); }; });
window.__back = () => {
  if (closeModal) { closeModal(); return true; }
  if (state.image && currentPage !== 'page-list') { show('page-list'); return true; }
  return false;
};

// ---------------------------------------------------------------- Image öffnen
// Zwei getrennte Modi: A = PC-Port (dw2.pak, Mods-Ordner, HD, Level, Kameras), B = PS1-Image (neues Image für Emulatoren).
function showMode(info) {
  const pak = info?.source_kind === 'pak';
  $('#grp-ps1').hidden = pak;
  $('#mode-banner').textContent = pak
    ? t('Modus A: PC-Port. Änderungen gehen als Mod in den Mods-Ordner des Ports (HD-Texturen, Digitationslevel, Kampfkameras, größere Dateien).')
    : t('Modus B: PS1-Image. „Neues Image exportieren“ schreibt ein neues, geprüftes Image (mit CUE) für PS1-Emulatoren; das Original bleibt unverändert. Größere DW3-Importdateien werden im Image verlagert, andere Ersatzdateien müssen in die Originalgröße passen. HD-Texturen, Digitationslevel und Kampfkameras gibt es nur im PC-Port (Modus A, braucht deine dw2.pak).');
  if (MOBILE) $('#mode-banner').textContent = t('PS1-Image: „Neues Image exportieren“ schreibt ein neues, geprüftes Image (mit CUE) für PS1-Emulatoren; das Original bleibt unverändert. Größere DW3-Importdateien werden im Image verlagert.');
  $('#subtitle').dataset.mode = pak ? 'A' : 'B';
}
async function openImage() {
  try {
    const info = await native('pick_image');
    if (!info) return;
    state.image = info; state.id = null; state.loaded = null; state.prefetch.clear(); view.clear();
    $('#b-saveimg').disabled = $('#b-overwrite').disabled = info.source_kind === 'pak';
    showMode(info);
    state.catalog = await native('catalog');
    $('#subtitle').textContent = `${info.name} · ${info.count} Digimon · ${info.source_kind === 'pak' ? t('Modus A: PC-Port') : t('Modus B: PS1-Image')}`;
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
  if (state.id !== id && typeof animEditor !== 'undefined' && animEditor.isOpen()) animEditor.close();
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
    if (info.shadow) view.setShadow(BASE + info.shadow).catch(e => log('Schatten: ' + e.message));
    else if (info.shadow_error) log('Schatten: ' + info.shadow_error);
    renderDiag(info);
    renderDw3Quality(info);
    if (info.hd_available && state.image?.source_kind === 'pak' && $('#o-autohd').checked) {
      try { const h = await native('hd_active', id); if (seq === loadSeq && h) { const hi = await view.setHdPreview(BASE + h.url); log(`HD-Textur ${hi.width}×${hi.height} ${t('angezeigt (wie im PC-Port)')}`); } }
      catch (e) { log('HD: ' + e.message); }
    }
    log(`${info.name}: ${t('geladen')} (${info.seconds} s)`);
    prefetchNeighbours(id);
  } catch (e) {
    if (seq !== loadSeq) return;
    view.clear();
    state.loaded = null;
    $('#anim').replaceChildren();
    $('#v-name').textContent = nameOf(id);
    $('#stage-msg').textContent = t('Modell konnte nicht geladen werden.');
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
    [t('Schatten'), info?.shadow ? t('Originalmodell 0x5B') : (info?.shadow_error || '–')],
  ];
  if (c.legacy) rows.push([t('Hinweis'), t('{n} Clips nur tolerant lesbar', { n: c.legacy })]);
  el.innerHTML = rows.map(([k, v]) => `<div><b>${esc(k)}:</b> ${esc(String(v))}</div>`).join('') +
    [...c.warnings, ...(src?.notes || [])].map(w => `<div class="warn">${esc(w)}</div>`).join('');
}
// DW3-Import: gemessene Verluste gegen das DW3-Original (dw3_native.quality_report)
function renderDw3Quality(info) {
  const q = info?.dw3_quality, card = $('#dw3q-card');
  card.hidden = !q;
  if (!q) return;
  if (q.error) { $('#dw3q-info').innerHTML = `<div class="warn">${esc(q.error)}</div>`; return; }
  const s = q.source, c = q.converted, x = q.texture;
  const lost = s.triangles - c.triangles;
  const db = v => v >= 99 ? t('identisch') : `${v} dB`;
  const rows = [
    [t('Quelle'), `${q.source_name || 'DW3'}: ${s.bones} ${t('Knochen')}, ${s.vertices} Vertices, ${s.triangles} ${t('Dreiecke')}, ${s.pages.length} ${t('Seiten')} (${s.pages.map(p => p.join('×')).join(', ')})`],
    [t('Konvertiert'), `${c.parts} ${t('Teile')}, ${c.triangles} ${t('Dreiecke')}` + (lost ? ` — ${t('{n} Dreiecke weniger (PS1-Optimierung)', { n: lost })}` : ` — ${t('keine Dreiecke verloren')}`)],
    [t('Atlas 1x'), `128×224, ${x.charts} ${t('Bereiche')} (${x.rotated} ${t('gedreht')}), ${t('Maßstab')} ${x.scale}`],
    [t('Textur 1x (Pixel-Look/PS1)'), `${db(x.psnr_1x)}, ${Math.round(x.changed_1x * 100)} % ${t('der Texel abweichend')}`],
    [t('HD-Textur'), x.hd ? `${x.hd.join('×')} (${x.hd_factor}×): ${db(x.psnr_hd)}, ${Math.round(x.changed_hd * 100)} % ${t('der Texel abweichend')}` : t('keine (PS1-Image)')],
    [t('UV-Abweichung'), `Ø ${q.uv.mean}, max ${q.uv.max} ${t('Quelltexel')}`],
    [t('Augen / Gesichtsteile'), `${q.face.eyes} / ${q.face.parts}`],
  ];
  $('#dw3q-info').innerHTML = rows.map(([k, v]) => `<div><b>${esc(k)}:</b> ${esc(String(v))}</div>`).join('') +
    (lost ? `<div class="warn">${esc(t('Geometrie wurde für das PS1-Image reduziert. Im Modus A (PC-Port) bleibt das Modell vollständig.'))}</div>` : '');
  $('#b-dw3-source').disabled = !q.source_url;
  $('#b-dw3-source').onclick = async () => {
    try { await view.load(BASE + q.source_url); toast(t('DW3-Original (Quelle, unverändert)')); } catch (e) { await fail(e); }
  };
  $('#b-dw3-back').onclick = () => loadModel(state.id);
  $('#b-anim-editor').onclick = () => animEditor.open(state.id);
}
const animEditor = initAnimEditor({ $, $$, native, view, t, toast, log, busy, fail, BASE, state, loadModel, esc });
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
// ---------------------------------------------------------------- Original-Hintergrund (DW2)
const prefs = (() => { try { return JSON.parse(localStorage.getItem('dw2bg') || '{}'); } catch { return {}; } })();
function savePrefs() { try { localStorage.setItem('dw2bg', JSON.stringify(prefs)); } catch { /* optional */ } }
function applyDw2Background() {
  const on = prefs.on !== false, speed = prefs.speed || 1;
  $('#o-dw2bg').checked = on; $('#o-dw2speed').value = speed;
  $('#stage').classList.toggle('dw2off', !on);
  $('#stage').style.setProperty('--dw2speed', speed);
  view.setOriginalBackground(on);
  $('#o-shadow').checked = prefs.shadow !== false; view.setShadowVisible(prefs.shadow !== false);
}
/** Spielpixel auf ganze Gerätepixel runden: etwa 260 Spielpixel über die Bühnenbreite (Original: 320). */
function sizeDw2Pixels() {
  const dpr = window.devicePixelRatio || 1, w = $('#stage').clientWidth || 360;
  const px = Math.max(1, Math.round(w * dpr / 260)) / dpr;
  $('#stage').style.setProperty('--px', px);
  const bar = Math.max(1, Math.round(px * dpr * 0.6)) / dpr;   // Bedienleisten: schmalerer Rahmen
  for (const el of [$('#viewbar'), $('#animbar')]) el.style.setProperty('--px', bar);
}
$('#o-shadow').onchange = e => { prefs.shadow = e.target.checked; savePrefs(); view.setShadowVisible(e.target.checked); };
$('#o-dw2bg').onchange = e => { prefs.on = e.target.checked; savePrefs(); applyDw2Background(); };
$('#o-dw2speed').oninput = e => { prefs.speed = Number(e.target.value); savePrefs(); applyDw2Background(); };
new ResizeObserver(sizeDw2Pixels).observe($('#stage'));
applyDw2Background(); sizeDw2Pixels();

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
  try { await native(kind); await afterChange(t(kind === 'undo' ? 'Rückgängig gemacht' : 'Wiederhergestellt')); if (currentPage === 'page-evo') renderDna(); }
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
async function import3dFile(file) {
  try {
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
        if (file.dw3) body += '<p class="hint">DW3-Animationen bleiben im GLB-Export erhalten. Beim nativen DW2-Ersatz werden die Animationen des DW2-Ziels verwendet. Native Größen- und Palettenlimits gelten weiter.</p>';
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
}
$('#b-3d-import').onclick = async () => {
  try { await import3dFile(await native('pick_file')); } catch (e) { await fail(e); }
};

// The DW3 catalog is independent of the selected DW2 replacement slot (desktop, app and web).
{
  const b = document.createElement('button');
  b.id = 'btn-dw3';
  b.className = 'small';
  b.textContent = MOBILE ? 'DW3' : 'DW3-Modelle öffnen';
  b.title = 'DW3-Modelle öffnen';
  $('#btn-open').parentNode.appendChild(b);
  b.onclick = async () => {
    try {
      // Schon geöffnetes DW3-Abbild weiterverwenden (auf dem Handy dauert das Übernehmen des Abbilds lange);
      // ein anderes Abbild öffnet der Reiter DW3-Import („DW3-Abbild öffnen“).
      let info = MOBILE ? await native('dw3_models') : null;
      if (!info?.open) info = await busy('DW3-Dateien werden gesucht …', () => native('pick_dw3'));
      if (!info) return;
      const id = await pickBox(`${info.name} · ${info.models.length} Modelle`, info.models.map(m => ({ value: m.id, label: dw3Label(m) })), null);
      if (id == null) return;
      const action = await modal((box, close) => {
        box.innerHTML = '<h3>DW3-Modell</h3><div class="btns"><button data-c="open">Ansehen / bisherige Knochenzuordnung</button><button data-c="native">DW2-Slot mit DW3-Skelett und Bewegungen ersetzen</button><button data-c="export">GLB mit Texturen und Animationen exportieren (ZIP)</button><button data-c="cancel">Abbrechen</button></div>';
        $$('button[data-c]', box).forEach(x => { x.onclick = () => close(x.dataset.c); });
      });
      if (!action || action === 'cancel') return;
      if (action === 'native') { await nativeDw3Flow(id); return; }
      if (action === 'export') { await exportFile(busy('DW3-Modell wird exportiert …', () => native('export_dw3', id))); return; }
      const model = await busy('DW3-Modell wird konvertiert …', () => native('prepare_dw3', id));
      await import3dFile({ path: model.path, name: model.name, dw3: true });
    } catch (e) { await fail(e); }
  };
}

$('#b-hd-pack').hidden=!window.DW2_DESKTOP;
$('#b-hd-pack').onclick=async()=>{
  if(state.id==null)return toast('Zuerst ein DW2-Modell auswählen.');
  try{const r=await busy('HD-Texturpack wird exportiert …',()=>native('export_hd_dialog',state.id));if(r)toast(`HD-Texturpack ${r.size.join('×')} exportiert. Im PC-Port HD-Modus verwenden.`);}catch(e){await fail(e);}
};

async function nativeDw3Flow(sourceId) {
  if(state.id==null)return toast('Zuerst ein DW2-Ziel auswählen und dw2.pak öffnen.');
  const targetId=state.id;
  const p=await busy('Nativer DW3-Import wird geprüft …',()=>native('dw3_native_plan',sourceId,targetId));
  const choice=await modal((box,close)=>{
    const assignments = p.assignments.map(a => structuredClone(a));
    box.innerHTML=`<h3>${esc(p.name)} → ${esc(p.target)}</h3><p>${p.source_bones} DW3-Knochen ersetzen ${p.target_bones} DW2-Knochen. ${state.image?.source_kind === 'pak' ? 'Benötigt den beiliegenden PC-Port mit Overlay-API 2.' : 'PS1-Image (Modus B): Größere Dateien als das Original werden ans Ende des Images verlagert (Dateitabelle des Spiels angepasst). Nichts wird verkleinert, außer du erlaubst es unten ausdrücklich.'}</p>${p.limits ? `<p class="hint">DW2-Formatgrenzen: ${p.limits.parts} von ${p.limits.max_parts} Modellteilen, ${p.limits.max_depth} von 8 Ebenen${p.limits.split_bones.length ? `; ${p.limits.split_bones.length} große Knochen werden in Teile mit höchstens 256 Vertices geteilt` : ''}${p.limits.flattened_bones.length ? `; ${p.limits.flattened_bones.length} Knochen unter Ebene 8 hängen exakt an Ebene 8` : ''}.</p>` : ''}${p.face ? `<p class="hint">Gesicht: ${p.face.eyes ? 'Augen blinzeln wie in DW3 (Augenrahmen aus DW3 übernommen)' : 'keine DW3-Augenrahmen'}${p.face.parts - p.face.eyes > 0 ? `, ${p.face.parts - p.face.eyes} weitere Gesichtsteile im Zyklus` : ''}${p.face.notes.length ? ' · ' + esc(p.face.notes.join(' ')) : ''}.</p>` : ''}<p class="hint">Vorbelegt aus den DW3-Kampfskripten des Modells (Standby, Treffer, K.o., Angriff) und den Kampfplätzen von DW2. Die Quelle steht neben jedem Platz. Jede Motion lässt sich ändern.</p>`+
    (p.field ? '<p class="hint">Domain-/Feldmodell: Vorhandene Clips statt Kampfplätze. Standby ist vorbelegt; weitere Bewegungen bitte selbst auswählen.</p>' : '')+
    p.assignments.map((a,i)=>`<label>${a.slot}${a.clip}${a.role ? ' · '+esc(a.role) : ''}<select data-motion="${i}">${a.action ? '<option value="" selected>DW3-Vorgabe (Aktionskette)</option>' : ''}${p.motions.map(m=>`<option value="${m.id}" ${!a.action && m.id===a.motion?'selected':''}>Motion ${m.id} · ${m.frames} Bilder · ${esc(motionEndText(m))}</option>`).join('')}</select><input data-loop="${i}" type="checkbox" ${a.loop?'checked':''}> Schleife <small class="hint" data-motion-hint="${i}">${esc(a.reason||'')}</small></label>`).join('')+
    `<label>Größenmaßstab <select id="d-mode"><option value="dw2" selected>DW2-Verhältnisse (${p.heights ? p.heights.dw2 : '–'} hoch)</option><option value="dw3">DW3-Verhältnisse (${p.heights ? p.heights.dw3 : '–'} hoch)</option></select></label>` +
    `<label>Größenfaktor <input id="d-scale" type="number" min="0.1" max="10" step="0.05" value="1"></label><p class="hint" id="d-size">${p.heights ? `Ersetzter Platz: ${p.heights.slot} hoch. ${esc(p.size_source || '')}.` : ''} Später unter Bearbeiten › Größe im Spiel änderbar.</p>`+
    `<label>HD-Textur <select id="d-hd"><option value="0" selected>Automatisch (volle DW3-Auflösung)</option><option value="2">256×512</option><option value="4">512×1024</option><option value="8">1024×2048</option><option value="16">2048×4096</option></select></label>${state.image?.source_kind === 'pak' ? '' : `<label class="row"><input type="checkbox" id="d-reduce"> ${t('Nur falls Verlagern nicht möglich: Verkleinerung für das PS1-Image erlauben')}</label>`}<div class="btns"><button id="d-cancel">Abbrechen</button><button id="d-apply" class="primary">Prüfen und vormerken</button></div>`;
    $('#d-cancel',box).onclick=()=>close(null);
    $$('[data-motion]',box).forEach(select => { select.onchange = () => {
      const i=Number(select.dataset.motion), checkbox=$(`[data-loop="${i}"]`,box);
      if (select.value === '') {
        assignments[i]=structuredClone(p.assignments[i]);
        $(`[data-motion-hint="${i}"]`,box).textContent=p.assignments[i].reason || '';
      } else {
        const motion=p.motions.find(m => m.id === Number(select.value));
        assignments[i]=chooseMotion(p.assignments[i],motion);
        $(`[data-motion-hint="${i}"]`,box).textContent=`Manuell gewählt: Motion ${motion.id} · ${motionEndText(motion)}`;
      }
      checkbox.checked=assignments[i].loop;
    }; });
    $('#d-apply',box).onclick=()=>close({assignments:assignments.map((a,i)=>({...a,loop:$(`[data-loop="${i}"]`,box).checked})),scale:Number($('#d-scale',box).value),hd:Number($('#d-hd',box).value),mode:$('#d-mode',box).value,reduce:!!$('#d-reduce',box)?.checked});
  });
  if(!choice)return;
  const r=await busy('Skelett, Geometrie und Bewegungen werden konvertiert …',()=>native('dw3_native_apply',sourceId,targetId,choice.assignments,choice.scale,choice.hd,null,choice.mode,choice.reduce));
  log(`DW3 nativ: ${r.bones} Knochen, ${r.triangles} Dreiecke, ${r.files} Dateien. ${r.hd_size ? 'HD: ' + r.hd_size.join('×') : 'PS1-Image, ohne HD'}`);
  if (r.ps1) {
    const opt = Object.entries(r.optimized || {});
    await modal((box, close) => {
      box.innerHTML = `<h3>${t('PS1-Image: Import angepasst')}</h3>` +
        ((r.relocated || []).length ? `<p>${t('Größer als das Original, deshalb ans Ende des Images verlagert (keine Verkleinerung):')}</p><ul>${r.relocated.map(x => `<li>${esc(x.file.split('/').pop())}: ${x.original} → ${x.new} Bytes</li>`).join('')}</ul>` : '') +
        (opt.length ? `<p>${t('Mit deiner Zustimmung verkleinert:')}</p><ul>${opt.map(([k, v]) => `<li><b>${esc(k)}</b>: ${esc(v)}</li>`).join('')}</ul><p class="hint">${t('Weniger Dreiecke wirken kantiger, weniger Bilder machen Bewegungen ruckiger. Im PC-Port (Modus A) gibt es diese Grenze nicht.')}</p>` : `<p>${t('Nichts wurde verkleinert: volle Geometrie und alle Bewegungsbilder.')}</p>`) +
        `<p class="hint">${esc(r.note || '')}</p><div class="btns"><button class="primary">OK</button></div>`;
      box.querySelector('button').onclick = () => close(true);
    });
    await afterChange('DW3-Modell und Bewegungen vorgemerkt. Unter Änderungen „Neues Image exportieren“.');
  } else {
    await afterChange('DW3-Modell und Bewegungen vorgemerkt. Unter Änderungen als PC-Port-Mod exportieren.');
  }
  show('page-view');
}

$('#b-port-mod').hidden = !window.DW2_DESKTOP;
$('#b-port-mod').onclick = async () => {
  try {
    // dw2.pak geöffnet: geprüfter Export mit Konflikterkennung; Disc-Image: bisheriger Weg (fragt nach der passenden dw2.pak)
    const pak = state.image?.source_kind === 'pak';
    const result = await busy('PC-Port-Mod wird geprüft und exportiert …', () => native(pak ? 'port_mods_dialog' : 'export_port_dialog', ...(pak ? ['export'] : [])));
    if (result) { log(`${result.count} Mods exportiert: ${result.manifest}`); toast(`${result.count} Mods exportiert. PC-Port neu starten.`); }
  } catch (e) { await fail(e); }
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
  const boxes = ['#f-name', '#f-size', '#f-type', '#f-evolution', '#f-camera', '#f-attacks', '#f-enemy', '#f-roster'];
  if (id == null || !state.image) { $('#edit-name').textContent = t('Digimon wählen'); $('#edit-sub').textContent = ''; boxes.forEach(s => { $(s).innerHTML = ''; }); return; }
  const c = state.catalog.find(x => x.id === id);
  $('#edit-name').textContent = `#${String(id).padStart(3, '0')} ${c.name}`; $('#edit-sub').textContent = ` · ${c.code}`;
  // Größe: erst beim Aufklappen (die Größentabelle aller Digimon braucht beim ersten Mal bis zu einer Minute
  // und hielt sonst jede weitere Aktion auf, z. B. das Umbenennen)
  const sizeCard = $('#f-size').closest('details');
  if (sizeCard.open) renderSize(id);
  else sizeCard.ontoggle = () => { if (sizeCard.open && state.id === id) renderSize(id); };
  renderName(id); renderType(id); renderEvolution(id); renderCamera(id); renderAttacks(id); renderEnemy(id); renderRoster(id);
}
async function renderEvolution(id) {
  const box = $('#f-evolution');
  try {
    const info = await native('evolution_info', id);
    if (state.id !== id) return;
    let rows = info.rows.map(x => ({...x}));
    const draw = () => {
      box.innerHTML = `<label>Stufe <select id="e-rank">${['Rookie','Champion','Ultimate','Mega'].map((x,i)=>`<option value="${i}" ${i===info.rank?'selected':''}>${x}</option>`).join('')}</select></label>` +
        rows.map((r,i)=>`<div class="row"><label>DP ab <input data-dp="${i}" type="number" min="0" max="255" value="${r.min_dp}" ${i===0?'disabled':''}></label><select data-target="${i}">${info.choices.filter(x=>x!==id).map(x=>`<option value="${x}" ${x===r.target?'selected':''}>#${x} ${esc(nameOf(x))}</option>`).join('')}</select><button data-remove="${i}">Entfernen</button></div>`).join('') +
        `<div class="btns"><button id="e-add" ${rows.length>=4?'disabled':''}>Ziel hinzufügen</button><button id="e-save" class="primary">Übernehmen</button></div><p class="hint">Bis zu vier vorhandene Ziele. DP-Grenzen beginnen bei 0. Das letzte Ziel gilt auch für höhere DP. Das Digitationslevel ist keine Eigenschaft dieser Tabelle.</p>`;
      const collect = () => rows.map((r,i)=>({min_dp:i?Number($(`[data-dp="${i}"]`,box).value):0,target:Number($(`[data-target="${i}"]`,box).value)}));
      $$('[data-remove]',box).forEach(b=>{b.onclick=()=>{rows=collect();rows.splice(Number(b.dataset.remove),1);if(rows.length)rows[0].min_dp=0;draw();};});
      $('#e-add',box).onclick=()=>{rows=collect();rows.push({min_dp:rows.length?rows.at(-1).min_dp+1:0,target:info.choices.find(x=>x!==id)});draw();};
      $('#e-save',box).onclick=async()=>{try{await native('set_evolution',id,collect(),Number($('#e-rank',box).value));await afterChange('Digitation / DP vorgemerkt');renderEvolution(id);}catch(e){await fail(e);}};
    };
    draw();
  } catch(e) { errBox(box,e); }
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
        await afterChange(t('Name vorgemerkt'));   // Liste, Änderungen und die Anzeige unter dem 3D-Bild
        renderEdit();
      } catch (e) { await fail(e); }
    };
    $('#b-name-ok').onclick = () => apply($('#in-name').value);
    $('#in-name').onkeydown = ev => { if (ev.key === 'Enter') apply($('#in-name').value); };
    $('#b-name-orig').onclick = () => apply(n.original);
  } catch (e) { errBox(box, e); }
}

async function renderSize(id) {
  const box = $('#f-size');
  if (!box.innerHTML.trim()) box.innerHTML = `<p class="hint">${t('Größentabelle wird berechnet … beim ersten Öffnen eines Images bis zu zwei Minuten, danach sofort.')}</p>`;
  try {
    const z = await native('size_info', id);
    if (state.id !== id) return;
    const sim = z.similar.map(s => `${esc(s.name)} (${s.height})`).join(', ');
    let html = `<p class="hint">Stehhöhe im Spiel: <b>${z.height}</b> Einheiten${z.original_height ? ` (Original ${z.original_height})` : ''}. Ähnlich groß: ${sim}. DW2-Digimon: ${z.range[0]}–${z.range[1]}.</p>`;
    if (z.imported) {
      html += `<label class="row"><span>Maßstab</span><select id="sz-m"><option value="dw2" ${z.size_mode === 'dw2' ? 'selected' : ''}>DW2-Verhältnisse</option><option value="dw3" ${z.size_mode === 'dw3' ? 'selected' : ''}>DW3-Verhältnisse</option></select></label>
        <label class="row"><span>Größenfaktor (×) gegenüber dem Maßstab</span><input type="range" id="sz-f" min="0.3" max="3" step="0.05" value="${z.factor}"><b id="sz-v">${Number(z.factor).toFixed(2)}</b></label>
        <p class="hint" id="sz-pre">Vorschau: etwa ${Math.round(z.height / z.factor * z.factor)} Einheiten.</p>
        <div class="btns"><button id="sz-ok" class="primary">Größe übernehmen (DW3 ${esc(z.source)} neu umsetzen)</button><button id="sz-auto">Automatisch (1,00)</button></div>
        <p class="hint">Die Größe wird in Modell und Bewegungen eingerechnet: Boden, Angriffe und Kamera passen sich mit an. Dafür muss das DW3-Abbild geöffnet sein.</p>`;
    } else {
      html += '<p class="hint">Größe ändern geht bei aus DW3 importierten Digimon (Reiter DW3-Import). Originale behalten ihre Spielgröße.</p>';
    }
    box.innerHTML = html;
    if (!z.imported) return;
    const base = z.height / z.factor;
    $('#sz-f').oninput = () => {
      const f = Number($('#sz-f').value);
      $('#sz-v').textContent = f.toFixed(2);
      const h = Math.round(base * f);
      const near = Object.values(z.similar).length ? '' : '';
      $('#sz-pre').textContent = `Vorschau: etwa ${h} Einheiten (jetzt ${z.height}).${near}`;
      if (view.model) view.model.scale.setScalar(f / z.factor);
    };
    const go = async f => {
      try { await busy('DW3-Modell wird neu umgesetzt …', () => native('dw3_resize', id, f, $('#sz-m').value)); if (view.model) view.model.scale.setScalar(1); await afterChange(`Größe ${f.toFixed(2)} vorgemerkt`); renderEdit(); }
      catch (e) { await fail(e); }
    };
    $('#sz-ok').onclick = () => go(Number($('#sz-f').value));
    $('#sz-auto').onclick = () => go(1);
  } catch (e) { box.innerHTML = `<p class="hint">${esc(e.message)}</p>`; }
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
        if (currentPage === 'page-evo') renderDna();
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
      if (currentPage === 'page-evo') await renderDna();
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
  retranslate = installDomTranslator(document.body, () => lang, trDom);
  applyLang();
  try {
    const a = await native('app_info');
    $('#about').textContent = `v${a.version} · ${t('Nur eigene Spiel-Images verwenden. Die App enthält keine Spieldaten.')}`;
    $('#app-title').textContent = `DW2 MOD STUDIO ${a.version}`;
    $('#app-h2').textContent = `DW2 Mod Studio ${a.version}`;
    document.title = MOBILE ? `DW2 Mod Studio ${a.version}` : `DW2 Mod Studio ${a.version} · PC`;
    $('#space-hint').textContent = MOBILE
      ? (a.free_mb != null ? `${t('Freier Speicher')}: ${a.free_mb} MB · ` : '') + t('Dateien werden nur auf diesem Gerät verarbeitet.')
      : `${t('Freier Speicher')}: ${a.free_mb} MB · ${t('Dateien werden lokal auf diesem PC verarbeitet.')}`;
  } catch { /* nur Anzeige */ }
})();

// Desktop navigation keeps the model visible alongside the selected tools.
window.__desktop = {show, openImage};
document.addEventListener('keydown', e => {
  if (e.target.matches('input,textarea,select,[contenteditable=true]') || closeModal) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'o') { e.preventDefault(); openImage(); }
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); historyStep(e.shiftKey ? 'redo' : 'undo'); }
  else if (e.key === 'ArrowLeft') $('#v-prev').click();
  else if (e.key === 'ArrowRight') $('#v-next').click();
  else if (e.code === 'Space') { e.preventDefault(); $('#play').click(); }
});

document.getElementById('btn-studio').onclick = () => native('open_studio').catch(fail);
if (MOBILE) {
  const hide = el => { if (el) { el.hidden = true; el.style.display = 'none'; } };
  ['btn-studio', 'grp-pc', 'b-hd-pack', 'b-hd-preview', 'b-hd-active', 'b-hd-off', 'lv-card'].forEach(id => hide(document.getElementById(id)));
  const dnaHint = document.querySelector('#dna-card p.hint');
  if (dnaHint) dnaHint.textContent = t('Zwei Partner (Champion oder höher), Ergebnis und Ergebnisstufe wählen. A + B und B + A sind dieselbe Regel. Die Regel wird in die DNA-Tabelle des Digi-Labors im Image geschrieben (STAG2000.PRO, USA-Version). Das Spiel sucht das Ergebnis über Typpaar, die kleinere Stufe und die DNA-Gruppen beider Partner: Teilen sich andere Paare dieselbe Tabellenzelle, stehen sie unter der Regel. Mit einer anderen DNA-Gruppe (0–7) im Digitations-Editor lassen sie sich trennen. Die Ergebnisstufe ist die Stufe der Ergebnisart im Spiel (DIGIMNDT) und gilt überall. Startlevel: Stufe × 10 + 1.');
  const fx = document.getElementById('fx-open');
  if (fx) fx.textContent = t('BIN / ISO öffnen');
}

// Reuse the same controls in a right-hand inspector at desktop widths.
const desktopTools = document.createElement('section');
desktopTools.id = 'page-tools'; desktopTools.className = 'page';
document.querySelector('main').append(desktopTools);
const viewerDetails = [...document.querySelectorAll('#page-view > details.card')];
function layoutDesktopTools() {
  const tools = document.getElementById('page-tools');
  if (!tools) return;
  const wide = window.matchMedia('(min-width:1000px)').matches;
  for (const detail of viewerDetails) (wide ? tools : document.getElementById('page-view')).append(detail);
  tools.classList.toggle('active', wide && ['page-view','page-list'].includes(currentPage));
}
window.addEventListener('resize', layoutDesktopTools);
layoutDesktopTools();

// ---------------------------------------------------------------- PC-Port-Mods verwalten (nichts wird gelöscht)
$('#b-port-off').onclick = async () => {
  if (!(await confirmBox('Alle aktiven Mods im gewählten PC-Port-Ordner deaktivieren? Die Dateien werden nach Mods\\disabled verschoben, nicht gelöscht. Das Spiel lädt danach wieder die Originale.'))) return;
  try {
    const r = await native('port_mods_dialog', 'disable');
    if (r) { log(`PC-Port-Mods deaktiviert (${r.set}): ${r.moved.join(', ')}`); toast(`${r.moved.length} Datei(en) deaktiviert. PC-Port neu starten.`); }
  } catch (e) { await fail(e); } finally { setOverlay(false); }
};
$('#b-port-on').onclick = async () => {
  try {
    const r = await native('port_mods_dialog', 'enable');
    if (r) { log(`PC-Port-Mods aktiviert (${r.set}): ${r.moved.join(', ')}`); toast(`${r.moved.length} Datei(en) aktiviert. PC-Port neu starten.`); }
  } catch (e) { await fail(e); } finally { setOverlay(false); }
};


// ================================================================ 0.17b: Bereiche des Mod Studios
const pad3 = n => String(n).padStart(3, '0');
const numIn = (id, value, min, max) => `<input id="${id}" type="number" min="${min}" max="${max}" value="${value}">`;
const digiName = id => nameOf(id);
// The current value is always an option, also when it is not in the catalogue (map figures
// such as #322): otherwise the select would show and save its first entry instead.
const digiOptions = (current, allowEmpty) => (allowEmpty ? `<option value="0" ${!current ? 'selected' : ''}>— leer —</option>` : '') +
  (current && !state.catalog.some(c => c.id === current) ? `<option value="${current}" selected>#${pad3(current)} (nicht in der Digimon-Liste, unverändert)</option>` : '') +
  state.catalog.map(c => `<option value="${c.id}" ${c.id === current ? 'selected' : ''}>#${pad3(c.id)} ${esc(c.name)}</option>`).join('');
async function refreshCatalogNames() {
  try { state.catalog = await native('catalog'); renderList(); } catch { /* Liste bleibt */ }
}
$('#dl-edit').onclick = () => { if (state.id == null) return toast('Zuerst ein Digimon in der Liste wählen.'); show('page-edit'); };
$('#dl-name').onclick = () => {
  if (state.id == null) return toast('Zuerst ein Digimon in der Liste wählen.');
  show('page-edit');
  setTimeout(() => { const d = $('#f-name')?.closest('details'); if (d) { d.open = true; d.scrollIntoView({ block: 'start' }); } $('#in-name')?.focus(); $('#in-name')?.select(); }, 400);
};
$('#dl-view').onclick = () => { if (state.id == null) return toast('Zuerst ein Digimon in der Liste wählen.'); show('page-view'); };

// ---------------------------------------------------------------- Seitenwechsel
window.__onPage = page => {
  const run = { 'page-files': renderFiles, 'page-attacks': renderAttacksPage, 'page-evo': renderEvoPage,
                'page-domains': renderDomains, 'page-dw3': renderDw3Page }[page];
  if (run) run();
  if (page === 'page-tex') {          // Textur-Editor = Texturkarte der 3D-Ansicht
    show('page-view');
    const card = $('#tex-card'); if (card) { card.open = true; card.scrollIntoView({ behavior: 'smooth' }); }
  }
};
// Reiter ohne geöffnetes Spiel: Datei-Explorer darf auch ohne Image
$$('.tab').forEach(b => { b.onclick = () => {
  if (!state.image && !['page-files', 'page-more'].includes(b.dataset.page)) return toast(t('Bitte zuerst ein Spiel-Image öffnen.'));
  show(b.dataset.page);
}; });

// ---------------------------------------------------------------- 1 Datei-Explorer
let filesCache = null;
async function renderFiles() {
  $('#files-source').textContent = state.image ? `· ${state.image.name}` : '· nichts geöffnet';
  if (!state.image) { $('#fx-list').innerHTML = ''; return; }
  try { filesCache = await native('files_list'); drawFiles(); } catch (e) { await fail(e); }
}
function drawFiles() {
  if (!filesCache) return;
  const q = $('#fx-q').value.toLowerCase().trim(), only = $('#fx-edited').checked;
  const rows = filesCache.files.filter(f => (!only || f.edited) && (!q || f.name.toLowerCase().includes(q) || String(f.lba) === q)).slice(0, 400);
  $('#fx-list').innerHTML = `<table><tr><th>Datei</th><th>LBA</th><th>Bytes</th><th></th><th></th></tr>` + rows.map(f =>
    `<tr class="${f.edited ? 'edited' : ''}"><td>${esc(f.name)}</td><td>${f.lba}</td><td>${f.size}</td><td>${f.edited ? 'geändert' : ''}</td>` +
    `<td><button class="small" data-x="${f.lba}">exportieren</button>${f.edited ? ` <button class="small" data-o="${f.lba}">Original</button>` : ''}</td></tr>`).join('') + '</table>' +
    (rows.length === 400 ? '<p class="hint">Erste 400 Treffer; Suche verfeinern.</p>' : '');
  $$('#fx-list [data-x]').forEach(b => { b.onclick = () => exportFile(native('file_export', Number(b.dataset.x), false)).catch(fail); });
  $$('#fx-list [data-o]').forEach(b => { b.onclick = () => exportFile(native('file_export', Number(b.dataset.o), true)).catch(fail); });
}
$('#fx-q').oninput = drawFiles; $('#fx-edited').onchange = drawFiles;
$('#fx-open').onclick = () => $('#btn-open').click();
$('#fx-dw3').onclick = () => openDw3();
$('#fx-loadproj').onclick = () => $('#b-loadproj').click();
$('#fx-saveproj').onclick = () => $('#b-saveproj').click();

// ---------------------------------------------------------------- 3 Digimon-Editor: Kamera
async function renderCamera(id) {
  const box = $('#f-camera');
  try {
    const c = await native('camera_info', id);
    if (state.id !== id) return;
    box.innerHTML = `<p class="hint">Nahaufnahme-Stufe (MODELDT, 9 Stufen, src/stag3000/camera.c): aktuell Stufe ${c.current.bucket}, Original ${c.original.field_1E} (Stufe ${c.original.bucket}). Beim DW3-Import automatisch.</p>` +
      `<label class="f">Kamerahöhe (${c.limits.field[0]}–${c.limits.field[1]})</label>${numIn('cam-f', c.current.field_1E, ...c.limits.field)}` +
      `<label class="f">Höhe der Treffereffekte (${c.limits.hit[0]}–${c.limits.hit[1]})</label>${numIn('cam-h', c.current.hit_fx_y, ...c.limits.hit)}` +
      `<div class="btns"><button id="cam-up" class="small">Stufe +1</button><button id="cam-down" class="small">Stufe −1</button><button id="cam-orig" class="small">Original</button><button id="cam-save" class="primary">Übernehmen</button></div>` +
      `<hr><b>Kampfkamera je Digimon (Angriff, Ziel, Nahaufnahme)</b><p class="hint">Wirkt mit dem mitgelieferten PC-Port ab 1.0 (Mods\\battle_camera.json). Abstand in % der Spielkamera, Höhen in Spieleinheiten, Winkel in 1/4096 Umdrehung. Leer = Kamera des Spiels.</p>` +
      `<div id="bc-box">lädt …</div>`;
    $('#cam-up').onclick = () => { $('#cam-f').value = Math.min(c.limits.field[1], Number($('#cam-f').value) + 256); };
    $('#cam-down').onclick = () => { $('#cam-f').value = Math.max(c.limits.field[0], Number($('#cam-f').value) - 256); };
    $('#cam-orig').onclick = () => { $('#cam-f').value = c.original.field_1E; $('#cam-h').value = c.original.hit_fx_y; };
    $('#cam-save').onclick = async () => {
      try { await native('camera_set', id, Number($('#cam-f').value), Number($('#cam-h').value)); await afterChange('Kamera vorgemerkt'); renderCamera(id); }
      catch (e) { await fail(e); }
    };
    if (!MOBILE) renderBattleCam(id);
    else { const bc = $('#bc-box'); for (let i = 0; i < 3 && bc?.previousElementSibling; i++) bc.previousElementSibling.remove(); bc?.remove(); }
  } catch (e) { box.innerHTML = `<p class="hint">${esc(e.message)}</p>`; }
}

const SHOT_NAMES = { closeup: 'Nahaufnahme', attack0: 'Angriff A', attack1: 'Angriff B', attack2: 'Angriff C', target: 'Ziel' };
let bcState = null;
async function renderBattleCam(id, setting) {
  const box = $('#bc-box');
  if (!box) return;
  try {
    const info = await native('battle_camera_info', id, setting ?? null);
    if (state.id !== id) return;
    bcState = { id, info, key: bcState?.id === id ? bcState.key : '0:attack0' };
    const s = info.setting, cl = s.closeup || {};
    const f = (k, v, lo, hi) => `<input data-bc="${k}" type="number" min="${lo}" max="${hi}" value="${v ?? ''}" placeholder="Spiel">`;
    const bad = info.checks.filter(r => !r.fits);
    box.innerHTML =
      `<div class="row">Angriff/Ziel: Abstand ${f('distance', s.distance, 25, 400)} % Höhe ${f('height', s.height, -20000, 20000)} Blickpunkt ${f('target', s.target, -20000, 20000)} Winkel ${f('angle', s.angle, -4095, 4095)}</div>` +
      `<div class="row">Nahaufnahme: Abstand ${f('c.distance', cl.distance, 25, 400)} % Höhe ${f('c.height', cl.height, -20000, 20000)} Blickpunkt ${f('c.target', cl.target, -20000, 20000)} Winkel ${f('c.angle', cl.angle, -4095, 4095)}</div>` +
      `<p class="${bad.length ? 'warn' : 'hint'}">${bad.length ? t('In {n} von {m} Einstellungen ragt das Digimon aus dem Bild ({s}).', { n: bad.length, m: info.checks.length, s: [...new Set(bad.map(r => t(SHOT_NAMES[r.shot])))].join(', ') }) : t('In allen {m} Einstellungen (6 Kampfplätze) ganz im Bild.', { m: info.checks.length })} ${t('Größe: {h} hoch, Radius {r}.', { h: info.box[1] - info.box[0], r: info.box[2] })}</p>` +
      `<div class="btns"><button id="bc-auto" class="small">Automatisch (ganz im Bild)</button><button id="bc-game" class="small">Kamera des Spiels</button><button id="bc-view" class="small">Vorschau wie im Kampf</button><button id="bc-save" class="primary">Übernehmen</button></div>`;
    const read = () => {
      const o = {}, c2 = {};
      $$('[data-bc]', box).forEach(x => { if (x.value === '') return; const [a, b] = x.dataset.bc.split('.'); if (b) c2[b] = Number(x.value); else o[a] = Number(x.value); });
      if (Object.keys(c2).length) o.closeup = c2;
      return o;
    };
    $$('[data-bc]', box).forEach(x => { x.onchange = () => renderBattleCam(id, read()).then(() => { if (view.savedCam) showShot(); }); });
    $('#bc-auto').onclick = () => renderBattleCam(id, info.auto).then(() => { if (view.savedCam) showShot(); });
    $('#bc-game').onclick = () => renderBattleCam(id, {}).then(() => { if (view.savedCam) showShot(); });
    $('#bc-save').onclick = async () => {
      try { await native('battle_camera_set', id, Object.keys(read()).length ? read() : null); await afterChange('Kampfkamera vorgemerkt'); renderBattleCam(id); }
      catch (e) { await fail(e); }
    };
    $('#bc-view').onclick = () => { show('page-view'); $('#cam-overlay').hidden = false; showShot(); };
  } catch (e) { box.innerHTML = `<p class="hint">${esc(e.message)}</p>`; }
}
const SHOT_KEYS = [];
for (let i = 0; i < 6; i++) for (const n of ['closeup', 'attack0', 'attack1', 'attack2', 'target']) SHOT_KEYS.push(`${i}:${n}`);
function showShot() {
  if (!bcState) return;
  const v = bcState.info.views[bcState.key];
  if (!v) return;
  view.battleCamera(v);
  const [pos, name] = bcState.key.split(':');
  const row = bcState.info.checks.find(r => r.position === Number(pos) && r.shot === name);
  $('#cam-ov-text').textContent = `#${pad3(bcState.id)} · ${SHOT_NAMES[name]} · Platz ${Number(pos) + 1}${Number(pos) < 3 ? ' (Team)' : ' (Gegner)'} · ${row?.fits ? 'ganz im Bild' : 'ragt heraus'}`;
}
$('#cam-ov-up').onclick = () => { if (!bcState) return; bcState.key = SHOT_KEYS[(SHOT_KEYS.indexOf(bcState.key) + 1) % SHOT_KEYS.length]; showShot(); };
$('#cam-ov-down').onclick = () => { if (!bcState) return; bcState.key = SHOT_KEYS[(SHOT_KEYS.indexOf(bcState.key) + SHOT_KEYS.length - 1) % SHOT_KEYS.length]; showShot(); };
$('#cam-ov-end').onclick = () => { view.endBattleCamera(); $('#cam-overlay').hidden = true; };

// ---------------------------------------------------------------- 4 Attacken-Editor
let techCache = null;
async function renderAttacksPage() {
  $('#at-sub').textContent = state.id != null ? `· gewählt: #${pad3(state.id)} ${digiName(state.id)}` : '· kein Digimon gewählt';
  try {
    techCache = (await native('techniques_catalog')).techniques; drawTechs();
    const b = await native('technique_budget');
    $('#at-budget').textContent = `Freie Technik-IDs: ${b.free_count} von 255 (${b.existing} belegt). ${b.reason}`;
  } catch (e) { await fail(e); }
}
const PART_NAMES = { effect: 'Effekte (Grafikteile, FX-Dateien)', sound: 'Ton / Ruf (XA)', status: 'Zustandseffekte', animation: 'Startanimation F/G/H' };
$('#at-parts').onclick = async () => {
  if (state.id == null) return toast('Zuerst ein Digimon wählen (Reiter Digimon).');
  const own = techCache.filter(r => r.users.length === 1 && r.users[0] === state.id);
  if (!own.length) return toast('Dieses Digimon hat noch keine eigene Technik. Zuerst „Eigene Technik … anlegen“.');
  const c = await modal((box, close) => {
    box.innerHTML = `<h3>Teile in eigene Technik übernehmen · #${pad3(state.id)} ${esc(digiName(state.id))}</h3>` +
      `<label class="f">Eigene Technik</label><select id="p-dst">${own.map(r => `<option value="${r.id}">${r.id} · ${esc(r.name)}</option>`).join('')}</select>` +
      `<label class="f">Von Technik</label><select id="p-src">${techCache.map(r => `<option value="${r.id}">${r.id} · ${esc(r.name)}</option>`).join('')}</select>` +
      Object.entries(PART_NAMES).map(([k, n]) => `<label class="row"><input type="checkbox" data-part="${k}" ${k === 'effect' ? 'checked' : ''}> ${esc(n)}</label>`).join('') +
      '<p class="hint">Die Trefferhöhe ist ein Wert des Digimon (Reiter Digimon, Karte Kamera), nicht der Technik.</p>' +
      '<div class="btns"><button id="p-no">Abbrechen</button><button id="p-ok" class="primary">Vormerken</button></div>';
    $('#p-no', box).onclick = () => close(null);
    $('#p-ok', box).onclick = () => close({ dst: Number($('#p-dst', box).value), src: Number($('#p-src', box).value), parts: $$('[data-part]', box).filter(x => x.checked).map(x => x.dataset.part) });
  });
  if (!c) return;
  try { const r = await native('technique_copy_parts', c.dst, c.src, c.parts, state.id); await afterChange(r.changed ? `Technik ${c.dst}: ${c.parts.length} Teil(e) von ${c.src} übernommen` : 'Keine Änderung'); renderAttacksPage(); }
  catch (e) { await fail(e); }
};
$('#at-assign').onclick = async () => {
  const tech = await pickBox('Welche Technik?', techCache.map(r => ({ value: r.id, label: `${r.id} · ${r.name}` })), null);
  if (tech == null) return;
  const ids = await modal((box, close) => {
    box.innerHTML = `<h3>Technik ${tech} als erlernbare Technik für …</h3><input id="m-q" type="search" placeholder="Suchen …"><div id="m-l" class="tablebox"></div>` +
      '<p class="hint">Ersetzt bei jedem gewählten Digimon die erlernbare Technik (DIGIMNDT). Ein Rückgängig-Schritt.</p><div class="btns"><button id="m-no">Abbrechen</button><button id="m-yes" class="primary">Vormerken</button></div>';
    const chosen = new Set(state.id != null ? [state.id] : []);
    const draw = () => {
      const q = $('#m-q', box).value.toLowerCase();
      $('#m-l', box).innerHTML = state.catalog.filter(c => `#${pad3(c.id)} ${c.name}`.toLowerCase().includes(q))
        .map(c => `<label class="row"><input type="checkbox" data-d="${c.id}" ${chosen.has(c.id) ? 'checked' : ''}> #${pad3(c.id)} ${esc(c.name)}</label>`).join('');
      $$('[data-d]', box).forEach(x => { x.onchange = () => { x.checked ? chosen.add(Number(x.dataset.d)) : chosen.delete(Number(x.dataset.d)); }; });
    };
    $('#m-q', box).oninput = draw; draw();
    $('#m-no', box).onclick = () => close(null); $('#m-yes', box).onclick = () => close([...chosen]);
  });
  if (!ids || !ids.length) return;
  try { const r = await native('technique_assign', tech, ids); await afterChange(`Technik ${tech} für ${r.changed.length} Digimon vorgemerkt`); renderAttacksPage(); }
  catch (e) { await fail(e); }
};
function drawTechs() {
  if (!techCache) return;
  const q = $('#at-q').value.toLowerCase().trim();
  const rows = techCache.filter(r => !q || r.name.toLowerCase().includes(q) || String(r.id) === q);
  $('#at-list').innerHTML = '<table><tr><th>ID</th><th>Name</th><th>MP</th><th>Stärke</th><th>Element</th><th>Start-Anim.</th><th>genutzt von</th><th></th></tr>' + rows.map(r => {
    const own = state.id != null && r.users.length === 1 && r.users[0] === state.id;
    return `<tr><td>${r.id}</td><td>${esc(r.name)}</td><td>${r.mp}</td><td>${r.power}</td><td>${r.specialty}</td><td>${'FGH'[r.cast] ?? r.cast}</td>` +
      `<td>${r.users.slice(0, 4).map(u => esc(digiName(u))).join(', ')}${r.users.length > 4 ? ` +${r.users.length - 4}` : ''}</td>` +
      `<td>${own ? `<button class="small" data-e="${r.id}">bearbeiten</button>` : ''} <button class="small" data-c="${r.id}">als Vorlage</button></td></tr>`;
  }).join('') + '</table>';
  $$('#at-list [data-c]').forEach(b => { b.onclick = () => techDialog(Number(b.dataset.c), null); });
  $$('#at-list [data-e]').forEach(b => { b.onclick = () => techDialog(null, Number(b.dataset.e)); });
}
$('#at-q').oninput = drawTechs;
$('#at-new').onclick = () => techDialog(null, null);
async function techDialog(sourceId, editId) {
  if (state.id == null) return toast('Zuerst ein Digimon wählen (Reiter Digimon).');
  const digimon = state.id;
  const src = techCache.find(r => r.id === (editId ?? sourceId)) || techCache[0];
  const enemy = editId == null ? await native('enemy_values', digimon).catch(() => ({ rows: [] })) : { rows: [] };
  const choice = await modal((box, close) => {
    box.innerHTML = `<h3>${editId == null ? 'Eigene Technik anlegen' : 'Eigene Technik bearbeiten'} · #${pad3(digimon)} ${esc(digiName(digimon))}</h3>` +
      (editId == null ? `<label class="f">Vorlage (Effekte, Animationsteile, Ton)</label><select id="t-src">${techCache.map(r => `<option value="${r.id}" ${r.id === src.id ? 'selected' : ''}>${r.id} · ${esc(r.name)}</option>`).join('')}</select>` : '') +
      `<label class="f">Name (höchstens 17 Zeichen)</label><input id="t-name" type="text" maxlength="17" value="${esc(editId == null ? '' : src.name)}">` +
      (editId == null ? '<label class="f">Beschreibung (optional, sonst die der Vorlage)</label><input id="t-desc" type="text" maxlength="120">' : '') +
      `<label class="f">MP-Kosten</label>${numIn('t-mp', src.mp, 0, 255)}<label class="f">Stärke (power)</label>${numIn('t-pow', src.power, -32768, 32767)}` +
      `<label class="f">Element / Spezialität (Code 0–15)</label>${numIn('t-spec', src.specialty, 0, 15)}` +
      `<label class="f">Startanimation</label><select id="t-cast">${['F', 'G', 'H', '(3)'].map((n, i) => `<option value="${i}" ${i === src.cast ? 'selected' : ''}>${n}</option>`).join('')}</select>` +
      (editId == null ? `<label class="row"><input type="checkbox" id="t-def" checked> als erlernbare Technik dieses Digimon</label>` +
        (enemy.rows || []).map((r, i) => `<label class="row"><input type="checkbox" data-enc="${i}"> Gegnergruppe ${r.key[0]}, Platz ${r.key[1] + 1}</label>`).join('') : '') +
      '<div class="btns"><button id="t-no">Abbrechen</button><button id="t-ok" class="primary">Vormerken</button></div>';
    $('#t-no', box).onclick = () => close(null);
    $('#t-ok', box).onclick = () => close({
      source: editId == null ? Number($('#t-src', box).value) : null, name: $('#t-name', box).value.trim(),
      description: editId == null ? $('#t-desc', box).value.trim() : null,
      values: { mp: Number($('#t-mp', box).value), power: Number($('#t-pow', box).value), specialty: Number($('#t-spec', box).value), cast: Number($('#t-cast', box).value) },
      asDefault: editId == null ? $('#t-def', box).checked : false,
      encounters: editId == null ? $$('[data-enc]', box).filter(x => x.checked).map(x => enemy.rows[Number(x.dataset.enc)].key) : [] });
  });
  if (!choice) return;
  try {
    if (editId == null) {
      const r = await native('technique_create', digimon, choice.source, choice.name, choice.description, choice.values, choice.asDefault, choice.encounters);
      await afterChange(`Eigene Technik ${r.id} „${choice.name}“ vorgemerkt`);
    } else {
      await native('technique_edit', editId, digimon, choice.values, choice.name);
      await afterChange('Technik geändert');
    }
    renderAttacksPage();
  } catch (e) { await fail(e); }
}

// ---------------------------------------------------------------- 5 Digitations-Editor (Linie)
async function renderDna() {
  try {
    const data = await native('dna_info');
    const choices = [...data.choices].sort((a,b) => a.id-b.id);
    for (const field of ['a', 'b', 'result']) {
      const el = $('#dna-' + field), old = el.value;
      el.innerHTML = choices.map(c => `<option value="${c.id}">#${pad3(c.id)} ${esc(c.name)}</option>`).join('');
      if (choices.some(c => String(c.id) === old)) el.value = old;
      else if (field === 'a' && choices.some(c => c.id === state.id)) el.value = String(state.id);
      else if (field === 'b' && choices.length > 1) el.value = String(choices[1].id);
    }
    const label = id => `#${pad3(id)} ${choices.find(c => c.id === id)?.name || ''}`;
    $('#dna-list').innerHTML = data.rules.map((r, i) => `<div class="row"><span>${esc(label(r.a))} + ${esc(label(r.b))} → ${esc(label(r.result))} (${['Rookie','Champion','Ultra','Mega'][r.rank]})${r.problem ? `<br><small class="bad">${esc(r.problem)}</small>` : ''}${r.shared?.length ? `<br><small class="hint">${esc(t('Gilt im Spiel auch für'))}: ${r.shared.slice(0, 12).map(x => `#${pad3(x.a)} + #${pad3(x.b)}`).join(', ')}${r.shared.length > 12 ? ' …' : ''}</small>` : ''}</span><button data-dna-edit="${i}">Bearbeiten</button><button data-dna-delete="${i}">Löschen</button></div>`).join('');
    $$('[data-dna-edit]').forEach(el => el.onclick = () => {
      const r = data.rules[Number(el.dataset.dnaEdit)];
      for (const key of ['a','b','result','rank']) $('#dna-' + key).value = String(r[key]);
    });
    $$('[data-dna-delete]').forEach(el => el.onclick = async () => {
      try {
        const r = data.rules[Number(el.dataset.dnaDelete)];
        await native('dna_remove', r.a, r.b); await afterChange('DNA-Regel entfernt'); await renderDna();
      } catch (e) { await fail(e); }
    });
    $('#dna-note').textContent = MOBILE && data.image === false ? data.problem
      : MOBILE ? (data.rules.length ? t('{n} DNA-Regeln vorgemerkt. „Neues Image exportieren“ schreibt sie in die DNA-Tabelle des Digi-Labors im Image.', { n: data.rules.length }) : t('Keine eigenen DNA-Regeln: Das Spiel verwendet seine normalen Kombinationen.'))
      : data.rules.length ? `${data.rules.length} DNA-Regeln vorgemerkt. Als Projekt speichern oder über „Mod installieren“ in den PC-Port übernehmen.` : 'Keine eigenen DNA-Regeln: Das Spiel verwendet seine normalen Kombinationen.';
  } catch (e) { $('#dna-note').textContent = e.message; }
}
$('#dna-save').onclick = async () => {
  try {
    await native('dna_set', ...['a','b','result','rank'].map(k => Number($('#dna-' + k).value)));
    await afterChange('DNA-Regel gespeichert'); await renderDna();
  } catch (e) { await fail(e); }
};

let evoLine = [];
async function renderEvoPage() {
  renderDna();
  renderLevels();
  if (state.id == null) { $('#evo-sub').textContent = '· zuerst ein Digimon wählen'; $('#evo-line').innerHTML = ''; return; }
  $('#evo-sub').textContent = `· ab #${pad3(state.id)} ${digiName(state.id)}`;
  try {
    evoLine = [];
    const seen = new Set();
    let frontier = [state.id];
    for (let depth = 0; depth < 4 && frontier.length; depth++) {
      const next = [];
      for (const id of frontier) {
        if (seen.has(id)) continue; seen.add(id);
        const info = await native('evolution_info', id);
        evoLine.push({ id, rank: info.rank, dna_group: info.dna_group, rows: info.rows, choices: info.choices });
        info.rows.forEach(r => next.push(r.target));
      }
      frontier = next;
    }
    drawEvo();
  } catch (e) { $('#evo-line').innerHTML = `<p class="hint">${esc(e.message)}</p>`; }
}
function drawEvo() {
  $('#evo-line').innerHTML = evoLine.map((d, i) => `<div class="card"><b>#${pad3(d.id)} ${esc(digiName(d.id))}</b>
    <label class="f">Stufe</label><select data-rank="${i}">${['Rookie', 'Champion', 'Ultimate', 'Mega'].map((n, k) => `<option value="${k}" ${k === d.rank ? 'selected' : ''}>${n}</option>`).join('')}</select>
    <label class="f">${t('DNA-Gruppe')}</label><select data-dnag="${i}">${[0, 1, 2, 3, 4, 5, 6, 7, 8].concat(d.dna_group > 8 ? [d.dna_group] : []).map(g => `<option value="${g}" ${g === d.dna_group ? 'selected' : ''}>${g}${g === 8 ? ' · ' + t('nur Bossformen (kein DNA)') : ''}</option>`).join('')}</select>
    ${[0, 1, 2, 3].map(k => { const r = d.rows[k] || { min_dp: k ? '' : 0, target: 0 };
      return `<div class="row">DP ab <input data-dp="${i}:${k}" type="number" min="0" max="255" value="${r.min_dp}" ${k === 0 ? 'readonly' : ''}> → <select data-tg="${i}:${k}"><option value="0">— kein Ziel —</option>${d.choices.filter(c => c !== d.id).map(c => `<option value="${c}" ${c === r.target ? 'selected' : ''}>#${pad3(c)} ${esc(digiName(c))}</option>`).join('')}</select></div>`; }).join('')}
    <button class="small" data-rm="${i}">aus Linie entfernen</button></div>`).join('');
  $$('[data-rm]').forEach(b => { b.onclick = () => { evoLine.splice(Number(b.dataset.rm), 1); drawEvo(); }; });
}
function readEvo() {
  return evoLine.map((d, i) => {
    const rows = [];
    for (let k = 0; k < 4; k++) {
      const target = Number($(`[data-tg="${i}:${k}"]`).value), dp = $(`[data-dp="${i}:${k}"]`).value;
      if (!target) break;
      rows.push({ min_dp: Number(dp || 0), target });
    }
    return { id: d.id, rows, rank: Number($(`[data-rank="${i}"]`).value), dna_group: Number($(`[data-dnag="${i}"]`).value) };
  });
}
$('#evo-add').onclick = async () => {
  const id = await pickBox('Digimon zur Linie', state.catalog.map(c => ({ value: c.id, label: `#${pad3(c.id)} ${c.name}` })), null);
  if (id == null || evoLine.some(d => d.id === id)) return;
  try { const info = await native('evolution_info', id); evoLine.push({ id, rank: info.rank, dna_group: info.dna_group, rows: info.rows, choices: info.choices }); drawEvo(); } catch (e) { await fail(e); }
};
async function renderLevels() {
  try {
    const r = await native('digivolve_levels_info');
    $('#lv-note').textContent = r.note + ` Format ${r.format}, Export als Mods\\digivolve_levels.json.`;
    $('#lv-who').textContent = state.id != null ? `#${pad3(state.id)} ${digiName(state.id)}` : 'kein Digimon gewählt';
    $('#lv-val').value = state.id != null ? (r.levels[String(state.id)] ?? '') : '';
    const rows = Object.entries(r.levels);
    $('#lv-list').textContent = rows.length ? 'Gespeichert (ohne Wirkung im aktuellen Port): ' + rows.map(([k, v]) => `#${pad3(Number(k))} ab ${v}`).join(', ') : 'Keine eigenen Werte gespeichert.';
  } catch (e) { $('#lv-note').textContent = e.message; }
}
$('#lv-set').onclick = async () => {
  if (state.id == null) return toast('Zuerst ein Digimon wählen.');
  try { await native('digivolve_level_set', state.id, Number($('#lv-val').value) || null); await afterChange('Digitationslevel gespeichert (Vorbereitung, im aktuellen Port ohne Wirkung)'); renderLevels(); } catch (e) { await fail(e); }
};
$('#lv-clear').onclick = async () => {
  if (state.id == null) return;
  try { await native('digivolve_level_set', state.id, null); await afterChange('Digitationslevel: Spielregel'); renderLevels(); } catch (e) { await fail(e); }
};
$('#evo-check').onclick = async () => {
  try {
    const r = await native('evolution_validate');
    const list = (items, cls) => items.map(i => `<li class="${cls}">${esc(i.text)}</li>`).join('');
    $('#evo-report').innerHTML = `<p><b>${r.errors.length ? r.errors.length + ' Fehler' : 'Keine Fehler'}</b>, ${r.warnings.length} Hinweise, ${r.info.length} nicht erreichbare Arten.</p>` +
      `<ul>${list(r.errors, 'err')}${list(r.warnings, 'warn')}</ul>` + (r.info.length ? `<details><summary>Nicht durch normale Digitation erreichbar (${r.info.length})</summary><ul>${list(r.info, '')}</ul></details>` : '');
  } catch (e) { await fail(e); }
};
$('#evo-save').onclick = async () => {
  try { const r = await native('evolution_line', readEvo()); await afterChange(r.changed.length ? `Digitationslinie vorgemerkt: ${r.changed.length} Digimon` : 'Keine Änderung'); renderEvoPage(); }
  catch (e) { await fail(e); }
};

// ---------------------------------------------------------------- 6 Domain-Editor
let domCache = null, groupsCache = null;
async function renderDomains() {
  try {
    domCache = (await native('domains_overview')).domains;
    groupsCache = await native('groups_list');
    $('#dom-sub').textContent = `· ${domCache.length} Domains, ${groupsCache.groups.length} Gegnergruppen (${groupsCache.free} IDs frei)`;
    const cur = Number($('#dom-pick').value || 0);
    $('#dom-pick').innerHTML = domCache.map(d => `<option value="${d.index}" ${d.index === cur ? 'selected' : ''}>${d.index}: ${esc(d.name.replace(/1F$/, ''))} (${d.floors.length} Etagen)</option>`).join('');
    const gcur = Number($('#grp-pick').value || groupsCache.groups[0]?.id);
    $('#grp-pick').innerHTML = groupsCache.groups.map(g => `<option value="${g.id}" ${g.id === gcur ? 'selected' : ''}>Gruppe ${g.id}: ${esc(g.members.join(', '))}</option>`).join('');
    drawFloors(); drawGroup();
  } catch (e) { await fail(e); }
}
const groupOptions = cur => `<option value="0" ${!cur ? 'selected' : ''}>—</option>` +
  (cur && !groupsCache.groups.some(g => g.id === cur) ? `<option value="${cur}" selected>${cur}: (fehlt in ENEMYSET)</option>` : '') + groupsCache.groups.map(g => `<option value="${g.id}" ${g.id === cur ? 'selected' : ''}>${g.id}: ${esc(g.members.join(', ').slice(0, 40))}</option>`).join('');
function drawFloors() {
  const d = domCache[Number($('#dom-pick').value || 0)];
  $('#dom-floors').innerHTML = d.floors.map(f => `<div class="row"><b>${esc(f.name)}</b> ${f.sets.map((s, k) => `<select data-fs="${f.floor}:${k}" ${k === 0 ? 'title="Platz 0: beim Erzeugen nicht gelesen"' : ''}>${groupOptions(s)}</select>`).join('')}
    <button class="small" data-fsave="${f.floor}">übernehmen</button></div>`).join('');
  $$('[data-fsave]').forEach(b => { b.onclick = async () => {
    const floor = Number(b.dataset.fsave), sets = [0, 1, 2, 3, 4].map(k => Number($(`[data-fs="${floor}:${k}"]`).value));
    try { const r = await native('domain_set_floor', d.index, floor, sets); await afterChange(r.changed ? `${d.floors[floor].name}: Gruppen vorgemerkt` : 'Keine Änderung'); renderDomains(); }
    catch (e) { await fail(e); }
  }; });
}
$('#dom-pick').onchange = drawFloors;
async function drawGroup() {
  const id = Number($('#grp-pick').value);
  if (!id) return;
  try {
    const g = await native('group_info', id);
    const h = g.header;
    $('#grp-edit').innerHTML = `<p class="hint">Verwendet in: ${g.usage.map(u => esc(u.name)).join(', ') || 'keiner Etage'}</p>
      <label class="f">Figur auf der Karte</label><select id="g-map">${digiOptions(h.map_digimon, false)}</select>
      <label class="f">KI-Typ (0–15)</label>${numIn('g-ai', h.ai, 0, 15)}<label class="f">Tempo (0–15)</label>${numIn('g-pace', h.pace, 0, 15)}
      <label class="f">Lieblingsgeschenk</label>${numIn('g-gift', h.liked_gift, 0, 255)}<label class="f">Punkte pro Level</label>${numIn('g-ppl', h.points_per_level, -32768, 32767)}
      <label class="f">Domain-Musik (0/1)</label>${numIn('g-bgm', h.dungeon_bgm, 0, 15)}<label class="f">Bosskampf (0/1)</label>${numIn('g-boss', h.boss, 0, 15)}` +
      g.members.map((m, i) => `<div class="card"><b>Gegner ${i + 1}</b><select data-m="${i}:digimon">${digiOptions(m.digimon, true)}</select>
        ${[['level', 'Level', 0, 99], ['hp', 'HP', 0, 9999], ['mp', 'MP', 0, 9999], ['attack', 'Angriff', 0, 255], ['defense', 'Abwehr', 0, 999], ['speed', 'Tempo', 0, 255]]
          .map(([k, n, lo, hi]) => `<label class="f">${n}</label><input data-m="${i}:${k}" type="number" min="${lo}" max="${hi}" value="${m[k]}">`).join('')}
        <label class="f">Techniken (IDs)</label>${[0, 1, 2].map(k => `<input data-s="${i}:${k}" type="number" min="0" max="255" value="${m.skills[k]}">`).join('')}</div>`).join('') +
      '<div class="btns"><button id="g-save" class="primary">Gruppe übernehmen</button></div>';
    $('#g-save').onclick = async () => {
      const header = { map_digimon: Number($('#g-map').value), ai: Number($('#g-ai').value), pace: Number($('#g-pace').value), liked_gift: Number($('#g-gift').value),
                       points_per_level: Number($('#g-ppl').value), dungeon_bgm: Number($('#g-bgm').value), boss: Number($('#g-boss').value) };
      const members = g.members.map((m, i) => {
        const out = { skills: [0, 1, 2].map(k => Number($(`[data-s="${i}:${k}"]`).value)) };
        for (const k of ['digimon', 'level', 'hp', 'mp', 'attack', 'defense', 'speed']) out[k] = Number($(`[data-m="${i}:${k}"]`).value);
        return out;
      });
      try { const r = await native('group_set', id, header, members); await afterChange(r.changed ? `Gegnergruppe ${id} vorgemerkt` : 'Keine Änderung'); renderDomains(); }
      catch (e) { await fail(e); }
    };
  } catch (e) { $('#grp-edit').innerHTML = `<p class="hint">${esc(e.message)}</p>`; }
}
$('#grp-pick').onchange = drawGroup;
$('#grp-clone').onclick = async () => {
  try { const r = await native('group_clone', Number($('#grp-pick').value)); await afterChange(`Neue Gegnergruppe ${r.id}`); await renderDomains(); $('#grp-pick').value = r.id; drawGroup(); }
  catch (e) { await fail(e); }
};

// ---------------------------------------------------------------- 7 DW3-Importer
let dw3Cache = null; const dw3Batch = [];
async function openDw3() {
  try { const info = await busy('DW3-Dateien werden gesucht …', () => native('pick_dw3')); if (info) { toast(`${info.models.length} DW3-Modelle`); renderDw3Page(); } }
  catch (e) { await fail(e); }
}
$('#dw3-open').onclick = openDw3;
async function renderDw3Page() {
  try {
    dw3Cache = await native('dw3_models');
    $('#dw3-sub').textContent = dw3Cache.open ? `· ${dw3Cache.name}, ${dw3Cache.models.length} Modelle · Ziel: ${state.id != null ? `#${pad3(state.id)} ${digiName(state.id)}` : 'im Reiter Digimon wählen'}` : '· noch kein DW3-Abbild geöffnet';
    drawDw3();
  } catch (e) { await fail(e); }
}
const dw3Label = m => `${m.digimon || m.name} · ${m.code || m.name} · ID ${(m.fighter_ids || [])[0] ?? '–'}`;
async function viewDw3(m) {
  try {
    const r = await busy(t('DW3-Modell wird konvertiert …'), () => native('prepare_dw3', m.id));
    show('page-view');
    const v = await view.load(BASE + r.url);
    $('#v-name').textContent = `${m.digimon || m.name} (DW3 ${m.code || m.name})`;
    $('#anim').innerHTML = v.animations.length ? v.animations.map((n, i) => `<option value="${i}">${esc(n)}</option>`).join('') : `<option>${t('Keine Animationen')}</option>`;
    if (v.animations.length) view.play(0);
    // Vorschaubild für die Liste (einmal je Modell, nur gelesen aus der Ansicht)
    if (!m.thumb) setTimeout(async () => {
      try { const url = view.snapshot(160); if (url) { await native('dw3_thumb_save', m.id, url); dw3Cache = null; } } catch (_) { /* Vorschau ist optional */ }
    }, 900);
  } catch (e) { await fail(e); }
}
function drawDw3() {
  if (!dw3Cache?.open) { $('#dw3-list').innerHTML = ''; drawBatch(); return; }
  const q = $('#dw3-q').value;
  const rows = dw3Cache.models.filter(m => dw3Matches(m, q)).map((m, i) => [dw3Rank(m, q), i, m]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(x => x[2]);
  $('#dw3-count').textContent = t('{n} von {m} Modellen', { n: rows.length, m: dw3Cache.models.length }) + (dw3Cache.names_note ? ' · ' + dw3Cache.names_note : '');
  $('#dw3-list').innerHTML = rows.map(m => `<div class="dw3-item" data-view="${m.id}">
      ${m.thumb ? `<img src="${BASE + m.thumb}" alt="">` : `<div class="dw3-noimg">${esc((m.code || m.name).slice(0, 4))}</div>`}
      <div class="dw3-text"><b>${esc(m.digimon || m.name)}</b>${m.variant ? ` <span class="hint">${esc(t(m.variant))}</span>` : ''}
        <div class="hint">${t('Dateikürzel')}: ${esc(m.code || m.name)} · ${t('Modell-ID')}: ${(m.fighter_ids || [])[0] ?? '–'} · ${esc(m.file || m.name)}${m.file_number != null ? ` · ${t('Datei-Nr.')} ${m.file_number}` : ''}</div>
        ${(m.aliases || []).length ? `<div class="hint">${t('Auch')}: ${m.aliases.map(esc).join(', ')}</div>` : ''}
        ${m.status !== 'unique' ? `<div class="hint warn">${esc(t(m.status_text || ''))}</div>` : ''}</div>
      <div class="dw3-btns"><button class="small" data-one="${m.id}">${t('Einzeln importieren')}</button><button class="small" data-add="${m.id}">${t('zum Stapel')}</button></div></div>`).join('');
  $$('#dw3-list .dw3-item').forEach(row => { row.onclick = e => { if (e.target.closest('button')) return; viewDw3(dw3Cache.models[Number(row.dataset.view)]); }; });
  $$('#dw3-list [data-one]').forEach(b => { b.onclick = () => (state.id == null ? toast('Zuerst Ziel-Digimon wählen.') : nativeDw3Flow(Number(b.dataset.one))); });
  $$('#dw3-list [data-add]').forEach(b => { b.onclick = async () => {
    const target = await pickBox('Welcher DW2-Slot wird ersetzt?', state.catalog.map(c => ({ value: c.id, label: `#${pad3(c.id)} ${c.name}` })), state.id);
    if (target == null) return;
    const src = dw3Cache.models.find(m => m.id === Number(b.dataset.add));
    const name = await promptBox('Neuer Name im Spiel (leer = unverändert)', '');
    dw3Batch.push({ source: src.id, sourceName: dw3Label(src), target, name: name || null }); drawBatch();
  }; });
  drawBatch();
}
function drawBatch() {
  $('#dw3-batch').innerHTML = dw3Batch.length ? '<table>' + dw3Batch.map((j, i) => `<tr><td>${esc(j.sourceName)}</td><td>→ #${pad3(j.target)} ${esc(digiName(j.target))}</td><td>${esc(j.name || '')}</td><td><button class="small" data-del="${i}">×</button></td></tr>`).join('') + '</table>' : '<p class="hint">Stapel leer.</p>';
  $$('#dw3-batch [data-del]').forEach(b => { b.onclick = () => { dw3Batch.splice(Number(b.dataset.del), 1); drawBatch(); }; });
}
$('#dw3-q').oninput = drawDw3;
$('#dw3-clear').onclick = () => { dw3Batch.length = 0; drawBatch(); };
$('#dw3-run').onclick = async () => {
  if (!dw3Batch.length) return toast('Stapel ist leer.');
  try {
    const r = await busy(`${dw3Batch.length} DW3-Digimon werden importiert …`, () => native('dw3_batch_apply', dw3Batch.map(j => ({ source: j.source, target: j.target, name: j.name }))));
    r.jobs.forEach(j => log(`DW3 → #${pad3(j.target)}: ${j.bones} Knochen, ${j.triangles} Dreiecke` + (j.camera ? `, Kamera Stufe ${j.camera.bucket}` : '') + ((j.relocated || []).length ? `, PS1: ${j.relocated.length} Datei(en) verlagert (größer als das Original)` : '') + (j.optimized ? `, PS1 verkleinert: ${Object.entries(j.optimized).map(([k, v]) => k + ' ' + v).join('; ')}` : '')));
    dw3Batch.length = 0; drawBatch(); await refreshCatalogNames();
    await afterChange(`${r.jobs.length} Digimon ersetzt (ein Rückgängig-Schritt)`);
  } catch (e) { await fail(e); }
};

// ---------------------------------------------------------------- 9 Mod-Export: prüfen, ersetzen, einlesen
function drawModReport(r) {
  const list = (title, items, cls) => items.length ? `<p class="${cls}"><b>${title}</b><br>${items.map(esc).join('<br>')}</p>` : '';
  $('#mod-report').innerHTML = `<p>${r.files.length} Datei(en), Schnittstelle des Ports: ${r.api}${r.dna != null ? `, ${r.dna} DNA-Regel(n)` : ''}${r.textures?.length ? `, ${r.textures.length} HD-Textur(en)` : ''}</p>` +
    list('Fehler', r.errors, 'err') + list('Konflikte', r.conflicts, 'warn') + list('Hinweise', r.warnings, 'hint') +
    (r.files.length ? '<table><tr><th>Datei</th><th>Inhalt</th><th>Bytes</th><th></th></tr>' + r.files.map(f => `<tr><td>${f.file}</td><td>${esc(f.name)} · ${esc(f.label)}</td><td>${f.size}</td><td>${f.needs_api2 ? 'braucht Schnittstelle 2' : ''}</td></tr>`).join('') + '</table>' : '');
}
$('#b-mod-check').onclick = async () => {
  try { const r = await busy('Mod wird geprüft …', () => native('port_mods_dialog', 'check')); if (r) drawModReport(r); } catch (e) { await fail(e); }
};
$('#b-mod-replace').onclick = async () => {
  if (!(await confirmBox('Vorhandenen Mod im gewählten Ordner nach Mods\\disabled verschieben und diesen Mod exportieren?'))) return;
  try { const r = await busy('Mod wird exportiert …', () => native('port_mods_dialog', 'replace')); if (r) { log(`Mod exportiert: ${r.count} Dateien${r.replaced ? `, vorheriger Mod → Mods\\disabled\\${r.replaced.set}` : ''}`); toast(`${r.count} Mod-Dateien${r.dna_overrides != null ? `, ${r.dna_overrides} DNA-Regel(n)` : ''} exportiert`); } }
  catch (e) { await fail(e); }
};
$('#b-mod-import').onclick = async () => {
  try { const r = await busy('Mod wird eingelesen …', () => native('port_mods_dialog', 'import')); if (r) { await refreshCatalogNames(); await afterChange(`Mod eingelesen: ${r.files} Dateien, ${r.textures} HD-Textur(en)`); } }
  catch (e) {
    const msg = e.message || String(e);
    if (!msg.includes('Trotzdem einlesen')) return fail(e);
    if (!(await confirmBox(msg.replace(' Einlesen nur mit „Trotzdem einlesen“.', '') + ' Der Mod ersetzt diese Dateien. Trotzdem einlesen?'))) return;
    try { const r = await busy('Mod wird eingelesen …', () => native('port_mods_dialog', 'import_force', 'last')); if (r) { await refreshCatalogNames(); await afterChange(`Mod eingelesen (eigene Änderungen ersetzt): ${r.files} Dateien`); } }
    catch (e2) { await fail(e2); }
  }
};

// ---------------------------------------------------------------- 8 Textur-Editor: HD-Vorschau bis 2048×4096
async function showHd(promise) {
  try {
    const r = await promise;
    if (!r) return;
    const info = await view.setHdPreview(BASE + r.url);
    toast(`HD-Vorschau ${info.width}×${info.height}`); log(`HD-Vorschau ${info.width}×${info.height} (Grafikkarte: bis ${info.max})`);
  } catch (e) { await fail(e); }
}
$('#b-hd-preview').onclick = async () => {
  if (state.id == null) return toast('Zuerst ein Digimon wählen.');
  try { const f = await native('pick_file'); if (f) await showHd(native('hd_preview', state.id, f.path)); } catch (e) { await fail(e); }
};
$('#b-hd-active').onclick = () => (state.id == null ? toast('Zuerst ein Digimon wählen.') : showHd(native('hd_active', state.id)));
$('#b-hd-off').onclick = () => view.clearHdPreview();
