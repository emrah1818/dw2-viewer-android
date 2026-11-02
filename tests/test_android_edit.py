"""Funktionstests 1–8 und 10 der Android-Bearbeitung (ohne Gerät, mit synthetischem ISO).

Aufruf:  python tests/test_android_edit.py
Vergleicht die Android-Ergebnisse direkt mit den Windows-Kernroutinen (replace_tim
im v3.1-Modus, digimon_transfer, NativeModel) und prüft Speichern + Wiederöffnen.
"""
import base64, io, json, os, shutil, struct, sys, tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/src/main/python'))
sys.path.insert(0, str(ROOT / 'tests'))
os.environ['DW2_DATA_DIR'] = str(ROOT / 'app/src/main/assets/data')

import android_api as api  # noqa: E402
from test_android_api import tables, dir_record, native_model, animation_bytes  # noqa: E402
from dw2studio.core.native_tim_patch import replace_tim, regions  # noqa: E402
from dw2studio.core.dw2_native_atlas import decode_native_atlas  # noqa: E402
from dw2studio.core.native_model import NativeModel  # noqa: E402
from dw2studio.core import digimon_transfer as dt  # noqa: E402

RESULTS = []


def ok(method, *args):
    r = json.loads(api.call(method, json.dumps(list(args))))
    assert r['ok'], (method, r)
    return r['data']


def fails(method, *args):
    r = json.loads(api.call(method, json.dumps(list(args))))
    assert not r['ok'], (method, 'hätte fehlschlagen müssen')
    return r['error']


def check(name, condition, detail=''):
    RESULTS.append((name, bool(condition), detail))
    assert condition, f'{name}: {detail}'


