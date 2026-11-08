"""Baut die Web-Version (GitHub Pages) aus denselben Quellen wie die Android-App.

    python web/build_web.py [Zielordner]   (Standard: build/web)

Inhalt: Oberfläche aus app/src/main/assets/www, Python-Kern als py.zip (läuft in Pyodide),
Brücke web/bridge.js + web/worker.js, Web-App-Manifest und Symbole für den Home-Bildschirm.
"""
import json, re, shutil, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'build' / 'web'
WWW = ROOT / 'app/src/main/assets/www'
PY = ROOT / 'app/src/main/python'
DATA = ROOT / 'app/src/main/assets/data'
version = re.search(r'versionName = "([^"]+)"', (ROOT / 'app/build.gradle.kts').read_text()).group(1)

if OUT.exists():
    shutil.rmtree(OUT)
shutil.copytree(WWW, OUT)
(OUT / 'web').mkdir()
for name in ('bridge.js', 'worker.js', 'web.css'):
    shutil.copy(ROOT / 'web' / name, OUT / 'web' / name)

with zipfile.ZipFile(OUT / 'py.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sorted(PY.rglob('*.py')):
        if '__pycache__' not in f.parts:
            z.write(f, f.relative_to(PY).as_posix())
    for f in sorted(DATA.rglob('*')):
        if f.is_file():
            z.write(f, 'data/' + f.relative_to(DATA).as_posix())

# Symbole (aus dem adaptiven App-Symbol)
from PIL import Image
bg = Image.open(ROOT / 'app/src/main/res/mipmap-xxxhdpi/ic_launcher_background.png').convert('RGBA')
fg = Image.open(ROOT / 'app/src/main/res/mipmap-xxxhdpi/ic_launcher_foreground.png').convert('RGBA')
full = bg.copy(); full.alpha_composite(fg)
s = full.width; v = round(s * 18 / 108)
icon = full.crop((v, v, s - v, s - v))
for size, name in ((512, 'icon-512.png'), (192, 'icon-192.png'), (180, 'apple-touch-icon.png')):
    icon.resize((size, size), Image.LANCZOS).convert('RGB').save(OUT / 'web' / name)
full.resize((512, 512), Image.LANCZOS).convert('RGB').save(OUT / 'web' / 'icon-maskable-512.png')

(OUT / 'manifest.webmanifest').write_text(json.dumps({
    'name': 'DW2 3D Viewer', 'short_name': 'DW2 Viewer', 'start_url': './', 'scope': './',
    'display': 'standalone', 'orientation': 'portrait', 'background_color': '#0f1929', 'theme_color': '#0f1929',
    'description': 'Digimon World 2 – 3D-Modelle, Animationen und Texturen im Browser (eigenes BIN/ISO nötig).',
    'icons': [{'src': 'web/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
              {'src': 'web/icon-512.png', 'sizes': '512x512', 'type': 'image/png'},
              {'src': 'web/icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'}],
}, ensure_ascii=False, indent=1))

html = (OUT / 'index.html').read_text()
head = f'''<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="web/apple-touch-icon.png">
<link rel="icon" href="web/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="DW2 Viewer">
<meta name="theme-color" content="#0f1929">
<link rel="stylesheet" href="web/web.css">
<script>window.DW2_VERSION = {json.dumps(version)};</script>
<script src="web/bridge.js"></script>
'''
assert '<script type="importmap">' in html
html = html.replace('<script type="importmap">', head + '<script type="importmap">', 1)
(OUT / 'index.html').write_text(html)
(OUT / '.nojekyll').write_text('')
print(f'Web-Version {version} gebaut: {OUT}')
