"""DW3 model names from the game's own name text (DIGNAM), for the import window and the editor.

Sources (dw3_decomp, MIT, https://github.com/ReGame-Labs/dw3_decomp):
- include/engine/file.h: TEXT_DIGIMON_NAMES = 0x4F ("DIGNAM", USDIGNAM.BIN); TEXT_FILE(file) = file on
  the USA disc. The European disc keeps one copy per language at other numbers (not read here).
- src/engine/text/text_tools.c getString(table, i): s32 count, then s32 offsets; string i is at
  table + table[i + 1]. battle_test.c names a fighter with getString(DIGNAM, FighterEntry.kind).
- src/engine/text/font.c decodeChar (non-Shift-JIS text): 0 ends, 1 + n is icon n, 2/3 + n are
  control codes (FONT_CODE_LENGTHS), 4.. are glyphs; FONT_GLYPH_MAP / FONT_ICON_MAP give each
  glyph's and icon's Shift-JIS character (tables below, copied from text_tools.c).
- dw3_fighters.fighters: FighterEntry {id, index, kind} and FighterInfo.model (file number), which
  ties each model file to the fighter(s) that use it.
Nothing is guessed: a name comes from the disc, or the model keeps its file name with a status that
says why. Alternative spellings are marked as not from the game.
"""
import json
import struct
import unicodedata
from pathlib import Path

DIGNAM_US = 0x4F
FONT_CODE_LENGTHS = (1, 2, 3, 2, 5, 3, 3, 2, 3, 2, 0)
GLYPHS = (0x824F,0x8250,0x8251,0x8252,0x8253,0x8254,0x8255,0x8256,0x8257,0x8258,0x8260,0x8261,0x8262,0x8263,0x8264,0x8265,0x8266,0x8267,0x8268,0x8269,0x826A,0x826B,0x826C,0x826D,0x826E,0x826F,0x8270,0x8271,0x8272,0x8273,0x8274,0x8275,0x8276,0x8277,0x8278,0x8279,0x8281,0x8282,0x8283,0x8284,0x8285,0x8286,0x8287,0x8288,0x8289,0x828A,0x828B,0x828C,0x828D,0x828E,0x828F,0x8290,0x8291,0x8292,0x8293,0x8294,0x8295,0x8296,0x8297,0x8298,0x8299,0x829A,0x829F,0x82A0,0x82A1,0x82A2,0x82A3,0x82A4,0x82A5,0x82A6,0x82A7,0x82A8,0x82A9,0x82AA,0x82AB,0x82AC,0x82AD,0x82AE,0x82AF,0x82B0,0x82B1,0x82B2,0x82B3,0x82B4,0x82B5,0x82B6,0x82B7,0x82B8,0x82B9,0x82BA,0x82BB,0x82BC,0x82BD,0x82BE,0x82BF,0x82C0,0x82C1,0x82C2,0x82C3,0x82C4,0x82C5,0x82C6,0x82C7,0x82C8,0x82C9,0x82CA,0x82CB,0x82CC,0x82CD,0x82CE,0x82CF,0x82D0,0x82D1,0x82D2,0x82D3,0x82D4,0x82D5,0x82D6,0x82D7,0x82D8,0x82D9,0x82DA,0x82DB,0x82DC,0x82DD,0x82DE,0x82DF,0x82E0,0x82E1,0x82E2,0x82E3,0x82E4,0x82E5,0x82E6,0x82E7,0x82E8,0x82E9,0x82EA,0x82EB,0x82EC,0x82ED,0x82F0,0x82F1,0x8340,0x8341,0x8342,0x8343,0x8344,0x8345,0x8346,0x8347,0x8348,0x8349,0x834A,0x834B,0x834C,0x834D,0x834E,0x834F,0x8350,0x8351,0x8352,0x8353,0x8354,0x8355,0x8356,0x8357,0x8358,0x8359,0x835A,0x835B,0x835C,0x835D,0x835E,0x835F,0x8360,0x8361,0x8362,0x8363,0x8364,0x8365,0x8366,0x8367,0x8368,0x8369,0x836A,0x836B,0x836C,0x836D,0x836E,0x836F,0x8370,0x8371,0x8372,0x8373,0x8374,0x8375,0x8376,0x8377,0x8378,0x8379,0x837A,0x837B,0x837C,0x837D,0x837E,0x8380,0x8381,0x8382,0x8383,0x8384,0x8385,0x8386,0x8387,0x8388,0x8389,0x838A,0x838B,0x838C,0x838D,0x838E,0x838F,0x8392,0x8393,0x8394,0x8145,0x8148,0x8149,0x815B,0x8160)
ICONS = (0x8140,0x8141,0x8142,0x8143,0x8144,0x8145,0x8146,0x8147,0x8148,0x8149,0x814F,0x8151,0x815B,0x815C,0x815E,0x815F,0x8160,0x8163,0x8166,0x8168,0x8169,0x816A,0x8175,0x8176,0x817B,0x817C,0x817E,0x8181,0x8183,0x8184,0x8185,0x8186,0x8187,0x8188,0x8189,0x818A,0x818E,0x818F,0x8190,0x8191,0x8192,0x8193,0x8195,0x8198,0x8199,0x819A,0x819B,0x819C,0x819F,0x81A0,0x81A1,0x81A2,0x81A3,0x81A5,0x81A8,0x81A9,0x81AA,0x81AB,0x889F,0x88A0,0x88A1,0x88A2,0x88A3,0x88A4,0x88A5,0x88A6,0x88A7,0x88A8,0x88A9,0x88AA,0x88AB,0x88AC,0x88AD,0x88AE,0x88AF,0x88B0,0x88B1,0x88B2,0x88B3,0x88B4,0x88B5,0x88B6,0x88B7,0x88B8,0x88B9,0x88BA,0x88BB,0x88BC,0x88BD,0x88BE,0x88BF,0x88C0,0x88C1,0x88C2,0x88C3,0x88C4,0x88C5,0x88C6,0x88C7,0x88C8,0x88C9,0x88CA,0x88CB,0x88CC,0x88CD,0x88CE,0x88CF,0x88D0,0x88D1,0x88D2,0x88D3,0x88D4,0x88D5,0x88D6)