def colorful_model(bones=2, tim=512):
    """Wie native_model, aber mit 16 verschiedenen Farben in Palette 0 und Augen-Metadaten."""
    m = bytearray(native_model(bones, tim))
    words = [0] + [((i * 2) & 31) | (((31 - i) & 31) << 5) | (((i * 5) & 31) << 10) for i in range(1, 16)]
    struct.pack_into('<16H', m, tim + 0x3840, *words)
    for p in range(128 * 224):  # Index-Muster 1..15
        at = tim + 64 + p // 2
        v = 1 + (p % 128 // 2) % 15
        m[at] = (m[at] & 0xF0) | v if p % 2 == 0 else (m[at] & 0x0F) | (v << 4)
    pos = 12 + 16 * bones   # Augen: Ziel (0,0) 4×4, Quellen (8,0) und (16,0)
    m[pos:pos + 10] = bytes([0, 0, 1, 4, 2, 0, 4, 0, 255, 255])
    return bytes(m)


def anim3():
    bones, clips = 3, 2
    table = 4 + bones * 4; begin = table + (clips + 1) * 4
    streams = [bytes([0] * bones + [255, 0, 0]) for _ in range(clips)]
    start = (begin + sum(map(len, streams)) + 3) // 4 * 4
    out = bytearray(start + bones * 24)
    for b in range(bones):
        at = start + b * 24; struct.pack_into('<I', out, 4 + b * 4, at)
        struct.pack_into('<12h', out, at, 4096, 0, 0, 0, 4096, 0, 0, 0, 4096, 0, b * 20, 0)
    pos = begin
    for i, d in enumerate(streams):
        struct.pack_into('<I', out, table + i * 4, pos); out[pos:pos + len(d)] = d; pos += len(d)
    return bytes(out).ljust(512, b'\0')


def make_iso(folder):
    files = {**tables(),
             'M003AGUM.BIN': colorful_model(), 'A003AGUM.BIN': animation_bytes(),
             'M005BETA.BIN': native_model(3, 1024), 'A005BETA.BIN': anim3()}
    sectors = [bytearray(2048) for _ in range(120)]
    root = dir_record('\x00', 18, 2048, True) + dir_record('\x01', 18, 2048, True)
    lba = 20
    for name, data in files.items():
        root += dir_record(name + ';1', lba, len(data))
        for i in range((len(data) + 2047) // 2048):
            chunk = data[i * 2048:(i + 1) * 2048]; sectors[lba + i][:len(chunk)] = chunk
        lba += (len(data) + 2047) // 2048
    sectors[18][:len(root)] = root
    pvd = sectors[16]; pvd[0] = 1; pvd[1:6] = b'CD001'
    pvd[156:190] = dir_record('\x00', 18, 2048, True)[:34].ljust(34, b'\0')
    path = Path(folder) / 'game.iso'; path.write_bytes(b''.join(bytes(s) for s in sectors))
    return path, files


def foreign_gltf(folder):
    """Fremdes Modell: zwei Gruppen (head/body), je ein Viereck, mit bunter 64×64-Textur."""
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype='<f4')
    uv = np.array([[0, 1], [1, 1], [0, 0], [1, 0]], dtype='<f4')
    idx = np.array([0, 1, 2, 2, 1, 3], dtype='<u2')
    blob = pos.tobytes() + uv.tobytes() + idx.tobytes()
    img = Image.new('RGBA', (64, 64))
    for y in range(64):
        for x in range(64):
            img.putpixel((x, y), ((x // 16) * 80, (y // 16) * 80, 120, 255))
    png = io.BytesIO(); img.save(png, 'PNG')
    doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0, 1]}],
           'nodes': [{'name': 'head', 'mesh': 0, 'translation': [0, 2, 0]}, {'name': 'body', 'mesh': 0}],
           'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1}, 'indices': 2, 'material': 0}]}],
           'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}],
           'textures': [{'source': 0}],
           'images': [{'uri': 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode()}],
           'buffers': [{'byteLength': len(blob), 'uri': 'data:application/octet-stream;base64,' + base64.b64encode(blob).decode()}],
           'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 48}, {'buffer': 0, 'byteOffset': 48, 'byteLength': 32},
                           {'buffer': 0, 'byteOffset': 80, 'byteLength': 12}],
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 4, 'type': 'VEC3', 'min': [0, 0, 0], 'max': [1, 1, 0]},
                         {'bufferView': 1, 'componentType': 5126, 'count': 4, 'type': 'VEC2'},
                         {'bufferView': 2, 'componentType': 5123, 'count': 6, 'type': 'SCALAR'}]}
    path = Path(folder) / 'fremd.gltf'; path.write_text(json.dumps(doc)); return path


def gltf_of(info):
    return json.loads((api.CACHE / info['url']).read_text())


