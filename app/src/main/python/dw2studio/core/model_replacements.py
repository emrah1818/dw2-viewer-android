"""Per-Digimon replacement registry: never leak MetalGreymon into other Digimon."""
from __future__ import annotations

import json
from pathlib import Path
from dw2studio.core.mini_assets import create_workcopy


def _manifest(root):
    return Path(root) / 'replacement.json'


def active_replacement(root):
    root = Path(root).resolve()
    mf = _manifest(root)
    if not mf.is_file():
        return None
    try:
        record = json.loads(mf.read_text(encoding='utf-8'))
        name = record['model']
        if not isinstance(name, str):
            return None
        model = (root / name).resolve()
        if model.is_relative_to(root) and model.is_file() and model.suffix.lower() in ('.gltf', '.glb', '.obj', '.stl'):
            return model
    except (ValueError, KeyError, OSError, TypeError):
        pass
    return None


def set_replacement(source, root):
    root = Path(root).resolve()
    replacement = create_workcopy(source, root)
    relative = replacement.relative_to(root)
    mf = _manifest(root)
    mf.parent.mkdir(parents=True, exist_ok=True)
    pending = mf.with_name('replacement.json.pending')
    try:
        pending.write_text(json.dumps({'model': relative.as_posix(), 'native_rom_patch': False}, indent=2), encoding='utf-8')
        pending.replace(mf)
    finally:
        pending.unlink(missing_ok=True)
    return replacement


def clear_replacement(root):
    """Remove only the mapping; preserve the project's editable model copies."""
    _manifest(root).unlink(missing_ok=True)


def publish_replacement(model,root):
    root=Path(root).resolve();model=Path(model).resolve()
    if not model.is_file() or not model.is_relative_to(root):raise ValueError('Modell liegt nicht im zugehörigen Viewer-Projekt.')
    mf=_manifest(root);pending=mf.with_name('replacement.json.pending')
    try:
        pending.write_text(json.dumps({'model':model.relative_to(root).as_posix(),'native_rom_patch':False},indent=2),encoding='utf-8');pending.replace(mf)
    finally:pending.unlink(missing_ok=True)
    return model
