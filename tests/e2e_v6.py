"""Oberflächentest 6.0 (Handy-Hochformat): Mod-Studio-Oberfläche als mobile Fassung, nur PS1-Image.

Echte WebView-Dateien + echter Python-Kern (app/src/main/python) + nativer DW3-Konverter (wie
libdw3conv.so in der App); die Android-Brücke wird wie in tests/e2e_ui.py nachgebildet.
Testdaten selbst erstellt (synthetisches DW2-ISO, Mini-DW3-Abbild, dw2.pak aus fixtures017).

Geprüft: elf Bereiche erreichbar (wischbare Leiste), PC-Port-Teile ausgeblendet, BIN/ISO öffnen,
dw2.pak wird abgewiesen, DW3-Abbild öffnen und Modell (Konverter) ansehen, Digitations-Editor
sichtbar, Englisch, keine JavaScript-Fehler.
Aufruf: python tests/e2e_v6.py [Screenshot-Ordner]   (vorher tools/run_studio_tests.sh und
tools/build_dw3conv.sh native)
"""
import json, os, shutil, sys, tempfile, traceback, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO_TESTS = ROOT / 'build/studio-tests/tests'
if not (STUDIO_TESTS / 'fixtures017.py').is_file():
    sys.exit('build/studio-tests fehlt: zuerst tools/run_studio_tests.sh ausführen.')
sys.path.insert(0, str(ROOT / 'app/src/main/python'))
sys.path.insert(0, str(STUDIO_TESTS))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'tests/studio_extra'))
os.environ['DW2_DATA_DIR'] = str(ROOT / 'app/src/main/assets/data')

from playwright.sync_api import sync_playwright  # noqa: E402
import android_api as api  # noqa: E402
from fixtures017 import make_pak  # noqa: E402
from test_native_anim import make_iso  # noqa: E402
from fixture_dw3 import make_dw3_iso  # noqa: E402
import hashlib  # noqa: E402
import dna_image  # noqa: E402
import test_dna_image as dnafix  # noqa: E402

HOST = 'https://appassets.androidplatform.net'
SHOTS = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
SHOTS.mkdir(parents=True, exist_ok=True)
TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png',
         '.json': 'application/json', '.gltf': 'model/gltf+json', '.glb': 'model/gltf-binary'}


class Bridge:
    """Wie MainActivity.kt: pick_* öffnet bzw. liefert die vorbereitete Datei, save_export kopiert."""
    def __init__(self, tmp):
        self.picks, self.saved = [], []
        self.out = tmp / 'gespeichert'; self.out.mkdir()

    def handle(self, method, args):
        if method.startswith('pick_'):
            if not self.picks:
                return {'ok': True, 'data': None}
            path = Path(self.picks.pop(0)); kind = method[5:]
            if kind == 'file':
                return {'ok': True, 'data': {'path': str(path), 'name': path.name}}
            call = {'image': 'open_image', 'dw3': 'open_dw3', 'roster': 'roster_open', 'project': 'load_project'}[kind]
            return json.loads(api.call(call, json.dumps([str(path)])))
        if method == 'save_export':
            target = self.out / Path(args[1]).name
            shutil.copy2(args[0], target); self.saved.append(target)
            return {'ok': True, 'data': True}
        if method == 'app_info':
            return {'ok': True, 'data': {'version': '6.0', 'free_mb': 9999}}
        return json.loads(api.call(method, json.dumps(args)))


