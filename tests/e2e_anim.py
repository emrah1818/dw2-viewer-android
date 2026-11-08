"""Oberflächentest der Animationswiedergabe (v4.2 „Full Animation Support“) im echten Browser.

Synthetisches Image aus tests/test_native_anim.py (Spielformat, keine Spieldaten). Prüft
Animationsauswahl, 30-Hz-Schritte, Schleife/Halten, Pause/Geschwindigkeit, Texturanimation,
Mischmodus-Zwilling, geteilte Animationen über MODELDT, Diagnosemodus und Animationsprüfung.
Aufruf: python tests/e2e_anim.py [Screenshot-Ordner]
"""
import json, shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import e2e_ui  # noqa: E402  (Brücke, Routen, Typen)
from e2e_ui import HOST, TYPES, Bridge, api  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from test_native_anim import make_iso  # noqa: E402

SHOTS = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
SHOTS.mkdir(parents=True, exist_ok=True)


def main():
    tmp = Path(tempfile.mkdtemp())
    api.configure(str(tmp / 'files'), str(tmp))
    iso = make_iso(tmp)
    bridge = Bridge(tmp)
    errors, steps = [], []

    def route(r):
        url = r.request.url[len(HOST):].split('?')[0]
        if url == '/__call':
            body = json.loads(r.request.post_data)
            result = bridge.handle(body['method'], json.loads(body['args']))
            return r.fulfill(status=200, body=json.dumps(result), content_type='application/json')
        base = ROOT / 'app/src/main' if url.startswith('/assets/') else api.CACHE.parent
        path = base / url.lstrip('/')
        if not path.is_file():
            return r.fulfill(status=404, body='')
        return r.fulfill(status=200, body=path.read_bytes(), content_type=TYPES.get(path.suffix, 'application/octet-stream'))

    def step(name, ok, detail=''):
        steps.append((name, bool(ok)))
        print(('OK    ' if ok else 'FEHLER'), name, detail)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
        page = browser.new_page(viewport={'width': 412, 'height': 900}, device_scale_factor=2, locale='de-DE')
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.route(HOST + '/**', route)
        page.add_init_script("""window.Android = { invoke: (id, method, args) =>
            fetch('%s/__call', {method: 'POST', body: JSON.stringify({id, method, args})})
              .then(r => r.text()).then(t => window.__resolve(id, t)) };""" % HOST)
        page.goto(HOST + '/assets/www/index.html')
        page.wait_for_selector('#btn-open2')
        ev = page.evaluate

        def idle():
            page.wait_for_function("document.querySelector('#overlay').hidden")
            page.wait_for_timeout(300)

        def wait_model():
            page.wait_for_function("document.querySelector('#stage-msg').textContent === ''", timeout=60000)
            page.wait_for_timeout(700)

        bridge.picks.append(str(iso)); page.click('#btn-open2'); idle()
        page.wait_for_selector('#list .item')
        page.click('#list .item[data-id="3"]'); wait_model()
        opts = page.eval_on_selector_all('#anim option', 'o => o.map(x => x.textContent)')
        step('Animationsliste wie im Spiel (anim_A1, anim_A2, anim_B0, anim_B1)', opts == ['anim_A1', 'anim_A2', 'anim_B0', 'anim_B1'], str(opts))
        step('Native Wiedergabe aktiv', ev('!!window.__dw2view.native'))
        # Schleife ab Zeile 1: nach einiger Zeit nie wieder Zeile 0 nach der ersten Runde
        frames = ev("""async () => { const v = window.__dw2view, out = [];
            for (let i = 0; i < 30; i++) { await new Promise(r => setTimeout(r, 25)); out.push(v.native.player.frame); } return out; }""")
        step('Loop springt auf Bild 2 (Zeile 1), nicht auf Bild 1', 0 not in frames[10:] and 1 in frames and 2 in frames, str(frames))
        info = page.inner_text('#anim-info')
        step('Statuszeile: Spiel-ID und Schleife', 'Spiel-ID 1' in info and 'Schleife ab Bild 2' in info, info)
        # Texturanimation läuft (Zyklus-Ziel ändert sich)
        words = ev("""async () => { const v = window.__dw2view, out = new Set();
            for (let i = 0; i < 25; i++) { await new Promise(r => setTimeout(r, 40)); out.add(v.native.tex.vram[40 * 32 + 10]); } return [...out]; }""")
        step('Texturzyklus läuft (3 Bilder)', len(words) >= 2, str([hex(w) for w in words]))
        step('Halbtransparenz-Zwilling mit additivem Modus', ev("""() => { let n = 0; window.__dw2view.model.traverse(o => {
            if (o.userData.dw2Twin && o.material.blendSrc === 201 && o.material.blendDst === 201) n++; }); return n; }""") >= 1)
        # Pause
        page.click('#play')
        a = ev('window.__dw2view.native.ticks'); page.wait_for_timeout(400); b = ev('window.__dw2view.native.ticks')
        step('Pause hält alle Kanäle an', a == b and 'pausiert' in page.inner_text('#anim-info'), f'{a} {b}')
        page.click('#play'); page.wait_for_timeout(400)
        step('Fortsetzen', ev('window.__dw2view.native.ticks') > b)
        # Geschwindigkeit
        page.eval_on_selector('#speed', "e => { e.value = '0.5'; e.dispatchEvent(new Event('input')); }")
        t0 = ev('window.__dw2view.native.ticks'); page.wait_for_timeout(1000); t1 = ev('window.__dw2view.native.ticks')
        page.eval_on_selector('#speed', "e => { e.value = '2'; e.dispatchEvent(new Event('input')); }")
        page.wait_for_timeout(1000); t2 = ev('window.__dw2view.native.ticks')
        step('Geschwindigkeit 0,5× / 2×', 20 <= t1 - t0 <= 40 and 95 <= t2 - t1 <= 130, f'{t1 - t0} / {t2 - t1} VBlanks pro s')
        page.eval_on_selector('#speed', "e => { e.value = '1'; e.dispatchEvent(new Event('input')); }")
        # Wechsel auf Einmal-Animation: startet bei Bild 1, hält am Ende
        page.select_option('#anim', '1')
        first = ev('window.__dw2view.native.player.frame')
        page.wait_for_timeout(600)
        st = ev('window.__dw2view.status()')
        step('Animationswechsel initialisiert sauber (Bild 1)', first == 0)
        step('Einmal-Animation hält letztes Bild', st['finished'] and st['frame'] == 2, str(st))
        r = ev("() => { document.querySelector('#play').click(); const p = window.__dw2view.native.player; return [p.frame, p.finished, window.__dw2view.playing]; }")
        step('▶ startet beendete Animation neu', r == [0, False, True], str(r))
        page.click('#view-settings summary'); page.check('#o-repeat'); page.wait_for_timeout(2000)
        step('Option: Einmal-Animationen wiederholen', ev('window.__dw2view.native.restarts') >= 1)
        page.uncheck('#o-repeat')
        # Diagnose
        page.click('#diag-card summary'); page.wait_for_timeout(200)
        diag = page.inner_text('#diag-info')
        step('Diagnose zeigt Kanäle', 'Rückseiten: PS1' in diag and 'Augen: 1' in diag and 'Texturzyklen: 1' in diag and 'additiv' in diag and 'MODELDT' in diag, diag.replace('\n', ' | '))
        page.uncheck('#c-cycles'); page.wait_for_timeout(300)
        step('Kanal aus: Zyklus zurück auf Originaltextur', ev('window.__dw2view.native.tex.vram[40*32+10] === window.__dw2view.native.tex.original[40*32+10]'))
        page.check('#c-cycles')
        side = ev("() => { let s = new Set(); window.__dw2view.model.traverse(o => { if (o.isMesh && !o.userData.dw2Shadow) s.add(o.material.side); }); return [...s]; }")
        step('Nur Vorderseiten (PS1-Culling) aktiv', side == [0] and 'Nur Vorderseiten' in diag or side == [0], str(side))
        page.uncheck('#c-cull'); page.wait_for_timeout(100)
        side2 = ev("() => { let s = new Set(); window.__dw2view.model.traverse(o => { if (o.isMesh && !o.userData.dw2Shadow) s.add(o.material.side); }); return [...s]; }")
        step('Culling abschaltbar (beidseitig)', side2 == [2], str(side2))
        page.check('#c-cull')
        page.uncheck('#c-bones'); f1 = ev('window.__dw2view.native.player.frame'); page.wait_for_timeout(300)
        step('Kanal aus: Skelett eingefroren', ev('window.__dw2view.native.player.frame') == f1)
        page.check('#c-bones')
        page.screenshot(path=SHOTS / 'a1_agumon_diagnose.png')
        # Wechsel des Digimon: geteilte Animation
        page.click('#v-next'); wait_model()
        opts = page.eval_on_selector_all('#anim option', 'o => o.map(x => x.textContent)')
        diag = page.inner_text('#diag-info')
        step('Betamon: geteilte Animation aus A003AGUM', opts == ['anim_A1', 'anim_A2'] and 'A=A003AGUM.BIN' in diag, str(opts))
        step('Betamon: subtraktiver Mischmodus, keine Texturanimation', 'subtraktiv' in diag and 'Augen: 0' in diag)
        page.screenshot(path=SHOTS / 'a2_betamon.png')
        page.click('#v-prev'); wait_model()
        step('Zurück zu Agumon ohne Fehler', ev('window.__dw2view.native.payload.texanim.cycles') == 1)
        # Original-Hintergrund (DW2): Zeilen gegenläufig, transparente Leinwand, abschaltbar
        tx = "() => ['.l2l','.l2r'].map(c => new DOMMatrix(getComputedStyle(document.querySelector('#dw2bg ' + c)).transform).m41)"
        a1 = ev(tx); page.wait_for_timeout(500); a2 = ev(tx)
        step('Hintergrund: Zeile 1/3 nach links, Zeile 2 nach rechts', a2[0] < a1[0] and a2[1] > a1[1], f'{a1} → {a2}')
        px = ev("parseFloat(document.querySelector('#stage').style.getPropertyValue('--px'))")
        step('Hintergrund: ganze Gerätepixel je Spielpixel', px > 0 and abs(px * 2 - round(px * 2)) < 1e-6, str(px))
        step('Leinwand transparent über dem Hintergrund', ev('window.__dw2view.scene.background === null'))
        step('Grünes Statusfenster hinter dem Modell', ev("getComputedStyle(document.querySelector('.stage-panel')).backgroundColor") == 'rgba(0, 93, 0, 0.63)'
             and ev("getComputedStyle(document.querySelector('.stage-panel')).zIndex") in ('auto', '0'))
        step('Original-Schatten geladen, unter dem Modell', ev("!!window.__dw2view.shadow && window.__dw2view.shadow.position.y === 0"))
        page.screenshot(path=SHOTS / 'a0_hintergrund.png')
        page.click('#view-settings summary') if not page.is_visible('#o-dw2bg') else None
        page.uncheck('#o-dw2bg'); page.wait_for_timeout(100)
        step('Hintergrund abschaltbar (einfarbig)', ev("getComputedStyle(document.querySelector('#dw2bg')).display") == 'none'
             and ev('window.__dw2view.scene.background !== null'))
        page.check('#o-dw2bg')
        # Animationsprüfung
        page.click('.tab[data-page="page-more"]'); page.click('#b-audit'); idle()
        page.wait_for_selector('#modal-box h3')
        txt = page.inner_text('#modal-box')
        page.screenshot(path=SHOTS / 'a3_pruefung.png')
        step('Animationsprüfung: Dialog mit Zusammenfassung', 'Modelle: 2' in txt and 'Mit Texturzyklus: 1' in txt, txt[:200].replace('\n', ' | '))
        page.click('#m-yes'); idle(); page.wait_for_timeout(500)
        step('Prüfbericht exportiert (JSON + CSV)', {s.suffix for s in bridge.saved} >= {'.json', '.csv'}, str(bridge.saved))
        browser.close()

    real = [e for e in errors if 'favicon' not in e]
    step('Keine JavaScript-Fehler', not real, '; '.join(real[:5]))
    failed = [s for s in steps if not s[1]]
    print(f'{len(steps) - len(failed)}/{len(steps)} Animationsschritte bestanden · Screenshots: {SHOTS}')
    shutil.rmtree(tmp, ignore_errors=True)
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