def run():
    tmp = Path(tempfile.mkdtemp())
    try:
        api.configure(str(tmp / 'files'), str(tmp))
        iso, files = make_iso(tmp)
        ok('open_image', str(iso))
        check('Katalog', [c['id'] for c in ok('catalog')] == [3, 5])
        native3 = files['M003AGUM.BIN']; tim3 = regions(native3)[0].offset

        # Test 1: PNG-Export = Windows-Dekodierung (Farben, Transparenz)
        exp = ok('png_export', 3, False, 1)
        exported = Image.open(exp['path']).convert('RGBA')
        windows = decode_native_atlas(native3, tim3)
        check('T1 PNG-Export 128×256', exported.size == (128, 256))
        check('T1 Farben/Alpha identisch zur Windows-Dekodierung', exported.tobytes() == windows.tobytes())
        exp2 = ok('png_export', 3, True, 2)
        check('T1 Arbeitsvorlage 2× (256×512)', Image.open(exp2['path']).size == (256, 512))

        # Test 2: PNG-Import (v3.1) – Vorschau, Vormerken, Live-Anzeige
        edited = exported.copy()
        for y in range(0, 3):
            for x in range(0, 7):
                edited.putpixel((x, y), (8, 200, 40, 255))
        png = tmp / 'bearbeitet.png'; edited.save(png)
        prev = ok('png_preview', 3, str(png), 'v31', False, 'BOX')
        check('T2 Vorschau mit 3 Bildern', set(prev['images']) == {'original', 'desired', 'result'})
        check('T2 Vorschaubilder vorhanden', all((api.CACHE / u).is_file() for u in prev['images'].values()))
        before = ok('prepare_model', 3)
        ok('png_apply', prev['token'])
        staged = api.S.session.current(next(e for e in api.S.entries if e.path.endswith('M003AGUM.BIN')))
        windows_bytes, _ = replace_tim(native3, png, 0, recolor=True, eye_frames=prev['eye_frames'], palette_mode='v31')
        check('T2 Android-Bytes == Windows replace_tim(v31)', staged == windows_bytes)
        after = ok('prepare_model', 3)
        check('T2 Live-Vorschau: neues Modell ohne Neuladen', after['url'] != before['url'] and after['edited'])
        doc = gltf_of(after)
        check('T2 Textur im neuen Modell', len(doc['images']) >= 1)
        result = Image.open(api.CACHE / prev['images']['result']).convert('RGBA')
        check('T2 Erwartetes Spielergebnis grünlich', result.getpixel((2, 1))[1] > result.getpixel((2, 1))[0])

        # Test 3: Textur ersetzen mit anderer Auflösung (2× → nativ)
        ok('undo')
        big = edited.resize((256, 512), Image.NEAREST); big_png = tmp / 'gross.png'; big.save(big_png)
        prev2 = ok('png_preview', 3, str(big_png), 'v31', False, 'NEAREST')
        check('T3 Faktor 2 erkannt', prev2['factor'] == 2)
        ok('png_apply', prev2['token'])
        staged2 = api.S.session.current(next(e for e in api.S.entries if e.path.endswith('M003AGUM.BIN')))
        check('T3 2×-PNG ergibt dieselben Spielbytes wie 1×', staged2 == windows_bytes)
        err = fails('png_preview', 3, str(png).replace('bearbeitet', 'gibtsnicht'), 'v31', False, 'BOX')
        check('T3 Fehlende Datei sauber gemeldet', bool(err))

        # Test 4: 3D-Export (Geometrie, Texturen, Knochen, Animationen, Spieldaten)
        glb = ok('model_export', 3, 'glb', 'agumon')
        check('T4 GLB mit eingebetteten Spieldaten', glb['native'])
        transfer = dt.read_transfer(glb['path'])
        check('T4 Spieldaten = aktueller Stand (inkl. Textur)', transfer.files['M'] == staged2)
        gdoc = dt.gt.document(glb['path'])
        check('T4 Geometrie/Animationen/Texturen', len(gdoc['meshes']) == 2 and len(gdoc['animations']) == 2 and gdoc['images'])
        gltf = ok('model_export', 3, 'gltf', 'agumon')
        check('T4 glTF-Export', Path(gltf['path']).suffix == '.gltf')

        # Test 5: 3D-Import des Exports (Ansicht + Austausch erkannt)
        ins = ok('inspect_3d', glb['path'], 5)
        check('T5 Austauschmodell erkannt', ins['kind'] == 'transfer' and ins['source']['name'])
        check('T5 Ansicht-Datei vorhanden', (api.CACHE / ins['view']).is_file())
        check('T5 Plan ohne Fehler', ins['plan']['errors'] == [], ins['plan'])

        # Test 6: Digimon 5 durch Digimon 3 ersetzen, Live-Vorschau, Original/Bearbeitet
        orig5 = ok('prepare_model', 5)
        ok('transfer_apply', ins['token'], 5)
        new5 = ok('prepare_model', 5)
        check('T6 Ersatz sofort sichtbar (2 statt 3 Knochen)', len(gltf_of(new5)['meshes']) == 2 and len(gltf_of(orig5)['meshes']) == 3)
        back = ok('prepare_model', 5, True)
        check('T6 Original-Ansicht unverändert', back['url'] == orig5['url'] and back['original'])
        # Fremdes Modell mit Knochenzuordnung
        foreign = ok('inspect_3d', str(foreign_gltf(tmp)), 3)
        check('T6 Fremdmodell erkannt', foreign['kind'] == 'foreign')
        rig = ok('rig_prepare', foreign['token'], 3)
        check('T6 Gruppen + Vorschlag', {g['group'] for g in rig['groups']} == {'head', 'body'} and rig['bones'] == 2)
        mapping = {g['group']: g['bone'] for g in rig['groups']}
        pre_rig = api.S.session.current(next(e for e in api.S.entries if e.path.endswith('M003AGUM.BIN')))
        res = ok('rig_apply', foreign['token'], 3, mapping, True, 'v31', 1.0)
        check('T6 Fremdtextur übernommen (keine Warnung)', res['warnings'] == [], res['warnings'])
        check('T6 Formatprüfung bestanden', res['report']['geometry_used'] <= res['report']['geometry_budget'])
        rigged = ok('prepare_model', 3)
        NativeModel(api.S.session.current(next(e for e in api.S.entries if e.path.endswith('M003AGUM.BIN'))))
        check('T6 Fremdmodell sofort sichtbar', rigged['edited'] and len(gltf_of(rigged)['meshes']) == 2)

        # Test 7: Animationen mit bearbeiteten Modellen
        check('T7 Animationen nach Modellersatz', len(rigged['animations']) == 2 and len(new5['animations']) == 2)
        chans = gltf_of(new5)['animations'][0]['channels']
        check('T7 Animationskanäle für jeden Knochen', len({c['target']['node'] for c in chans}) == 2)

        # Rückgängig / Wiederherstellen
        h = ok('history')
        m3 = lambda: api.S.session.current(next(e for e in api.S.entries if e.path.endswith('M003AGUM.BIN')))
        rigged_bytes = m3()
        ok('undo'); check('Undo stellt Stand vor dem Modellersatz her', m3() == pre_rig and ok('history')['redo'] == 1)
        ok('redo'); check('Redo stellt Modellersatz wieder her', m3() == rigged_bytes and ok('history')['undo'] == h['undo'])

        # Test 8: Spiel-Image exportieren, wieder öffnen, Bytes prüfen
        expected = {e.path: api.S.session.current(e) for e in api.S.entries if e.path.endswith(('M003AGUM.BIN', 'M005BETA.BIN', 'A005BETA.BIN'))}
        saved = ok('save_image', 'neu')
        ok('open_image', saved['path'])
        reread = {e.path: api.S.session.current(e) for e in api.S.entries if e.path in expected}
        check('T8 Gespeichertes Image enthält alle Änderungen', reread == expected)
        check('T8 Neues Image öffnet und konvertiert', ok('prepare_model', 5)['animations'])
        # Überschreiben: neues Image übernehmen, Sicherung behalten
        ok('open_image', str(iso)); ok('png_preview', 3, str(png), 'v31', False, 'BOX')
        adopt = ok('adopt_image', saved['path'], str(iso))
        check('Überschreiben: Sicherung angelegt', adopt['backup'] and Path(adopt['backup']).is_file())
        check('Überschreiben: Arbeitsstand = neues Image', api.S.session.current(next(e for e in api.S.entries if e.path.endswith('M005BETA.BIN'))) == expected[next(p for p in expected if p.endswith('M005BETA.BIN'))])

        # Wiederherstellen des Originalmodells
        fails('undo')
        print('\n'.join(f"{'OK ' if c else 'FEHLER'}  {n}" for n, c, _ in RESULTS))
        print(f'Alle {len(RESULTS)} Prüfungen der Bearbeitungstests bestanden')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_android_edit():
    run()


if __name__ == '__main__':
    run()
