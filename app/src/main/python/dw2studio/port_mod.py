"""Conservative export of staged DW2 image edits to PC-port Mods/files.

Only exact-length replacements matching verified original PAK bytes are exported.
No PAK, SLUS or original image is modified. Exports are create-only.
"""
import hashlib
import json
from pathlib import Path
from .pak import PakFile


def plan(session, pak, *, allow_resize=False):
    if not isinstance(pak, PakFile):
        raise TypeError('pak must be a PakFile')
    session._check_source()
    lba_map = {}
    for entry in pak.entries:
        lba_map.setdefault(entry.lba, []).append(entry)
    changes = []
    used_ids = set()
    for edit in session.edits.values():
        if edit.relocate and not allow_resize:
            raise ValueError(f'{edit.path}: relocated edits are not supported by the overlay')
        candidates = [e for e in lba_map.get(edit.lba, ()) if e.size == len(edit.original)]
        matches = [e for e in candidates if hashlib.sha256(edit.original).digest() == e.sha256]
        if len(matches) != 1:
            raise ValueError(f'{edit.path}: no unique matching original PAK entry (LBA/size/hash)')
        entry = matches[0]
        if entry.format != 0:
            raise ValueError(f'{edit.path}: audio/movie entries cannot be replaced')
        pak.read(entry.id)  # Verify actual payload, not only the index hash.
        if len(edit.replacement) != entry.size and not allow_resize:
            raise ValueError(f'{edit.path}: replacement must have exactly {entry.size} bytes')
        if entry.id in used_ids:
            raise ValueError(f'PAK entry {entry.id} is staged more than once')
        used_ids.add(entry.id)
        if not edit.replacement or len(edit.replacement) > 2*1024*1024:
            raise ValueError('Replacement exceeds the API 2 asset limit')
        changes.append({'id': entry.id, 'path': edit.path, 'lba': entry.lba,
                        'replacement_size': len(edit.replacement),
                        'size': entry.size, 'original_sha256': entry.sha256.hex(),
                        'replacement_sha256': hashlib.sha256(edit.replacement).hexdigest(),
                        'label': edit.label, 'payload': edit.replacement})
    return changes


def export(session, pak, port_dir, *, mod_name='DW2 Mod Studio'):
    from .pak_workspace import PakSession
    extended = any(e.relocate or len(e.replacement) != len(e.original) for e in session.edits.values())
    if extended and not isinstance(session, PakSession):
        raise ValueError('Vergrößerte PC-Port-Dateien benötigen eine PAK-Sitzung.')
    if extended:
        capabilities = Path(port_dir) / 'dw2_mod_api.json'
        try:
            api = json.loads(capabilities.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ValueError('Für größere Dateien den mit dem Viewer gelieferten PC-Port mit Mod-Schnittstelle 2 (Overlay-API 2) verwenden (dw2_mod_api.json fehlt).') from exc
        if api.get('mod_api') != 2:
            raise ValueError('PC-Port unterstützt Overlay-API 2 nicht.')
    changes = plan(session, pak, allow_resize=extended)
    if not changes:
        raise ValueError('No staged edits to export')
    port_dir = Path(port_dir)
    mods = port_dir / 'Mods'
    files = mods / 'files'
    manifest = mods / 'dw2studio_mod.json'
    targets = [files / f"{change['id']:04X}.bin" for change in changes]
    extra = session.active_hd_files() if hasattr(session,'active_hd_files') else {}
    extra_targets = [(mods/Path(name),data) for name,data in extra.items()]
    if any(not target.resolve().is_relative_to(mods.resolve()) or target.exists() for target,data in extra_targets):
        raise FileExistsError('HD-Texturziel existiert bereits oder verlässt Mods.')
    existing_ids = set()
    if files.exists():
        for item in files.iterdir():
            if item.suffix.lower() == '.bin':
                try:
                    existing_ids.add(int(item.stem, 16))
                except ValueError:
                    pass
    if manifest.exists() or any(change['id'] in existing_ids for change in changes):
        raise FileExistsError('A mod export already exists; remove or back it up manually')
    files.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        for change, target in zip(changes, targets):
            with target.open('xb') as stream:
                stream.write(change['payload'])
            written.append(target)
        for target,data in extra_targets:
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(data)
            written.append(target)
        info = {'format': 'DW2 Mod Studio overlay 2' if extended else 'DW2 Mod Studio overlay 1', 'name': mod_name,
                'mod_api': 2 if extended else 1, 'textures': [str(t.relative_to(mods)) for t,d in extra_targets],
                'pak_name': pak.path.name, 'files': [
                    {k: v for k, v in change.items() if k != 'payload'} for change in changes]}
        with manifest.open('x', encoding='utf-8') as stream:
            json.dump(info, stream, indent=2, ensure_ascii=False)
        written.append(manifest)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return {'manifest': str(manifest), 'count': len(changes), 'files': [str(t) for t in targets]}
