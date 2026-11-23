"""6.0: DNA-Regeln direkt im PS1-Image (dna_image.py) – Tabelle des Digi-Labors in STAG2000.PRO.

Synthetisches ISO mit selbst gebautem DIGIMNDT.BIN und einer STAG2000.PRO-Attrappe, die die
Originaltabelle an der dokumentierten Stelle trägt. Die SHA-1-Prüfung des echten Overlays wird
für die Attrappe umgestellt; alles andere läuft wie mit einem echten Image.
"""
import json
import struct

import pytest
import android_api as api
import dna_image
from fixture_dw3 import _dir_record


def digimndt(rows):
    out = bytearray()
    for ident, typ, rank, group in rows:
        r = bytearray(18)
        struct.pack_into('<h', r, 0, ident)
        r[3] = group
        r[4] = (rank << 4) | typ
        r[17] = 0xA5
        out += r
    return bytes(out + bytes(18))


# id, Typ (0–2), Stufe (0 Rookie … 3 Mega), DNA-Gruppe
ROWS = ((3, 0, 0, 0), (5, 0, 1, 0), (6, 1, 1, 2), (7, 0, 1, 0), (8, 2, 2, 5), (9, 1, 3, 1), (10, 0, 1, 8), (11, 1, 2, 3))


def overlay():
    data = bytearray(0xD000)
    data[dna_image.TYPE_OFFSET:dna_image.TYPE_OFFSET + 9] = bytes(sum(dna_image.TYPE_INDEX, ()))
    data[dna_image.TABLE_OFFSET:dna_image.TABLE_OFFSET + dna_image.TABLE_SIZE] = dna_image.ORIGINAL_TABLE
    return bytes(data)