# common English spellings for names the game abbreviates; shown and searched, marked as not
# from the game data
ALIASES = {
    'Imperialdramon-F': ['Imperialdramon Fighter Mode', 'Imperialdramon FM', 'ImperialdramonFM'],
    'Imperialdramon-P': ['Imperialdramon Paladin Mode', 'Imperialdramon PM', 'ImperialdramonPM'],
    'BK WarGreymon': ['BlackWarGreymon', 'Black WarGreymon'],
    'BK Seraphimon': ['Black Seraphimon'],
    'BK MegaGargomon': ['Black MegaGargomon'],
    'BK Imperialdramon': ['Black Imperialdramon'],
    'BK WarGrowlmon': ['Black WarGrowlmon', 'BlackWarGrowlmon'],
    'BK KingNumemon': ['Black KingNumemon'],
    'H-Kabuterimon': ['HerculesKabuterimon', 'Hercules Kabuterimon'],
    'Myotismon': ['Vamdemon'],
    'Veemon': ['V-mon'],
    'Gallantmon': ['Dukemon'],
    'Omnimon': ['Omegamon'],
}
STATUS = {
    'unique': 'Aus Spieldaten, eindeutig',
    'shared': 'Aus Spieldaten, Name bei mehreren Modellen (Variante über Dateikürzel)',
    'placeholder': 'Im Spiel ohne echten Namen (Platzhalter)',
    'no_fighter': 'Kein Kämpfer in der DW3-Kämpfertabelle',
    'unreadable': 'Namenstext nicht lesbar (nur USA-Version unterstützt)',
}


def _char(code):
    c = bytes([code >> 8, code & 0xFF]).decode('shift_jis', errors='replace')
    c = unicodedata.normalize('NFKC', c)
    return {'\u2212': '-', '\u3000': ' '}.get(c, c)


def decode(raw):
    """One DIGNAM string (bytes up to its 0) as text."""
    out, i = [], 0
    while i < len(raw) and raw[i] != 0:
        b = raw[i]
        if b == 1:
            n = raw[i + 1] if i + 1 < len(raw) else 0
            out.append(_char(ICONS[n - 1]) if 1 <= n <= len(ICONS) else '?')
            i += 2
        elif b < 4:
            n = raw[i + 1] if i + 1 < len(raw) else 0
            i += FONT_CODE_LENGTHS[n] if n < len(FONT_CODE_LENGTHS) and FONT_CODE_LENGTHS[n] else 2
        elif b - 4 < len(GLYPHS):
            out.append(_char(GLYPHS[b - 4]))
            i += 1
        else:
            out.append('?')
            i += 1
    return ''.join(out).strip()


def read_dignam(data):
    """All strings of a DIGNAM file: index -> text (index 0 is the empty first entry)."""
    if len(data) < 8:
        raise ValueError('DIGNAM zu kurz.')
    count = struct.unpack_from('<i', data)[0]
    if not 1 <= count <= 1000 or 4 + 4 * (count + 1) > len(data):
        raise ValueError('DIGNAM: ungültige Anzahl.')
    offs = struct.unpack_from(f'<{count + 1}i', data, 4)
    names = {}
    for i, o in enumerate(offs):
        if 0 < o < len(data):
            end = data.find(b'\0', o)
            names[i] = decode(data[o:end if end >= 0 else len(data)])
    return names


