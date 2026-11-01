"""Prüft die Android-Brücke (android_api.py) ohne Qt/VTK mit synthetischem ISO und Spielstand.

Aufruf:  python tests/test_android_api.py
Tabellen- und Spielstandlayouts stammen aus den Tests der Desktop-Version (v3.8/v4.0).
"""
import json, os, shutil, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/src/main/python'))
os.environ['DW2_DATA_DIR'] = str(ROOT / 'app/src/main/assets/data')

from dw2studio.core.digimon_names import encode_name  # noqa: E402
from dw2studio.core.roster_save import ROSTER, STRIDE, checksum  # noqa: E402
import android_api as api  # noqa: E402


def call(method, *args):
    r = json.loads(api.call(method, json.dumps(list(args))))
    return r


def ok(method, *args):
    r = call(method, *args)
    assert r['ok'], (method, r)
    return r['data']


def tables():
    names = {1: 'Basic', 31: 'Pepper Breath', 36: 'Nova Blast', 48: 'Giga Blaster', 90: 'Hail Storm', 96: 'SubZero Ice', 180: 'Hyper Flash'}
    pool = bytearray(4); pointers = {}
    for identifier, text in names.items():
        pointers[identifier] = len(pool); pool += encode_name(text) + b'\xff'
    desc = len(pool); pool += encode_name('Battle skill') + b'\xfe\x41\xff'; pool += bytes((-len(pool)) % 4)
    start = len(pool); waza = pool + bytearray(68 * (len(names) + 1)); struct.pack_into('<I', waza, 0, start)
    for row, (identifier, _) in enumerate(names.items()):
        o = start + 68 * row; waza[o:o + 68] = bytes([0xA5]) * 68
        struct.pack_into('<I', waza, o, identifier | ((row % 4) << 18) | (6 << 20) | (2 << 24) | (3 << 28))
        waza[o + 4] = 12; struct.pack_into('<h', waza, o + 8, 40); struct.pack_into('<II', waza, o + 0x24, pointers[identifier], desc)
    base = bytearray(18 * 5)
    for row, (identifier, skill) in enumerate([(3, 31), (5, 36), (12, 48), (23, 96)]):
        base[row * 18:row * 18 + 18] = bytes([0xAB]) * 18; struct.pack_into('<hB', base, row * 18, identifier, skill)
    enemy = bytearray(400)
    for group, specs in enumerate([[(5, (36, 180, 0))], [(23, (96, 0, 0)), (3, (31, 0, 0))], [(23, (90, 1, 0))]], 1):
        o = (group - 1) * 100; enemy[o] = group
        for slot, (identifier, skills) in enumerate(specs):
            row = o + 8 + slot * 30; enemy[row:row + 30] = bytes([0x31]) * 30
            struct.pack_into('<h', enemy, row, identifier); enemy[row + 10] = 7 + group; enemy[row + 15:row + 18] = bytes(skills)
            rules = ((1, 2, 0), (0, 1, 7), (0, 4, 0), (0, 0, 0)) if skills[1] else ((0, 1, 7), (0, 4, 0), (0, 0, 0), (0, 0, 0))
            enemy[row + 18:row + 30] = bytes(v for r in rules for v in r)
    return {'DIGIMNDT.BIN': bytes(base), 'ENEMYSET.BIN': bytes(enemy), 'WAZADATA.BIN': bytes(waza)}


def dir_record(name, lba, size, directory=False):
    ident = name.encode(); length = 33 + len(ident)
    rec = bytearray(length + (length % 2)); rec[0] = len(rec); struct.pack_into('<I', rec, 2, lba); struct.pack_into('>I', rec, 6, lba)
    struct.pack_into('<I', rec, 10, size); struct.pack_into('>I', rec, 14, size); rec[25] = 2 if directory else 0; rec[32] = len(ident); rec[33:33 + len(ident)] = ident
    return bytes(rec)


def make_iso(folder):
    files = {**tables(), 'M003AGUM.BIN': b'\x00' * 100, 'A003AGUM.BIN': b'\x00' * 100}
    sectors = [bytearray(2048) for _ in range(60)]
    root = dir_record('\x00', 18, 2048, True) + dir_record('\x01', 18, 2048, True)
    lba = 20
    for name, data in files.items():
        root += dir_record(name + ';1', lba, len(data))
        sectors[lba][:len(data)] = data
        lba += 1
    sectors[18][:len(root)] = root
    pvd = sectors[16]; pvd[0] = 1; pvd[1:6] = b'CD001'; pvd[40:72] = b'DW2TEST'.ljust(32)
    pvd[156:190] = dir_record('\x00', 18, 2048, True)[:34].ljust(34, b'\0')
    path = Path(folder) / 'game.iso'; path.write_bytes(b''.join(bytes(s) for s in sectors)); return path


def make_save(folder):
    data = bytearray(0x4000); data[:4] = b'SC\x13\x02'
    struct.pack_into('<I', data, 0x200, 0x100)
    offset = ROSTER; data[offset:offset + STRIDE] = b'\xA5' * STRIDE
    data[offset:offset + 2] = bytes([3, 3]); data[offset + 13:offset + 16] = bytes([5, 2, 30])
    struct.pack_into('<i7h', data, offset + 0x10, 35, 100, 80, 90, 70, 30, 20, 15)
    data[offset + 0x47:offset + 0x49] = bytes([17, 4])
    data[offset + 0x4C:offset + 0x5A] = (encode_name('Agumon') + b'\xff').ljust(14, b'\xff')
    struct.pack_into('<H', data, 0x3FFC, 0x102); struct.pack_into('<H', data, 0x3FFE, checksum(data))
    path = Path(folder) / 'save.sav'; path.write_bytes(data); return path


