"""Regressionstests für die originalgetreue Animationsunterstützung (v4.2 „Full Animation Support“).

Synthetische Daten im Spielformat (keine Spieldaten). Prüft:
  * Clip-Tabelle wie Anim_StepModelAnim (Lücke, Schleife ab Zwischenbild, Halten)
  * texAnimParts wie Gfx_AnimateModelTex (Augen, 3-Bild-Zyklus, erweitert)
  * ABR-Mischmodus aus dem tpage-Wort
  * Zuordnung der A–K-Dateien über MODELDT (geteilte Animationen)
  * Nutzlast im glTF für den Viewer + Animationsprüfung aller Modelle
  * frühere tolerante Lesart bleibt als Rückfall erhalten
Aufruf: python tests/test_native_anim.py   (schreibt zusätzlich tests/_fixture_payload.json für den JS-Test)
"""
import base64, io, json, os, shutil, struct, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/src/main/python'))
sys.path.insert(0, str(ROOT / 'tests'))
os.environ['DW2_DATA_DIR'] = str(ROOT / 'app/src/main/assets/data')

from dw2studio.core.native_anim import parse_anim_file, parse_tex_anim, primitive_modes, matrix_flags  # noqa: E402
from dw2studio.core.native_gltf import Animation, convert_model, texture_images  # noqa: E402
from dw2studio.core.digimon_names import encode_name  # noqa: E402
import android_api as api  # noqa: E402
from test_android_api import tables, dir_record, animation_bytes as legacy_animation  # noqa: E402

FAILS = []


def check(cond, label):
    print(('OK   ' if cond else 'FEHL ') + label)
    if not cond:
        FAILS.append(label)


def tex_region():
    eye0 = bytes([2, 10, 2, 4, 0, 10, 4, 10, 6, 10])      # Ziel (2,10) 2×4 Wörter; Quellen offen/halb/zu
    eye1 = bytes([0xFF] * 10)
    cycle = bytes([10, 40, 4, 8, 2, 40, 14, 40, 18, 40])   # 3-Bild-Zyklus (eigene Quellen, wie im Spiel nötig)
    ext = bytearray(42)
    ext[0:10] = bytes([20, 60, 2, 2, 24, 60, 1, 1, 6, 3])  # Periode 6 → 3 Bilder, Startphase 3
    for f in range(3):
        ext[10 + 4 * f:14 + 4 * f] = bytes([20, 70 + 4 * f, 26, 70 + 4 * f])
    return eye0 + eye1 + cycle + b'\xfe' + bytes(ext) + b'\xff'


def native_model(bones=2, tim=1024, region=None, abr=1, clut=224 * 64):
    region = tex_region() if region is None else region
    start = 12 + 16 * bones
    begin = (start + max(24, len(region)) + 3) // 4 * 4
    data = bytearray(tim + 0x4040 + 4)
    struct.pack_into('<III', data, 0, tim, tim + 0x4040, bones)
    data[start:start + len(region)] = region
    cursor = begin; pointers = [[], [], []]
    for bone in range(bones):
        pointers[0].append(cursor); struct.pack_into('<IH', data, cursor, 4, 0)
        for j, c in enumerate(((0, 0, 0), (20, 0, 0), (0, -20, 0), (20, -20, 0))):
            struct.pack_into('<hhh', data, cursor + 6 + j * 6, *c)
        cursor = (cursor + 30 + 3) // 4 * 4; pointers[1].append(cursor); struct.pack_into('<IHhhh', data, cursor, 1, 0, 0, 0, 4096); cursor += 12
        pointers[2].append(cursor)
        semi = bone == 0
        # Blockfolge: Anzahl halbtransparenter Quads, Quads, Anzahl undurchsichtiger Quads, Quads, dann Dreiecke
        if semi:
            struct.pack_into('<I', data, cursor, 1); p = cursor + 4
        else:
            struct.pack_into('<II', data, cursor, 0, 1); p = cursor + 8
        data[p:p + 8] = bytes([0, 1, 2, 3, 0, 0, 0, 0]); data[p + 8:p + 16] = bytes([0, 0, 7, 0, 0, 3, 7, 3])
        struct.pack_into('<HH', data, p + 16, clut, (abr << 5) if semi else 0)
        struct.pack_into('<III', data, p + 20, 0, 0, 0) if semi else struct.pack_into('<II', data, p + 20, 0, 0); cursor += 36
    for i, table in enumerate(pointers):
        struct.pack_into(f'<{bones}I', data, 12 + i * bones * 4, *table)
    struct.pack_into(f'<{bones}I', data, 12 + 12 * bones, *range(bones))
    struct.pack_into('<III4H', data, tim, 16, 8, 44, 0, 0, 256, 1); struct.pack_into('<I4H', data, tim + 52, 16396, 0, 0, 32, 256)
    data[tim + 64:tim + 0x3840] = b'\x11' * (0x3840 - 64)
    # Quellen der Texturanimation mit anderen Indizes füllen (2 = grün mit STP, 3 = blau)
    for x, y, w, h, v in ((4, 10, 2, 4, 0x22), (6, 10, 2, 4, 0x33), (14, 40, 4, 8, 0x22), (18, 40, 4, 8, 0x33)):
        for yy in range(y, y + h):
            o = tim + 64 + yy * 64 + x * 2
            data[o:o + w * 2] = bytes([v]) * (w * 2)
    struct.pack_into('<1024H', data, tim + 0x3840, *([0, 31, 0x8000 | (31 << 5), 31 << 10, 0x8000] + [0] * 1019))
    data[tim + 64 + 200 * 64:tim + 64 + 200 * 64 + 4] = b'\x44' * 4     # Schwarz mit STP-Bit (0x8000), Zeile 200
    return bytes(data)


