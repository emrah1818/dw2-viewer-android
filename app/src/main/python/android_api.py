"""Qt-freie Schnittstelle zwischen der Android-Oberfläche (WebView) und dem DW2-Kern.

Kotlin ruft ausschließlich `call(methode, json_argumente)` auf und erhält immer
einen JSON-Text {"ok": true, "data": ...} oder {"ok": false, "error": "..."}.
Alle Schreibvorgänge nutzen dieselben Kernmodule wie die Windows-Version
(EditSession, NameRepository, TypeRepository, PropertyRepository, RosterSave ...).
"""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import struct
import threading
import time
import traceback

CACHE = None          # Arbeitsordner der App (filesDir/viewer)
NATIVE_DIR = None     # nativeLibraryDir (enthält libdw2conv.so)
_lock = threading.RLock()
CONVERTER_VERSION = 'v7'   # erhöhen, wenn sich die Konvertierung ändert (alter Cache wird ignoriert)


class State:
    def __init__(self):
        self.image_path = None
        self.session = None
        self.entries = []
        self.catalog = []
        self.index_key = None
        self.names = None
        self.attacks = None
        self.types = None
        self.props = {}
        self.roster = None
        self.source_names = {}


S = State()


# --------------------------------------------------------------------------- Setup
def configure(files_dir, native_dir, data_dir=None):
    global CACHE, NATIVE_DIR
    if data_dir:
        os.environ['DW2_DATA_DIR'] = str(data_dir)
    CACHE = Path(files_dir) / 'viewer'
    CACHE.mkdir(parents=True, exist_ok=True)
    NATIVE_DIR = native_dir
    return {'cache': str(CACHE)}


def _need_session():
    if S.session is None:
        raise ValueError('Bitte zuerst ein Spiel-Image öffnen.')
    return S.session


def _find(identifier):
    for c in S.catalog:
        if c.id == identifier:
            return c
    raise ValueError(f'Digimon #{identifier} nicht im Image gefunden.')


def _key(c):
    return f'{c.id:03d}{c.code}'


# --------------------------------------------------------------------------- Image
def open_image(path):
    from dw2studio.core.fast_loading import scan_image
    from dw2studio.core.edit_session import EditSession
    entries, catalog, info = scan_image(path, CACHE)
    S.image_path = Path(info['path'])
    S.session = EditSession(S.image_path, info['sector_size'])
    S.entries, S.catalog = entries, catalog
    S.index_key = info['cache_key']
    S.names = S.attacks = S.types = None
    S.props = {}
    S.roster = None
    S.source_names = {c.id: c.name for c in catalog}
    return {'name': S.image_path.name, 'count': len(catalog), 'cached': info['cached'],
            'seconds': round(info['seconds'], 2), 'sector_size': info['sector_size'],
            'name_error': info.get('name_error', '')}


def catalog_list():
    _need_session()
    return [{'id': c.id, 'code': c.code, 'name': c.name} for c in S.catalog]


# --------------------------------------------------------------------------- Repositories
def _names():
    from dw2studio.core.digimon_names import NameRepository
    s = _need_session()
    if S.names is None or S.names.session is not s:
        S.names = NameRepository(s, S.entries)
    return S.names


def _attacks():
    from dw2studio.core.battle_skills import AttackRepository
    s = _need_session()
    if S.attacks is None or S.attacks.session is not s:
        S.attacks = AttackRepository(s, S.entries)
    return S.attacks


def _types():
    from dw2studio.core.digimon_types import TypeRepository
    s = _need_session()
    if S.types is None or S.types.session is not s:
        S.types = TypeRepository(s, S.entries)
    return S.types


def _props(filename):
    from dw2studio.core.digimon_properties import PropertyRepository
    s = _need_session()
    repo = S.props.get(filename)
    if repo is None or repo.session is not s:
        repo = S.props[filename] = PropertyRepository(s, S.entries, filename)
    return repo


def _refresh_names():
    try:
        names = _names().names()
    except (ValueError, OSError):
        return
    for c in S.catalog:
        c.name = names.get(c.id, S.source_names.get(c.id, c.name))


# --------------------------------------------------------------------------- Name / Typ / Specialty
def name_info(identifier):
    from dw2studio.core.digimon_names import MAX_NAME_LENGTH
    repo = _names()
    entry, table = repo.lookup(identifier)
    return {'current': table.record(identifier).text, 'original': repo.original_name(identifier),
            'max_length': MAX_NAME_LENGTH, 'file': Path(entry.path).name}


