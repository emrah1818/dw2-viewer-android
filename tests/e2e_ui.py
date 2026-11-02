"""Oberflächentest im Browser: echte App-Oberfläche (WebView-Dateien) + echter Python-Kern.

Die Android-Brücke (window.Android) wird nachgebildet; Dateiauswahl liefert vorbereitete
Dateien, „Speichern unter“ kopiert in einen Ausgabeordner. Aufruf:
    python tests/e2e_ui.py [Screenshot-Ordner]
"""
import json, os, shutil, sys, tempfile, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/src/main/python'))
sys.path.insert(0, str(ROOT / 'tests'))
os.environ['DW2_DATA_DIR'] = str(ROOT / 'app/src/main/assets/data')

from playwright.sync_api import sync_playwright  # noqa: E402
from PIL import Image  # noqa: E402
import android_api as api  # noqa: E402
from test_android_edit import make_iso, foreign_gltf  # noqa: E402

HOST = 'https://appassets.androidplatform.net'
SHOTS = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
SHOTS.mkdir(parents=True, exist_ok=True)
TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png',
         '.json': 'application/json', '.gltf': 'model/gltf+json', '.glb': 'model/gltf-binary', '.obj': 'text/plain'}


class Bridge:
    def __init__(self, tmp):
        self.picks = []
        self.saved = []
        self.out = tmp / 'gespeichert'; self.out.mkdir()
        self.image = None

    def handle(self, method, args):
        if method.startswith('pick_'):
            if not self.picks:
                return {'ok': True, 'data': None}
            path = Path(self.picks.pop(0))
            kind = method[5:]
            if kind == 'file':
                return {'ok': True, 'data': {'path': str(path), 'name': path.name}}
            if kind == 'image':
                self.image = path
            call = {'image': 'open_image', 'roster': 'roster_open', 'project': 'load_project'}[kind]
            return json.loads(api.call(call, json.dumps([str(path)])))
        if method == 'save_export':
            target = self.out / Path(args[1]).name
            shutil.copy2(args[0], target)
            self.saved.append(target)
            return {'ok': True, 'data': True}
        if method == 'app_info':
            return {'ok': True, 'data': {'version': 'test', 'free_mb': 9999}}
        if method == 'overwrite_original':
            shutil.copy2(args[0], self.out / 'ueberschriebenes_original.bin')
            return json.loads(api.call('adopt_image', json.dumps([args[0], str(self.image)])))
        return json.loads(api.call(method, json.dumps(args)))