def small_tim_shadow():
    """Schattenmodell wie 0x5B: kleine 4-Bit-TIM (32×32), Palette in Zeile 31, Schwarz mit STP-Bit."""
    m = bytearray(native_model(bones=1, region=bytes([0xFF] * 24), abr=0, clut=31 * 64))
    tim = struct.unpack_from('<I', m, 0)[0]
    w, h = 8, 32
    pix = bytearray(b'\x11' * (w * h * 2))
    struct.pack_into('<2H', pix, 31 * w * 2, 0, 0x8000)          # Palette: 0 = durchsichtig, 1 = Schwarz+STP
    block = struct.pack('<II', 16, 8) + struct.pack('<I4H', 44, 0, 0, 16, 1) + bytes(32) \
        + struct.pack('<I4H', 12 + len(pix), 0, 0, w, h) + bytes(pix)
    m[tim:tim + len(block)] = block
    struct.pack_into('<I', m, 4, tim + len(block))
    return bytes(m[:tim + len(block)])


def game_animation(bones=2):
    out = bytearray(140)
    struct.pack_into('<3I', out, 0, 0, 44, 92)
    struct.pack_into('<4I', out, 12, 0, 28, 37, 1)        # Index 0 leer (Lücke), dann zwei Clips, Abschluss 1
    out[28:37] = bytes([0, 0, 1, 0, 0, 1, 0xFE, 2, 0])      # Schleife zurück auf Byte 2 = Zeile 1
    out[37:44] = bytes([0, 0, 1, 1, 0xFF, 0, 0])            # einmalig
    def key(offset, m, t):
        struct.pack_into('<12h', out, offset, *[int(round(v * 4096)) for row in m for v in row], *t)
    ident = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    key(44, ident, (0, 0, 0)); key(68, ((0, -1, 0), (1, 0, 0), (0, 0, 1)), (5, 0, 0))
    key(92, ident, (0, -20, 0)); key(116, ((1, .5, 0), (0, 1, 0), (0, 0, 1)), (0, -20, 0))   # Scherung
    return bytes(out)


def modeldt(records):
    """MODELDT-Tabelle: Kopf (records_start, pool_end), Namenspool, 40-Byte-Sätze, Nullsatz."""
    pool = bytearray(); pointers = {}
    for ident, name, *_ in records:
        pointers[ident] = 8 + len(pool); raw = encode_name(name) + b'\xff'; pool += raw + bytes((-len(raw)) % 4)
    pool_end = 8 + len(pool); start = pool_end
    data = bytearray(start + 40 * (len(records) + 1))
    struct.pack_into('<II', data, 0, start, pool_end); data[8:pool_end] = pool
    for i, (ident, _name, model, anims) in enumerate(records):
        row = start + 40 * i
        struct.pack_into('<IHh', data, row, pointers[ident], ident << 1, model)
        struct.pack_into('<11h', data, row + 8, *(anims + [0] * (11 - len(anims))))
    return bytes(data)


