"""3D exports with animation-preserving glTF <-> GLB conversion.

OBJ/STL output is an evaluated static mesh. glTF/GLB conversion carries mesh
buffers, skins, animation clips and image data without resampling animations.
"""
from __future__ import annotations
from pathlib import Path
import copy
import io
import json
import shutil
from urllib.parse import quote
from PIL import Image
from dw2studio.core import gltf_textures


def supported_export_filters():
    return ('glTF (Animationen erhalten) (*.gltf);;'
            'GLB (Animationen erhalten) (*.glb);;'
            'OBJ (statisch, ohne Animationen) (*.obj)')


def copy_gltf_with_dependencies(source, target):
    """Copy a glTF with its buffers/images.

    Companion files get the target's name as prefix (``<ziel>_<datei>``) and the
    JSON is rewritten accordingly. So an export can never overwrite another
    model's ``buffer.bin`` in the same folder, and exporting twice to the same
    name simply refreshes our own companion files.
    """
    source, target = Path(source).resolve(), Path(target).resolve()
    doc = json.loads(source.read_text(encoding='utf-8'))
    target.parent.mkdir(parents=True, exist_ok=True)
    used = set()
    copies = []
    for entry in doc.get('buffers', []) + doc.get('images', []):
        uri = entry.get('uri')
        if not uri or uri.startswith('data:'):
            continue
        src = gltf_textures._safe_uri(source, uri)
        if not src.is_file():
            raise FileNotFoundError(src)
        name = f'{target.stem}_{src.name}'
        i = 2
        while name in used:
            name = f'{target.stem}_{i}_{src.name}'
            i += 1
        used.add(name)
        dst = target.parent / name
        if dst.resolve() in (source, target):
            raise ValueError('Ungültige Begleitdatei beim Export')
        entry['uri'] = quote(name)
        copies.append((src, dst))
    for src, dst in copies:
        if src != dst.resolve():
            shutil.copy2(src, dst)
    pending = target.with_name(target.name + '.pending')
    try:
        pending.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding='utf-8')
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return target


def glb_to_gltf(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    doc, binary, _ = gltf_textures.read_glb(source)
    doc = copy.deepcopy(doc)
    if binary:
        if len(doc.get('buffers', [])) != 1:
            raise ValueError('GLB enthält keine eindeutige Binärpuffer-Zuordnung')
        buf_name = f'{target.stem}_model.bin'
        buf_path = target.parent / buf_name
        if buf_path == source or buf_path == target:
            raise ValueError('Ungültige Binärpuffer-Datei')
        doc['buffers'][0]['uri'] = quote(buf_name)
        # JSON byteLength is allowed to exclude padding at the end of GLB BIN.
        buf_path.parent.mkdir(parents=True, exist_ok=True)
        buf_path.write_bytes(binary)
    target.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding='utf-8')
    return target


def gltf_to_glb(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    doc = copy.deepcopy(json.loads(source.read_text(encoding='utf-8')))
    output = bytearray()
    starts = []
    # Consolidate glTF buffers; only bufferViews address them in glTF 2.0.
    for item in doc.get('buffers', []):
        if not 'uri' in item:
            raise ValueError('glTF-Buffer ohne URI kann nicht eingebettet werden')
        raw = gltf_textures._uri_bytes(source, item['uri'])
        if len(raw) < item.get('byteLength', 0):
            raise ValueError('glTF-Buffer ist kürzer als die angegebene Länge')
        output.extend(b'\0' * (-len(output) % 4))
        starts.append(len(output))
        output.extend(raw)
    for view in doc.get('bufferViews', []):
        index = view.get('buffer', 0)
        if not 0 <= index < len(starts):
            raise ValueError('Fehlerhafter Bufferindex in glTF')
        view['byteOffset'] = view.get('byteOffset', 0) + starts[index]
        view['buffer'] = 0
    for img in doc.get('images', []):
        uri = img.pop('uri', None)
        if uri is None:
            continue
        raw = gltf_textures._uri_bytes(source, uri)
        try:
            if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                with Image.open(io.BytesIO(raw)) as im:
                    memory=io.BytesIO();im.convert('RGBA').save(memory,format='PNG');raw=memory.getvalue()
        except Exception as exc:
            raise ValueError('Eingebettete glTF-Textur konnte nicht gelesen werden') from exc
        output.extend(b'\0' * (-len(output) % 4))
        start = len(output)
        output.extend(raw)
        view_id = len(doc.setdefault('bufferViews', []))
        doc['bufferViews'].append({'buffer': 0, 'byteOffset': start, 'byteLength': len(raw)})
        img['bufferView'] = view_id
        img['mimeType'] = 'image/png'
    doc['buffers'] = [{'byteLength': len(output)}] if output or doc.get('buffers') else []
    # The GLB spec requires one binary buffer, with padding handled by writer.
    gltf_textures.write_glb(target, doc, bytes(output), [(b'JSON', b'{}'), (b'BIN\0', b'')])
    return target


def _obj_copy(source, target):
    """Keep Wavefront MTL and local texture references with the OBJ."""
    from dw2studio.core.model_import import _obj_refs, _local_dependency
    source, target = Path(source).resolve(), Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    for uri in _obj_refs(source):
        src = _local_dependency(source.parent, uri)
        dst = (target.parent / uri).resolve()
        if not dst.is_relative_to(target.parent):
            raise ValueError('Unsichere OBJ-Abhängigkeit')
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src != dst:
            shutil.copy2(src, dst)
    if source != target:
        shutil.copy2(source, target)
    return target


def export_model(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise ValueError('Original-/Projektdatei nicht überschreiben')
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = target.suffix.lower()
    origin = source.suffix.lower()
    if suffix == '.gltf':
        if origin == '.gltf':
            return copy_gltf_with_dependencies(source, target)
        if origin == '.glb':
            return glb_to_gltf(source, target)
        if origin in {'.obj', '.stl'}:
            import tempfile
            import trimesh
            scene = trimesh.load(str(source), force='scene', process=False)
            with tempfile.TemporaryDirectory(prefix='dw2_export_') as temp:
                temporary = Path(temp) / (target.stem + '.glb')
                temporary.write_bytes(scene.export(file_type='glb'))
                return glb_to_gltf(temporary, target)
        raise ValueError('Unbekanntes 3D-Format')
    if suffix == '.glb':
        if origin == '.glb':
            shutil.copy2(source, target)
            return target
        if origin == '.gltf':
            return gltf_to_glb(source, target)
        if origin in {'.obj', '.stl'}:
            import trimesh
            scene = trimesh.load(str(source), force='scene', process=False)
            target.write_bytes(scene.export(file_type='glb'))
            return target
        raise ValueError('Unbekanntes 3D-Format')
    if suffix == '.obj':
        if origin == '.obj':
            return _obj_copy(source, target)
        if origin == '.stl':
            import trimesh
            mesh = trimesh.load(str(source), force='mesh', process=False)
            target.write_text(mesh.export(file_type='obj'), encoding='utf-8')
            return target
        from dw2studio.core.posed_export import export_evaluated_obj
        return export_evaluated_obj(source, target)
    raise ValueError('Erlaubte Exportformate: .gltf, .glb, .obj')