def rename(identifier, text):
    s = _need_session()
    before = s.edits.copy()
    try:
        changed = _names().rename(identifier, text)
        _refresh_names()
    except Exception:
        s.edits = before
        raise
    return {'changed': changed, 'name': _find(identifier).name}


def type_info(identifier):
    from dw2studio.core.digimon_types import TYPES, type_name
    repo = _types()
    code = repo.table().type_of(identifier)
    original = repo.original_type(identifier)
    return {'code': code, 'name': type_name(code), 'original': original,
            'original_name': type_name(original),
            'choices': [{'code': k, 'name': v} for k, v in TYPES.items()]}


def set_type(identifier, code):
    return {'changed': _types().change(identifier, int(code))}


def specialty_info(identifier):
    from dw2studio.core.digimon_properties import SPECIALTIES, specialty_name
    repo = _props('DIGIMNDT.BIN')
    code = repo.specialty(identifier)
    original = repo.specialty(identifier, original=True)
    return {'code': code, 'name': specialty_name(code), 'original': original,
            'original_name': specialty_name(original),
            'choices': [{'code': k, 'name': v} for k, v in SPECIALTIES.items()]}


def set_specialty(identifier, code):
    return {'changed': _props('DIGIMNDT.BIN').change_specialty(identifier, int(code))}


# --------------------------------------------------------------------------- Gegnerwerte
def enemy_values(identifier):
    from dw2studio.core.digimon_properties import ENEMY_FIELDS
    repo = _props('ENEMYSET.BIN')
    rows = [{'key': list(row.key), 'level': row.level,
             'values': repo.values(row), 'original': repo.values(row, original=True)}
            for row in repo.enemies().for_digimon(identifier)]
    fields = {k: {'min': v[2], 'max': v[3]} for k, v in ENEMY_FIELDS.items()}
    return {'rows': rows, 'fields': fields}


def set_enemy_values(identifier, changes):
    parsed = {tuple(int(x) for x in k.split(',')): {n: int(v) for n, v in fields.items()}
              for k, fields in changes.items()}
    return {'changed': _props('ENEMYSET.BIN').apply_enemies(identifier, parsed)}


# --------------------------------------------------------------------------- Attacken
def attack_info(identifier):
    from dw2studio.core.battle_skills import power_label, BaseTable
    repo = _attacks()
    skills, base, enemies = repo.tables()
    try:
        original_base = BaseTable(repo.session.original(repo.entries['DIGIMNDT.BIN']))
    except (ValueError, KeyError, OSError):
        original_base = None
    catalogue = [{'id': r.identifier, 'name': r.name, 'mp': r.mp, 'power': r.power,
                  'label': f'{r.identifier:02X} · {r.name} · {r.mp} MP · {power_label(r.power)}'}
                 for r in skills.records.values()]
    default = base.records[identifier][1] if identifier in base.records else None
    original = original_base.records[identifier][1] if original_base and identifier in original_base.records else None
    encounters = [{'key': list(r.key), 'level': r.level, 'skills': list(r.skills)}
                  for r in enemies.for_digimon(identifier)]
    return {'skills': catalogue, 'default': default, 'original_default': original,
            'encounters': encounters}


def apply_attacks(identifier, default, encounters, techniques):
    from dw2studio.core.battle_skills import AttackPlan
    repo = _attacks()
    _, _, enemies = repo.tables()
    enc = {}
    for k, skills in (encounters or {}).items():
        key = tuple(int(x) for x in k.split(','))
        if key not in enemies.records:
            raise ValueError('Gegnerbegegnung wurde nicht gefunden.')
        enc[key] = (tuple(int(s) for s in skills), enemies.records[key].rules)
    tech = {int(k): {n: int(v) for n, v in f.items()} for k, f in (techniques or {}).items()}
    plan = AttackPlan(identifier, int(default) if default is not None else None, enc, tech)
    return {'files': repo.apply(plan)}


# --------------------------------------------------------------------------- Memorycard / Spielstand
def roster_open(path):
    from dw2studio.core.roster_save import RosterSave
    S.roster = RosterSave(path)
    return {'name': Path(path).name}


def _need_roster():
    if S.roster is None:
        raise ValueError('Bitte zuerst eine Memorycard oder einen Spielstand öffnen.')
    return S.roster