def build(disc, entries):
    """The name database for the model ENTRIES (Dw3Disc.entries order = catalog id)."""
    from . import dw3_fighters as F
    exe, _ = F._exe(disc)
    table, rows = F.fighters(disc)
    names, note = {}, None
    if exe == 'SLUS_014.36' and DIGNAM_US in table:
        lba, n = table[DIGNAM_US]
        try:
            names = read_dignam(disc.read(lba, n * 2048))
        except ValueError as e:
            note = str(e)
    else:
        note = f'{exe}: Namenstext wird nur in der USA-Version gelesen.'
    by_lba = {lba: fid for fid, (lba, _) in table.items()}
    users = {}
    for r in rows:
        users.setdefault(r['model'][0], []).append(r)
    out = []
    for cid, e in enumerate(entries):
        stem = Path(e.path).stem.upper()
        fid = by_lba.get(e.lba)
        fs = users.get(fid, [])
        kinds = sorted({r['kind'] for r in fs})
        row = {'id': cid, 'code': stem[4:] if len(stem) == 8 else stem, 'file': Path(e.path).name.split(';')[0],
               'path': e.path, 'file_number': fid, 'fighter_ids': sorted(r['id'] for r in fs),
               'name_index': kinds[0] if len(kinds) == 1 else None, 'enemy': bool(fs) and all(r['enemy'] for r in fs),
               'name': stem, 'aliases': [], 'variant': '', 'status': 'no_fighter'}
        if fs and len(kinds) == 1:
            text = names.get(kinds[0])
            if not names:
                row['status'] = 'unreadable'
            elif not text or len(text) < 3 or not any(ch.isupper() for ch in text):
                row['status'] = 'placeholder'
                row['raw_name'] = text or ''
            else:
                row['name'] = text
                row['status'] = 'unique'
        elif fs:
            row['status'] = 'unreadable'
        out.append(row)
    # same name on several models: mark the variant (partner / enemy, its file code)
    groups = {}
    for r in out:
        if r['status'] == 'unique':
            groups.setdefault(r['name'].lower(), []).append(r)
    for g in groups.values():
        if len(g) > 1:
            for k, r in enumerate(sorted(g, key=lambda r: (r['name_index'] is None, r['name_index'] if r['name_index'] is not None else -1, r['code'], r['id'])), 1):
                r['status'] = 'shared'
                r['variant'] = f"{'Gegner' if r['enemy'] else 'Partner'}, Variante {k} von {len(g)} ({r['code']})"
    for r in out:
        if r['status'] in ('unique', 'shared') and not r['variant']:
            r['variant'] = 'Gegner' if r['enemy'] else 'Partner'
        r['aliases'] = list(ALIASES.get(r['name'], []))
        r['status_text'] = STATUS[r['status']]
    return {'version': 1, 'source': exe, 'note': note, 'models': out}


def _norm(s):
    return ''.join(ch for ch in unicodedata.normalize('NFKC', str(s)).lower() if ch.isalnum())


def matches(row, query):
    """Case-insensitive search over name, aliases, code, file name and the ids."""
    q = str(query or '').strip()
    if not q:
        return True
    num = q.removeprefix('#')
    if num.isascii() and num.isdigit():
        return int(num) in [row['id'], row.get('file_number'), *row.get('fighter_ids', [])]
    nq = _norm(q)
    hay = [row['name'], row.get('raw_name', ''), row['code'], row['file'], *row['aliases']]
    if any(nq and nq in _norm(h) for h in hay):
        return True
    return False


def rank(row, query):
    """Sort key: exact name, then name start, then the rest (stable within each)."""
    nq, name = _norm(query), _norm(row['name'])
    names = [name] + [_norm(a) for a in row['aliases']]
    return 0 if nq in names else 1 if any(n.startswith(nq) for n in names) else 2


def load_or_build(cache_dir, key, disc, entries):
    """The database from CACHE_DIR/dw3_names_KEY.json, or built from the disc and saved there."""
    path = Path(cache_dir) / f'dw3_names_{key}.json'
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
        if doc.get('version') == 1 and len(doc.get('models', [])) == len(entries) and all(
                m['path'] == e.path for m, e in zip(doc['models'], entries)):
            return doc
    except (OSError, ValueError, KeyError, TypeError):
        pass
    doc = build(disc, entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)
    return doc
