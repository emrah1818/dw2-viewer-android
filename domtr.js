// Translates German UI text that is not marked with data-i18n (text built at runtime,
// tooltips, placeholders). German stays the source language: in German mode the original
// text is restored; in English mode every text node, title and placeholder is looked up
// in EN (exact match) and then in EN_PATTERNS (texts with numbers or names).
const ORIG = new WeakMap();          // node -> German original
const ATTR = ['title', 'placeholder'];

export function makeTranslator(EN, PATTERNS) {
  function tr(s) {
    const key = s.trim();
    if (!key) return null;
    const hit = EN[key];
    if (typeof hit === 'string') return s.replace(key, hit);
    for (const [re, rep] of PATTERNS) {
      if (re.test(key)) {
        const out = key.replace(re, (...m) => (typeof rep === 'function' ? rep(...m, tr) : rep.replace(/\$(\d)/g, (_, i) => m[i] ?? '')));
        return s.replace(key, out);
      }
    }
    return null;
  }
  return tr;
}

export function installDomTranslator(root, getLang, tr) {
  let busy = false;
  function textNode(n) {
    if (!n.parentElement || n.parentElement.closest('script,style,textarea,[data-no-tr]')) return;
    const cur = n.textContent;
    if (getLang() === 'en') {
      const o = ORIG.get(n);
      const src = o && o.en === cur ? o.de : cur;
      const out = tr(src);
      if (out != null && out !== cur) { ORIG.set(n, { de: src, en: out }); n.textContent = out; }
    } else {
      const o = ORIG.get(n);
      if (o && o.en === cur) n.textContent = o.de;
    }
  }
  function attrs(el) {
    for (const a of ATTR) {
      if (!el.hasAttribute || !el.hasAttribute(a)) continue;
      const cur = el.getAttribute(a), key = `__tr_${a}`;
      if (getLang() === 'en') {
        const src = el[key] && el[key].en === cur ? el[key].de : cur;
        const out = tr(src);
        if (out != null && out !== cur) { el[key] = { de: src, en: out }; el.setAttribute(a, out); }
      } else if (el[key] && el[key].en === cur) el.setAttribute(a, el[key].de);
    }
  }
  function walk(node) {
    if (node.nodeType === 3) { textNode(node); return; }
    if (node.nodeType !== 1) return;
    attrs(node);
    const w = document.createTreeWalker(node, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    while (w.nextNode()) { const n = w.currentNode; if (n.nodeType === 3) textNode(n); else attrs(n); }
  }
  const obs = new MutationObserver(list => {
    if (busy) return;
    busy = true;
    try {
      for (const m of list) {
        if (m.type === 'characterData') textNode(m.target);
        else if (m.type === 'attributes') attrs(m.target);
        else m.addedNodes.forEach(walk);
      }
    } finally { busy = false; obs.takeRecords(); }
  });
  obs.observe(root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTR });
  return () => { busy = true; try { walk(root); } finally { busy = false; obs.takeRecords(); } };
}