def main():
    tmp = Path(tempfile.mkdtemp())
    lib = tmp / 'lib'; lib.mkdir()
    shutil.copy(ROOT / 'build/dw3conv/dw3_converter', lib / 'libdw3conv.so')
    api.configure(str(tmp / 'files'), str(lib))
    pak = make_pak(tmp / 'port')
    iso = make_iso(tmp)
    dw3 = make_dw3_iso(tmp)
    bridge = Bridge(tmp)
    errors, steps = [], []

    def route(r):
        url = r.request.url[len(HOST):].split('?')[0]
        if url == '/__call':
            body = json.loads(r.request.post_data)
            try:
                result = bridge.handle(body['method'], json.loads(body['args']))
            except Exception as exc:
                traceback.print_exc(); result = {'ok': False, 'error': str(exc)}
            return r.fulfill(status=200, body=json.dumps(result), content_type='application/json')
        base = ROOT / 'app/src/main' if url.startswith('/assets/') else api.CACHE.parent
        path = base / url.lstrip('/')
        if not path.is_file():
            return r.fulfill(status=404, body='')
        return r.fulfill(status=200, body=path.read_bytes(), content_type=TYPES.get(path.suffix, 'application/octet-stream'))

    def step(name, ok, detail=''):
        steps.append(bool(ok)); print(('OK    ' if ok else 'FEHLER'), name, detail)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
        page = browser.new_page(viewport={'width': 412, 'height': 900}, device_scale_factor=2, locale='de-DE')
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.route(HOST + '/**', route)
        page.add_init_script("""window.Android = { invoke: (id, method, args) =>
            fetch('%s/__call', {method: 'POST', body: JSON.stringify({id, method, args})})
              .then(r => r.text()).then(t => window.__resolve(id, t)) };""" % HOST)
        page.goto(HOST + '/assets/www/index.html')
        page.wait_for_selector('#btn-open2')
        page.wait_for_function("document.title.startsWith('DW2 Mod Studio 6')", timeout=20000)   # app.js vollständig gestartet

        def idle():
            page.wait_for_function("document.querySelector('#overlay').hidden", timeout=60000)
            page.wait_for_timeout(300)

        def tab(name):
            page.locator(f'.tab[data-page="{name}"]').scroll_into_view_if_needed()
            page.click(f'.tab[data-page="{name}"]'); page.wait_for_timeout(400)

        # Start: elf Bereiche, Leiste wischbar, PC-Teile ausgeblendet, Kopfzeile einzeilig
        n_tabs = page.locator('#tabs .tab').count()
        scroll = page.evaluate("(() => { const n = document.querySelector('#tabs'); return [n.scrollWidth, n.clientWidth]; })()")
        step('Alle elf Bereiche in der Leiste', n_tabs == 11, str(n_tabs))
        step('Leiste wischbar (breiter als der Bildschirm)', scroll[0] > scroll[1], str(scroll))
        step('PC-Studiofenster ausgeblendet', page.locator('#btn-studio').is_hidden())
        step('DW3-Knopf in der Kopfzeile', page.inner_text('#btn-dw3') == 'DW3')
        h = page.evaluate("document.querySelector('header#top').getBoundingClientRect().height")
        step('Kopfzeile einzeilig', h < 70, f'{h:.0f}px')
        step('Titel ohne „· PC“', page.title() == 'DW2 Mod Studio 6.0', page.title())
        page.screenshot(path=SHOTS / 'v6_01_start.png')

        # BIN/ISO öffnen (PS1-Image)
        bridge.picks.append(str(iso)); page.click('#btn-open2'); idle()
        page.wait_for_selector('#list .item')
        step('PS1-Image geöffnet', page.locator('#list .item').count() == 2 and 'Modus B' in page.inner_text('#subtitle'),
             page.inner_text('#subtitle'))

        # Mod-Export: nur Image-Weg, keine PC-Port-Teile
        tab('page-changes')
        step('PC-Port-Gruppe ausgeblendet', page.locator('#grp-pc').is_hidden())
        step('„Neues Image exportieren“ sichtbar', page.locator('#b-saveimg').is_visible())
        step('Hinweis ohne PC-Port', 'PC-Port' not in page.inner_text('#mode-banner'), page.inner_text('#mode-banner')[:120])
        page.screenshot(path=SHOTS / 'v6_02_export.png', full_page=True)

        # Texturen: keine HD-Pack-Knöpfe
        step('HD-Texturpack-Knöpfe ausgeblendet', all(page.locator(f'#{i}').is_hidden() for i in ('b-hd-pack', 'b-hd-preview', 'b-hd-active', 'b-hd-off')))

        # Digitation: Editor da, PC-Port-Karten (freie DNA-Regeln, Level) ausgeblendet
        tab('page-list'); page.click('#list .item[data-id="3"]'); page.wait_for_timeout(1500)
        tab('page-evo')
        step('Digitations-Editor sichtbar', page.locator('#evo-save').is_visible())
        step('DNA-Karte sichtbar, PC-Port-Level ausgeblendet', page.locator('#dna-card').is_visible() and page.locator('#lv-card').is_hidden())
        page.screenshot(path=SHOTS / 'v6_03_digitation.png', full_page=True)

        # dw2.pak wird abgewiesen, das geöffnete Image bleibt
        bridge.picks.append(str(pak)); page.click('#btn-open'); idle(); page.wait_for_timeout(300)
        toast = page.inner_text('#toast') if page.locator('#toast').is_visible() else ''
        step('dw2.pak abgewiesen', 'nur PS1-Images' in toast, toast[:120])
        step('Image bleibt geöffnet', 'Modus B' in page.inner_text('#subtitle'))

        # DW3: Abbild öffnen, Modell mit dem Konverter umwandeln und ansehen
        tab('page-dw3')
        bridge.picks.append(str(dw3)); page.click('#dw3-open'); idle()
        page.wait_for_selector('#dw3-list .dw3-item', timeout=30000)
        step('DW3-Abbild geöffnet', page.locator('#dw3-list .dw3-item').count() == 1)
        page.locator('#dw3-list .dw3-item').first.click(); idle(); page.wait_for_timeout(2000)
        msg = page.evaluate("document.querySelector('#stage-msg').textContent")
        step('DW3-Modell umgewandelt und angezeigt', msg == '' and page.locator('#page-view').is_visible(), msg)
        page.screenshot(path=SHOTS / 'v6_04_dw3.png')
        step('„Einzeln importieren“ vorhanden', page.locator('#dw3-list [data-one]').count() == 1)

        # DNA-Digitation im Image (Attrappe des Digi-Labor-Overlays mit Originaltabelle)
        ov = dnafix.overlay(); dna_image.OVERLAY_SHA1 = hashlib.sha1(ov).hexdigest()
        dna_iso = dnafix.make_iso(tmp, {'DIGIMNDT.BIN': dnafix.digimndt(dnafix.ROWS), 'STAG2000.PRO': ov})
        bridge.picks.append(str(dna_iso)); page.click('#btn-open'); idle()
        tab('page-evo')
        page.wait_for_function("document.querySelectorAll('#dna-a option').length > 1", timeout=20000)
        page.select_option('#dna-a', '5'); page.select_option('#dna-b', '6')
        page.select_option('#dna-result', '9'); page.select_option('#dna-rank', '3')
        page.click('#dna-save'); idle()
        page.wait_for_function("document.querySelectorAll('#dna-list .row').length === 1", timeout=20000)
        lst = page.inner_text('#dna-list')
        step('DNA-Regel im Image angelegt', 'Mega' in lst and 'Gilt im Spiel auch für' in lst, lst.replace('\n', ' ')[:160])
        step('Hinweis: wird ins Image geschrieben', 'Digi-Labors im Image' in page.inner_text('#dna-note'))
        page.screenshot(path=SHOTS / 'v6_05_dna.png', full_page=True)
        tab('page-changes')
        step('Änderungsliste zeigt STAG2000.PRO', 'STAG2000.PRO' in page.inner_text('#pending-list').upper())
        page.click('#b-saveimg'); page.fill('#m-in', 'mit_dna'); page.click('#m-yes'); idle()
        out = next((x for x in bridge.saved if x.suffix == '.iso'), None)
        ok = False
        if out:
            data = out.read_bytes()
            ok = data.count(dna_image.ORIGINAL_TABLE) == 0 and len(data) == dna_iso.stat().st_size
        step('Neues Image mit geänderter DNA-Tabelle gespeichert', ok, str(out))

        # Englisch
        tab('page-more'); page.select_option('#lang', 'en'); page.wait_for_timeout(400)
        tab('page-changes')
        step('Englisch: Hinweis übersetzt', page.inner_text('#mode-banner').startswith('PS1 image'), page.inner_text('#mode-banner')[:60])
        browser.close()

    real = [e for e in errors if 'favicon' not in e and '404' not in e]
    step('Keine JavaScript-Fehler', not real, '; '.join(real[:5]))
    failed = steps.count(False)
    print(f'{len(steps) - failed}/{len(steps)} Schritte (6.0) bestanden · Screenshots: {SHOTS}')
    shutil.rmtree(tmp, ignore_errors=True)
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
