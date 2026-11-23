/**
 * Animationseditor für DW3-Importe (0.96): jede DW2-Kampfanimation (A0 … K0) ist eine Aktion aus
 * mehreren DW3-Motions (Abschnitte mit Start-/Endbild, Wiederholungen, Übergang) und endet mit
 * „halten“ oder „ab Bild X wiederholen“ – genau das, was das DW2-Format kann (0xFF / 0xFE + Zeile).
 * Das Spiel und der PC-Port lesen diese Daten unverändert; der Export ist der normale Mod-Export.
 */
const STATUS_CLASS = { data: 'st-data', auto: 'st-auto', manual: 'st-manual', open: 'st-open' };
// Kampfabläufe wie im Spiel (src/stag3000/fighter.c); Zeilen = Bilder mit 30/s. Sprungdauer DW2:
// Stg30_HitReactHop1/2Motion (Geschwindigkeit −0x18000 / −0x14000, Schwerkraft 0x2666) ≈ 20 / 17 Bilder.
const SIMS = {
  'Attacke 1': [['A0', 45], ['F0', 'done+60'], ['A0', 60]],
  'Attacke 2': [['A0', 45], ['G0', 'done+60'], ['A0', 60]],
  'Attacke 3': [['A0', 45], ['H0', 'done+60'], ['A0', 60]],
  'Verteidigung (Treffer bei Abwehr)': [['A0', 45], ['B0', 'done'], ['A0', 60]],
  'Getroffen: Fallen und Aufstehen': [['A0', 45], ['C0', 20], ['C1', 17], ['C2', 'done'], ['J0', 'done'], ['A0', 60]],
  'K.o.': [['A0', 45], ['C0', 20], ['C1', 17], ['C2', 'done'], ['K0', 'done+60']],
  'Sieg': [['A0', 45], ['I0', 'done+90']],
};

