"""Qt-freie Schnittstelle zwischen der Android-Oberfläche (WebView) und dem DW2-Kern.

Kotlin ruft ausschließlich `call(methode, json_argumente)` auf und erhält immer
einen JSON-Text {"ok": true, "data": ...} oder {"ok": false, "error": "..."}.
Alle Schreibvorgänge nutzen dieselben Kernmodule wie die Windows-Version
(EditSession, NameRepository, TypeRepository, PropertyRepository, RosterSave ...).
"""
from dw2studio.version import VERSION
import sys
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
CONVERTER_VERSION = 'v10'  # preserve every MODELDT slot when a file is reused


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
        self.digivolve_levels = {}   # Mods/digivolve_levels.json (PC port 1.0)
        self.dna_modified = False
        self.dna_overrides = {}
        self.battle_camera = {}      # Mods/battle_camera.json (PC port 1.0)
        self.dw3_imports = {}        # target id -> how it was imported (source model, size, HD), for 'Größe ändern'


S = State()
DW3 = None


def open_dw3(path):
    global DW3
    from dw2studio.dw3 import Dw3Disc
    candidate = Dw3Disc(path, CACHE)
    DW3 = candidate
    return {'name': candidate.path.name, 'models': candidate.catalog()}


def prepare_dw3(identifier):
    if DW3 is None:
        raise ValueError('Bitte zuerst ein DW3-Image öffnen.')
    return DW3.prepare(identifier)


def dw3_native_plan(source_id, target_id):
    from dw2studio.dw3_import import prepare
    return prepare(__import__(__name__),source_id,target_id)['info']


def dw3_native_apply(source_id, target_id, assignments, scale_factor=1., hd_scale=0, camera=None, size_mode='dw2',
                     allow_reduce=False):
    from dw2studio.dw3_import import apply
    return apply(__import__(__name__),source_id,target_id,assignments,scale_factor,hd_scale,camera,size_mode or 'dw2',
                 bool(allow_reduce))


def export_hd_pack(identifier, png, port_dir):
    from dw2studio.core.native_rom_bridge import native_model_entry
    from dw2studio.hd_pack import export
    entry=native_model_entry(S.entries,_find(identifier))
    return export(_need_session().current(entry),png,port_dir)


def export_dw3(identifier):
    import zipfile
    info = prepare_dw3(identifier)
    folder = Path(info['path']).parent
    target = _exports() / _unique_name(_exports(), info['name'] + '.zip')
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.iterdir()):
            if path.is_file():
                archive.write(path, path.name)
    return {'path': str(target), 'name': target.name}


def export_port_mod(port_dir, pak_path=None):
    from dw2studio.pak import PakFile
    from dw2studio.port_mod import export
    s = _need_session()
    pak = s.pak if hasattr(s, 'pak') else PakFile(pak_path)
    return export(s, pak, port_dir, mod_name='DW2 Mod Studio ' + VERSION)


def port_mod_status(port_dir):
    from dw2studio.port_mod_manage import status
    return status(port_dir)


def port_mod_disable(port_dir):
    from dw2studio.port_mod_manage import disable
    return disable(port_dir)


def port_mod_enable(port_dir, set_name=None):
    from dw2studio.port_mod_manage import enable
    return enable(port_dir, set_name)


# --------------------------------------------------------------------------- Setup
def configure(files_dir, native_dir, data_dir=None):
    global CACHE, NATIVE_DIR
    if data_dir:
        os.environ['DW2_DATA_DIR'] = str(data_dir)
    CACHE = Path(files_dir) / 'viewer'
    CACHE.mkdir(parents=True, exist_ok=True)
    # Android: filesDir heißt /data/user/0/<app>/files, ist aber ein Verweis auf /data/data/<app>/files.
    # Mit dem aufgelösten Pfad passen alle relative_to-Vergleiche (6.0: DW3 „Ansehen“).
    CACHE = CACHE.resolve()
    NATIVE_DIR = native_dir
    if native_dir and (Path(native_dir) / 'libdw3conv.so').is_file():
        # Android: DW3-Konverter als ausführbares Programm im nativeLibraryDir (tools/build_dw3conv.sh android)
        os.environ['DW3_CONVERTER'] = str(Path(native_dir) / 'libdw3conv.so')
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
    if Path(path).suffix.lower() == '.pak':
        from dw2studio.pak_workspace import open_workspace
        session, entries, catalog, key = open_workspace(path)
        S.image_path, S.session = session.source, session
        S.entries, S.catalog, S.index_key = entries, catalog, key
        S.names = S.attacks = S.types = None
        S.digivolve_levels = {}
        S.dna_modified = False
        S.dna_overrides = {}
        S.battle_camera = {}
        S.dw3_imports = {}
        S.props, S.roster = {}, None
        S.source_names = {c.id: c.name for c in catalog}
        return {'name': S.image_path.name, 'count': len(catalog), 'cached': False,
                'seconds': 0, 'sector_size': 2048, 'source_kind': 'pak', 'name_error': ''}
    from dw2studio.core.fast_loading import scan_image
    from dw2studio.core.edit_session import EditSession
    entries, catalog, info = scan_image(path, CACHE)
    S.open_path = Path(path)
    S.image_path = Path(info['path'])
    S.session = EditSession(S.image_path, info['sector_size'])
    S.entries, S.catalog = entries, catalog
    S.index_key = info['cache_key']
    S.names = S.attacks = S.types = None
    S.props = {}
    S.roster = None
    S.dna_overrides = {}
    S.dna_modified = False
    S.source_names = {c.id: c.name for c in catalog}
    return {'name': S.image_path.name, 'count': len(catalog), 'cached': info['cached'],
            'seconds': round(info['seconds'], 2), 'sector_size': info['sector_size'],
            'name_error': info.get('name_error', ''), 'source_kind': 'image'}


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