def main():
    tmp = Path(tempfile.mkdtemp())
    api.configure(str(tmp / 'files'), str(tmp))
    iso, _ = make_iso(tmp)
    bridge = Bridge(tmp)
    errors, log, steps = [], [], []

    def route(r):
        url = r.request.url[len(HOST):].split('?')[0]
        if url == '/__call':
            body = json.loads(r.request.post_data)
            try:
                result = bridge.handle(body['method'], json.loads(body['args']))
            except Exception as exc:  # Fehler der Nachbildung sichtbar machen
                traceback.print_exc(); result = {'ok': False, 'error': str(exc)}
            return r.fulfill(status=200, body=json.dumps(result), content_type='application/json')
        base = ROOT / 'app/src/main' if url.startswith('/assets/') else api.CACHE.parent
        path = (base / url.lstrip('/'))
        if not path.is_file():
            return r.fulfill(status=404, body='')
        return r.fulfill(status=200, body=path.read_bytes(), content_type=TYPES.get(path.suffix, 'application/octet-stream'))

    def step(name, ok, detail=''):
        steps.append((name, bool(ok), detail))
        print(('OK    ' if ok else 'FEHLER'), name, detail)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
        page = browser.new_page(viewport={'width': 412, 'height': 900}, device_scale_factor=2, locale='de-DE')
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: (errors if m.type == 'error' else log).append(m.text))
        page.route(HOST + '/**', route)
        page.add_init_script("""window.Android = { invoke: (id, method, args) =>
            fetch('%s/__call', {method: 'POST', body: JSON.stringify({id, method, args})})
              .then(r => r.text()).then(t => window.__resolve(id, t)) };""" % HOST)
        page.goto(HOST + '/assets/www/index.html')
        page.wait_for_selector('#btn-open2')
        page.screenshot(path=SHOTS / '01_start.png')

        def idle():
            page.wait_for_function("document.querySelector('#overlay').hidden")
            page.wait_for_timeout(300)

        def wait_model():
            page.wait_for_function("document.querySelector('#stage-msg').textContent === ''", timeout=60000)
            page.wait_for_timeout(700)

        # Image öffnen
        bridge.picks.append(str(iso)); page.click('#btn-open2'); idle()
        page.wait_for_selector('#list .item')
        step('Image öffnen → Liste', page.locator('#list .item').count() == 2)

        # Digimon öffnen
        page.click('#list .item[data-id="3"]'); wait_model()
        page.screenshot(path=SHOTS / '02_modell.png')
        step('3D-Ansicht geladen', page.inner_text('#v-name') != '–' and not errors, '; '.join(errors))

        # Test 1: PNG exportieren
        page.click('#tex-card summary'); page.click('#b-png-export')
        page.click('#modal-box .opt[data-v="1"]'); idle()
        png = next((s for s in bridge.saved if s.suffix == '.png'), None)
        step('T1 PNG exportiert', png is not None and Image.open(png).size == (128, 256), str(png))

        # Test 2: PNG importieren mit Vorschau
        edited = Image.open(png).convert('RGBA')
        for y in range(3):
            for x in range(7):
                edited.putpixel((x, y), (8, 200, 40, 255))
        edit_path = tmp / 'bearbeitet.png'; edited.save(edit_path)
        bridge.picks.append(str(edit_path)); page.click('#b-png-import'); idle()
        page.wait_for_selector('#modal-box .cmp img')
        page.screenshot(path=SHOTS / '03_png_vorschau.png')
        step('T2 Vorschau zeigt 3 Bilder', page.locator('#modal-box .cmp img').count() == 3)
        page.click('#m-yes'); idle(); wait_model()
        page.screenshot(path=SHOTS / '04_nach_import.png')
        step('T2 Live-Vorschau: Modell geändert', 'vorgemerkt' in page.inner_text('#edit-state'), page.inner_text('#edit-state'))
        step('Änderungs-Zähler', page.inner_text('#badge') == '1', page.inner_text('#badge'))

        # Original / Bearbeitet
        page.click('#b-compare'); wait_model()
        step('Vergleich: Original', page.inner_text('#b-compare') == 'Original')
        page.screenshot(path=SHOTS / '05_original.png')
        page.click('#b-compare'); wait_model()
        step('Vergleich: Bearbeitet', page.inner_text('#b-compare') == 'Bearbeitet')

        # Rückgängig / Wiederherstellen
        page.click('#b-undo'); idle(); wait_model()
        step('Rückgängig', page.locator('#badge').is_hidden())
        page.click('#b-redo'); idle(); wait_model()
        step('Wiederherstellen', page.inner_text('#badge') == '1')

        # Test 4: GLB exportieren
        page.click('#model-card summary'); page.click('#b-glb'); idle()
        glb = next((s for s in bridge.saved if s.suffix == '.glb'), None)
        step('T4 GLB exportiert', glb is not None and glb.read_bytes()[:4] == b'glTF', str(glb))

        # Test 5+6: GLB importieren und Digimon 5 ersetzen
        page.click('.tab[data-page="page-list"]'); page.click('#list .item[data-id="5"]'); wait_model()
        bridge.picks.append(str(glb)); page.click('.tab[data-page="page-view"]'); page.click('#b-3d-import'); idle()
        page.wait_for_selector('#modal-box button[data-c="replace"]')
        page.screenshot(path=SHOTS / '06_import_dialog.png')
        page.click('#modal-box button[data-c="replace"]'); idle(); wait_model()
        page.screenshot(path=SHOTS / '07_ersetzt.png')
        step('T6 Digimon ersetzt (Live-Vorschau)', 'vorgemerkt' in page.inner_text('#edit-state') and page.inner_text('#badge') == '3',
             page.inner_text('#badge'))

        # Fremdes Modell mit Knochenzuordnung
        page.click('.tab[data-page="page-list"]'); page.click('#list .item[data-id="3"]'); wait_model()
        bridge.picks.append(str(foreign_gltf(tmp))); page.click('#b-3d-import'); idle()
        page.click('#modal-box button[data-c="replace"]')
        page.wait_for_selector('#modal-box select[data-g]'); page.screenshot(path=SHOTS / '08_knochen.png')
        step('Knochenzuordnung: 2 Gruppen', page.locator('#modal-box select[data-g]').count() == 2)
        page.click('#m-yes'); idle(); wait_model()
        page.screenshot(path=SHOTS / '09_fremdmodell.png')
        step('T6 Fremdmodell eingebaut', 'vorgemerkt' in page.inner_text('#edit-state'))

        # Nur ansehen (Import ohne Ersatz)
        bridge.picks.append(str(glb)); page.click('#b-3d-import'); idle()
        page.click('#modal-box button[data-c="view"]'); page.wait_for_timeout(1500)
        step('Import nur ansehen', 'Import' in page.inner_text('#edit-state'))

        # Test 8: neues Image exportieren
        page.click('.tab[data-page="page-changes"]'); page.wait_for_timeout(500)
        page.screenshot(path=SHOTS / '10_aenderungen.png')
        page.click('#b-saveimg'); page.fill('#m-in', 'neu'); page.click('#m-yes'); idle()
        iso_out = next((s for s in bridge.saved if s.suffix == '.iso'), None)
        step('T8 Neues Image gespeichert', iso_out is not None and iso_out.stat().st_size == iso.stat().st_size, str(iso_out))

        # Image überschreiben (mit Sicherheitsabfrage und Sicherung)
        page.click('#b-overwrite'); page.wait_for_selector('#m-yes'); page.click('#m-yes'); idle()
        page.wait_for_timeout(800)
        step('Image überschrieben + Sicherung', (bridge.out / 'ueberschriebenes_original.bin').is_file()
             and page.locator('#b-backup').is_visible())
        page.screenshot(path=SHOTS / '11_ueberschrieben.png')

        # Regression: Bearbeiten-Seite, Sprache
        page.click('.tab[data-page="page-edit"]'); page.wait_for_timeout(1200)
        # Test-Image hat keine Namenstabelle (MODELDT): dort erscheint eine Meldung statt des Felds.
        step('Bearbeiten-Seite (Typ/Attacken/Werte)', page.locator('#sel-type').count() == 1 and page.locator('#s-def').count() == 1)
        page.click('.tab[data-page="page-more"]'); page.select_option('#lang', 'en'); page.wait_for_timeout(300)
        page.click('.tab[data-page="page-view"]'); page.wait_for_timeout(300)
        step('Englisch', page.inner_text('#tex-card summary').strip() == 'Textures')
        page.screenshot(path=SHOTS / '12_englisch.png')
        browser.close()

    real = [e for e in errors if 'favicon' not in e]
    step('Keine JavaScript-Fehler', not real, '; '.join(real[:5]))
    failed = [s for s in steps if not s[1]]
    print(f'{len(steps) - len(failed)}/{len(steps)} Oberflächenschritte bestanden · Screenshots: {SHOTS}')
    shutil.rmtree(tmp, ignore_errors=True)
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
