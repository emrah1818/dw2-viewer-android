"""DNA-Digitation direkt im PS1-Image (Android-App / Web-Version 6.0).

Das Spiel bestimmt das DNA-Ergebnis in Stg20_GetDnaResult (dw2-pc-port src/stag2000/dna.c):

    Ergebnis = Stg20_DnaResultTbl[Typpaar][min(Stufe A, Stufe B) - 1][DNA-Gruppe A][DNA-Gruppe B]

    Typpaar  = Stg20_DnaTypeIndexTbl[Typ A][Typ B]   (Typ: DIGIMNDT +4, untere 4 Bit)
    Stufe    = DIGIMNDT +4, obere 4 Bit (0 Rookie, 1 Champion, 2 Ultimate, 3 Mega)
    Gruppe   = DIGIMNDT +3 (0–7; 8 = nur Bossformen, außerhalb der Tabelle)

Die Tabelle (3 × 3 × 8 × 8 Bytes) liegt in der Stage-Overlay-Datei STAG2000.PRO (USA, SLUS_011.93):
Symbol Stg20_DnaResultTbl = 0x80070138, Overlay geladen nach 0x80063360 (dw2-pc-port
configs/USA/sym.stag2000.txt, configs/USA/stag2000.yaml) → Dateioffset 0xCDD8. Bevor etwas
geschrieben wird, muss das Original von STAG2000.PRO im Image die SHA-1 aus stag2000.yaml haben
und an dieser Stelle die Tabelle aus dna.c stehen; sonst wird nichts verändert.

Eine DNA-Regel A + B → Ergebnis schreibt die zugehörige Tabellenzelle (beide Reihenfolgen).
Die Ergebnisstufe ist im Spiel die Stufe der Ergebnisart (DIGIMNDT); sie wird dort gesetzt.
Eine Zelle gilt für alle Paare mit gleichem Typpaar, gleicher kleinerer Stufe und gleichen
DNA-Gruppen – die Oberfläche zeigt, welche Paare das zusätzlich betrifft. Eigene Kombinationen
lassen sich über die DNA-Gruppe im Digitations-Editor trennen.
"""
import hashlib

OVERLAY = 'STAG2000.PRO'
OVERLAY_SHA1 = '9e8f8a1f1eb3aacda2b4a3492abce26264ee9029'
TABLE_OFFSET = 0x80070138 - 0x80063360     # 0xCDD8
TYPE_OFFSET = 0x8007012C - 0x80063360      # Stg20_DnaTypeIndexTbl, 0xCDCC
TYPE_INDEX = ((0, 0, 2), (0, 1, 1), (2, 1, 2))
TABLE_SIZE = 3 * 3 * 8 * 8
RANKS = ('Rookie', 'Champion', 'Ultimate', 'Mega')

# Stg20_DnaResultTbl aus dw2-pc-port src/stag2000/dna.c (Originaldaten des Spiels), zeilenweise.
_ROWS = '''
BCBCBCBF444412C5 BCBFBFBFBFBFBFC5 BCBF2E2E2E11C5C5 BFBF2EBFBFBFBFBF 44BF2EBF1F1F1FC5 44BF11BF1F111144 12BFC5BF1F111212 C5C5C5BFC54412C5
094C8FC624512F23 4C43434366666623 8F43B8B8B84E5B5B C643B832C6325F5F 2466B8C6C73AC20A 51664E323A5E264F 2F665B5FC2260845 23235B5F0A4F450A
7BBD68377171CBCA BD4343436666663D 6843BAC8C971CACA 3743C8C037C037C0 7166C9371B0D383D 716671C00D717171 CB66CA3738715858 CA3DCAC03D71583D
6F6F6F2D47470339 6F6F6F6F6F6F6FB6 6F6F6F6F6FCE3939 2D6F6F2D2D2D912D 476F6F2D625454B6 476FCE2D54CE47CE 036F399154470303 39B6392DB6CE03B6
1313130717CF05D2 13131313131313D2 1313131313211C1C 07131315806A8007 171313801430E9D1 CF13216A30164B34 05131C80E94B0505 D2D21C07D13405D1
B5B5B5BB0ED40C18 B5B5B5B5B5B5B518 B5B5B5B5B50EB9B9 BBB5B5BBBBB4B4B4 0EB5B5BBD33F28B9 D4B50EB43FB7B7D4 0CB5B9B428B70C7C 1818B9B4B9D47C18
7A7A7A4A676784DA 7A202020202020DA 7A20DBDBDB506D6D 4A20DB4A4A4A4A4A 6720DB4AD983606D 6720504A83505067 84206D4A60500484 DADA6D4A6D6784DA
5C498B89484886DD 493333333333336E 8B33DE194D22DCDC 8933198989898989 48334D890625646E 4833228925222248 8633DC8964228565 DD6EDC896E4865DD
8D1CE3E246468E70 1CE2E2E2E2E2E277 E3E27979792AE0E0 E2E279E2E2E2E2E2 46E279E242DF5A77 46E22AE2DF2A2A46 8EE2E0E25A2A361A 7077E0E277461AE1
'''
ORIGINAL_TABLE = bytes.fromhex(''.join(_ROWS.split()))
assert len(ORIGINAL_TABLE) == TABLE_SIZE