def evolution_info(identifier):
    from dw2studio.core.evolution import EvolutionRepository
    return EvolutionRepository(_need_session(), S.entries).info(identifier)


def set_evolution(identifier, rows, rank=None, dna_group=None):
    from dw2studio.core.evolution import EvolutionRepository
    return {'changed': EvolutionRepository(_need_session(), S.entries).change(identifier, rows, rank, dna_group)}


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
    if S.dna_modified or S.dna_overrides:
        out.append({'kind': 'dna', 'file': 'dna_overrides.json', 'label': 'DNA-Digitation',
                    'detail': f'{len(S.dna_overrides)} Regeln · PC-Port-Mod', 'shared': False})
    if S.roster is not None and S.roster.dirty:
        out.append({'kind': 'roster', 'file': S.roster.path.name, 'label': 'Spielstand/Memorycard',
                    'detail': 'Persönliche Werte, EXP und Parents', 'shared': False})
    return out


def discard(kind, path=None, lba=None):
    if kind == 'dna':
        S.dna_overrides = {}
        S.dna_modified = False
        return True
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
    cue = _write_cue(output)
    return {'path': str(output), 'name': output.name, 'size': output.stat().st_size,
            'cue': str(cue) if cue else None}


def cue_for(bin_name, template=None):
    """CUE text for a single-track raw image: the source CUE with the new file name, or the
    standard PS1 data track (MODE2/2352) when there is no source CUE (IMG/CCD, plain BIN)."""
    pattern = re.compile(r'(?im)^(\s*FILE\s+)(?:"[^"]+"|\S+)(\s+BINARY\s*)$')
    if template and len(pattern.findall(template)) == 1:
        return pattern.sub(lambda m: f'{m.group(1)}"{bin_name}"{m.group(2)}', template, count=1)
    return f'FILE "{bin_name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'


def _write_cue(output):
    """Write <output>.cue next to a newly exported 2352-byte image so emulators can open it."""
    output = Path(output)
    if _need_session().sector_size != 2352 or output.suffix.lower() != '.bin':
        return None
    template = None
    for cand in (getattr(S, 'open_path', None), S.image_path.with_suffix('.cue')):
        if cand and Path(cand).suffix.lower() == '.cue' and Path(cand).is_file():
            template = Path(cand).read_text(encoding='utf-8-sig', errors='replace')
            break
    out = output.with_suffix('.cue')
    if out.exists():
        return None
    out.write_text(cue_for(output.name, template), encoding='utf-8')
    return out


def save_project(name):
    s = _need_session()
    folder = _exports()
    target = folder / _unique_name(folder, name if name.endswith('.dw2mod') else name + '.dw2mod')
    s.export_project(target)
    levels = getattr(S, 'digivolve_levels', {}) or {}
    cams = getattr(S, 'battle_camera', {}) or {}
    dna = _dna_model().to_dict()['rules']
    if levels or cams or dna or S.dna_modified or getattr(S, 'dw3_imports', None):
        import zipfile
        from dw2studio.digivolve_levels import dumps, FILENAME
        from dw2studio.core import battle_shots
        with zipfile.ZipFile(target, 'a') as archive:
            if dna or S.dna_modified:
                from dw2studio.core.dna_overrides import DnaOverrides, FILENAME as DNA_FILE
                archive.writestr(DNA_FILE, DnaOverrides(dna).to_json())
            if levels:
                archive.writestr(FILENAME, dumps(levels))
            if cams:
                archive.writestr('battle_camera.json', battle_shots.dumps(cams))
            if getattr(S, 'dw3_imports', None):
                archive.writestr('dw3_imports.json', json.dumps({str(k): v for k, v in S.dw3_imports.items()}))
    return {'path': str(target), 'name': target.name}