def roster_records(identifier):
    rows = []
    for r in _need_roster().records(identifier):
        r = dict(r)
        r['key'] = list(r['key'])
        rows.append(r)
    return rows


def roster_change(key, fields):
    from dw2studio.core.roster_save import next_level_exp
    doc = _need_roster()
    k = tuple(key)
    doc.change(k, {n: int(v) for n, v in fields.items()})
    record = doc.record(k)
    return {'record': {**record, 'key': list(record['key'])},
            'next_exp': next_level_exp(record['level'], record['max_level'], record['exp'])}


def roster_restore(key):
    _need_roster().restore(tuple(key))
    return True


def roster_export(name):
    doc = _need_roster()
    folder = _exports()
    stem, suffix = os.path.splitext(doc.path.name)
    target = folder / _unique_name(folder, (name or stem + '_bearbeitet') + suffix)
    out = doc.export(target)
    return {'path': str(out), 'name': out.name}


# --------------------------------------------------------------------------- Vormerkungen / Speichern
def _exports():
    folder = CACHE / 'exports'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _unique_name(folder, name):
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', name) or 'export'
    candidate, n = name, 1
    stem, suffix = os.path.splitext(name)
    while (Path(folder) / candidate).exists():
        n += 1
        candidate = f'{stem}_{n}{suffix}'
    return candidate


def pending():
    from dw2studio.core.digimon_names import FILE_INDEX, NameTable, basename
    from dw2studio.core.battle_skills import FILE_INDEX as ATTACK_FILES
    out = []
    if S.session is not None:
        for e in S.session.edits.values():
            label, detail = e.label, e.label
            if basename(e.path) in FILE_INDEX:
                try:
                    old, new = NameTable(e.original), NameTable(e.replacement)
                    changes = [f'#{i:03}: {r.text} → {new.record(i).text}'
                               for i, r in old.records.items() if new.record(i).text != r.text]
                    if changes:
                        label, detail = f'{len(changes)} Name(n) vorgemerkt', '\n'.join(changes)
                except ValueError:
                    pass
            if e.relocate:
                label += ' · neuer Dateibereich'
            out.append({'kind': 'file', 'file': Path(e.path).name, 'label': label, 'detail': detail,
                        'path': e.path, 'lba': e.lba, 'shared': basename(e.path) in ATTACK_FILES})
    if S.roster is not None and S.roster.dirty:
        out.append({'kind': 'roster', 'file': S.roster.path.name, 'label': 'Spielstand/Memorycard',
                    'detail': 'Persönliche Werte, EXP und Parents', 'shared': False})
    return out


def discard(kind, path=None, lba=None):
    if kind == 'roster':
        if S.roster is not None:
            S.roster.raw = bytearray(S.roster.original)
        return True
    _need_session().remove((path, int(lba)))
    _refresh_names()
    return True


def save_image(name):
    """Schreibt ein neues, geprüftes Image in den App-Ordner; Kotlin kopiert es zum gewählten Ziel."""
    s = _need_session()
    if not s.edits:
        raise ValueError('Es gibt noch keine vorgemerkten Spieländerungen.')
    folder = _exports()
    suffix = '.bin' if s.sector_size == 2352 else '.iso'
    base = re.sub(r'\.(bin|iso|img)$', '', name or '', flags=re.I) or 'dw2_bearbeitet'
    free = shutil.disk_usage(folder).free
    if free < S.image_path.stat().st_size + (32 << 20):
        raise ValueError(f'Zu wenig Speicherplatz: {S.image_path.stat().st_size >> 20} MB nötig, {free >> 20} MB frei.')
    target = folder / _unique_name(folder, base + suffix)
    output, _ = s.save(target, overwrite=False)
    return {'path': str(output), 'name': output.name, 'size': output.stat().st_size}


def save_project(name):
    s = _need_session()
    folder = _exports()
    target = folder / _unique_name(folder, name if name.endswith('.dw2mod') else name + '.dw2mod')
    s.export_project(target)
    return {'path': str(target), 'name': target.name}


