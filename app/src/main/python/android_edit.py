"""Textur- und 3D-Bearbeitung für die Android-App – gleiche Kernroutinen wie Windows v4.0.

PNG-Import: dieselbe Kette wie main.import_native_png (read_png → native_scale →
reduce_for_native → infer_full_eye_atlas → preview_native_texture → replace_tim),
Palettenmodus standardmäßig 'v31' (golden-getestet gegen die echte v3.1).
3D: Austausch-Export/-Import wie main.replace_digimon (digimon_transfer),
Rig-Import fremder Modelle wie main.import_rigged (RigProject), Knochenzuordnung
je Gruppe statt Flächen-Malen.
"""
from pathlib import Path
import re
import shutil
import uuid

import numpy as np

import android_api as api

PENDING = {}   # token -> vorbereitete Aktion (wird erst bei apply vorgemerkt)
PALETTE_MODES = ('v31', 'protect', 'exact')


def _native(identifier):
    from dw2studio.core.native_rom_bridge import native_model_entry
    from dw2studio.core.native_tim_patch import regions
    s = api._need_session()
    s._check_source()
    entry = native_model_entry(S().entries, api._find(identifier))
    data = s.current(entry)
    found = regions(data)
    if not found:
        raise ValueError('Kein nativer TIM-Block erkannt.')
    return entry, data, found[0]


def S():
    return api.S


def _work(*parts):
    folder = api.CACHE.joinpath('work', *parts)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _url(path):
    return Path(path).relative_to(api.CACHE).as_posix()


def _native_image(data, region, eyes):
    """Wie main.native_image: Atlas der echten Paletten, optional mit allen Augenposen."""
    from dw2studio.assets.tim import TIM
    from dw2studio.core.dw2_native_atlas import decode_native_atlas, is_native_dw2_tim
    from dw2studio.core.dw2_eyes import eye_layout
    tim = TIM(data[region.offset:])
    if not is_native_dw2_tim(tim):
        return tim.to_image()
    return decode_native_atlas(data, region.offset, include_eye_frames=bool(eyes and eye_layout(data)))


# --------------------------------------------------------------------------- Texturen
def png_export(identifier, eyes=True, factor=1):
    """Native PNG-Vorlage (128×256, Arbeitsfaktor 1–4) wie „Native PNG-Vorlage exportieren“."""
    from dw2studio.core.texture_resolution import export_template
    from dw2studio.core.dw2_eyes import eye_layout
    entry, data, region = _native(identifier)
    image = _native_image(data, region, eyes)
    c = api._find(identifier)
    suffix = '_Augen' if eyes and eye_layout(data) else '_Native'
    folder = api._exports()
    target = folder / api._unique_name(folder, f'{c.id:03d}{c.code}{suffix}' + (f'_{factor}x' if factor != 1 else '') + '.png')
    export_template(image, target, int(factor))
    return {'path': str(target), 'name': target.name, 'eyes': bool(eye_layout(data))}