def load_project(path):
    import zipfile
    from dw2studio.core.digimon_names import basename
    from dw2studio.core.battle_skills import FILE_INDEX as ATTACK_FILES, PARSERS
    s = _need_session()
    before = s.edits.copy()
    before_dna = dict(S.dna_overrides)
    before_dna_modified = S.dna_modified
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
        from dw2studio.digivolve_levels import loads, FILENAME
        with zipfile.ZipFile(path) as archive:
            from dw2studio.core.dna_overrides import DnaOverrides, FILENAME as DNA_FILE
            S.dna_modified = DNA_FILE in archive.namelist()
            S.dna_overrides = DnaOverrides.from_json(archive.read(DNA_FILE).decode('utf-8'), _dna_choices()).rules if DNA_FILE in archive.namelist() else {}
            if FILENAME in archive.namelist():
                S.digivolve_levels = loads(archive.read(FILENAME).decode('utf-8'))
            if 'dw3_imports.json' in archive.namelist():
                S.dw3_imports = {int(k): v for k, v in json.loads(archive.read('dw3_imports.json')).items()}
            if 'battle_camera.json' in archive.namelist():
                from dw2studio.core import battle_shots
                S.battle_camera = battle_shots.loads(archive.read('battle_camera.json').decode('utf-8'))
        for filename in tables:
            PARSERS[filename](s.current(_props(filename).entry))
        _refresh_names()
    except Exception:
        s.edits = before
        S.dna_overrides = before_dna
        S.dna_modified = before_dna_modified
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
    seen = {(model.path, model.lba)}
    targets = {}
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
        entry_key = (chosen.path, chosen.lba)
        if entry_key not in seen:
            files.append(chosen)
            seen.add(entry_key)
        info['slots'][slot] = {'file': _basename(chosen), 'origin': origin, 'shared': _basename(chosen)[1:] != f'{stem}.BIN'}
        target = f'{slot}{stem}.BIN'
        targets.setdefault(entry_key, []).append(target)
    for entry in files[1:]:
        names = targets[(entry.path, entry.lba)]
        if len(names) > 1 or names[0] != _basename(entry):
            aliases[(entry.path, entry.lba)] = names if len(names) > 1 else names[0]
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
    dw3, hd = None, False
    if not original:
        job = (getattr(S, 'dw3_imports', {}) or {}).get(c.id)
        if job and job.get('quality'):
            dw3 = dict(job['quality'], source_name=job.get('source_name'))
            view = Path(str(dw3.pop('source_view', '') or ''))
            try:
                dw3['source_url'] = view.resolve().relative_to(CACHE.resolve()).as_posix() if view.is_file() else None
            except ValueError:
                dw3['source_url'] = None
        try:
            from dw2studio.core.native_rom_bridge import native_model_entry
            hd = bool(getattr(s, 'hd_files', None) and s.hd_files.get(
                hashlib.sha256(s.current(native_model_entry(S.entries, c))).hexdigest()))
        except Exception:
            hd = False
    return {'url': model.relative_to(CACHE).as_posix(), 'name': c.name, 'id': c.id, 'code': c.code,
            'dw3_quality': dw3, 'hd_available': hd,
            'animations': animations, 'anim_source': family, 'edited': edited, 'original': bool(original),
            **dict(zip(('shadow', 'shadow_error'), _shadow_url())),
            'seconds': round(time.perf_counter() - started, 2)}


# --------------------------------------------------------------------------- Schatten (Originalmodell)
SHADOW_FILE_ID = 0x5B   # main/shadow.c Gfx_ShadowUpdate: Gfx_AttachModel(actor, 0x5B), Boden y 0 unter Knochen 0


def _private_file(file_id):
    """Datei über die private US-Dateitabelle in SLUS_011.93 lesen (wie Cd_GetFileLba)."""
    from dw2studio.core.disc import Disc
    s = _need_session()
    if hasattr(s, 'pak'):
        return s.pak.read(file_id)
    exe = [e for e in S.entries if not e.directory and _basename(e) == 'SLUS_011.93']
    if len({(e.lba, e.size) for e in exe}) != 1:
        raise ValueError('SLUS_011.93 nicht eindeutig gefunden.')
    data = s.current(exe[0])
    count, lba_base, size_base = 3675, 0x33F94, 0x37900
    if not data.startswith(b'PS-X EXE') or len(data) < size_base + count * 2 or not 0 <= file_id < count:
        raise ValueError('US-Dateitabelle in SLUS_011.93 nicht erkannt.')
    lba = struct.unpack_from('<I', data, lba_base + 4 * file_id)[0]
    sectors = struct.unpack_from('<H', data, size_base + 2 * file_id)[0]
    if not sectors:
        raise ValueError(f'Datei {file_id} ist leer.')
    disc = Disc(S.image_path)
    try:
        return disc.read(lba, sectors * 2048)
    finally:
        disc.close()


def _shadow_url():
    """Schattenmodell des Spiels (Datei 0x5B) als glTF: (url, None) oder (None, Grund)."""
    from dw2studio.core.native_gltf import convert_model
    from dw2studio.core.native_model import NativeModel
    target = CACHE / 'models' / CONVERTER_VERSION / S.index_key / 'shadow' / 'shadow.gltf'
    try:
        if not target.is_file():
            native = _private_file(SHADOW_FILE_ID)
            NativeModel(native)
            target.parent.mkdir(parents=True, exist_ok=True)
            convert_model(native, {}, target)
        return target.relative_to(CACHE).as_posix(), None
    except Exception as exc:     # ohne Schatten anzeigen, Grund in der Diagnose
        if not isinstance(exc, ValueError):
            traceback.print_exc()
        return None, f'{exc.__class__.__name__}: {exc}'



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
    by_name = {_basename(e): e for e in files}
    for slot, binding in family['slots'].items():
        e = by_name[binding['file']]
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


# --------------------------------------------------------------------------- 0.17b: Mod prüfen / ersetzen / einlesen
def _pak():
    s = _need_session()
    if not hasattr(s, 'pak'):
        raise ValueError('Dafür bitte dw2.pak öffnen.')
    return s, s.pak


def mod_check(port_dir):
    from dw2studio.mod_io import check
    s, pak = _pak()
    return check(s, pak, port_dir, S.digivolve_levels, S.battle_camera, _dna_model() if S.dna_modified or S.dna_overrides else None)


def mod_export(port_dir):
    from dw2studio.mod_io import export_checked
    s, pak = _pak()
    return export_checked(s, pak, port_dir, replace=False, name='DW2 Mod Studio ' + VERSION, levels=S.digivolve_levels, cameras=S.battle_camera, dna=_dna_model() if S.dna_modified or S.dna_overrides else None)


def mod_export_replace(port_dir):
    from dw2studio.mod_io import export_checked
    s, pak = _pak()
    return export_checked(s, pak, port_dir, replace=True, name='DW2 Mod Studio ' + VERSION, levels=S.digivolve_levels, cameras=S.battle_camera, dna=_dna_model() if S.dna_modified or S.dna_overrides else None)