def build_stub(folder):
    src = Path(folder) / 'stub.cpp'
    src.write_text('#include <cstdio>\n#include <string>\nextern "C" int dw2_convert(const char*s,const char*d){std::string p=std::string(d)+"/M003AGUM.gltf";FILE*f=fopen(p.c_str(),"wb");if(!f)return 2;fputs("{\\"asset\\":{\\"version\\":\\"2.0\\"},\\"animations\\":[{\\"name\\":\\"Idle\\"},{\\"name\\":\\"Walk\\"}]}",f);fclose(f);return 0;}')
    lib = Path(folder) / 'libdw2conv.so'
    subprocess.run(['g++', '-shared', '-fPIC', str(src), '-o', str(lib)], check=True)
    return lib


def run():
    tmp = Path(tempfile.mkdtemp())
    try:
        os.environ['DW2_CONVERTER_LIB'] = str(build_stub(tmp))
        api.configure(str(tmp / 'files'), str(tmp))
        iso = make_iso(tmp)
        info = ok('open_image', str(iso)); assert info['count'] == 1, info
        cat = ok('catalog'); assert cat[0]['id'] == 3 and cat[0]['code'] == 'AGUM', cat
        # Typ / Specialty
        assert ok('set_type', 3, 2)['changed'] and ok('type_info', 3)['name'] == 'Virus'
        orig_type = ok('type_info', 3)['original']
        assert ok('set_specialty', 3, 1)['changed'] and ok('specialty_info', 3)['name'] == 'Fire'
        # Gegnerwerte inkl. Bereichsprüfung
        ev = ok('enemy_values', 23); assert len(ev['rows']) == 2, ev
        key = ','.join(map(str, ev['rows'][0]['key']))
        assert ok('set_enemy_values', 23, {key: {'hp': 999, 'attack': 77}})['changed']
        assert ok('enemy_values', 23)['rows'][0]['values']['hp'] == 999
        bad = call('set_enemy_values', 23, {key: {'attack': 999}}); assert not bad['ok'] and 'attack' in bad['error']
        # Attacken: Standard, Gegnerslots, globale Technikwerte
        ai = ok('attack_info', 23); assert ai['default'] == 96 and len(ai['encounters']) == 2 and ai['skills']
        enc = {','.join(map(str, ai['encounters'][0]['key'])): [31, 0, 0]}
        assert ok('apply_attacks', 23, 36, enc, {'36': {'mp': 20}})['files'] >= 1
        ai2 = ok('attack_info', 23); assert ai2['default'] == 36 and ai2['original_default'] == 96
        assert [s for s in ai2['skills'] if s['id'] == 36][0]['mp'] == 20
        # Vormerkungen, Mod-Projekt, Image speichern
        p = ok('pending'); assert {x['file'] for x in p} >= {'DIGIMNDT.BIN', 'ENEMYSET.BIN', 'WAZADATA.BIN'}, p
        proj = ok('save_project', 'test'); assert Path(proj['path']).is_file()
        saved = ok('save_image', 'test_bearbeitet'); out = Path(saved['path'])
        assert out.name.endswith('.iso') and out.stat().st_size == iso.stat().st_size and out.read_bytes() != iso.read_bytes()
        # Verwerfen + Projekt wieder laden
        for item in p:
            ok('discard', 'file', item['path'], item['lba'])
        assert ok('pending') == [] and ok('type_info', 3)['code'] == orig_type
        assert ok('load_project', proj['path'])['edits'] == 3 and ok('type_info', 3)['name'] == 'Virus'
        # Gespeichertes Image erneut öffnen: Änderungen sind wirklich drin
        ok('open_image', str(out)); assert ok('type_info', 3)['name'] == 'Virus' and ok('attack_info', 23)['default'] == 36
        # Memorycard / Spielstand
        ok('roster_open', str(make_save(tmp)))
        rows = ok('roster_records', 3); assert len(rows) == 1 and rows[0]['parent1'] == 17
        r = ok('roster_change', rows[0]['key'], {'max_hp': 500, 'hp': 400, 'exp': 1000, 'parent1': 5})
        assert r['record']['hp'] == 400 and r['next_exp'] >= 0
        assert not call('roster_change', rows[0]['key'], {'hp': 9999})['ok']  # HP > Max
        assert any(x['kind'] == 'roster' for x in ok('pending'))
        exp = ok('roster_export', 'spielstand'); assert Path(exp['path']).is_file()
        ok('roster_open', exp['path']); assert ok('roster_records', 3)[0]['hp'] == 400
        # Modell (Stub-Konverter) inkl. Cache-Treffer
        m = ok('prepare_model', 3); assert m['animations'] == ['Idle', 'Walk'], m
        assert (tmp / 'files/viewer' / m['url']).is_file() and ok('prepare_model', 3)['url'] == m['url']
        # Fehler kommen als JSON zurück
        assert not call('rename', 999, 'X')['ok'] and not call('gibt_es_nicht')['ok']
        print('Alle Android-API-Tests bestanden')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_android_api():
    run()


if __name__ == '__main__':
    run()