def png_preview(identifier, png, palette_mode='v31', eyes_only=False, resize='BOX'):
    """Wie main.import_native_png + _confirm_native_colors: kodieren, zurücklesen, zeigen – noch nichts vormerken."""
    from dw2studio.core.texture_resolution import read_png, native_scale, reduce_for_native
    from dw2studio.core.dw2_eyes import eye_layout, infer_full_eye_atlas
    from dw2studio.core.dw2_native_atlas import decode_native_atlas, is_native_dw2_tim
    from dw2studio.core.dw2_palette_recolor import preview_native_texture, native_edit_report
    from dw2studio.assets.tim import TIM
    if palette_mode not in PALETTE_MODES:
        raise ValueError('Unbekannter Palettenmodus.')
    entry, data, region = _native(identifier)
    image = read_png(png)
    factor = native_scale(image.size, (region.width, region.height))
    incoming = reduce_for_native(image, (region.width, region.height), resize)
    layout = eye_layout(data)
    eye_frames = bool(layout and (eyes_only or infer_full_eye_atlas(data, incoming)))
    if eyes_only:
        if layout is None:
            raise ValueError('Keine sicheren Augenbereiche für dieses Modell.')
        masked = _native_image(data, region, True)
        for x, y, w, h in set(layout.sources + (layout.target,)):
            masked.paste(incoming.crop((x, y, x + w, y + h)), (x, y))
        incoming = masked
    token = uuid.uuid4().hex
    folder = _work('png', token)
    prepared = folder / 'prepared.png'
    incoming.save(prepared)
    tim = TIM(data[region.offset:])
    result = {'token': token, 'factor': factor, 'eye_frames': eye_frames, 'mode': palette_mode,
              'size': list(image.size), 'native': [region.width, region.height]}
    if is_native_dw2_tim(tim):
        skipped = native_edit_report(data, region.offset, incoming, eye_frames=eye_frames)
        native_bytes, encoded, quality = preview_native_texture(
            data, region.offset, incoming, recolor=True, eye_frames=eye_frames, palette_mode=palette_mode)
        if native_bytes == tim.data[:tim.end]:
            raise ValueError('Die PNG enthält keine wirksamen Änderungen an den Körper- oder Augenflächen. '
                             'Änderungen außerhalb dieser Flächen bzw. in den unteren 32 Palette-Zeilen '
                             'werden aus Sicherheitsgründen nicht ins Spiel geschrieben.')
        original = decode_native_atlas(data, region.offset, include_eye_frames=eye_frames)
        for name, picture in (('original', original), ('desired', incoming), ('result', encoded)):
            picture.save(folder / f'{name}.png')
        result.update(quality={k: getattr(quality, k) for k in quality.__dataclass_fields__},
                      reserved_ignored=skipped.palette_storage_ignored, unmapped_ignored=skipped.unmapped_texture_ignored,
                      images={n: _url(folder / f'{n}.png') for n in ('original', 'desired', 'result')},
                      warn=bool(palette_mode == 'v31' and (quality.edited_chroma_lost or quality.edited_mean_rgb_error > 18
                                                           or quality.edited_bad_pixel_fraction > .10)))
    else:
        result.update(quality=None, images={'desired': _url(prepared)})
    PENDING[token] = {'kind': 'png', 'id': identifier, 'entry': entry, 'data': data, 'png': prepared,
                      'eye_frames': eye_frames, 'mode': palette_mode,
                      'label': 'Augen vollständig ersetzt' if eyes_only else 'Native PNG inkl. erkannter Augen'}
    return result


def png_apply(token):
    from dw2studio.core.native_tim_patch import replace_tim
    job = PENDING.pop(token, None)
    if not job or job['kind'] != 'png':
        raise ValueError('Vorschau abgelaufen. Bitte PNG erneut wählen.')
    entry, data, region = _native(job['id'])
    if data != job['data']:
        raise ValueError('Das Modell wurde inzwischen geändert. Bitte PNG erneut wählen.')
    changed, _ = replace_tim(data, job['png'], 0, recolor=True, eye_frames=job['eye_frames'], palette_mode=job['mode'])
    job['png'].unlink(missing_ok=True)
    if changed == data:
        return {'changed': False}
    S().session.stage(entry, changed, job['label'])
    return {'changed': True}


def cancel(token):
    job = PENDING.pop(token, None)
    if job and job.get('folder'):
        shutil.rmtree(job['folder'], ignore_errors=True)
    elif job and job.get('png'):
        shutil.rmtree(job['png'].parent, ignore_errors=True)
    return True