def mod_import(port_dir):
    from dw2studio.mod_io import import_into
    s, _ = _pak()
    dna = _dna_import(port_dir)
    if S.dna_overrides and S.dna_overrides != dna:
        from dw2studio.mod_io import ModConflict
        raise ModConflict([{'text': 'DNA-Regeln weichen von eigenen Änderungen ab.'}])
    result = import_into(s, S.entries, port_dir)
    result['dna_overrides'] = len(dna)
    S.dna_overrides = dna
    S.dna_modified = (Path(port_dir) / "Mods" / "dna_overrides.json").exists()
    return result


def mod_import_force(port_dir):
    """Import even though the mod replaces files changed here (after the user confirmed)."""
    from dw2studio.mod_io import import_into
    s, _ = _pak()
    dna = _dna_import(port_dir)
    result = import_into(s, S.entries, port_dir, force=True)
    result['dna_overrides'] = len(dna)
    S.dna_overrides = dna
    S.dna_modified = (Path(port_dir) / "Mods" / "dna_overrides.json").exists()
    return result


# --------------------------------------------------------------------------- 0.17b: Domains und Gegnergruppen
def _current_names():
    names = {c.id: c.name for c in S.catalog}
    try:
        from dw2studio.core.digimon_names import NameRepository
        names.update({i: n for i, n in NameRepository(_need_session(), S.entries).names().items() if n})
    except (ValueError, OSError, AttributeError, TypeError):
        pass
    return names


def _domains():
    from dw2studio.core.domains import DomainRepository
    return DomainRepository(_need_session(), S.entries)


def _ids():
    from dw2studio.core.battle_skills import AttackRepository
    skills, base, _ = AttackRepository(_need_session(), S.entries).tables()
    return {c.id for c in S.catalog} | set(base.records), set(skills.records)


def domains_overview():
    return {'domains': _domains().overview()}


def domain_set_floor(index, floor, sets):
    return {'changed': _domains().set_floor(int(index), int(floor), [int(v) for v in sets])}


def group_info(set_id):
    repo = _domains()
    info = repo.groups().group(int(set_id))
    names = _current_names()
    for m in info['members']:
        m['name'] = names.get(m['digimon'], '')
    info['map_name'] = names.get(info['header']['map_digimon'], '')
    info['usage'] = repo.usage(int(set_id))
    return info


def group_set(set_id, header=None, members=None):
    digimon, skills = _ids()
    return {'changed': _domains().set_group(int(set_id), header or None, members or None, digimon, skills)}


def group_clone(source_id):
    return {'id': _domains().clone_group(int(source_id))}


def groups_list():
    g = _domains().groups()
    names = _current_names()
    out = []
    for sid in sorted(g.groups):
        info = g.group(sid)
        out.append({'id': sid, 'members': [names.get(m['digimon'], str(m['digimon'])) for m in info['members'] if m['digimon']],
                    'levels': [m['level'] for m in info['members'] if m['digimon']]})
    return {'groups': out, 'free': len(g.free_ids())}


# --------------------------------------------------------------------------- 0.17b: Individuelle Techniken
def _techniques():
    from dw2studio.core.techniques import TechniqueRepository
    return TechniqueRepository(_need_session(), S.entries)


def techniques_catalog():
    return {'techniques': _techniques().catalog()}


def technique_usage(technique):
    return _techniques().usage(int(technique))


def technique_create(digimon, source, name, description=None, values=None, as_default=True, encounters=None):
    return _techniques().create(int(digimon), int(source), name, description=description or None,
                                values=values or None, as_default=bool(as_default),
                                encounters=[tuple(k) for k in (encounters or [])])


def technique_edit(technique, digimon, values=None, name=None):
    return {'changed': _techniques().edit(int(technique), values or None, name or None, digimon=int(digimon))}


def technique_copy_parts(technique, source, parts, digimon):
    from dw2studio.core.techniques import copy_parts
    return {'changed': copy_parts(_techniques(), int(technique), int(source), list(parts or ()), digimon=int(digimon))}


def technique_assign(technique, digimon_ids):
    from dw2studio.core.techniques import assign
    return {'changed': assign(_techniques(), int(technique), [int(d) for d in (digimon_ids or ())])}


def technique_budget():
    from dw2studio.core.techniques import id_budget
    return id_budget(_techniques())


def _dna_choices():
    from dw2studio.core.evolution import EvolutionRepository
    from dw2studio.core.battle_skills import BaseTable
    repo = EvolutionRepository(_need_session(), S.entries)
    return sorted(i for i in BaseTable(repo.session.current(repo.entry)).records if 1 <= i <= 255)


def _dna_model():
    from dw2studio.core.dna_overrides import DnaOverrides
    model = DnaOverrides(valid_ids=_dna_choices()) if S.dna_overrides else DnaOverrides()
    for (a, b), (result, rank) in S.dna_overrides.items():
        model.add(a, b, result, rank)
    return model


def dna_info():
    model = _dna_model()
    names = _current_names()
    return {**model.to_dict(), 'choices': [{'id': i, 'name': names.get(i, str(i))} for i in _dna_choices()]}


def dna_set(a, b, result, rank):
    model = _dna_model()
    model.valid_ids = frozenset(_dna_choices())
    model.set(a, b, result, rank)
    S.dna_overrides = model.rules
    S.dna_modified = True
    return dna_info()


def dna_remove(a, b):
    model = _dna_model()
    model.remove(a, b)
    S.dna_overrides = model.rules
    S.dna_modified = True
    return dna_info()


def _dna_import(port_dir):
    from dw2studio.core.dna_overrides import DnaOverrides, FILENAME
    path = Path(port_dir) / 'Mods' / FILENAME
    return DnaOverrides.from_json(path.read_text(encoding='utf-8-sig'), _dna_choices()).rules if path.exists() else {}


