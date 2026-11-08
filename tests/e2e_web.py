"""Oberflächentest der Web-Version (Pyodide) im echten Browser.

Baut build/web, liefert es per HTTP aus, öffnet ein synthetisches Image (Spielformat, keine
Spieldaten) und prüft: Laden von Python, Digimon-Liste, Modell + Animation, Hintergrund,
Schatten, Diagnose, PNG-Export als Download, Animationsprüfung.
Aufruf: python tests/e2e_web.py [Screenshot-Ordner]   (benötigt Internet für Pyodide vom CDN)
"""
import functools, http.server, os, subprocess, sys, tempfile, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from playwright.sync_api import sync_playwright  # noqa: E402
from test_native_anim import make_iso  # noqa: E402

SHOTS = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()); SHOTS.mkdir(parents=True, exist_ok=True)


def main():
    subprocess.run([sys.executable, str(ROOT / 'web/build_web.py'), str(ROOT / 'build/web')], check=True)
    tmp = Path(tempfile.mkdtemp())
    iso = make_iso(tmp)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / 'build/web'))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}/index.html'
    steps, errors = [], []

    def step(name, ok, detail=''):
        steps.append(bool(ok)); print(('OK    ' if ok else 'FEHLER'), name, detail)

    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    with sync_playwright() as p:
        browser = p.chromium.launch(proxy={'server': proxy, 'bypass': '127.0.0.1'} if proxy else None,
                                    args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
        ctx = browser.new_context(viewport={'width': 412, 'height': 900}, device_scale_factor=2, locale='de-DE',
                                  ignore_https_errors=True, accept_downloads=True)
        page = ctx.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.goto(url)
        page.wait_for_selector('#py-banner', state='detached', timeout=240000)
        step('Python (Pyodide) mit numpy/Pillow geladen', True)
        with page.expect_file_chooser() as fc:
            page.click('#btn-open2')
        fc.value.set_files(str(iso))
        page.wait_for_selector('#list .item', timeout=120000)
        n = page.eval_on_selector_all('#list .item', 'e => e.length')
        step('Image geöffnet, Digimon-Liste', n == 2, f'{n} Einträge')
        page.click('#list .item[data-id="3"]')
        page.wait_for_function("document.querySelector('#stage-msg').textContent === '' && window.__dw2view && window.__dw2view.native", timeout=120000)
        page.wait_for_timeout(1500)
        ev = page.evaluate
        opts = page.eval_on_selector_all('#anim option', 'o => o.map(x => x.textContent)')
        step('Modell und Animationen geladen', opts == ['anim_A1', 'anim_A2', 'anim_B0', 'anim_B1'], str(opts))
        t0 = ev('window.__dw2view.native.ticks'); page.wait_for_timeout(800)
        step('Animation läuft', ev('window.__dw2view.native.ticks') > t0)
        step('Original-Schatten geladen', ev('!!window.__dw2view.shadow'))
        step('Original-Hintergrund aktiv', ev("getComputedStyle(document.querySelector('#dw2bg')).display") != 'none')
        page.screenshot(path=SHOTS / 'web_3d.png')
        page.click('#tex-card summary') if page.is_visible('#tex-card summary') else None
        with page.expect_download(timeout=60000) as dl:
            page.click('#b-png-export')
            page.wait_for_selector('#modal-box .opt', timeout=10000)
            page.click('#modal-box .opt >> nth=0')
        step('PNG-Export als Download', dl.value.suggested_filename.endswith('.png'), dl.value.suggested_filename)
        page.click('.tab[data-page="page-more"]')
        page.click('#b-audit')
        page.wait_for_selector('#modal-box h3', timeout=120000)
        step('Animationsprüfung im Browser', 'Modelle: 2' in page.inner_text('#modal-box'))
        page.click('#m-no')
        browser.close()
    server.shutdown()
    real = [e for e in errors if 'favicon' not in e]
    step('Keine JavaScript-Fehler', not real, '; '.join(real[:4]))
    print(f'{sum(steps)}/{len(steps)} Web-Schritte bestanden · Screenshots: {SHOTS}')
    if not all(steps):
        sys.exit(1)


if __name__ == '__main__':
    main()