def load_project(path):
    import zipfile
    from dw2studio.core.digimon_names import basename
    from dw2studio.core.battle_skills import FILE_INDEX as ATTACK_FILES, PARSERS
    s = _need_session()
    before = s.edits.copy()
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.getinfo('project.json').file_size > 4 * 1024 * 1024:
                raise ValueError('Projektmanifest zu groß.')
            manifest = json.loads(archive.read('project.json'))
        tables = {basename(i.get('path', '')) for i in manifest.get('files', [])} & ATTACK_FILES.keys()
        for filename in tables:
            _props(filename)
        try:
            _names()
        except (ValueError, OSError):
            pass
        s.import_project(path, S.entries)
        for filename in tables:
            PARSERS[filename](s.current(_props(filename).entry))
        _refresh_names()
    except Exception:
        s.edits = before
        raise
    return {'edits': len(s.edits)}


def delete_export(path):
    p = Path(path).resolve()
    if _exports().resolve() in p.parents and p.is_file():
        p.unlink()
    return True


# --------------------------------------------------------------------------- 3D-Modell
def _convert(source, output):
    from dw2studio.core.native_gltf import convert_folder
    convert_folder(source, output)


def _basename(entry):
    return Path(entry.path.replace('\\', '/')).name.upper()


def _model_family(c, original=False, repo=None):
    """M-Datei plus die Animationsdateien, die das Spiel für diese Digimon-ID lädt.

    Zuordnung wie Digi_GetAnimFile (MODELDT animFiles[11] → A–K). Jede so gefundene
    Datei muss zur Knochenzahl des Modells passen; sonst bzw. ohne Tabelle gilt die
    bisherige Dateinamen-Zuordnung (gleicher Stamm). Rückgabe: (files, aliases, info).
    """
    from dw2studio.core.auto_models import selected_model_entries, model_entries
    from dw2studio.core.native_anim import game_anim_slots, parse_anim_file, SLOTS
    s = _need_session()
    stem = f'{c.id:03d}{c.code}'.upper()
    own = {}
    for entry in selected_model_entries(S.entries, c):
        own.setdefault(_basename(entry)[0], entry)
    model = own.get('M')
    info = {'source': 'filename', 'slots': {}, 'notes': []}
    if model is None:
        return list(own.values()), {}, info
    read = s.original if original else s.current
    try:
        bones = struct.unpack_from('<I', read(model), 8)[0]
    except (struct.error, OSError, ValueError):
        return list(own.values()), {}, info
    slots, table = game_anim_slots(s, S.entries, c.id, f'M{stem}.BIN', repo)
    info['table'] = table
    by_name = {}
    for entry in model_entries(S.entries):
        by_name.setdefault(_basename(entry), entry)
    files, aliases = [model], {}
    for slot in SLOTS:
        chosen, origin = None, None
        name = slots.get(slot)
        if name:
            entry = by_name.get(name)
            if entry is None:
                info['notes'].append(f'{slot}: {name} fehlt im Image')
            else:
                try:
                    parse_anim_file(read(entry), bones, strict=False)
                    chosen, origin = entry, 'MODELDT'
                except (ValueError, OSError) as exc:
                    info['notes'].append(f'{slot}: {name} passt nicht ({exc})')
        if chosen is None and slot in own:
            chosen = own[slot]
            origin = 'filename' if not slots else 'fallback' if slot in slots else 'unassigned'
            if origin == 'unassigned':
                info['notes'].append(f'{slot}: {_basename(chosen)} ist laut Spieltabelle keinem Slot zugeordnet (trotzdem angezeigt)')
        if chosen is None:
            continue
        files.append(chosen)
        info['slots'][slot] = {'file': _basename(chosen), 'origin': origin, 'shared': _basename(chosen)[1:] != f'{stem}.BIN'}
        target = f'{slot}{stem}.BIN'
        if _basename(chosen) != target:
            aliases[(chosen.path, chosen.lba)] = target
    if slots:
        info['source'] = 'MODELDT'
    return files, aliases, info