def digivolve_levels_info():
    from dw2studio.digivolve_levels import DEFAULT, FORMAT
    return {'levels': {str(k): v for k, v in (getattr(S, 'digivolve_levels', {}) or {}).items()},
            'default': DEFAULT, 'format': FORMAT,
            'note': 'Mindestlevel, ab dem dieses Digimon im Digi-Labor digitieren darf (statt Rookie 11, Champion 21, '
                    'Ultimate 31). Mega bleibt gesperrt, die DP-Ziele gelten weiter. Wirkt mit dem mitgelieferten '
                    'PC-Port ab 1.0 (Mods\\digivolve_levels.json); ältere Ports ignorieren die Datei.'}


def digivolve_level_set(digimon, level=None):
    from dw2studio.digivolve_levels import validate
    levels = dict(getattr(S, 'digivolve_levels', {}) or {})
    if level in (None, '', 0):
        levels.pop(int(digimon), None)
    else:
        levels[int(digimon)] = int(level)
    S.digivolve_levels = validate(levels)
    return digivolve_levels_info()


def _digi_box(identifier):
    from dw2studio.core.battle_shots import model_box
    s = _need_session()
    family, _, _ = _model_family(_find(identifier))
    model = next(e for e in family if Path(e.path).name.startswith('M'))
    anims = [s.current(e) for k in 'AFGH' for e in family if Path(e.path).name[0] == k]
    if not anims:
        raise ValueError('Ohne Animationsdateien lässt sich die Größe nicht messen.')
    return model_box(s.current(model), anims, points=True)


def battle_camera_info(identifier, setting=None):
    """Attack / target / close-up shots of a Digimon: current setting, automatic suggestion, which
    shots keep the whole Digimon on screen, and eye / target points for the preview."""
    from dw2studio.core import battle_shots as B
    from dw2studio.core.battle_camera import CameraRepository
    ident = int(identifier)
    cur = B.validate(setting) if setting is not None else dict(S.battle_camera.get(ident, {}))
    box = _digi_box(ident)
    field = CameraRepository(_need_session(), S.entries).values(ident)['field_1E']
    shot_adj = {k: v for k, v in cur.items() if k != 'closeup'} or None
    close_adj = cur.get('closeup') or None
    rows = B.check(box, shot_adj, close_adj, field)
    views = {}
    for i in range(6):
        for name, frame in B.shots(i, field):
            a = close_adj if frame['kind'] == 'closeup' else shot_adj
            views[f'{i}:{name}'] = B.preview(B.adjusted(frame, a), i)
    auto = B.auto(box)
    auto_close = B.auto_closeup(box, field)
    suggestion = dict(auto or {})
    if auto_close:
        suggestion['closeup'] = auto_close
    return {'setting': cur, 'auto': suggestion, 'box': [round(v) for v in box[:3]], 'checks': rows,
            'all_fit': all(r['fits'] for r in rows), 'views': views, 'field_1E': field,
            'limits': B.LIMITS}


def battle_camera_set(identifier, setting=None):
    from dw2studio.core import battle_shots as B
    ident = int(identifier)
    if setting:
        S.battle_camera[ident] = B.validate(setting)
    else:
        S.battle_camera.pop(ident, None)
    return {'setting': S.battle_camera.get(ident, {})}


_HEIGHTS = {}


def _height_of(candidate, original=False, repo=None):
    from dw2studio.core.dw3_native import model_height
    s = _need_session()
    family, _, meta = _model_family(candidate, original=original, repo=repo)
    model = next(e for e in family if Path(e.path).name.startswith('M'))
    name = meta['slots'].get('A', {}).get('file')
    anim = next(e for e in family if _basename(e) == name) if name else next(e for e in family if not _basename(e).startswith('M'))
    get = s.original if original else s.current
    return model_height(get(model), get(anim))


def size_info(identifier):
    """Battle size of a Digimon (standing height in DW2 units) with the DW2 originals as the scale,
    and for DW3 imports the factor it was imported with (dw3_resize changes it)."""
    ident = int(identifier)
    cand = _find(ident)
    if _HEIGHTS.get('_image') != S.index_key:
        # one name table for all 395 Digimon: discovering it per Digimon took most of a minute
        # on a BIN and blocked every other Studio action queued behind it (renaming, export)
        from dw2studio.core.digimon_names import NameRepository
        _HEIGHTS.clear()
        _HEIGHTS['_image'] = S.index_key
        cache = CACHE / 'heights' / f'{S.index_key}.json'
        try:
            _HEIGHTS.update({int(k): tuple(v) for k, v in json.loads(cache.read_text(encoding='utf-8')).items()})
        except (OSError, ValueError):
            repo = NameRepository(_need_session(), S.entries)
            for c in S.catalog:
                try:
                    _HEIGHTS[c.id] = (c.name, round(_height_of(c, original=True, repo=repo)))
                except Exception:
                    pass
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({k: v for k, v in _HEIGHTS.items() if k != '_image'}), encoding='utf-8')
            except OSError:
                pass
    now = round(_height_of(cand))
    job = (getattr(S, 'dw3_imports', {}) or {}).get(ident)
    table = {i: v for i, v in _HEIGHTS.items() if i != '_image'}
    near = sorted(((abs(h - now), n, h) for i, (n, h) in table.items() if i != ident))[:3]
    return {'height': now, 'original_height': table.get(ident, (None, None))[1],
            'imported': bool(job), 'factor': job.get('scale', 1.) if job else None,
            'size_mode': job.get('size_mode', 'dw2') if job else None,
            'source': job.get('source_name') if job else None,
            'similar': [{'name': n, 'height': h} for _, n, h in near],
            'range': [min(h for _, h in table.values()), max(h for _, h in table.values())]}