# --------------------------------------------------------------------------- 3D-Export
def model_export(identifier, fmt='glb', name=None):
    """GLB/glTF mit Geometrie, Paletten-Texturen, Knochen, A–K-Animationen und eingebetteten Spieldaten."""
    from dw2studio.core.digimon_transfer import make_payload, role, export_exchange
    if fmt not in ('glb', 'gltf'):
        raise ValueError('Unterstützt: GLB oder glTF.')
    c = api._find(identifier)
    info = api.prepare_model(identifier)
    files = {}
    for entry in _family(c):
        r = role(entry)
        data = S().session.current(entry)
        if r in files and files[r] != data:
            raise ValueError('Mehrdeutige Quell-Dateirolle: ' + r)
        files[r] = data
    folder = api._exports()
    stem = re.sub(r'\.(gltf|glb)$', '', name or f'{c.id:03d}{c.code}_{c.name}', flags=re.I)
    target = folder / api._unique_name(folder, stem + '.' + fmt)
    try:
        payload = make_payload(c, files)
    except ValueError:
        payload = None   # z. B. Animationen, die der strenge Schreibleser ablehnt: Anzeige-Export ohne Spieldaten
    if payload is None:
        from dw2studio.core.model_export import export_model
        export_model(api.CACHE / info['url'], target)
    else:
        export_exchange(api.CACHE / info['url'], target, payload)
    return {'path': str(target), 'name': target.name, 'native': payload is not None}


def _family(c):
    from dw2studio.core.auto_models import selected_model_entries
    unique = {}
    for entry in selected_model_entries(S().entries, c):
        unique[(entry.lba, entry.size, Path(entry.path.replace('\\', '/')).name.upper())] = entry
    return list(unique.values())


# --------------------------------------------------------------------------- 3D-Import
def inspect_3d(path, identifier=None):
    """Datei prüfen: Austauschmodell (Digimon ersetzen), fremdes Modell (Knochenzuordnung/Ansicht) oder native BIN."""
    path = Path(path)
    suffix = path.suffix.lower()
    token = uuid.uuid4().hex
    folder = _work('import', token)
    copy = folder / ('model' + suffix)
    shutil.copy2(path, copy)
    job = {'kind': 'model', 'path': copy, 'folder': folder, 'suffix': suffix, 'name': path.name}
    result = {'token': token, 'name': path.name, 'view': _url(copy) if suffix in ('.gltf', '.glb', '.obj') else None,
              'format': suffix.lstrip('.')}
    if suffix == '.bin':
        result['kind'] = 'native_bin'
    elif suffix in ('.gltf', '.glb'):
        from dw2studio.core.digimon_transfer import read_transfer
        try:
            transfer = read_transfer(copy)
            job['transfer'] = transfer
            result.update(kind='transfer', source=transfer.source)
        except ValueError as exc:
            result.update(kind='foreign', transfer_note=str(exc))
    elif suffix == '.obj':
        result['kind'] = 'foreign'
    else:
        raise ValueError('Unterstützt: GLB, glTF, OBJ oder native Modell-BIN.')
    PENDING[token] = job
    if identifier is not None and result['kind'] == 'transfer':
        result['plan'] = transfer_plan(token, identifier)
    return result


def _job(token):
    job = PENDING.get(token)
    if not job or job.get('kind') != 'model':
        raise ValueError('Import abgelaufen. Bitte Datei erneut wählen.')
    return job


def transfer_plan(token, identifier):
    from dw2studio.core.digimon_transfer import plan_transfer
    job = _job(token)
    if 'transfer' not in job:
        raise ValueError('Diese Datei enthält keine DW2-Austauschdaten.')
    plan = plan_transfer(job['transfer'], _family(api._find(identifier)), S().session)
    job['plan'] = (identifier, plan)
    return {'rows': [list(r) for r in plan.rows], 'errors': list(plan.errors),
            'source_bones': plan.source_bones, 'target_bones': plan.target_bones,
            'source': plan.transfer.source}


def transfer_apply(token, identifier):
    from dw2studio.core.digimon_transfer import apply_plan
    job = _job(token)
    transfer_plan(token, identifier)
    _, plan = job['plan']
    count = apply_plan(plan, S().session)
    return {'files': count}