def prepare_model(identifier, original=False):
    from dw2studio.core.fast_loading import ModelRequest, build_model
    from dw2studio.core.auto_models import model_animation_names
    s = _need_session()
    c = _find(identifier)
    key = _key(c)
    files, aliases, family = _model_family(c, original)
    if not files:
        raise ValueError('Für dieses Digimon wurden keine Modell-Dateien gefunden.')
    overrides = {}
    for e in files:
        edit = s.edits.get((e.path, e.lba))
        if edit and not original:
            overrides[Path(e.path.replace('\\', '/')).name] = edit.replacement
    edited = any((e.path, e.lba) in s.edits for e in files)
    folder = CACHE / 'models' / CONVERTER_VERSION / S.index_key / key
    if overrides:
        digest = hashlib.sha256()
        for name, data in sorted(overrides.items()):
            encoded = name.encode('utf-8')
            digest.update(len(encoded).to_bytes(4, 'little'))
            digest.update(encoded)
            digest.update(len(data).to_bytes(8, 'little'))
            digest.update(data)
        folder = folder / 'edits' / digest.hexdigest()
    started = time.perf_counter()
    request = ModelRequest(f'{S.index_key}/{key}', str(S.image_path), files, folder, c, '', overrides, aliases)
    model = build_model(request, _convert)
    try:
        animations = model_animation_names(model)
    except Exception:
        animations = []
    return {'url': model.relative_to(CACHE).as_posix(), 'name': c.name, 'id': c.id, 'code': c.code,
            'animations': animations, 'anim_source': family, 'edited': edited, 'original': bool(original),
            'seconds': round(time.perf_counter() - started, 2)}


# --------------------------------------------------------------------------- Animations-Prüfung
def _audit_one(c, repo=None):
    from dw2studio.core.native_anim import parse_anim_file, parse_tex_anim, primitive_modes, matrix_flags
    from dw2studio.core.native_model import NativeModel
    s = _need_session()
    files, aliases, family = _model_family(c, repo=repo)
    row = {'id': c.id, 'code': c.code, 'name': c.name, 'anim_source': family['source'], 'notes': list(family['notes'])}
    model = next((e for e in files if _basename(e).startswith('M')), None)
    if model is None:
        row['error'] = 'keine M-Datei'
        return row
    native = s.current(model)
    try:
        m = NativeModel(native)
    except ValueError as exc:
        row['error'] = f'Modell: {exc}'
        return row
    row['bones'] = m.bone_count
    try:
        tex = parse_tex_anim(native)
        row.update(eyes=len(tex.eyes), tex_cycles=len(tex.cycles), tex_extended=len(tex.extended),
                   tex_palette=tex.touches_palette(), tex_warnings=tex.warnings)
    except (ValueError, struct.error) as exc:
        row.update(eyes=0, tex_cycles=0, tex_extended=0, tex_palette=False, tex_warnings=[str(exc)])
    abr = {}
    semi = 0
    for modes in primitive_modes(native):
        for stp, _clut, mode in modes:
            if stp:
                semi += 1
                abr[mode] = abr.get(mode, 0) + 1
    row['semi_faces'] = semi
    row['abr'] = {str(k): v for k, v in sorted(abr.items())}
    anims, flags = {}, {'keys': 0, 'scaled_keys': 0, 'sheared_keys': 0, 'mirrored_keys': 0}
    clips = loops = holds = gaps = 0
    for e in files:
        slot = (aliases.get((e.path, e.lba)) or _basename(e))[0]
        if slot == 'M':
            continue
        data = s.current(e)
        try:
            a = parse_anim_file(data, m.bone_count, strict=False)
        except ValueError as exc:
            anims[slot] = {'file': _basename(e), 'error': str(exc)}
            continue
        f = matrix_flags(data, a)
        for k in flags:
            flags[k] += f[k]
        lp = [c2.loop_row for c2 in a.clips if c2.terminator == 0xFE]
        anims[slot] = {'file': _basename(e), 'shared': family['slots'].get(slot, {}).get('shared', False),
                       'clips': len(a.clips), 'gaps': a.gaps, 'loop_rows': lp,
                       'holds': sum(c2.terminator == 0xFF for c2 in a.clips),
                       'rows': [len(c2.rows) for c2 in a.clips], 'warnings': a.warnings}
        clips += len(a.clips)
        loops += len(lp)
        holds += anims[slot]['holds']
        gaps += len(a.gaps)
    row.update(anims=anims, clips=clips, loops=loops, holds=holds, table_gaps=gaps, **flags)
    # Was dem Viewer bis v4.1 fehlte (zur Übersicht):
    need = []
    if row['eyes']:
        need.append('Augen (Spielrhythmus)')
    if row['tex_cycles'] or row['tex_extended']:
        need.append('Texturanimation')
    if row['tex_palette']:
        need.append('Palettenkopie')
    if any(k != '0' for k in row['abr']):
        need.append('Mischmodus ' + '/'.join(k for k in row['abr'] if k != '0'))
    if gaps:
        need.append('Clips hinter Tabellenlücke')
    if any(v.get('shared') for v in anims.values()):
        need.append('Geteilte Animationen (MODELDT)')
    if any(lr for v in anims.values() for lr in v.get('loop_rows', [])):
        need.append('Schleife ab Zwischenbild')
    if holds:
        need.append('Einmal-Animationen')
    if flags['sheared_keys']:
        need.append('Scherung/Skalierung')
    row['viewer_v41_missing'] = need
    return row