def dw3_resize(target, factor, size_mode=None):
    """Import an already imported DW3 Digimon again with another size factor (same source model,
    motions and HD setting). Needs the DW3 image that was used."""
    ident = int(target)
    job = (getattr(S, 'dw3_imports', {}) or {}).get(ident)
    if not job:
        raise ValueError('Dieses Digimon wurde in diesem Projekt nicht aus DW3 importiert.')
    listing = dw3_models()
    if not listing['open']:
        raise ValueError('Zuerst das DW3-Abbild öffnen, aus dem importiert wurde.')
    models = {m['name']: m['id'] for m in listing['models']}
    if job['source_name'] not in models:
        raise ValueError(f'DW3-Modell {job["source_name"]} ist im geöffneten Abbild nicht vorhanden.')
    f = float(factor)
    if not 0.1 <= f <= 10:
        raise ValueError('Größenfaktor 0,1–10.')
    from dw2studio.dw3_import import apply as native_apply
    return native_apply(sys.modules[__name__], models[job['source_name']], ident, job['assignments'], f,
                        job.get('hd', 0), None, size_mode or job.get('size_mode', 'dw2'))


def _dw3_job(target):
    ident = int(target)
    job = (getattr(S, 'dw3_imports', {}) or {}).get(ident)
    if not job:
        raise ValueError('Dieses Digimon wurde in diesem Projekt nicht aus DW3 importiert.')
    listing = dw3_models()
    if not listing['open']:
        raise ValueError('Zuerst das DW3-Abbild öffnen, aus dem importiert wurde.')
    models = {m['name']: m['id'] for m in listing['models']}
    if job['source_name'] not in models:
        raise ValueError(f'DW3-Modell {job["source_name"]} ist im geöffneten Abbild nicht vorhanden.')
    return ident, job, models[job['source_name']]


def anim_editor(target):
    """Everything the animation editor shows for a DW3 import: the DW2 places with their actions
    (as imported, or the DW3 defaults where the import predates 0.96), the DW3 motions (frames, how
    each ends, which scripts use it) and the defaults for 'reset'."""
    from dw2studio.dw3_import import prepare
    from dw2studio import dw3_actions
    ident, job, source_id = _dw3_job(target)
    prepared = prepare(sys.modules[__name__], source_id, ident)
    info = prepared['info']
    table = dw3_actions.motion_table(prepared['source'])
    defaults = {(d['slot'], d['clip']): d['action'] for d in info['assignments']}
    current = {(r['slot'], r['clip']): r for r in job['assignments']}
    used = {}
    for sc in info.get('scripts') or []:
        for m in sc.get('motions', []):
            used.setdefault(m, []).append(sc['index'])
    model = next((m for m in DW3.catalog() if m['name'] == job['source_name']), {})
    places = []
    for d in info['assignments']:
        key = (d['slot'], d['clip'])
        row = current.get(key)
        if row and isinstance(row.get('action'), dict):
            act = row['action']
        elif row and row.get('motion') in table:
            act = dw3_actions.legacy(table, row['motion'], bool(row.get('loop')))
        else:
            act = defaults[key]
        places.append({'slot': d['slot'], 'clip': d['clip'], 'id': 10 * 'ABCDEFGHIJK'.index(d['slot']) + d['clip'],
                       'role': d.get('role', dw3_actions.ROLES.get(key, 'Feld-Animation (nicht im Kampf)')), 'action': act,
                       'default': defaults[key], 'transitions': dw3_actions.transitions(prepared['source'], act)})
    motions = [dict(m, scripts=used.get(m['id'], [])) for m in info['motions']]
    return {'target': ident, 'source': job['source_name'], 'field': ident >= 300, 'places': places, 'motions': motions,
            'status': dw3_actions.STATUS, 'scripts': info.get('scripts') or [],
            'digimon': model.get('digimon', job['source_name']), 'model_id': (model.get('fighter_ids') or [None])[0],
            'code': model.get('code'), 'file_number': model.get('file_number'), 'variant': model.get('variant', ''),
            'name_status': model.get('status_text', '')}


def anim_check(target, action):
    """Validate one action and report its pose jumps, without changing anything."""
    from dw2studio.dw3_import import prepare
    from dw2studio import dw3_actions
    ident, job, source_id = _dw3_job(target)
    prepared = prepare(sys.modules[__name__], source_id, ident)
    table = dw3_actions.motion_table(prepared['source'])
    dw3_actions.validate(action, table)
    rows, loop_row = dw3_actions.frames_of(action, table)
    return {'frames': len(rows), 'loop_row': loop_row, 'transitions': dw3_actions.transitions(prepared['source'], action)}


def anim_apply(target, places):
    """Import the DW3 Digimon again with the edited actions (PLACES: [{'slot', 'clip', 'action'}]),
    keeping its size, HD and size mode. A changed action is marked 'manual'."""
    from dw2studio.dw3_import import apply as native_apply
    ident, job, source_id = _dw3_job(target)
    rows = []
    for pl in places:
        act = dict(pl['action'])
        rows.append({'slot': pl['slot'], 'clip': int(pl['clip']), 'action': act,
                     'motion': act['segments'][0]['motion'], 'loop': act.get('end') == 'loop'})
    report = native_apply(sys.modules[__name__], source_id, ident, rows, job.get('scale', 1.), job.get('hd', 0), None,
                          job.get('size_mode', 'dw2'))
    return {'target': ident, 'files': report.get('files'), 'triangles': report.get('triangles')}


