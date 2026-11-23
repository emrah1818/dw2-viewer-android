"""PC-port mods: check before export, export (optionally replacing the active mod), read back.

Format = what dw2-pc-port's loader reads (host/pak.c, load_mod_dir; doc/MOD_API2.md):
Mods/files/<ID as 4 hex digits>.bin replaces file ID; Mods/Textures/<pack>/<hash>_<w>x<h>_m0.png
is a TexRep texture pack (backend/texrep.c). dw2studio_mod.json is the Studio's own manifest;
the port ignores it.
"""
import hashlib
import json
import re
from pathlib import Path

from .port_mod import plan, export
from .port_mod_manage import MANIFEST, disable

MOD_FILE = re.compile(r'^([0-9A-Fa-f]{4})\.bin$')
LIMIT = 2 * 1024 * 1024


def _api_level(port):
    try:
        return json.loads((Path(port) / 'dw2_mod_api.json').read_text(encoding='utf-8')).get('mod_api', 1)
    except (OSError, ValueError, AttributeError):
        return 1


def check(session, pak, port_dir, levels=None, cameras=None, dna=None):
    """What an export would write and what stands in its way. Writes nothing."""
    port = Path(port_dir)
    report = {'files': [], 'errors': [], 'conflicts': [], 'warnings': [], 'api': _api_level(port)}
    if not port.is_dir():
        report['errors'].append('PC-Port-Ordner nicht gefunden.')
        return report
    if not (port / 'dw2.exe').is_file() and not (port / 'dw2').is_file():
        report['warnings'].append('Im Ordner liegt keine dw2.exe. Ist das der PC-Port-Ordner?')
    if levels:
        from .digivolve_levels import port_supports, FILENAME
        report['levels'] = len(levels)
        if not port_supports(port):
            report['warnings'].append(f'Digitationslevel für {len(levels)} Digimon werden als Mods\\{FILENAME} '
                                      'mitgeschrieben. Dieser PC-Port meldet die Schnittstelle nicht '
                                      '(dw2_mod_api.json ohne "digivolve_levels"); er ignoriert die Datei. '
                                      'Den mitgelieferten Port ab 1.0 verwenden.')
    if cameras:
        report['cameras'] = len(cameras)
        try:
            api_doc = json.loads((port / 'dw2_mod_api.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            api_doc = {}
        if not isinstance(api_doc, dict) or int(api_doc.get('battle_camera', 0) or 0) < 1:
            report['warnings'].append(f'Kampfkameras für {len(cameras)} Digimon werden als Mods\\battle_camera.json '
                                      'mitgeschrieben. Dieser PC-Port meldet die Schnittstelle nicht und ignoriert sie. '
                                      'Den mitgelieferten Port ab 1.0 verwenden.')
    if dna is not None:
        report['dna'] = len(dna.rules)
        try:
            api_doc = json.loads((port / 'dw2_mod_api.json').read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            api_doc = {}
        if not isinstance(api_doc, dict) or api_doc.get('dna_overrides') != 1:
            report['errors'].append('DNA-Regeln benötigen den PC-Port mit "dna_overrides": 1 in dw2_mod_api.json.')
    for sidecar in ('digivolve_levels.json', 'battle_camera.json', 'dna_overrides.json'):
        if (port / 'Mods' / sidecar).exists():
            report['conflicts'].append(f'{sidecar} ist schon als Mod aktiv.')
    if not session.edits and not levels and not cameras and dna is None:
        report['errors'].append('Es sind keine Änderungen vorgemerkt.')
        return report
    extended = any(e.relocate or len(e.replacement) != len(e.original) for e in session.edits.values())
    try:
        changes = plan(session, pak, allow_resize=extended)
    except ValueError as exc:
        report['errors'].append(str(exc))
        return report
    if extended and report['api'] != 2:
        report['errors'].append('Größere Dateien brauchen den mitgelieferten PC-Port mit Mod-Schnittstelle 2 '
                                '(dw2_mod_api.json mit "mod_api": 2 fehlt im Ordner).')
    from .core.format_limits import check_staged
    report['errors'].extend('Formatgrenze: ' + p for p in check_staged(session))
    files = port / 'Mods' / 'files'
    active = {int(m.group(1), 16): p for p in (files.iterdir() if files.is_dir() else []) if (m := MOD_FILE.match(p.name))}
    for c in changes:
        report['files'].append({'file': f"{c['id']:04X}.bin", 'id': c['id'], 'name': Path(c['path']).name,
                                'label': c['label'], 'size': c['replacement_size'], 'original_size': c['size'],
                                'needs_api2': c['replacement_size'] != c['size']})
        if c['id'] in active:
            report['conflicts'].append(f"{c['id']:04X}.bin ist schon als Mod aktiv.")
    if (port / 'Mods' / MANIFEST).exists():
        report['conflicts'].append('Im Ordner ist bereits ein Studio-Mod aktiv (dw2studio_mod.json).')
    textures = session.active_hd_files() if hasattr(session, 'active_hd_files') else {}
    for name in textures:
        if (port / 'Mods' / name).exists():
            report['conflicts'].append(f'HD-Textur {name} existiert schon.')
    report['textures'] = sorted(textures)
    report['ok'] = not report['errors']
    return report


def export_checked(session, pak, port_dir, *, replace=False, name='DW2 Mod Studio', levels=None, cameras=None, dna=None):
    report = check(session, pak, port_dir, levels, cameras, dna)
    if report['errors']:
        raise ValueError(' '.join(report['errors']))
    moved = None
    if report['conflicts']:
        if not replace:
            raise FileExistsError('Konflikt mit vorhandenem Mod: ' + ' '.join(report['conflicts']) +
                                  ' Mit „Vorhandenen Mod ersetzen“ wird er nach Mods\\disabled verschoben.')
        moved = disable(port_dir)
    if session.edits:
        result = export(session, pak, port_dir, mod_name=name)
    else:
        mods = Path(port_dir) / 'Mods'
        (mods / 'files').mkdir(parents=True, exist_ok=True)
        manifest = mods / MANIFEST
        manifest.write_text(json.dumps({'format': 'DW2 Mod Studio overlay 2', 'mod_api': 2,
                                       'name': name, 'files': [], 'textures': []}), encoding='utf-8')
        result = {'manifest': str(manifest), 'count': 0, 'files': []}
    if dna is not None:
        from .core.dna_overrides import FILENAME as DNA_FILE
        (Path(port_dir) / 'Mods' / DNA_FILE).write_text(dna.to_json(), encoding='utf-8')
        result['dna_overrides'] = len(dna.rules)
    result['replaced'] = moved
    if levels:
        from .digivolve_levels import dumps, FILENAME
        (Path(port_dir) / 'Mods' / FILENAME).write_text(dumps(levels), encoding='utf-8')
        result['digivolve_levels'] = len(levels)
    if cameras:
        from .core.battle_shots import dumps as cam_dumps
        (Path(port_dir) / 'Mods' / 'battle_camera.json').write_text(cam_dumps(cameras), encoding='utf-8')
        result['battle_camera'] = len(cameras)
    result['warnings'] = report['warnings']
    return result


def read_mod(port_dir, pak):
    """Files and textures of the active mod in PORT_DIR, checked against PAK. Changes nothing."""
    mods = Path(port_dir) / 'Mods'
    folder = mods / 'files'
    if not folder.is_dir() and not (mods / 'dna_overrides.json').is_file():
        raise ValueError('Im Ordner gibt es kein Mods\\files.')
    try:
        manifest = json.loads((mods / MANIFEST).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        manifest = {}
    expected = {row.get('id'): row for row in manifest.get('files', []) if isinstance(row, dict)}
    by_id = {e.id: e for e in pak.entries}
    files, problems = {}, []
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        m = MOD_FILE.match(path.name)
        if not m:
            continue
        fid = int(m.group(1), 16)
        entry = by_id.get(fid)
        data = path.read_bytes()
        if entry is None or not entry.sectors:
            problems.append(f'{path.name}: diese Datei gibt es in dw2.pak nicht.')
        elif entry.format != 0:
            problems.append(f'{path.name}: Audio/Video kann nicht ersetzt werden.')
        elif not data or len(data) > LIMIT:
            problems.append(f'{path.name}: leer oder größer als 2 MiB.')
        elif fid in expected and expected[fid].get('original_sha256') not in (None, entry.sha256.hex()):
            problems.append(f'{path.name}: der Mod wurde für eine andere dw2.pak erstellt.')
        else:
            files[fid] = data
    textures = {}
    for rel in manifest.get('textures', []) or []:
        # a mod exported on Windows lists its textures with backslashes: same file on every system
        norm = str(rel).replace('\\', '/')
        p = (mods / norm)
        if '..' in Path(norm).parts or Path(norm).is_absolute() or not p.is_file():
            problems.append(f'HD-Textur {rel} fehlt oder liegt außerhalb von Mods.')
            continue
        textures[norm] = p.read_bytes()
    return {'files': files, 'textures': textures, 'problems': problems, 'manifest': manifest}


class ModConflict(ValueError):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__('Der Mod überschneidet sich mit eigenen Änderungen: ' +
                         '; '.join(c['text'] for c in conflicts[:6]) +
                         (' …' if len(conflicts) > 6 else '') + ' Einlesen nur mit „Trotzdem einlesen“.')


def import_conflicts(session, entries, files):
    """Files the mod replaces that the session has already changed differently.

    For WAZADATA the technique ids are compared as well: an id that both sides added or changed
    with different bytes is named, because the mod would silently replace that technique."""
    from .core.game_files import file_entry
    from .core.battle_skills import SkillTable
    out = []
    for fid, data in sorted(files.items()):
        try:
            entry = file_entry(session, entries, fid)
        except Exception:
            continue
        key = (entry.path, entry.lba)
        if key not in session.edits:
            continue
        mine, orig = session.current(entry), session.original(entry)
        if mine == data:
            continue
        item = {'file': fid, 'label': session.edits[key].label,
                'text': f'Datei {fid:04X} ({session.edits[key].label})'}
        if fid == 603:
            try:
                a, b, o = SkillTable(mine), SkillTable(data), SkillTable(orig)
                rec = lambda t, i: t.data[t.records[i].offset:t.records[i].offset + 68]
                ids = sorted(i for i in set(a.records) & set(b.records)
                             if (i not in o.records or rec(a, i) != rec(o, i) or rec(b, i) != rec(o, i))
                             and (rec(a, i) != rec(b, i) or a.records[i].name != b.records[i].name))
                if ids:
                    item['technique_ids'] = ids
                    item['text'] = 'Technik-IDs doppelt belegt: ' + ', '.join(map(str, ids))
            except Exception:
                pass
        out.append(item)
    return out


def import_into(session, entries, port_dir, force=False):
    """Stage the active mod of PORT_DIR as edits of SESSION (a dw2.pak session)."""
    from .core.game_files import file_entry
    from .core.dw3_native import hd_name
    pak = getattr(session, 'pak', None)
    if pak is None:
        raise ValueError('Zum Einlesen eines Mods bitte dw2.pak öffnen.')
    found = read_mod(port_dir, pak)
    if found['problems']:
        raise ValueError(' '.join(found['problems']))
    from .core.dna_overrides import DnaOverrides, FILENAME as DNA_FILE
    dna_path = Path(port_dir) / 'Mods' / DNA_FILE
    dna = DnaOverrides.from_json(dna_path.read_text(encoding='utf-8-sig')) if dna_path.exists() else None
    if not found['files'] and dna is None:
        raise ValueError('Im Mod-Ordner liegen keine Ersatzdateien.')
    conflicts = import_conflicts(session, entries, found['files'])
    if conflicts and not force:
        raise ModConflict(conflicts)
    before = dict(session.edits)
    staged = []
    try:
        for fid, data in sorted(found['files'].items()):
            entry = file_entry(session, entries, fid)
            session.stage(entry, data, f'Aus Mod eingelesen: {fid:04X}.bin')
            staged.append((entry, data))
    except Exception:
        session.edits = before
        raise
    linked = 0
    for entry, data in staged:
        try:
            name = hd_name(data)
        except Exception:
            continue
        matches = {k: v for k, v in found['textures'].items() if Path(k).name == name}
        if matches:
            session.hd_files[hashlib.sha256(data).hexdigest()] = matches
            linked += len(matches)
    return {'files': len(staged), 'textures': linked, 'unlinked_textures': len(found['textures']) - linked,
            'name': found['manifest'].get('name', '')}