def bin_apply(token, identifier):
    from dw2studio.core.native_rom_bridge import native_model_entry
    from dw2studio.core.native_model import validate_replacement
    job = _job(token)
    entry = native_model_entry(S().entries, api._find(identifier))
    data = S().session.current(entry)
    raw = job['path'].read_bytes()
    if len(raw) != len(data):
        raise ValueError(f'Native BIN muss exakt {len(data)} Bytes haben.')
    S().session.stage(entry, validate_replacement(data, raw), 'Native Modell-BIN')
    return {'files': 1}


def _rig_project(job, identifier):
    from dw2studio.core.native_rom_bridge import native_model_entry
    from dw2studio.core.rig_import import RigProject, ObjMesh
    from dw2studio.core.gltf_mesh import GltfMesh
    c = api._find(identifier)
    if job['suffix'] in ('.gltf', '.glb'):
        source = GltfMesh(job['path'])
        obj = source.write_obj(job['folder'] / 'mesh.obj')
        job['gltf'] = source
    else:
        obj = job['path']
        job['gltf'] = None
    entry = native_model_entry(S().entries, c)
    companions = {}
    for e in _family(c):
        if (e.path, e.lba) == (entry.path, entry.lba):
            continue
        companions[Path(e.path.replace('\\', '/')).name] = (e, S().session.current(e))
    project = RigProject(ObjMesh(obj), S().session.current(entry), {n: d for n, (e, d) in companions.items()})
    return project, entry, companions


def _bone_points(project):
    """Weltpositionen aller Original-Vertices je Knochen in der Referenzpose (wie RigImportDialog.fit_model)."""
    import struct
    from dw2studio.core.rig_animation import D
    world = project.binding_world()
    per_bone = []
    for i, part in enumerate(project.model.parts):
        v = np.array([struct.unpack_from('<hhh', project.original, part.vertices + 6 + j * 6)
                      for j in range(part.vertex_count)], dtype=float) @ D
        per_bone.append((np.c_[v, np.ones(len(v))] @ world[i].T)[:, :3])
    return per_bone


def _fit(project):
    """Automatisch einpassen – identisch zu RigImportDialog.fit_model."""
    points = np.vstack(_bone_points(project))
    source = project.mesh.vertices
    extent = np.ptp(source, axis=0)
    axis = int(np.argmax(np.ptp(points, axis=0)))
    scale = float(np.ptp(points, axis=0)[axis] / max(extent[axis], 1e-6))
    project.scale = scale
    project.rotation = [0., 0., 0.]
    project.offset = ((points.min(0) + points.max(0)) / 2 - (source.min(0) + source.max(0)) / 2 * scale).tolist()


def _suggest(project):
    """Gruppe → Knochen: Namen bone_/mesh_/geometry_N, sonst nächster Knochen (Mittelpunkt)."""
    faces = project.mesh.faces
    groups = list(dict.fromkeys(f.group for f in faces))
    centers = np.array([pts.mean(0) if len(pts) else np.zeros(3) for pts in _bone_points(project)])
    vertices = project.source_vertices()
    result = []
    for g in groups:
        ids = [i for i, f in enumerate(faces) if f.group == g]
        m = re.search(r'(?:bone|mesh|geometry)_(\d+)', g)
        if m and int(m.group(1)) < project.model.bone_count:
            bone, how = int(m.group(1)), 'Name'
        else:
            center = vertices[np.unique(project.mesh.face_indices[ids].ravel())].mean(0)
            bone, how = int(np.argmin(np.linalg.norm(centers - center, axis=1))), 'nächster Knochen'
        result.append({'group': g, 'faces': len(ids), 'bone': bone, 'how': how})
    return result