def evolution_validate():
    from dw2studio.core.evolution import EvolutionRepository, validate
    return validate(EvolutionRepository(_need_session(), S.entries))


# --------------------------------------------------------------------------- 0.17b: Kamera, Digitationslinien, Mehrfach-Import
def camera_info(identifier):
    from dw2studio.core.battle_camera import CameraRepository, FIELD_MIN, FIELD_MAX, HIT_MIN, HIT_MAX
    repo = CameraRepository(_need_session(), S.entries)
    from dw2studio.core.battle_camera import closeup
    return {'current': repo.values(int(identifier)), 'original': repo.values(int(identifier), original=True),
            'limits': {'field': [FIELD_MIN, FIELD_MAX], 'hit': [HIT_MIN, HIT_MAX]},
            'closeups': [closeup(0x300 + 256 * b) for b in range(9)]}


def camera_set(identifier, field, hit):
    from dw2studio.core.battle_camera import CameraRepository
    return {'changed': CameraRepository(_need_session(), S.entries).set(int(identifier), int(field), int(hit))}


def evolution_line(lines):
    from dw2studio.core.evolution import EvolutionRepository, change_line
    return {'changed': change_line(EvolutionRepository(_need_session(), S.entries), lines)}


def dw3_batch_apply(jobs):
    """Several DW3 -> DW2 slot replacements as one step. JOBS: [{'source', 'target', 'assignments'?,
    'scale'?, 'hd'?, 'camera'?, 'name'?}]. Missing assignments use the script-based defaults."""
    from dw2studio.dw3_import import apply as native_apply
    if not isinstance(jobs, list) or not jobs:
        raise ValueError('Mindestens ein DW3-Digimon und ein Zielslot.')
    targets = [int(j['target']) for j in jobs]
    if len(set(targets)) != len(targets):
        raise ValueError('Jeder DW2-Slot darf nur einmal ersetzt werden.')
    s = _need_session()
    before, hd = dict(s.edits), dict(getattr(s, 'hd_files', {}))
    reports = []
    try:
        for job in jobs:
            assignments = job.get('assignments') or dw3_native_plan(int(job['source']), int(job['target']))['assignments']
            r = native_apply(__import__(__name__), int(job['source']), int(job['target']), assignments,
                             float(job.get('scale', 1.)), int(job.get('hd', 0)), job.get('camera'),
                             job.get('size_mode', 'dw2'), bool(job.get('allow_reduce', False)))
            if job.get('name'):
                rename(int(job['target']), job['name'])
            reports.append({'target': int(job['target']), **r})
    except Exception:
        s.edits = before
        if hasattr(s, 'hd_files'):
            s.hd_files = hd
        raise
    return {'jobs': reports}


# --------------------------------------------------------------------------- 0.17b: Datei-Explorer
def files_list():
    s = _need_session()
    edited = {(e.path, e.lba) for e in s.edits.values()}
    rows = []
    for e in S.entries:
        if e.directory:
            continue
        rows.append({'path': e.path, 'name': Path(e.path).name, 'lba': e.lba, 'size': e.size,
                     'edited': (e.path, e.lba) in edited})
    rows.sort(key=lambda r: (r['name'], r['lba']))
    return {'source': S.image_path.name if S.image_path else '', 'files': rows}


def file_export(lba, original=False):
    s = _need_session()
    matches = [e for e in S.entries if not e.directory and e.lba == int(lba)]
    if not matches:
        raise ValueError('Datei nicht gefunden.')
    entry = matches[0]
    data = s.original(entry) if original else s.current(entry)
    target = _exports() / _unique_name(_exports(), Path(entry.path).name)
    target.write_bytes(data)
    return {'path': str(target), 'name': target.name}


def dw3_models():
    if DW3 is None:
        return {'open': False, 'models': []}
    names = getattr(DW3, 'names', None) or {}
    return {'open': True, 'name': DW3.path.name, 'models': DW3.catalog(), 'names_source': names.get('source'),
            'names_note': names.get('note')}


def dw3_thumb_save(identifier, data_url):
    """Store the viewer's preview of DW3 model IDENTIFIER (data:image/png;base64,...)."""
    import base64
    if DW3 is None:
        raise ValueError('Bitte zuerst ein DW3-Image öffnen.')
    prefix = 'data:image/png;base64,'
    if not isinstance(data_url, str) or not data_url.startswith(prefix) or len(data_url) > 400000:
        raise ValueError('Vorschaubild ungültig.')
    return DW3.save_thumb(int(identifier), base64.b64decode(data_url[len(prefix):], validate=True))


def dw3_find(query):
    """DW3 models whose name, alternative name, file code, file name or id matches QUERY."""
    from dw2studio.dw3_names import matches, rank
    if DW3 is None:
        return []
    out = []
    for m in DW3.catalog():
        row = {'name': m.get('digimon', m['name']), 'code': m.get('code', ''), 'file': m.get('file', m['name']),
               'aliases': m.get('aliases', []), 'id': m['id'], 'file_number': m.get('file_number'),
               'name_index': m.get('name_index'), 'fighter_ids': m.get('fighter_ids', [])}
        if matches(row, query):
            out.append((rank(row, query), m))
    return [m for _, m in sorted(out, key=lambda x: x[0])]


# --------------------------------------------------------------------------- 0.17b: HD-Vorschau
def _hd_publish(data):
    import io
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        if image.format != 'PNG':
            raise ValueError('HD-Textur muss PNG sein.')
        w, h = image.size
    if w % 128 or h % 256 or w // 128 != h // 256 or not 1 <= w // 128 <= 16:
        raise ValueError('HD-PNG muss 128×256 mal 1–16 groß sein (bis 2048×4096).')
    folder = CACHE / 'hdpreview'
    folder.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(data).hexdigest()[:24] + '.png'
    (folder / name).write_bytes(data)
    return {'url': f'hdpreview/{name}', 'size': [w, h]}