def _api():
    import android_api
    return android_api


def _overlay():
    """Eintrag von STAG2000.PRO und sein Original; geprüft über SHA-1 und Tabelleninhalt."""
    api = _api()
    session = api._need_session()
    if hasattr(session, 'pak'):
        raise ValueError('DNA im Image: bitte ein PS1-Image (BIN/ISO) öffnen.')
    found = [e for e in api.S.entries if not e.directory and e.path.replace('\\', '/').split('/')[-1].split(';')[0].upper() == OVERLAY]
    if len(found) != 1:
        raise ValueError('STAG2000.PRO (Digi-Labor) wurde im Image nicht eindeutig gefunden. DNA-Regeln im Image '
                         'gibt es nur für die USA-Version (SLUS_011.93).')
    entry = found[0]
    original = session.original(entry)
    if hashlib.sha1(original).hexdigest() != OVERLAY_SHA1:
        raise ValueError('STAG2000.PRO hat nicht den bekannten Inhalt der USA-Version. Die DNA-Tabelle wird nicht verändert.')
    if original[TABLE_OFFSET:TABLE_OFFSET + TABLE_SIZE] != ORIGINAL_TABLE or \
            original[TYPE_OFFSET:TYPE_OFFSET + 9] != bytes(sum(TYPE_INDEX, ())):
        raise ValueError('DNA-Tabelle steht nicht an der erwarteten Stelle. Die DNA-Tabelle wird nicht verändert.')
    return session, entry


def _species():
    """id -> (Typ, Stufe, DNA-Gruppe) aus dem aktuellen DIGIMNDT (mit vorgemerkten Änderungen)."""
    from dw2studio.core.evolution import EvolutionRepository
    from dw2studio.core.battle_skills import BaseTable
    api = _api()
    repo = EvolutionRepository(api._need_session(), api.S.entries)
    data = repo.session.current(repo.entry)
    out = {}
    for i, (offset, *_rest) in BaseTable(data).records.items():
        if 1 <= i <= 255:
            out[i] = (data[offset + 4] & 15, data[offset + 4] >> 4, data[offset + 3])
    return repo, out


def _cell(info, a, b):
    """(Index in der Tabelle für A,B), (für B,A) – oder ValueError, wenn das Spiel das Paar nicht nachschlägt."""
    names = _api()._current_names()
    for x in (a, b):
        if x not in info:
            raise ValueError(f'Digimon #{x:03} hat keinen DIGIMNDT-Eintrag.')
        typ, rank, group = info[x]
        if typ > 2:
            raise ValueError(f'#{x:03} {names.get(x, "")}: Typ {typ} kommt in der DNA-Tabelle des Spiels nicht vor.')
        if rank < 1:
            raise ValueError(f'#{x:03} {names.get(x, "")} ist Rookie: Das Digi-Labor nimmt für DNA nur Champion und höher.')
        if group > 7:
            raise ValueError(f'#{x:03} {names.get(x, "")} hat DNA-Gruppe {group} (nur Bossformen); '
                             'im Digitations-Editor eine DNA-Gruppe 0–7 wählen.')
    ta, ra, ga = info[a]
    tb, rb, gb = info[b]
    m = min(ra, rb) - 1
    if m > 2:
        raise ValueError('Zwei Mega-Partner: die DNA-Tabelle des Spiels hat dafür keinen Eintrag.')
    base = (TYPE_INDEX[ta][tb] * 3 + m) * 64
    return base + ga * 8 + gb, base + gb * 8 + ga


def _shared(info, a, b, cells):
    """Andere Paare (Champion+), die dieselbe Tabellenzelle verwenden."""
    out = []
    ids = sorted(info)
    for i, x in enumerate(ids):
        for y in ids[i + 1:]:
            if {x, y} == {a, b}:
                continue
            try:
                if set(_cell(info, x, y)) & set(cells):
                    out.append((x, y))
            except ValueError:
                pass
    return out


def _build(rules, info):
    table = bytearray(ORIGINAL_TABLE)
    owner = {}
    for (a, b), (result, _rank) in sorted(rules.items()):
        for c in _cell(info, a, b):
            if c in owner and table[c] != result:
                x, y = owner[c]
                raise ValueError(f'#{a:03} + #{b:03} teilt die Tabellenzelle des Spiels mit der Regel #{x:03} + #{y:03}, '
                                 'aber mit anderem Ergebnis. Im Digitations-Editor einem Partner eine andere DNA-Gruppe geben.')
            table[c] = result
            owner[c] = (a, b)
    return bytes(table)