def rig_prepare(token, identifier):
    job = _job(token)
    project, _, _ = _rig_project(job, identifier)
    _fit(project)
    suggestion = _suggest(project)
    begin = min(min(p.vertices, p.normals) for p in project.model.parts)
    gltf = job.get('gltf')
    return {'groups': suggestion, 'bones': project.model.bone_count, 'faces': len(project.mesh.faces),
            'parents': project.parents, 'budget': project.model.tim_start - begin,
            'minimum': 16 * len(project.mesh.faces) + 40 * project.model.bone_count,
            'scale': project.scale, 'has_texture': bool(gltf and gltf.main_image() is not None)}


def rig_apply(token, identifier, mapping, use_texture=True, palette_mode='v31', scale_factor=1.0):
    """Gruppen den Knochen zuordnen, natives Modell bauen (Formatprüfung) und vormerken."""
    from PIL import Image
    import io
    job = _job(token)
    project, entry, companions = _rig_project(job, identifier)
    _fit(project)
    if scale_factor and float(scale_factor) != 1.0:
        f = float(scale_factor)
        center = np.asarray(project.offset) + (project.mesh.vertices.min(0) + project.mesh.vertices.max(0)) / 2 * project.scale
        project.scale *= f
        project.offset = (center - (project.mesh.vertices.min(0) + project.mesh.vertices.max(0)) / 2 * project.scale).tolist()
    project.uv_mode = 'fit224'
    for i, face in enumerate(project.mesh.faces):
        bone = mapping.get(face.group)
        if bone is None:
            raise ValueError(f'Gruppe {face.group} ist keinem Knochen zugeordnet.')
        if not 0 <= int(bone) < project.model.bone_count:
            raise ValueError('Ungültiger Knochen.')
        project.assignment[i] = int(bone)
    native, report = project.build_native()
    warnings = []
    gltf = job.get('gltf')
    if use_texture and gltf is not None and gltf.main_image() is not None:
        try:
            native = _apply_texture(native, Image.open(io.BytesIO(gltf.image_bytes(gltf.main_image()))), palette_mode)
        except ValueError as exc:
            warnings.append('Textur nicht übernommen (Geometrie schon): ' + str(exc))
    staged = [(entry, native, 'Modell ersetzt mit Knochenzuordnung')]
    for name, data in project.adjusted_animation_bytes().items():
        e, original = companions[name]
        if data != original:
            staged.append((e, data, 'Animationskorrektur'))
    before = S().session.edits.copy()
    try:
        for e, data, label in staged:
            S().session.stage(e, data, label)
    except Exception:
        S().session.edits = before
        raise
    return {'report': report, 'warnings': warnings}


def _apply_texture(native, picture, palette_mode):
    """Fremdtextur auf den 128×224-Nutzbereich (UV „fit224“) legen – wie der Rig-Import der Windows-Version.

    Der Windows-Rig-Dialog schreibt Texturen mit NativeTexture.replace (max. 16 Farben je Palette).
    Damit beliebige Bilder passen, wird die Fremdtextur vorher auf 14 Farben reduziert (deckend).
    """
    from PIL import Image
    from dw2studio.core.native_tim_patch import regions
    from dw2studio.core.native_texture import NativeTexture
    region = regions(native)[0]
    canvas = _native_image(native, region, False).convert('RGBA')
    body = picture.convert('RGB').resize((128, 224), Image.BOX).quantize(colors=14, method=Image.Quantize.MEDIANCUT)
    canvas.paste(body.convert('RGBA'), (0, 0))
    path = _work('rigtex') / (uuid.uuid4().hex + '.png')
    canvas.save(path)
    try:
        return NativeTexture(native).replace(path)
    finally:
        path.unlink(missing_ok=True)


def restore_original(identifier):
    """Alle Modell-/Animationsänderungen dieses Digimon verwerfen (wie „Originalmodell wiederherstellen“)."""
    keys = {(e.path, e.lba) for e in _family(api._find(identifier))}
    count = 0
    for key in keys:
        if key in S().session.edits:
            S().session.remove(key)
            count += 1
    return {'removed': count}