def animation_audit():
    """Prüft alle Digimon-Modelle des Images; schreibt JSON und CSV nach exports."""
    _need_session()
    started = time.perf_counter()
    rows = []
    try:
        from dw2studio.core.digimon_names import NameRepository
        repo = NameRepository(S.session, S.entries)
    except (ValueError, OSError):
        repo = None
    for c in S.catalog:
        try:
            rows.append(_audit_one(c, repo))
        except Exception as exc:  # ein Modell darf die Prüfung nicht abbrechen
            traceback.print_exc()
            rows.append({'id': c.id, 'code': c.code, 'name': c.name, 'error': f'{exc.__class__.__name__}: {exc}'})
    summary = {'models': len(rows), 'errors': sum('error' in r for r in rows),
               'with_eyes': sum(bool(r.get('eyes')) for r in rows),
               'with_tex_cycles': sum(bool(r.get('tex_cycles')) for r in rows),
               'with_tex_extended': sum(bool(r.get('tex_extended')) for r in rows),
               'with_palette_copy': sum(bool(r.get('tex_palette')) for r in rows),
               'with_semi_faces': sum(bool(r.get('semi_faces')) for r in rows),
               'with_abr_non_average': sum(any(k != '0' for k in r.get('abr', {})) for r in rows),
               'with_shared_anims': sum(any(v.get('shared') for v in r.get('anims', {}).values()) for r in rows),
               'without_anims': sum(not r.get('clips') for r in rows if 'error' not in r),
               'with_table_gaps': sum(bool(r.get('table_gaps')) for r in rows),
               'with_loop_offset': sum(any(lr for v in r.get('anims', {}).values() for lr in v.get('loop_rows', [])) for r in rows),
               'with_sheared_keys': sum(bool(r.get('sheared_keys')) for r in rows),
               'anim_source_table': sum(r.get('anim_source') == 'MODELDT' for r in rows),
               'seconds': 0}
    summary['seconds'] = round(time.perf_counter() - started, 1)
    folder = _exports()
    stamp = time.strftime('%Y%m%d_%H%M%S')
    path = folder / f'animationspruefung_{stamp}.json'
    path.write_text(json.dumps({'summary': summary, 'models': rows}, ensure_ascii=False, indent=1), encoding='utf-8')
    import csv
    csv_path = folder / f'animationspruefung_{stamp}.csv'
    cols = ['id', 'code', 'name', 'bones', 'anim_source', 'clips', 'loops', 'holds', 'table_gaps', 'eyes', 'tex_cycles',
            'tex_extended', 'tex_palette', 'semi_faces', 'abr', 'keys', 'sheared_keys', 'scaled_keys', 'viewer_v41_missing', 'error', 'notes']
    with csv_path.open('w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh, delimiter=';')
        w.writerow(cols)
        for r in rows:
            w.writerow([json.dumps(r.get(k), ensure_ascii=False) if isinstance(r.get(k), (dict, list)) else r.get(k, '') for k in cols])
    top = [{'id': r['id'], 'name': r['name'], 'missing': r.get('viewer_v41_missing', [])} for r in rows
           if any(x in ('Texturanimation', 'Palettenkopie') or x.startswith('Mischmodus') for x in r.get('viewer_v41_missing', []))]
    return {'summary': summary, 'path': str(path), 'name': path.name, 'csv': str(csv_path), 'csv_name': csv_path.name,
            'highlight': top[:400]}


def native_files_export(identifier):
    """Rohdateien (M + zugeordnete A–K) eines Digimon als ZIP – zur technischen Analyse."""
    import zipfile
    s = _need_session()
    c = _find(identifier)
    files, aliases, family = _model_family(c)
    folder = _exports()
    target = folder / _unique_name(folder, f'{c.id:03d}{c.code}_native.zip')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for e in files:
            z.writestr(_basename(e), s.current(e))
        z.writestr('zuordnung.json', json.dumps({'id': c.id, 'code': c.code, 'name': c.name, 'family': family,
                                                  'aliases': {_basename(e): aliases.get((e.path, e.lba)) for e in files}},
                                                 ensure_ascii=False, indent=1, default=str))
    return {'path': str(target), 'name': target.name}


# --------------------------------------------------------------------------- Verlauf (Rückgängig / Wiederherstellen)
UNDO, REDO = [], []
MUTATING = {'rename', 'set_type', 'set_specialty', 'set_enemy_values', 'apply_attacks', 'roster_change',
            'roster_restore', 'discard', 'load_project', 'png_apply', 'transfer_apply', 'bin_apply',
            'rig_apply', 'restore_original'}


def _snapshot():
    return (dict(S.session.edits) if S.session else {},
            bytes(S.roster.raw) if S.roster is not None else None)


def _restore(snap):
    edits, roster = snap
    if S.session is not None:
        S.session.edits = dict(edits)
    if S.roster is not None and roster is not None:
        S.roster.raw = bytearray(roster)
    _refresh_names()


def history():
    return {'undo': len(UNDO), 'redo': len(REDO)}


def undo():
    if not UNDO:
        raise ValueError('Nichts zum Rückgängigmachen.')
    REDO.append(_snapshot())
    _restore(UNDO.pop())
    return history()


def redo():
    if not REDO:
        raise ValueError('Nichts zum Wiederherstellen.')
    UNDO.append(_snapshot())
    _restore(REDO.pop())
    return history()


# --------------------------------------------------------------------------- Image überschreiben
def adopt_image(new_path, old_path):
    """Nach erfolgreichem Überschreiben: neues Image als Arbeitsstand übernehmen, altes als Sicherung behalten."""
    new_path, old_path = Path(new_path), Path(old_path)
    backup = old_path.with_name('Sicherung_' + old_path.name)
    backup.unlink(missing_ok=True)
    if old_path.exists():
        old_path.replace(backup)
    new_path.replace(old_path)
    info = open_image(str(old_path))
    UNDO.clear(); REDO.clear()
    info['backup'] = str(backup) if backup.exists() else None
    return info


def clear_cache():
    for sub in ('models', 'exports', 'indexes', 'work'):
        shutil.rmtree(CACHE / sub, ignore_errors=True)
    return True


def translate(texts, language):
    from dw2studio.i18n import translate as tr
    return [tr(t, language) for t in texts]


# --------------------------------------------------------------------------- Einstieg
_METHODS = {
    'configure': configure, 'open_image': open_image, 'catalog': catalog_list,
    'name_info': name_info, 'rename': rename, 'type_info': type_info, 'set_type': set_type,
    'specialty_info': specialty_info, 'set_specialty': set_specialty,
    'enemy_values': enemy_values, 'set_enemy_values': set_enemy_values,
    'attack_info': attack_info, 'apply_attacks': apply_attacks,
    'roster_open': roster_open, 'roster_records': roster_records, 'roster_change': roster_change,
    'roster_restore': roster_restore, 'roster_export': roster_export,
    'pending': pending, 'discard': discard, 'save_image': save_image,
    'save_project': save_project, 'load_project': load_project, 'delete_export': delete_export,
    'prepare_model': prepare_model, 'clear_cache': clear_cache, 'translate': translate,
    'history': history, 'undo': undo, 'redo': redo, 'adopt_image': adopt_image,
    'animation_audit': animation_audit, 'native_files_export': native_files_export,
}


def _register_edit():
    import android_edit as e
    for name in ('png_export', 'png_preview', 'png_apply', 'cancel', 'model_export', 'inspect_3d',
                 'transfer_plan', 'transfer_apply', 'bin_apply', 'rig_prepare', 'rig_apply', 'restore_original'):
        _METHODS[name] = getattr(e, name)


_register_edit()


def call(method, args_json='[]'):
    try:
        if method not in _METHODS:
            raise ValueError(f'Unbekannte Methode: {method}')
        args = json.loads(args_json) if args_json else []
        with _lock:
            before = _snapshot() if method in MUTATING else None
            data = _METHODS[method](*args)
            if before is not None and before != _snapshot():
                UNDO.append(before)
                del UNDO[:-50]
                REDO.clear()
            if method == 'open_image':
                UNDO.clear(); REDO.clear()
        return json.dumps({'ok': True, 'data': data}, ensure_ascii=False)
    except Exception as exc:  # Fehlertext geht an die Oberfläche; Details ins Log
        traceback.print_exc()
        return json.dumps({'ok': False, 'error': str(exc) or exc.__class__.__name__}, ensure_ascii=False)
