"""Installierte PC-Port-Mods ansehen, deaktivieren und wieder aktivieren.

Ergänzt den create-only-Export (port_mod.py). Es wird nichts gelöscht und nichts überschrieben:
Deaktivieren verschiebt Mods/files/*.bin, das Manifest und die dort genannten HD-Texturen nach
Mods/disabled/<Zeitstempel>/ (gleiche Unterordner). Der PC-Port lädt dann wieder die Originale
aus dw2.pak. Aktivieren verschiebt einen solchen Satz zurück, wenn kein Ziel belegt ist.
dw2.pak, dw2.pak.slus und Spielstände werden nicht berührt.
"""
import json
import time
from pathlib import Path

MANIFEST = 'dw2studio_mod.json'


def _mods(port_dir):
    port = Path(port_dir).resolve()
    if not port.is_dir():
        raise ValueError('PC-Port-Ordner nicht gefunden.')
    return port / 'Mods'


def _manifest(folder):
    try:
        doc = json.loads((folder / MANIFEST).read_text(encoding='utf-8'))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _members(root):
    """Dateien eines Mod-Satzes unter `root`, relativ zu `root`: Datei-Mods, Manifest, HD-Texturen."""
    found = []
    if (root / 'files').is_dir():
        found += sorted(p.relative_to(root) for p in (root / 'files').iterdir()
                        if p.is_file() and p.suffix.lower() == '.bin')
    doc = _manifest(root)
    for name in doc.get('textures') or []:
        rel = Path(str(name))
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('Manifest nennt einen Pfad außerhalb von Mods.')
        if (root / rel).is_file() and rel not in found:
            found.append(rel)
    for name in ('digivolve_levels.json', 'battle_camera.json', 'dna_overrides.json'):
        if (root / name).is_file():
            found.append(Path(name))
    if (root / MANIFEST).is_file():
        found.append(Path(MANIFEST))
    return found


def _describe(root):
    doc = _manifest(root)
    labels = {f"{row['id']:04X}.bin".upper(): row for row in doc.get('files') or []
              if isinstance(row, dict) and isinstance(row.get('id'), int)}
    rows = []
    for rel in _members(root):
        row = labels.get(rel.name.upper(), {}) if rel.parts[0] == 'files' else {}
        rows.append({'file': rel.as_posix(), 'name': str(row.get('path', '')).replace('\\', '/').rsplit('/', 1)[-1],
                     'label': row.get('label', '')})
    return {'name': doc.get('name', ''), 'mod_api': doc.get('mod_api'), 'files': rows}


def status(port_dir):
    mods = _mods(port_dir)
    disabled = []
    if (mods / 'disabled').is_dir():
        for folder in sorted(p for p in (mods / 'disabled').iterdir() if p.is_dir()):
            info = _describe(folder)
            if info['files']:
                disabled.append({'set': folder.name, **info})
    return {'active': _describe(mods), 'disabled': disabled}


def _move(source, destination, members):
    for rel in members:
        if (destination / rel).exists():
            raise FileExistsError(f'{destination / rel} existiert bereits. Es wurde nichts verschoben.')
    moved = []
    try:
        for rel in members:
            (destination / rel).parent.mkdir(parents=True, exist_ok=True)
            (source / rel).rename(destination / rel)
            moved.append(rel)
    except OSError:
        for rel in reversed(moved):      # Teilverschiebung zurücknehmen
            (destination / rel).rename(source / rel)
        raise
    return [rel.as_posix() for rel in moved]


def disable(port_dir):
    """Alle aktiven Datei-Mods abschalten. Liefert den Namen des abgelegten Satzes."""
    mods = _mods(port_dir)
    members = _members(mods)
    if not members:
        raise ValueError('Es sind keine PC-Port-Mods aktiv.')
    name = time.strftime('%Y%m%d_%H%M%S')
    target = mods / 'disabled' / name
    suffix = 1
    while target.exists():
        suffix += 1
        target = mods / 'disabled' / f'{name}_{suffix}'
    return {'set': target.name, 'moved': _move(mods, target, members)}


def enable(port_dir, set_name=None):
    """Einen deaktivierten Satz zurückholen (ohne Namen: den neuesten)."""
    mods = _mods(port_dir)
    sets = [row['set'] for row in status(port_dir)['disabled']]
    if not sets:
        raise ValueError('Es gibt keine deaktivierten PC-Port-Mods.')
    chosen = set_name or sets[-1]
    if chosen not in sets:
        raise ValueError('Dieser deaktivierte Mod-Satz existiert nicht.')
    if _members(mods):
        raise FileExistsError('Es sind bereits Mods aktiv. Bitte zuerst deaktivieren.')
    source = mods / 'disabled' / chosen
    moved = _move(source, mods, _members(source))
    for folder in sorted((p for p in source.rglob('*') if p.is_dir()), reverse=True):
        if not any(folder.iterdir()):
            folder.rmdir()
    if not any(source.iterdir()):
        source.rmdir()
    return {'set': chosen, 'moved': moved}