def make_iso(folder, files):
    sectors = [bytearray(2048) for _ in range(80)]
    root = _dir_record('\x00', 18, 2048, True) + _dir_record('\x01', 18, 2048, True)
    lba = 20
    for name, data in files.items():
        root += _dir_record(name + ';1', lba, len(data))
        for i in range((len(data) + 2047) // 2048):
            chunk = data[i * 2048:(i + 1) * 2048]
            sectors[lba + i][:len(chunk)] = chunk
        lba += (len(data) + 2047) // 2048
    sectors[18][:len(root)] = root
    pvd = sectors[16]
    pvd[0] = 1; pvd[1:6] = b'CD001'
    pvd[156:190] = _dir_record('\x00', 18, 2048, True)[:34].ljust(34, b'\0')
    path = folder / 'dna.iso'
    path.write_bytes(b''.join(bytes(s) for s in sectors))
    return path


def call(method, *args):
    r = json.loads(api.call(method, json.dumps(args)))
    assert r['ok'], r
    return r['data']


def fail(method, *args):
    r = json.loads(api.call(method, json.dumps(args)))
    assert not r['ok']
    return r['error']


@pytest.fixture
def image(tmp_path, monkeypatch):
    import hashlib
    ov = overlay()
    monkeypatch.setattr(dna_image, 'OVERLAY_SHA1', hashlib.sha1(ov).hexdigest())
    iso = make_iso(tmp_path, {'DIGIMNDT.BIN': digimndt(ROWS), 'STAG2000.PRO': ov})
    api.configure(str(tmp_path / 'store'), '')
    call('open_image', str(iso))
    return iso


def table():
    from dw2studio.core.disc import Disc
    entry = next(e for e in api.S.entries if e.path.upper().endswith('STAG2000.PRO;1') or e.path.upper().endswith('STAG2000.PRO'))
    return api.S.session.current(entry)[dna_image.TABLE_OFFSET:dna_image.TABLE_OFFSET + dna_image.TABLE_SIZE]


def cell(a, b):
    t = {r[0]: r for r in ROWS}
    _, ta, ra, ga = t[a]
    _, tb, rb, gb = t[b]
    return (dna_image.TYPE_INDEX[ta][tb] * 3 + min(ra, rb) - 1) * 64 + ga * 8 + gb


def test_table_matches_the_decompilation():
    assert dna_image.TABLE_OFFSET == 0xCDD8 and dna_image.TYPE_OFFSET == 0xCDCC
    # Stichproben aus dna.c: [0][0][0][0] = 0xBC, [2][2][7][7] = 0xE1, [1][1][3][4] = 0x80
    t = dna_image.ORIGINAL_TABLE
    assert t[0] == 0xBC and t[-1] == 0xE1 and t[(1 * 3 + 1) * 64 + 3 * 8 + 4] == 0x80


def test_info_reports_image_mode(image):
    info = call('dna_info')
    assert info['image'] is True and info['rules'] == []
    assert {c['id'] for c in info['choices']} == {r[0] for r in ROWS}


def test_set_writes_both_orders_and_result_rank(image):
    call('dna_set', 5, 6, 9, 3)
    t = table()
    assert t[cell(5, 6)] == 9 and t[cell(6, 5)] == 9
    changed = sum(1 for x, y in zip(t, dna_image.ORIGINAL_TABLE) if x != y)
    assert changed == 2
    info = call('dna_info')
    assert info['rules'] == [{'a': 5, 'b': 6, 'result': 9, 'rank': 3, 'shared': [{'a': 6, 'b': 7}]}]
    pend = call('pending')
    assert [p['file'] for p in pend if p['kind'] == 'file'] and not [p for p in pend if p['kind'] == 'dna']


def test_result_rank_is_written_to_digimndt(image):
    from dw2studio.core.evolution import EvolutionRepository
    call('dna_set', 5, 6, 11, 3)                      # #11 ist Ultimate, Regel verlangt Mega
    repo = EvolutionRepository(api.S.session, api.S.entries)
    assert repo.info(11)['rank'] == 3
    call('dna_remove', 5, 6)                           # keine Regel braucht #11 mehr: Original-Stufe zurück
    assert repo.info(11)['rank'] == 2
    assert table() == dna_image.ORIGINAL_TABLE
    assert not api.S.session.edits


def test_undo_redo(image):
    call('dna_set', 5, 8, 9, 3)
    assert table()[cell(5, 8)] == 9
    call('undo')
    assert table() == dna_image.ORIGINAL_TABLE and not api.S.dna_overrides
    call('redo')
    assert table()[cell(5, 8)] == 9 and api.S.dna_overrides


def test_conflicting_rules_in_one_cell_are_refused_without_side_effects(image):
    call('dna_set', 5, 6, 9, 3)
    before = dict(api.S.session.edits)
    msg = fail('dna_set', 6, 7, 8, 2)                  # 6+7 nutzt dieselbe Zelle wie 5+6
    assert 'DNA-Gruppe' in msg
    assert api.S.session.edits == before and list(api.S.dna_overrides) == [(5, 6)]


def test_game_rules_rookie_and_boss_group(image):
    assert 'Rookie' in fail('dna_set', 3, 5, 9, 3)
    assert 'DNA-Gruppe 8' in fail('dna_set', 10, 5, 9, 3)
    assert not api.S.session.edits


def test_discard_of_overlay_clears_rules(image):
    call('dna_set', 5, 6, 9, 3)
    stag = next(p for p in call('pending') if 'STAG2000' in p['file'].upper())
    call('discard', 'file', stag['path'], stag['lba'])
    assert not api.S.dna_overrides


def test_new_image_contains_the_rule(image, tmp_path):
    call('dna_set', 5, 6, 9, 3)
    out = call('save_image', 'mit_dna')
    api.configure(str(tmp_path / 'store2'), '')
    call('open_image', out['path'])
    assert table()[cell(5, 6)] == 9


def test_unknown_overlay_is_refused(tmp_path):
    iso = make_iso(tmp_path, {'DIGIMNDT.BIN': digimndt(ROWS), 'STAG2000.PRO': overlay()})   # SHA-1 passt nicht
    api.configure(str(tmp_path / 'store'), '')
    call('open_image', str(iso))
    assert call('dna_info')['image'] is False
    assert 'USA-Version' in fail('dna_set', 5, 6, 9, 3)
    assert not api.S.session.edits


def test_dna_group_change_in_evolution_editor_moves_the_rule(image):
    call('dna_set', 5, 6, 9, 3)
    old = cell(5, 6)
    call('evolution_line', [{'id': 5, 'rows': [], 'rank': 1, 'dna_group': 4}])
    t = table()
    new = (dna_image.TYPE_INDEX[0][1] * 3 + 0) * 64 + 4 * 8 + 2
    assert t[new] == 9 and t[old] == dna_image.ORIGINAL_TABLE[old]
    call('undo')
    assert table()[old] == 9


def test_editor_change_that_would_collide_is_refused_atomically(image):
    call('dna_set', 5, 6, 9, 3)       # Typpaar 0/1, Champion, Gruppen 0×2
    call('dna_set', 7, 11, 8, 2)      # Typpaar 0/1, Champion, Gruppen 0×3
    before = dict(api.S.session.edits)
    msg = fail('evolution_line', [{'id': 11, 'rows': [], 'rank': 2, 'dna_group': 2}])   # 7+11 fiele in die Zelle von 5+6
    assert 'DNA-Gruppe' in msg
    assert api.S.session.edits == before