def _stage(rules, info):
    session, entry = _overlay()
    data = bytearray(session.current(entry))
    data[TABLE_OFFSET:TABLE_OFFSET + TABLE_SIZE] = _build(rules, info)
    session.stage(entry, bytes(data), 'DNA-Digitation (Digi-Labor)')


def _set_rank(repo, identifier, rank):
    current = repo.info(identifier)
    if current['rank'] != rank:
        repo.change(identifier, current['rows'], rank=rank)


def dna_info():
    api = _api()
    model = api._dna_model()
    names = api._current_names()
    data = {**model.to_dict(), 'choices': [{'id': i, 'name': names.get(i, str(i))} for i in api._dna_choices()]}
    try:
        _overlay()
        repo, info = _species()
        for rule in data['rules']:
            try:
                cells = _cell(info, rule['a'], rule['b'])
                rule['shared'] = [{'a': x, 'b': y} for x, y in _shared(info, rule['a'], rule['b'], cells)][:50]
            except ValueError as exc:
                rule['problem'] = str(exc)
        data['image'] = True
    except ValueError as exc:
        data['image'] = False
        data['problem'] = str(exc)
    return data


def _atomic(fn):
    """Bei einem Fehler bleiben Image-Änderungen und Regeln wie vorher (keine halbe Regel)."""
    def run(*args):
        api = _api()
        edits = dict(api._need_session().edits)
        rules = dict(api.S.dna_overrides)
        try:
            return fn(*args)
        except Exception:
            api.S.session.edits.clear()
            api.S.session.edits.update(edits)
            api.S.dna_overrides = rules
            raise
    run.__name__ = fn.__name__
    return run


@_atomic
def dna_set(a, b, result, rank):
    api = _api()
    S = api.S
    model = api._dna_model()
    model.valid_ids = frozenset(api._dna_choices())
    model.set(a, b, result, rank)
    repo, info = _species()
    # Ergebnisstufe = Stufe der Ergebnisart im Spiel; vor dem Tabellenbau setzen (die Zellen hängen
    # von den Stufen der Partner ab).
    _set_rank(repo, result, rank)
    repo, info = _species()
    _stage(model.rules, info)
    S.dna_overrides = dict(model.rules)
    S.dna_modified = False
    return dna_info()


@_atomic
def dna_remove(a, b):
    api = _api()
    S = api.S
    model = api._dna_model()
    removed = model.rules.get(tuple(sorted((a, b))))
    model.remove(a, b)
    repo, info = _species()
    if removed and not any(r == removed[0] for r, _ in model.rules.values()):
        # Stufe der Ergebnisart wieder wie im Original, wenn keine Regel sie mehr braucht
        from dw2studio.core.battle_skills import BaseTable
        original = repo.session.original(repo.entry)
        offset = BaseTable(original).records[removed[0]][0]
        _set_rank(repo, removed[0], original[offset + 4] >> 4)
        repo, info = _species()
    _stage(model.rules, info)
    S.dna_overrides = dict(model.rules)
    S.dna_modified = False
    return dna_info()


def pending(original):
    """DNA-Regeln stehen als geänderte STAG2000.PRO in der Liste, nicht als PC-Port-Mod."""
    return [p for p in original() if p.get('kind') != 'dna']


def discard(original, kind, path=None, lba=None):
    result = original(kind, path, lba)
    if kind == 'file' and path and path.replace('\\', '/').split('/')[-1].split(';')[0].upper() == OVERLAY:
        _api().S.dna_overrides = {}
    return result


def _follow(original):
    """Digitations-Editor ändert Stufe/Typ/DNA-Gruppe: vorhandene DNA-Regeln auf ihre neuen
    Tabellenzellen umschreiben (oder mit Erklärung abweisen, alles in einem Schritt)."""
    @_atomic
    def run(*args):
        result = original(*args)
        if _api().S.dna_overrides:
            _repo, info = _species()
            _stage(_api().S.dna_overrides, info)
        return result
    return run


def register(methods, mutating):
    methods['evolution_line'] = _follow(methods['evolution_line'])
    methods['set_evolution'] = _follow(methods['set_evolution'])
    methods['dna_info'] = dna_info
    methods['dna_set'] = dna_set
    methods['dna_remove'] = dna_remove
    p, d = methods['pending'], methods['discard']
    methods['pending'] = lambda: pending(p)
    methods['discard'] = lambda kind, path=None, lba=None: discard(d, kind, path, lba)
