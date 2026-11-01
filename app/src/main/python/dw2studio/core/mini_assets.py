"""Safe editable copies of OBJ, glTF, GLB and STL models and textures.

Embedded GLB/glTF images can be replaced without changing animations/skin data.
No function in this module writes to a Digimon World 2 game image.
"""
from pathlib import Path
import json
import shutil
from PIL import Image
from dw2studio.core.model_import import stage_model
from dw2studio.core import gltf_textures
from .png_source import verified_png,write_bytes_atomic,SIGNATURE

SUPPORTED = {'.gltf', '.glb', '.obj', '.stl'}
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}


def create_workcopy(source, root):
    source = Path(source).resolve()
    if not source.is_file() or source.suffix.lower() not in SUPPORTED:
        raise ValueError('Bitte OBJ, glTF, GLB oder STL wählen.')
    root = Path(root).resolve()
    target = root / (source.stem + '_projekt')
    if target.exists():
        i = 2
        while (root / (source.stem + f'_projekt_{i}')).exists():
            i += 1
        target = root / (source.stem + f'_projekt_{i}')
    if source.suffix.lower() in {'.obj', '.gltf', '.glb'}:
        path, _ = stage_model(source, target)
    else:
        target.mkdir(parents=True)
        path = target / source.name
        shutil.copy2(source, path)
    return path


def texture_slots(model):
    """Return (label, external file or None); embedded slots are editable too."""
    model = Path(model)
    if model.suffix.lower() in {'.gltf', '.glb'}:
        found = []
        doc = gltf_textures.document(model)
        for i, entry in enumerate(doc.get('images', [])):
            local = None
            uri = entry.get('uri')
            if uri and not uri.startswith('data:'):
                try:
                    local = gltf_textures._safe_uri(model, uri)
                except ValueError:
                    local = None
            title = f'Textur {i+1}: {entry.get("name") or (local.name if local else "eingebettet")} '
            found.append((title.strip(), local if local and local.is_file() else None))
        return found
    if model.suffix.lower() == '.obj':
        from dw2studio.core.model_import import obj_dependencies, _map_name, _resolve_obj_ref, _MTL_MAPS
        files, _ = obj_dependencies(model)
        base = model.parent.resolve()
        found = []
        for mtl in [f for f in files.values() if f.suffix.lower() == '.mtl']:
            for line in mtl.read_text(errors='replace').splitlines():
                tokens = line.strip().split()
                if len(tokens) < 2 or tokens[0].lower() not in _MTL_MAPS:
                    continue
                _, ref = _map_name(tokens)
                p = _resolve_obj_ref(mtl.parent, ref) if ref else None
                if p and p.suffix.lower() in IMAGE_EXT and p.is_relative_to(base) and p not in [x[1] for x in found]:
                    found.append((p.name, p))
        return found
    return []


def replace_texture(model, slot, png):
    """Replace a *project* image slot; preserve glTF/GLB animation references."""
    model, png = Path(model).resolve(), Path(png).resolve()
    slots = texture_slots(model)
    if not 0 <= slot < len(slots):
        raise IndexError('Textur-Slot nicht vorhanden')
    if slots[slot][1] is not None and slots[slot][1].resolve() == png:
        raise ValueError('Die Ersatzdatei ist bereits die aktive Textur.')
    payload,_=verified_png(png)
    if model.suffix.lower() in {'.gltf','.glb'}:return gltf_textures.replace_png(model,slot,png)
    target=slots[slot][1]
    if target is None:raise ValueError('Diese Textur kann nicht ersetzt werden.')
    if target.suffix.lower()=='.png':return write_bytes_atomic(target,payload)
    # A PNG replacing a JPEG remains PNG. Update portable MTL references;
    # never convert the new texture back to lossy JPEG.
    from .model_import import obj_dependencies,_map_name,_resolve_obj_ref,_MTL_MAPS
    import os
    replacement=target.with_name(target.stem+'_ersetzt.png');updates=[]
    files,_=obj_dependencies(model)
    for mtl in (p for p in files.values() if p.suffix.lower()=='.mtl'):
        lines=[];changed=False
        for line in mtl.read_text(encoding='utf-8',errors='replace').splitlines():
            tokens=line.strip().split()
            if tokens and tokens[0].lower() in _MTL_MAPS:
                start,ref=_map_name(tokens)
                resolved=_resolve_obj_ref(mtl.parent,ref) if ref else None
                if resolved==target:
                    relative=os.path.relpath(replacement,mtl.parent).replace('\\','/')
                    line=' '.join(tokens[:start]+[relative]);changed=True
            lines.append(line)
        if changed:updates.append((mtl,'\n'.join(lines)+'\n'))
    if not updates:raise ValueError('MTL-Texturverweis konnte nicht eindeutig aktualisiert werden.')
    write_bytes_atomic(replacement,payload)
    for mtl,text in updates:write_bytes_atomic(mtl,text.encode('utf-8'))
    return replacement


def export_texture(model, slot, target):
    model = Path(model)
    slots = texture_slots(model)
    if not 0 <= slot < len(slots):
        raise IndexError('Bitte eine vorhandene Textur auswählen.')
    if model.suffix.lower() in {'.gltf', '.glb'}:
        return gltf_textures.export_png(model, slot, target)
    local = slots[slot][1]
    if local is None:
        raise ValueError('Diese Textur kann nicht exportiert werden.')
    payload=local.read_bytes()
    if payload.startswith(SIGNATURE):Path(target).write_bytes(payload)
    else:
        with Image.open(local) as img:img.convert('RGBA').save(target,'PNG')
    return Path(target)