def make_iso(folder):
    ids = json.loads((ROOT / 'app/src/main/assets/data/native_file_ids_us.json').read_text())
    files = {**tables(), 'M003AGUM.BIN': native_model(), 'A003AGUM.BIN': game_animation(),
             'B003AGUM.BIN': legacy_animation(), 'M004BETA.BIN': native_model(region=bytes([0xFF] * 20) + b'\xff\xff\xff\xff', abr=2),
             'MODELDT0.BIN': modeldt([(3, 'Agumon', ids['M003AGUM.BIN'], [ids['A003AGUM.BIN'], ids['B003AGUM.BIN']]),
                                      (4, 'Betamon', ids['M004BETA.BIN'], [ids['A003AGUM.BIN']])])}
    # Schattenmodell (Datei-ID 0x5B) und SLUS_011.93 mit privater Dateitabelle (wie Cd_GetFileLba)
    shadow = small_tim_shadow()
    exe = bytearray(0x37900 + 3675 * 2); exe[:8] = b'PS-X EXE'
    files = {'SHADOW.BIN': shadow, **files, 'SLUS_011.93': exe}
    struct.pack_into('<I', exe, 0x33F94 + 4 * 0x5B, 20); struct.pack_into('<H', exe, 0x37900 + 2 * 0x5B, (len(shadow) + 2047) // 2048)
    sectors = [bytearray(2048) for _ in range(300)]
    root = dir_record('\x00', 18, 2048, True) + dir_record('\x01', 18, 2048, True)
    lba = 20
    for name, data in files.items():
        root += dir_record(name + ';1', lba, len(data))
        for i in range((len(data) + 2047) // 2048):
            chunk = data[i * 2048:(i + 1) * 2048]; sectors[lba + i][:len(chunk)] = chunk
        lba += (len(data) + 2047) // 2048
    sectors[18][:len(root)] = root
    pvd = sectors[16]; pvd[0] = 1; pvd[1:6] = b'CD001'; pvd[40:72] = b'DW2TEST'.ljust(32)
    pvd[156:190] = dir_record('\x00', 18, 2048, True)[:34].ljust(34, b'\0')
    path = Path(folder) / 'game.iso'; path.write_bytes(b''.join(bytes(s) for s in sectors)); return path


def ok(method, *args):
    r = json.loads(api.call(method, json.dumps(list(args))))
    assert r['ok'], (method, r)
    return r['data']


def run():
    # --- Knochenanimation im Spielformat
    a = parse_anim_file(game_animation(), 2)
    check([c.index for c in a.clips] == [1, 2] and a.gaps == [0] and a.table_slots == 3, 'Clip-Tabelle: Lücke bleibt als Index erhalten')
    check(a.clips[0].terminator == 0xFE and a.clips[0].loop_row == 1, 'Schleife ab Zwischenbild (Zeile 1)')
    check(a.clips[1].terminator == 0xFF and a.clips[1].loop_row is None, 'Einmal-Clip (0xFF hält letztes Bild)')
    f = matrix_flags(game_animation(), a)
    check(f['sheared_keys'] == 1 and f['keys'] == 4, 'Scherung in Schlüsselmatrix erkannt')
    anim = Animation(game_animation(), 2)
    check(not anim.legacy and [anim.clip_name('A', c, i) for i, c in enumerate(anim.clips)] == ['anim_A1', 'anim_A2'],
          'Clipnamen folgen dem Spielindex (anim_A1/anim_A2)')
    legacy = Animation(legacy_animation(), 2)
    check(legacy.legacy and [legacy.clip_name('B', c, i) for i, c in enumerate(legacy.clips)] == ['anim_B0', 'anim_B1'],
          'Rückfall: frühere tolerante Lesart unverändert')
    try:
        parse_anim_file(game_animation(), 3); bad = False
    except ValueError:
        bad = True
    check(bad, 'Falsche Knochenzahl wird abgelehnt')

    # --- Texturanimation
    native = native_model()
    t = parse_tex_anim(native)
    check(len(t.eyes) == 1 and t.eyes[0]['frames'] == [(0, 10), (4, 10), (6, 10)], 'Augenrechteck mit 3 Posen')
    check(len(t.cycles) == 1 and len(t.extended) == 1 and t.extended[0]['period'] == 6 and t.extended[0]['phase'] == 3,
          'Zyklus und erweiterter Eintrag (Periode/Phase) gelesen')
    check(t.terminated and not t.warnings and not t.touches_palette(), 'Block korrekt abgeschlossen')
    plain = parse_tex_anim(native_model(region=bytes([0xFF] * 20) + b'\xff\xff\xff\xff'))
    check(not plain.any and plain.terminated, 'Modell ohne Texturanimation')

    # --- Mischmodus
    modes = primitive_modes(native)
    check(modes[0] == [(True, 224 * 64, 1)] and modes[1] == [(False, 224 * 64, 0)], 'ABR aus tpage (additiv) gelesen')

    # --- Konverter-Nutzlast
    tmp = Path(tempfile.mkdtemp())
    try:
        out = convert_model(native, {'A': game_animation(), 'B': legacy_animation()}, tmp / 'm.gltf')
        doc = json.loads(out.read_text())
        p = doc['scenes'][0]['extras']['dw2_native']
        check([x['name'] for x in doc['animations']] == [x['name'] for x in p['anims']] == ['anim_A1', 'anim_A2', 'anim_B0', 'anim_B1'],
              'glTF-Animationen und native Nutzlast in gleicher Reihenfolge')
        check(p['anims'][0]['id'] == 1 and p['anims'][2]['id'] == 10 and p['anims'][0]['offset'] == 28, 'Spiel-Animations-IDs und Offsets')
        check(base64.b64decode(p['files']['A']) == game_animation() and len(base64.b64decode(p['vram'])) == 0x4000,
              'Animationsdatei und Texturwörter unverändert eingebettet')
        check(p['texanim']['eyes'] == 1 and p['texanim']['cycles'] == 1 and p['texanim']['extended'] == 1, 'Texturanimation in Nutzlast')
        mats = [m['extras'] for m in doc['materials']]
        check({(m['semi_transparent'], m['abr']) for m in mats} == {(True, 1), (False, 0)}, 'Materialien tragen den Mischmodus')
        check(doc['animations'][0]['extras']['loop_row'] == 1 and doc['animations'][1]['extras']['loop_row'] is None, 'Loop-Zeile im glTF')
        imgs = texture_images(native)
        check(len(imgs) == 2, 'Texturen je Material')
        semi_i = [i for i, m in enumerate(mats) if m['semi_transparent']][0]
        a_semi = imgs[semi_i].getpixel((0, 200))[3]; a_opaque = imgs[1 - semi_i].getpixel((0, 200))[3]
        check(a_semi == 127 and a_opaque == 255 and imgs[semi_i].getpixel((0, 0))[3] == 255,
              '0x8000 (Schwarz+STP) auf halbtransparenter Fläche gemischt, sonst deckend')
        fixture = {'payload': p, 'materials': mats,
                   'images': [base64.b64encode(i.tobytes()).decode() for i in imgs]}
        (ROOT / 'tests' / '_fixture_payload.json').write_text(json.dumps(fixture))

        # --- Android-API: Zuordnung über MODELDT, Prüfung, Rohdaten
        api.configure(str(tmp / 'files'), str(tmp))
        iso = make_iso(tmp)
        info = ok('open_image', str(iso))
        check(info['count'] == 2, 'Test-Image mit zwei Digimon')
        m3 = ok('prepare_model', 3)
        check(m3['animations'] == ['anim_A1', 'anim_A2', 'anim_B0', 'anim_B1'] and m3['anim_source']['source'] == 'MODELDT',
              'Agumon: A und B über die Spieltabelle')
        m4 = ok('prepare_model', 4)
        slots = m4['anim_source']['slots']
        check(m4['animations'] == ['anim_A1', 'anim_A2'] and slots['A']['shared'] and slots['A']['file'] == 'A003AGUM.BIN',
              'Betamon: geteilte Animation aus A003AGUM (vorher: keine Animation)')
        g4 = json.loads((tmp / 'files/viewer' / m4['url']).read_text())
        check(g4['scenes'][0]['extras']['dw2_native']['texanim']['eyes'] == 0 and
              {m['extras']['abr'] for m in g4['materials'] if m['extras']['semi_transparent']} == {2}, 'Betamon: eigene Textur/ABR, keine Texturanimation')
        sh = m3.get('shadow')
        check(sh and json.loads((tmp / 'files/viewer' / sh).read_text())['meshes'] and not m3.get('shadow_error'),
              'Schattenmodell 0x5B (kleine 32×32-TIM) über die Dateitabelle gelesen')
        from PIL import Image as _I
        sdoc = json.loads((tmp / 'files/viewer' / sh).read_text())
        spng = _I.open(io.BytesIO(base64.b64decode(sdoc['images'][0]['uri'].split(',', 1)[1])))
        check(spng.size == (128, 256) and spng.getpixel((0, 0))[3] > 0 and spng.getpixel((0, 0))[:3] == (0, 0, 0)
              and spng.getpixel((100, 100))[3] == 0, 'Schattentextur: schwarz, außerhalb der kleinen TIM durchsichtig')
        audit = ok('animation_audit')
        s = audit['summary']
        check(s['models'] == 2 and s['errors'] == 0 and s['with_tex_cycles'] == 1 and s['with_shared_anims'] == 1
              and s['with_table_gaps'] == 2 and s['with_abr_non_average'] == 2 and s['with_sheared_keys'] == 2, 'Animationsprüfung zählt korrekt')
        check(Path(audit['path']).is_file() and Path(audit['csv']).read_text(encoding='utf-8-sig').startswith('id;code'), 'Prüfbericht JSON/CSV geschrieben')
        z = ok('native_files_export', 4)
        import zipfile
        with zipfile.ZipFile(z['path']) as zf:
            names = set(zf.namelist())
        check(names == {'M004BETA.BIN', 'A003AGUM.BIN', 'zuordnung.json'}, 'Rohdaten-ZIP enthält Modell und zugeordnete Animation')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILS:
        raise SystemExit(f'{len(FAILS)} Prüfungen fehlgeschlagen')
    print('Alle Animationstests bestanden')


def test_native_anim():
    run()


if __name__ == '__main__':
    run()
