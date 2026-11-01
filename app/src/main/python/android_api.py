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
import threading
import time
import traceback

CACHE = None          # Arbeitsordner der App (filesDir/viewer)
NATIVE_DIR = None     # nativeLibraryDir (enthält libdw2conv.so)
_lock = threading.RLock()
CONVERTER_VERSION = 'v3'   # erhöhen, wenn sich die Konvertierung ändert (alter Cache wird ignoriert)


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


def prepare_model(identifier):
    from dw2studio.core.fast_loading import ModelRequest, build_model
    from dw2studio.core.auto_models import selected_model_entries, model_animation_names
    s = _need_session()
    c = _find(identifier)
    key = _key(c)
    unique = {}
    for entry in selected_model_entries(S.entries, c):
        unique[(entry.lba, entry.size, Path(entry.path.replace('\\', '/')).name.upper())] = entry
    files = list(unique.values())
    if not files:
        raise ValueError('Für dieses Digimon wurden keine Modell-Dateien gefunden.')
    overrides = {}
    for e in files:
        edit = s.edits.get((e.path, e.lba))
        if edit:
            overrides[Path(e.path.replace('\\', '/')).name] = edit.replacement
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
    request = ModelRequest(f'{S.index_key}/{key}', str(S.image_path), files, folder, c, '', overrides)
    model = build_model(request, _convert)
    try:
        animations = model_animation_names(model)
    except Exception:
        animations = []
    native = next((e for e in files if Path(e.path.replace('\\', '/')).name.upper().startswith('M')), None)
    eyes = _eye_frames(s.current(native), model.parent) if native else None
    return {'url': model.relative_to(CACHE).as_posix(), 'name': c.name, 'id': c.id, 'code': c.code,
            'animations': animations, 'eyes': eyes, 'seconds': round(time.perf_counter() - started, 2)}


def _eye_frames(native, folder):
    """Augenposen wie in der Windows-Vorschau, aber je Material/Palette als eigene Textur.

    Rückgabe: {'frames': [[url je Material] je Pose], 'default': Index der Ruhepose} oder None.
    """
    from dw2studio.core.dw2_eyes import eye_layout
    from dw2studio.core.native_gltf import _tim, texture_images
    from dw2studio.core.native_model import NativeModel
    try:
        layout = eye_layout(native)
        if layout is None or len(layout.sources) < 2:
            return None
        tx, ty, tw, th = layout.target
        base, _ = _tim(native, NativeModel(native))
        frames = []
        for f, (sx, sy, w, h) in enumerate(layout.sources):
            names = sorted(folder.glob(f'eyes_{f}_*.png'), key=lambda p: int(p.stem.rsplit('_', 1)[1]))
            if not names:
                indices = base.copy()
                indices[ty:ty + th, tx:tx + tw] = base[sy:sy + h, sx:sx + w]
                for i, image in enumerate(texture_images(native, indices)):
                    image.save(folder / f'eyes_{f}_{i}.png')
                names = sorted(folder.glob(f'eyes_{f}_*.png'), key=lambda p: int(p.stem.rsplit('_', 1)[1]))
            frames.append([p.relative_to(CACHE).as_posix() for p in names])
        return {'frames': frames, 'default': len(frames) - 1}
    except Exception:
        traceback.print_exc()
        return None


def texture_list(identifier):
    from dw2studio.core.mini_assets import texture_slots
    info = prepare_model(identifier)
    return {'slots': [name for name, _ in texture_slots(CACHE / info['url'])], 'url': info['url']}


def texture_export(identifier, slot, name):
    from dw2studio.core.mini_assets import export_texture
    info = prepare_model(identifier)
    folder = _exports()
    target = folder / _unique_name(folder, name)
    export_texture(CACHE / info['url'], int(slot), target)
    return {'path': str(target), 'name': target.name}


def model_export(identifier, fmt, name):
    from dw2studio.core.model_export import export_model
    if fmt not in ('glb', 'gltf'):
        raise ValueError('Unterstützt: GLB oder glTF.')
    info = prepare_model(identifier)
    folder = _exports()
    stem = re.sub(r'\.(gltf|glb|obj)$', '', name, flags=re.I)
    target = folder / _unique_name(folder, stem + '.' + fmt)
    export_model(CACHE / info['url'], target)
    return {'path': str(target), 'name': target.name}


def clear_cache():
    for sub in ('models', 'exports', 'indexes'):
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
    'prepare_model': prepare_model, 'texture_list': texture_list, 'texture_export': texture_export,
    'model_export': model_export, 'clear_cache': clear_cache, 'translate': translate,
}


def call(method, args_json='[]'):
    try:
        if method not in _METHODS:
            raise ValueError(f'Unbekannte Methode: {method}')
        args = json.loads(args_json) if args_json else []
        with _lock:
            data = _METHODS[method](*args)
        return json.dumps({'ok': True, 'data': data}, ensure_ascii=False)
    except Exception as exc:  # Fehlertext geht an die Oberfläche; Details ins Log
        traceback.print_exc()
        return json.dumps({'ok': False, 'error': str(exc) or exc.__class__.__name__}, ensure_ascii=False)
