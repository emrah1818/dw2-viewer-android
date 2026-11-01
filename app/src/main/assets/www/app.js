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
    const info = await native('prepare_model', id);
    if (seq !== loadSeq) return;
    const r = await view.load(BASE + info.url);
    if (seq !== loadSeq) return;
    state.loaded = { id, info };
    $('#stage-msg').textContent = '';
    $('#v-name').textContent = info.name;
    $('#anim').innerHTML = r.animations.length
      ? r.animations.map((n, i) => `<option value="${i}">${esc(n)}</option>`).join('')
      : `<option>${t('Keine Animationen')}</option>`;
    if (r.animations.length) view.play(0);
    if (info.eyes) view.setEyes(info.eyes.frames.map(u => BASE + u)).catch(e => log('Augen: ' + e.message));
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
$('#play').onclick = () => { view.playing = !view.playing; $('#play').textContent = view.playing ? '⏸' : '▶'; };
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
$('#b-tex').onclick = async () => {
  if (state.id == null) return toast(t('Digimon wählen'));
  try {
    const list = await busy('Modell wird vorbereitet …', () => native('texture_list', state.id));
    let slot = 0;
    if (list.slots.length > 1) {
      slot = await pickBox(t('Textur wählen'), list.slots.map((n, i) => ({ value: i, label: n })), 0);
      if (slot == null) return;
    }
    const code = state.loaded?.info.code ?? 'textur';
    await exportFile(busy('Modell wird vorbereitet …', () => native('texture_export', state.id, slot, `${code}_${state.id}_${slot}.png`)));
  } catch (e) { await fail(e); }
};
$('#b-glb').onclick = async () => {
  if (state.id == null) return toast(t('Digimon wählen'));
  const code = state.loaded?.info.code ?? 'modell';
  try { await exportFile(busy('Modell wird vorbereitet …', () => native('model_export', state.id, 'glb', `${code}_${state.id}.glb`))); }
  catch (e) { await fail(e); }
};

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
$('#b-saveroster').onclick = async () => {
  if (!pendingItems.some(p => p.kind === 'roster')) return toast(t('Keine Änderungen vorgemerkt.'));
  try { await exportFile(native('roster_export', '')); } catch (e) { await fail(e); }
};

// ---------------------------------------------------------------- Mehr
$('#lang').onchange = e => { lang = e.target.value; localStorage.setItem('lang', lang); applyLang(); };
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