export function initAnimEditor(env) {
  const { $, $$, native, view, t, toast, log, busy, fail, BASE, state, loadModel, esc } = env;
  const card = $('#animed-card'), body = $('#ae-body');
  let ed = null;          // {target, data, places, sel, dirty:Set, mode, motion, sim}
  let raf = 0;

  const hue = m => (m * 47) % 360;
  const key = p => `${p.slot}${p.clip}`;
  const clone = o => JSON.parse(JSON.stringify(o));
  const motionInfo = id => ed.data.motions.find(m => m.id === id) || { frames: 1, end: 'hold', loop_frame: 0, scripts: [] };
  const endText = m => m.end === 'loop' ? t('wiederholt ab Bild {f}', { f: m.loop_frame }) : m.end === 'idle' ? t('geht in Standby über') : t('hält das letzte Bild');
  function simulations() {
    if (!ed.data.field) return SIMS;
    const idle = ed.places.find(p => p.clip === 0) || ed.places[0];
    const move = ed.places.find(p => p.clip === 1);
    return { 'Standby (Domain)': [[key(idle), 90]],
      ...(move ? { 'Gehen (Domain)': [[key(idle), 30], [key(move), 90], [key(idle), 30]] } : {}) };
  }

  /** Zeilen einer Aktion wie dw3_actions.frames_of: [{seg, rep, motion, frame, blend}] und Loop-Zeile. */
  function layout(act) {
    const rows = []; let loopRow = null;
    act.segments.forEach((s, i) => {
      const bl = s.blend || 0;
      if (bl && rows.length) for (let k = 0; k < bl; k++) rows.push({ seg: i, rep: -1, motion: s.motion, frame: s.start, blend: true });
      for (let r = 0; r < (s.repeat || 1); r++) {
        for (let f = s.start; f <= s.end; f++) {
          if (act.end === 'loop' && i === act.loop_segment && r === 0 && f === act.loop_frame) loopRow = rows.length;
          rows.push({ seg: i, rep: r, motion: s.motion, frame: f, blend: false });
        }
      }
    });
    if (act.end === 'loop' && loopRow === null) loopRow = 0;
    return { rows, loopRow };
  }

  // ------------------------------------------------------------------ Laden
  async function open(target) {
    try {
      const data = await busy('Animationen werden gelesen …', () => native('anim_editor', target));
      ed = { target, data, places: data.places.map(p => ({ ...p, action: clone(p.action) })), sel: 0, dirty: new Set(),
             mode: 'action', motion: data.motions[0]?.id ?? 1, row: 0 };
      card.hidden = false; card.open = true;
      render();
      selectPlace(0);
    } catch (e) { await fail(e); }
  }

  function close() { ed = null; card.hidden = true; body.innerHTML = ''; cancelAnimationFrame(raf); }

  /** Kurzform der Kette für die Platzliste: „15→16→…→1 ⟲“. */
  function chain(a) {
    const ms = a.segments.map(s => s.motion).filter((m, j, arr) => arr.indexOf(m) === j);
    const txt = ms.length > 4 ? [...ms.slice(0, 2), '…', ms[ms.length - 1]].join('→') : ms.join('→');
    return esc(txt) + (a.end === 'loop' ? ' ⟲' : '');
  }

  // ------------------------------------------------------------------ Darstellung
  function render() {
    if (!ed) return;
    const p = ed.places[ed.sel];
    const a = p.action;
    const statusLegend = Object.entries(ed.data.status).map(([k, v]) => `<span class="st ${STATUS_CLASS[k]}">${esc(t(v))}</span>`).join(' ');
    body.innerHTML = `
      <p><b>${esc(ed.data.digimon || ed.data.source)}</b>${ed.data.variant ? ` <span class="hint">(${esc(t(ed.data.variant))})</span>` : ''}</p>
      <p class="hint">${esc(t('Modell-ID'))} ${ed.data.model_id ?? '–'} · ${esc(t('Dateikürzel'))} ${esc(ed.data.code || ed.data.source)} · ${esc(ed.data.source)} · ${ed.data.motions.filter(m => m.frames > 1).length} ${esc(t('DW3-Motions'))} · ${statusLegend}</p>
      <table class="ae-places">${ed.places.map((q, i) => `<tr data-i="${i}" class="${i === ed.sel ? 'sel' : ''}">
        <td><b>${key(q)}</b></td><td>${esc(t(q.role))}</td>
        <td><span class="st ${STATUS_CLASS[q.action.status] || ''}">${esc(t(ed.data.status[q.action.status] || q.action.status))}</span>${ed.dirty.has(i) ? ' ✎' : ''}</td>
        <td class="hint ae-chain">${chain(q.action)}</td></tr>`).join('')}</table>
      <h4>${key(p)} · ${esc(t(p.role))}</h4>
      <p class="hint">${esc(a.reason || '')}</p>
      <canvas id="ae-tl" height="54"></canvas>
      <div class="btns ae-play">
        <button id="ae-first" title="${esc(t('Erstes Bild'))}">⏮</button><button id="ae-prev" title="${esc(t('Bild zurück'))}">◀</button>
        <button id="ae-toggle">⏯</button><button id="ae-next" title="${esc(t('Bild vor'))}">▶</button><button id="ae-last" title="${esc(t('Letztes Bild'))}">⏭</button>
        <span id="ae-pos" class="hint"></span>
      </div>
      <div class="btns">
        <button id="ae-set-start">${esc(t('Start = dieses Bild'))}</button><button id="ae-set-end">${esc(t('Ende = dieses Bild'))}</button>
        <button id="ae-set-loop">${esc(t('Loop ab diesem Bild'))}</button>
      </div>
      <div class="ae-scroll"><table class="ae-segs"><tr><th>#</th><th>${esc(t('Motion'))}</th><th>${esc(t('Start'))}</th><th>${esc(t('Ende'))}</th><th>${esc(t('Wdh.'))}</th><th>${esc(t('Übergang'))}</th><th></th></tr>
      ${a.segments.map((s, i) => `<tr data-s="${i}">
        <td>${i + 1}</td>
        <td><select data-f="motion">${ed.data.motions.map(m => `<option value="${m.id}" ${m.id === s.motion ? 'selected' : ''}>${m.id} · ${m.frames} ${esc(t('Bilder'))}${m.scripts.length ? ' · S' + m.scripts.join(',') : ''}</option>`).join('')}</select></td>
        <td><input data-f="start" type="number" min="0" max="${motionInfo(s.motion).frames - 1}" value="${s.start}"></td>
        <td><input data-f="end" type="number" min="0" max="${motionInfo(s.motion).frames - 1}" value="${s.end}"></td>
        <td><input data-f="repeat" type="number" min="1" max="99" value="${s.repeat || 1}"></td>
        <td><input data-f="blend" type="number" min="0" max="30" value="${s.blend || 0}" title="${esc(t('Bilder, die aus der vorigen Pose überblenden (nicht original)'))}"></td>
        <td><button data-op="up" class="small">↑</button><button data-op="down" class="small">↓</button><button data-op="del" class="small">✕</button></td></tr>`).join('')}
      </table></div>
      <div class="btns"><button id="ae-add">${esc(t('+ Abschnitt'))}</button></div>
      <label class="row"><input type="radio" name="ae-end" value="hold" ${a.end === 'hold' ? 'checked' : ''}> ${esc(t('Am Ende das letzte Bild halten'))}</label>
      <label class="row"><input type="radio" name="ae-end" value="loop" ${a.end === 'loop' ? 'checked' : ''}> ${esc(t('Wiederholen ab Abschnitt'))}
        <input id="ae-lseg" type="number" min="1" max="${a.segments.length}" value="${(a.loop_segment ?? 0) + 1}" style="width:4em">
        ${esc(t('Bild'))} <input id="ae-lframe" type="number" value="${a.loop_frame ?? 0}" style="width:5em"></label>
      <div id="ae-check" class="hint"></div>
      <div class="btns">
        <button id="ae-apply" class="primary">${esc(t('Übernehmen und Vorschau'))}</button>
        <button id="ae-default">${esc(t('DW3-Vorgabe'))}</button>
        <select id="ae-sim">${Object.keys(simulations()).map(k => `<option>${esc(t(k))}</option>`).join('')}</select>
        <button id="ae-simgo">${esc(t('Kampfaktion simulieren'))}</button>
        <button id="ae-close">${esc(t('Schließen'))}</button>
      </div>
      <details class="ae-motions"><summary>${esc(t('DW3-Motions dieses Digimon'))}</summary>
        <p class="hint">${esc(t('Ansehen lädt das DW3-Original in den Viewer (Bild für Bild mit ◀ ▶). „Übernehmen und Vorschau“ zeigt wieder den Import.'))}</p>
        <table>${ed.data.motions.filter(m => m.frames > 1).map(m => `<tr><td>${m.id}</td><td>${m.frames} ${esc(t('Bilder'))}</td><td class="hint">${esc(endText(m))}</td>
          <td class="hint">${m.scripts.length ? esc(t('Skript')) + ' ' + m.scripts.join(', ') : ''}</td>
          <td><button class="small" data-view="${m.id}">${esc(t('Ansehen'))}</button><button class="small" data-addm="${m.id}">${esc(t('+ als Abschnitt'))}</button></td></tr>`).join('')}</table>
      </details>`;
    wire();
    check();
    draw();
  }

  function markDirty() {
    const p = ed.places[ed.sel];
    p.action.status = 'manual';
    p.action.reason = t('Manuell zugeordnet im Animationseditor');
    ed.dirty.add(ed.sel);
  }

  function wire() {
    const p = ed.places[ed.sel], a = p.action;
    $$('.ae-places tr', body).forEach(tr => { tr.onclick = () => selectPlace(Number(tr.dataset.i)); });
    $$('.ae-segs tr[data-s]', body).forEach(tr => {
      const i = Number(tr.dataset.s), s = a.segments[i];
      $$('[data-f]', tr).forEach(inp => {
        inp.onchange = () => {
          const f = inp.dataset.f, v = Number(inp.value);
          if (f === 'motion') { s.motion = v; s.start = 0; s.end = motionInfo(v).frames - 1; }
          else s[f] = v;
          fixAction(a); markDirty(); render();
        };
      });
      $$('[data-op]', tr).forEach(b => {
        b.onclick = () => {
          const op = b.dataset.op;
          if (op === 'del' && a.segments.length > 1) a.segments.splice(i, 1);
          if (op === 'up' && i > 0) [a.segments[i - 1], a.segments[i]] = [a.segments[i], a.segments[i - 1]];
          if (op === 'down' && i < a.segments.length - 1) [a.segments[i + 1], a.segments[i]] = [a.segments[i], a.segments[i + 1]];
          fixAction(a); markDirty(); render();
        };
      });
    });
    $('#ae-add', body).onclick = () => { const m = a.segments[a.segments.length - 1].motion; a.segments.push({ motion: m, start: 0, end: motionInfo(m).frames - 1, repeat: 1 }); markDirty(); render(); };
    $$('input[name=ae-end]', body).forEach(r => { r.onchange = () => { a.end = r.value; fixAction(a); markDirty(); render(); }; });
    $('#ae-lseg', body).onchange = e => { a.loop_segment = Math.max(0, Math.min(a.segments.length - 1, Number(e.target.value) - 1)); a.loop_frame = a.segments[a.loop_segment].start; a.end = 'loop'; markDirty(); render(); };
    $('#ae-lframe', body).onchange = e => { a.loop_frame = Number(e.target.value); a.end = 'loop'; fixAction(a); markDirty(); render(); };
    $('#ae-default', body).onclick = () => { p.action = clone(p.default); ed.dirty.add(ed.sel); render(); };
    $('#ae-apply', body).onclick = applyAll;
    $('#ae-close', body).onclick = close;
    $('#ae-simgo', body).onclick = () => simulate(Object.keys(simulations())[$('#ae-sim', body).selectedIndex]);
    $('#ae-first', body).onclick = () => seek(0);
    $('#ae-last', body).onclick = () => seek(total() - 1);
    $('#ae-prev', body).onclick = () => seek(ed.row - 1);
    $('#ae-next', body).onclick = () => seek(ed.row + 1);
    $('#ae-toggle', body).onclick = togglePlay;
    $('#ae-set-start', body).onclick = () => setFromRow('start');
    $('#ae-set-end', body).onclick = () => setFromRow('end');
    $('#ae-set-loop', body).onclick = () => setFromRow('loop');
    $$('[data-view]', body).forEach(b => { b.onclick = () => viewMotion(Number(b.dataset.view)); });
    $$('[data-addm]', body).forEach(b => {
      b.onclick = () => { const m = Number(b.dataset.addm); a.segments.push({ motion: m, start: 0, end: motionInfo(m).frames - 1, repeat: 1 }); markDirty(); render(); };
    });
    const tl = $('#ae-tl', body);
    tl.onclick = e => { const r = tl.getBoundingClientRect(); seek(Math.floor((e.clientX - r.left) / r.width * total())); };
  }

  /** Grenzen einhalten (Start ≤ Ende in der Motion, Loop im Abschnitt). */
  function fixAction(a) {
    for (const s of a.segments) {
      const n = motionInfo(s.motion).frames;
      s.start = Math.max(0, Math.min(n - 1, s.start | 0)); s.end = Math.max(s.start, Math.min(n - 1, s.end | 0));
      s.repeat = Math.max(1, Math.min(99, s.repeat | 0 || 1)); s.blend = Math.max(0, Math.min(30, s.blend | 0));
    }
    a.loop_segment = Math.max(0, Math.min(a.segments.length - 1, a.loop_segment | 0));
    const ls = a.segments[a.loop_segment];
    a.loop_frame = Math.max(ls.start, Math.min(ls.end, a.loop_frame | 0));
  }

  async function check() {
    const p = ed.places[ed.sel];
    const box = $('#ae-check', body);
    try {
      const r = await native('anim_check', ed.target, p.action);
      if (!ed || ed.places[ed.sel] !== p) return;
      box.innerHTML = `${r.frames} ${esc(t('Bilder'))} (${(r.frames / 30).toFixed(1)} s)` +
        (r.loop_row !== null ? ` · ${esc(t('Loop ab Bild'))} ${r.loop_row}` : ` · ${esc(t('hält am Ende'))}`) +
        (r.transitions.length ? `<div class="warn">${esc(t('Sichtbare Sprünge'))}: ${r.transitions.map(x => `${esc(t(x.where))} (${x.degrees}°)`).join(', ')}. ${esc(t('Abhilfe: anderes Start-/Endbild oder Übergang 3–6 Bilder.'))}</div>` : ` · ${esc(t('keine großen Sprünge'))}`);
    } catch (e) { box.innerHTML = `<div class="warn">${esc(e.message)}</div>`; }
  }

  // ------------------------------------------------------------------ Zeitleiste / Wiedergabe
  function clipIndex(k) {
    const anims = view.native?.payload.anims || [];
    const id = 10 * 'ABCDEFGHIJK'.indexOf(k[0]) + Number(k.slice(1));
    return anims.findIndex(a => a.id === id);
  }
  function total() {
    if (ed.mode === 'motion') return motionInfo(ed.motion).frames;
    const info = view.native && view.nativeClipInfo(clipIndex(key(ed.places[ed.sel])));
    return info ? info.rows : layout(ed.places[ed.sel].action).rows.length;
  }
  function seek(row) {
    const n = total();
    ed.row = Math.max(0, Math.min(n - 1, row));
    if (ed.mode === 'motion') {
      const i = view.actions?.findIndex(x => x.getClip().name === `motion_${ed.motion}`) ?? -1;
      if (i >= 0) view.gltfSeek(i, ed.row);
    } else {
      const ci = clipIndex(key(ed.places[ed.sel]));
      if (ci >= 0) view.nativeSeek(ci, ed.row);
    }
    draw();
  }
  function togglePlay() {
    if (ed.mode === 'motion') {
      const i = view.actions?.findIndex(x => x.getClip().name === `motion_${ed.motion}`) ?? -1;
      if (i < 0) return;
      const act = view.actions[i];
      act.paused = !act.paused; view.playing = !act.paused;
    } else {
      const ci = clipIndex(key(ed.places[ed.sel]));
      if (ci < 0) return toast(t('Erst „Übernehmen und Vorschau“.'));
      if (!view.playing) { if (view.native.anim?.id !== view.native.payload.anims[ci].id) view.play(ci); view.playing = true; }
      else view.playing = false;
    }
    loop();
  }
  function loop() {
    cancelAnimationFrame(raf);
    const step = () => {
      if (!ed) return;
      if (ed.mode === 'motion') {
        const i = view.actions?.findIndex(x => x.getClip().name === `motion_${ed.motion}`) ?? -1;
        if (i >= 0) ed.row = Math.floor(view.actions[i].time * 30) % Math.max(1, total());
      } else if (view.native) ed.row = view.nativeRow();
      draw();
      if (view.playing) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
  }

  function draw() {
    const cv = $('#ae-tl', body); if (!cv || !ed) return;
    const w = cv.clientWidth || 600; cv.width = w;
    const g = cv.getContext('2d'), H = cv.height;
    g.clearRect(0, 0, w, H);
    let segs, loopRow, n;
    if (ed.mode === 'motion') {
      const m = motionInfo(ed.motion); n = m.frames;
      segs = [{ from: 0, to: n, motion: ed.motion, label: `${t('DW3-Motion')} ${ed.motion}` }];
      loopRow = m.end === 'loop' ? m.loop_frame : null;
    } else {
      const lay = layout(ed.places[ed.sel].action); n = Math.max(1, lay.rows.length); loopRow = lay.loopRow;
      segs = [];
      lay.rows.forEach((r, i) => {
        const last = segs[segs.length - 1];
        if (last && last.seg === r.seg && last.blend === r.blend) last.to = i + 1;
        else segs.push({ seg: r.seg, from: i, to: i + 1, motion: r.motion, blend: r.blend, label: r.blend ? '↝' : `${r.seg + 1}: M${r.motion}` });
      });
    }
    const x = r => r / n * w;
    for (const s of segs) {
      g.fillStyle = s.blend ? '#777' : `hsl(${hue(s.motion)} 55% 42%)`;
      g.fillRect(x(s.from), 14, Math.max(1, x(s.to) - x(s.from)) - 1, H - 22);
      g.fillStyle = '#fff'; g.font = '11px sans-serif';
      if (x(s.to) - x(s.from) > 34) g.fillText(s.label, x(s.from) + 3, 30);
    }
    if (loopRow !== null && loopRow !== undefined) {
      g.fillStyle = 'rgba(255,214,0,.28)'; g.fillRect(x(loopRow), 10, w - x(loopRow), H - 14);
      g.strokeStyle = '#ffd600'; g.lineWidth = 2; g.beginPath(); g.moveTo(x(loopRow), 6); g.lineTo(x(loopRow), H - 2); g.stroke();
      g.fillStyle = '#ffd600'; g.fillText('⟲ Loop', Math.min(w - 46, x(loopRow) + 3), 10);
    } else { g.fillStyle = '#9ad'; g.fillText(t('hält am Ende'), w - 80, 10); }
    g.fillStyle = '#ff4d4d'; g.fillRect(x(ed.row), 0, 2, H);
    const pos = $('#ae-pos', body);
    if (pos) {
      if (ed.mode === 'motion') pos.textContent = `${t('DW3-Motion')} ${ed.motion}: ${t('Bild')} ${ed.row} / ${n - 1}`;
      else {
        const r = layout(ed.places[ed.sel].action).rows[ed.row];
        pos.textContent = `${t('Bild')} ${ed.row} / ${n - 1}` + (r ? ` · ${t('Abschnitt')} ${r.seg + 1}, Motion ${r.motion}, ${t('Bild')} ${r.frame}${r.blend ? ' (' + t('Übergang') + ')' : ''}` : '') +
          (ed.dirty.has(ed.sel) ? ` · ${t('noch nicht übernommen')}` : '');
      }
    }
  }

  function setFromRow(what) {
    if (ed.mode === 'motion') return toast(t('Erst die Aktion ansehen (Übernehmen und Vorschau).'));
    const a = ed.places[ed.sel].action, r = layout(a).rows[ed.row];
    if (!r || r.blend) return;
    const s = a.segments[r.seg];
    if (what === 'start') s.start = Math.min(r.frame, s.end);
    if (what === 'end') s.end = Math.max(r.frame, s.start);
    if (what === 'loop') { a.end = 'loop'; a.loop_segment = r.seg; a.loop_frame = r.frame; }
    fixAction(a); markDirty(); render();
  }

  async function selectPlace(i) {
    ed.sel = i; ed.row = 0;
    if (ed.mode === 'motion') { ed.mode = 'action'; await loadModel(state.id); }
    render();
    const ci = clipIndex(key(ed.places[i]));
    if (ci >= 0) { $('#anim').value = String(ci); seek(0); }
  }

  async function viewMotion(id) {
    try {
      const info = await native('prepare_model', state.id, false);
      const url = info.dw3_quality?.source_url;
      if (!url) return toast(t('DW3-Original nicht gefunden.'));
      if (ed.mode !== 'motion') await view.load(BASE + url);
      ed.mode = 'motion'; ed.motion = id; ed.row = 0;
      view.playing = false; seek(0); draw();
    } catch (e) { await fail(e); }
  }

  async function applyAll() {
    try {
      const places = ed.places.map(p => ({ slot: p.slot, clip: p.clip, action: p.action }));
      await busy('Animationen werden übernommen …', () => native('anim_apply', ed.target, places));
      ed.dirty.clear(); ed.mode = 'action';
      await loadModel(state.id);
      const fresh = await native('anim_editor', ed.target);
      ed.data = fresh; ed.places = fresh.places.map(p => ({ ...p, action: clone(p.action) }));
      render(); seek(0);
      log(t('Animationen übernommen (vorgemerkt). Export wie gewohnt unter Änderungen.'));
    } catch (e) { await fail(e); }
  }

  /** Spielt einen Kampfablauf wie im Spiel: Clip für Clip, „done“ = bis der Clip einmal durch ist. */
  async function simulate(name) {
    if (ed.mode === 'motion') { ed.mode = 'action'; await loadModel(state.id); }
    const seq = simulations()[name];
    const missing = seq.map(s => s[0]).filter(k => clipIndex(k) < 0);
    if (missing.length) return toast(t('Fehlt in diesem Platz: {k}', { k: missing.join(', ') }));
    const token = {}; ed.sim = token;
    view.playing = true;
    for (const [k, until] of seq) {
      if (ed?.sim !== token) return;
      const ci = clipIndex(k);
      view.play(ci); $('#anim').value = String(ci);
      const info = view.nativeClipInfo(ci);
      let frames = typeof until === 'number' ? until : info.rows + (Number(String(until).split('+')[1]) || 0);
      log(`${t('Simulation')}: ${k} (${frames} ${t('Bilder')})`);
      await new Promise(res => setTimeout(res, frames * 1000 / 30 / (view.speed || 1)));
    }
    if (ed?.sim === token) ed.sim = null;
  }

  return { open, close, isOpen: () => !!ed };
}
