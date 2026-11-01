"""Collapse VTK OBJ material textures into one RGBA atlas and remap OBJ UVs.

OBJ/MTL has no embedded texture support. Result: OBJ + MTL + one PNG.
"""
from pathlib import Path
import math
import hashlib
from PIL import Image


def _materials(path):
    materials = {}
    current = None
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        parts = line.strip().split(maxsplit=1)
        if not parts:
            continue
        if parts[0] == 'newmtl' and len(parts) > 1:
            current = parts[1]
            materials[current] = None
        elif parts[0].lower() == 'map_kd' and current and len(parts) > 1:
            # VTK writes simple texture names; don't silently misparse MTL options.
            value = parts[1].strip().strip('"')
            if value.startswith('-'):
                raise ValueError('MTL-Texturoptionen werden für Atlas-Export nicht unterstützt: ' + value)
            materials[current] = value
    return materials


def collapse_obj_textures(obj_path, mtl_path, texture_directory, output_stem):
    """Return (OBJ text, MTL text, atlas image); source files remain untouched."""
    obj_path, mtl_path = Path(obj_path), Path(mtl_path)
    directory = Path(texture_directory).resolve()
    materials = _materials(mtl_path)
    if not materials:
        raise ValueError('Keine Materialien im OBJ-Export vorhanden.')
    # VTK can export the same source atlas under many different filenames.
    # Deduplicate by actual decoded RGBA pixels (including dimensions), not path.
    # Different palettes, alpha or pixel content must remain separate tiles.
    images = {}
    canonical_by_digest = {}
    canonical_for_path = {}
    for name, ref in materials.items():
        if ref is None:
            raise ValueError('Material ohne diffuse Textur: ' + name)
        file = (directory / ref).resolve()
        if not file.is_relative_to(directory) or not file.is_file():
            raise FileNotFoundError('MTL-Textur fehlt oder liegt außerhalb: ' + ref)
        if file in canonical_for_path:
            continue
        with Image.open(file) as img:
            rgba = img.convert('RGBA')
        digest = hashlib.sha256(
            rgba.width.to_bytes(8, 'big') + rgba.height.to_bytes(8, 'big') + rgba.tobytes()
        ).digest()
        canonical = canonical_by_digest.get(digest)
        if canonical is None:
            canonical_by_digest[digest] = file
            images[file] = rgba
            canonical = file
        canonical_for_path[file] = canonical
    if not images:
        raise ValueError('Keine Texturen für den Atlas gefunden.')
    # Power-of-two-like tiled layout without resizing: preserves original pixel quality.
    unique = list(images)
    cols = math.ceil(math.sqrt(len(unique)))
    rows = math.ceil(len(unique) / cols)
    padding = 2
    tile_w = max(images[p].width for p in unique) + 2 * padding
    tile_h = max(images[p].height for p in unique) + 2 * padding
    width, height = cols * tile_w, rows * tile_h
    atlas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    rectangles = {}
    for i, path in enumerate(unique):
        img = images[path]
        x = (i % cols) * tile_w + padding
        y = (i // cols) * tile_h + padding
        atlas.paste(img, (x, y))
        # Edge padding to avoid texture bleeding at tile borders.
        atlas.paste(img.crop((0, 0, 1, img.height)).resize((padding, img.height)), (x-padding, y))
        atlas.paste(img.crop((img.width-1, 0, img.width, img.height)).resize((padding, img.height)), (x+img.width, y))
        atlas.paste(img.crop((0, 0, img.width, 1)).resize((img.width, padding)), (x, y-padding))
        atlas.paste(img.crop((0, img.height-1, img.width, img.height)).resize((img.width, padding)), (x, y+img.height))
        rectangles[path] = (x, y, img.width, img.height)
    regions = {name: rectangles[canonical_for_path[(directory / ref).resolve()]] for name, ref in materials.items()}
    lines = obj_path.read_text(encoding='utf-8', errors='replace').splitlines()
    vt = [None]
    for line in lines:
        if line.startswith('vt '):
            parts = line.split()
            vt.append((float(parts[1]), float(parts[2])))
    # Reuse OBJ positions/normals; allocate new UVs for each material + old UV pair.
    remapped = {}
    new_vt = []
    result = []
    active = None
    for line in lines:
        if line.startswith('mtllib '):
            result.append('mtllib ' + output_stem + '.mtl')
        elif line.startswith('vt '):
            continue
        elif line.startswith('usemtl '):
            active = line[7:].strip()
            if active not in regions:
                raise ValueError('Unbekanntes OBJ-Material: ' + active)
            result.append('usemtl DW2_Atlas')
        elif line.startswith('f '):
            if active is None:
                raise ValueError('OBJ-Face ohne aktives Material.')
            out_face = []
            for vertex in line[2:].split():
                parts = vertex.split('/')
                if len(parts) < 2 or not parts[1]:
                    raise ValueError('OBJ-Face ohne UV-Koordinaten.')
                old = int(parts[1])
                if old < 0:
                    old = len(vt) + old
                if old <= 0 or old >= len(vt):
                    raise ValueError('Ungültiger OBJ-UV-Index: ' + str(old))
                key = (active, old)
                if key not in remapped:
                    u, v = vt[old]
                    x, y, w, h = regions[active]
                    # OBJ V=0 at bottom; PIL atlas Y=0 at top.
                    nu = (x + u * w) / width
                    nv = 1.0 - (y + (1.0 - v) * h) / height
                    new_vt.append(f'vt {nu:.10f} {nv:.10f}')
                    remapped[key] = len(new_vt)
                parts[1] = str(remapped[key])
                out_face.append('/'.join(parts))
            result.append('f ' + ' '.join(out_face))
        else:
            result.append(line)
    # UVs can be declared anywhere before faces in OBJ; insert before first face.
    index = next((i for i, line in enumerate(result) if line.startswith('f ')), len(result))
    result[index:index] = new_vt
    mtl_text = 'newmtl DW2_Atlas\nKa 1 1 1\nKd 1 1 1\nKs 0 0 0\nd 1\nillum 1\nmap_Kd ' + output_stem + '_texture.png\n'
    return '\n'.join(result) + '\n', mtl_text, atlas