def hd_preview(identifier, path):
    from dw2studio.core.png_source import verified_png
    payload, info = verified_png(path)
    return _hd_publish(payload)


def hd_active(identifier):
    from dw2studio.core.native_rom_bridge import native_model_entry
    s = _need_session()
    if not hasattr(s, 'hd_files'):
        raise ValueError('HD-Texturen gibt es nur bei geöffneter dw2.pak.')
    entry = native_model_entry(S.entries, _find(int(identifier)))
    files = s.hd_files.get(hashlib.sha256(s.current(entry)).hexdigest(), {})
    if not files:
        raise ValueError('Für dieses Modell ist keine HD-Textur vorgemerkt (z. B. aus dem DW3-Import).')
    return _hd_publish(next(iter(files.values())))


# --------------------------------------------------------------------------- Verlauf (Rückgängig / Wiederherstellen)
UNDO, REDO = [], []
MUTATING = {'dna_set', 'dna_remove', 'anim_apply', 'digivolve_level_set', 'battle_camera_set', 'dw3_resize', 'dw3_native_apply', 'dw3_batch_apply', 'mod_import', 'mod_import_force', 'technique_copy_parts', 'technique_assign', 'domain_set_floor', 'group_set', 'group_clone',
            'technique_create', 'technique_edit', 'camera_set', 'evolution_line', 'set_evolution', 'rename', 'set_type', 'set_specialty', 'set_enemy_values', 'apply_attacks', 'roster_change',
            'roster_restore', 'discard', 'load_project', 'png_apply', 'transfer_apply', 'bin_apply',
            'rig_apply', 'restore_original'}


def _snapshot():
    return (dict(S.session.edits) if S.session else {},
            bytes(S.roster.raw) if S.roster is not None else None,
            (dict(getattr(S, 'dna_overrides', {}) or {}), S.dna_modified),
            dict(getattr(S, 'digivolve_levels', {}) or {}),
            {k: dict(v) for k, v in (getattr(S, 'battle_camera', {}) or {}).items()},
            {k: dict(v) for k, v in (getattr(S, 'dw3_imports', {}) or {}).items()})


def _restore(snap):
    edits, roster, dna, levels, cams, imports = snap
    S.dna_overrides = dict(dna[0])
    S.dna_modified = dna[1]
    S.digivolve_levels = dict(levels)
    S.battle_camera = {k: dict(v) for k, v in cams.items()}
    S.dw3_imports = {k: dict(v) for k, v in imports.items()}
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
    'export_hd_pack': export_hd_pack,
    'anim_editor': anim_editor, 'anim_check': anim_check, 'anim_apply': anim_apply,
    'dw3_native_plan': dw3_native_plan, 'dw3_native_apply': dw3_native_apply,
    'evolution_info': evolution_info, 'set_evolution': set_evolution, 'evolution_line': evolution_line,
    'mod_check': mod_check, 'mod_export': mod_export, 'mod_export_replace': mod_export_replace, 'mod_import': mod_import,
    'domains_overview': domains_overview, 'domain_set_floor': domain_set_floor, 'group_info': group_info,
    'group_set': group_set, 'group_clone': group_clone, 'groups_list': groups_list,
    'techniques_catalog': techniques_catalog, 'technique_usage': technique_usage,
    'technique_create': technique_create, 'technique_edit': technique_edit,
    'technique_copy_parts': technique_copy_parts, 'technique_assign': technique_assign,
    'technique_budget': technique_budget, 'evolution_validate': evolution_validate,
    'dna_info': dna_info, 'dna_set': dna_set, 'dna_remove': dna_remove,
    'digivolve_levels_info': digivolve_levels_info, 'digivolve_level_set': digivolve_level_set,
    'battle_camera_info': battle_camera_info, 'battle_camera_set': battle_camera_set,
    'dw3_resize': dw3_resize, 'size_info': size_info, 'mod_import_force': mod_import_force,
    'hd_preview': hd_preview, 'hd_active': hd_active, 'files_list': files_list, 'file_export': file_export, 'dw3_models': dw3_models,
    'camera_info': camera_info, 'camera_set': camera_set, 'dw3_batch_apply': dw3_batch_apply,
    'open_dw3': open_dw3, 'prepare_dw3': prepare_dw3, 'dw3_thumb_save': dw3_thumb_save, 'dw3_find': dw3_find, 'export_dw3': export_dw3, 'export_port_mod': export_port_mod,
    'port_mod_status': port_mod_status, 'port_mod_disable': port_mod_disable, 'port_mod_enable': port_mod_enable,
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



def _image_only():
    """Android-App / Web-Version: nur PS1-Images (BIN/ISO). dw2.pak (PC-Port, Modus A) wird abgewiesen."""
    original = _METHODS['open_image']

    def open_image_mobile(path):
        from dw2studio.pak import MAGIC
        with open(path, 'rb') as f:
            if f.read(len(MAGIC)) == MAGIC:
                raise ValueError('Die mobile Version bearbeitet nur PS1-Images (BIN/ISO). dw2.pak und PC-Port-Mods bitte im Mod Studio am PC bearbeiten.')
        return original(path)
    _METHODS['open_image'] = open_image_mobile
    import dna_image   # DNA-Regeln als Tabelle des Digi-Labors im Image (STAG2000.PRO)
    dna_image.register(_METHODS, MUTATING)


_image_only()


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
