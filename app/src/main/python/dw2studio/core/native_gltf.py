"""Reiner Python-Konverter: native DW2-Modell-BIN (M…) + A–K-Animationen -> glTF.

Ersetzt auf Android die Windows-EXE (dw2_model_converter von jype, MIT).
Formatlogik wie dort und wie RigProject.export_gltf dieses Projekts:
NativeModel (Geometrie), NativeAnimation (Matrizen/Clips), NativeTexture (Paletten).
Ausgabe: <Ziel>/M<ID><CODE>.gltf mit eingebetteten Puffern und PNG.
"""
from pathlib import Path
import base64
import io
import json
import re
import struct

import numpy as np

from .native_model import NativeModel
from .native_texture import NativeTexture
from .rig_animation import D, NativeAnimation, parents_from_depths

MODEL = re.compile(r'^M(\d{3}[A-Z0-9]{4})\.BIN$', re.I)


def _native(matrix):
    """PS1-Matrix wie im Original-Konverter anwenden (v' = M·v).

    NativeAnimation liefert für den Rig-Editor die transponierte Rotation;
    für die Anzeige wird sie zurückgedreht, sonst verdrehen sich Gliedmaßen.
    """
    m = np.array(matrix, dtype=float)
    m[:3, :3] = m[:3, :3].T
    return m


def _trs(matrix):
    matrix = _native(matrix)
    scale = np.linalg.norm(matrix[:3, :3], axis=0)
    if np.min(scale) < 1e-8:
        return matrix[:3, 3].tolist(), [0., 0., 0., 1.], [1., 1., 1.]
    r = matrix[:3, :3] / scale
    u, _, vt = np.linalg.svd(r)
    r = u @ vt
    if np.linalg.det(r) < 0:          # Spiegelung: als negative Skalierung abbilden
        r[:, 0] *= -1
        scale[0] *= -1
    trace = np.trace(r)
    if trace > 0:
        s = np.sqrt(trace + 1) * 2
        q = np.array([(r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s, .25 * s])
    else:
        i = int(np.argmax(np.diag(r)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = np.sqrt(max(0., 1 + r[i, i] - r[j, j] - r[k, k])) * 2
        if s < 1e-10:
            return matrix[:3, 3].tolist(), [0., 0., 0., 1.], scale.tolist()
        q = np.zeros(4)
        q[i] = .25 * s
        q[j] = (r[j, i] + r[i, j]) / s
        q[k] = (r[k, i] + r[i, k]) / s
        q[3] = (r[k, j] - r[j, k]) / s
    return matrix[:3, 3].tolist(), (q / np.linalg.norm(q)).tolist(), scale.tolist()


def convert_model(native, animations, target):
    """native: Bytes der M-BIN; animations: {Präfix 'A'..'K': Bytes}; target: .gltf-Pfad."""
    native = bytes(native)
    model = NativeModel(native)
    n = model.bone_count
    depths = list(struct.unpack_from(f'<{n}I', native, 12 + 12 * n))
    parents = parents_from_depths(depths)
    clips = {}
    for prefix, data in sorted(animations.items()):
        try:
            clips[prefix] = NativeAnimation(data, n)
        except ValueError:
            continue  # defekte/fremde Animationsdatei überspringen, Modell trotzdem zeigen

    doc = {'asset': {'version': '2.0', 'generator': 'DW2 3D Viewer Android (jype-Format)'}, 'scene': 0,
           'scenes': [{'nodes': [], 'extras': {'blinking_data': list(native[model.blink_offset:model.blink_offset + 24])}}],
           'nodes': [], 'meshes': [], 'animations': [], 'buffers': [], 'bufferViews': [], 'accessors': [],
           'materials': [
               {'name': 'opaque', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}, 'metallicFactor': 0., 'roughnessFactor': 1.},
                'alphaMode': 'MASK', 'alphaCutoff': .1, 'doubleSided': True},
               {'name': 'semi_transparent', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}, 'metallicFactor': 0., 'roughnessFactor': 1.},
                'alphaMode': 'BLEND', 'doubleSided': True}],
           'textures': [{'sampler': 0, 'source': 0}],
           'samplers': [{'magFilter': 9728, 'minFilter': 9728, 'wrapS': 33071, 'wrapT': 33071}]}
    binary = bytearray()

    def accessor(values, kind):
        arr = np.asarray(values, dtype='<f4')
        start = (len(binary) + 3) // 4 * 4
        binary.extend(bytes(start - len(binary)))
        binary.extend(arr.tobytes())
        view = len(doc['bufferViews'])
        doc['bufferViews'].append({'buffer': 0, 'byteOffset': start, 'byteLength': arr.nbytes})
        row = {'bufferView': view, 'componentType': 5126, 'count': len(arr), 'type': kind}
        if len(arr):
            flat = arr.reshape(len(arr), -1)
            row.update(min=flat.min(0).tolist(), max=flat.max(0).tolist())
        doc['accessors'].append(row)
        return len(doc['accessors']) - 1

    # Skelett in der ersten Pose der ersten Animation (wie der Original-Konverter).
    first = next(iter(clips.values())).local_pose() if clips else [np.eye(4)] * n
    for i in range(n):
        t, q, s = _trs(first[i])
        doc['nodes'].append({'name': f'bone_{i}', 'translation': t, 'rotation': q, 'scale': s, 'children': []})
    for i, parent in enumerate(parents):
        (doc['scenes'][0]['nodes'] if parent < 0 else doc['nodes'][parent]['children']).append(i)

    for bone, part in enumerate(model.parts):
        vertices = np.array([struct.unpack_from('<hhh', native, part.vertices + 6 + i * 6) for i in range(part.vertex_count)], dtype=float) @ D
        normals = np.array([struct.unpack_from('<hhh', native, part.normals + 6 + i * 6) for i in range(part.normal_count)], dtype=float) @ D / 4096
        groups = {False: ([], [], []), True: ([], [], [])}
        for vs, normal_ids, uv, clut, stp in part.primitives:
            points, ns, uvs = groups[stp]
            for order in ((2, 1, 0), (1, 2, 3)) if len(vs) == 4 else ((2, 1, 0),):
                for j in order:
                    points.append(vertices[vs[j]])
                    ns.append(normals[normal_ids[j]])
                    uvs.append((uv[j][0] / 128, uv[j][1] / 256))
        primitives = []
        for stp in (False, True):
            points, ns, uvs = groups[stp]
            if points:
                primitives.append({'attributes': {'POSITION': accessor(points, 'VEC3'), 'NORMAL': accessor(ns, 'VEC3'),
                                                  'TEXCOORD_0': accessor(uvs, 'VEC2')}, 'material': int(stp), 'mode': 4})
        doc['meshes'].append({'name': f'mesh_{bone}', 'primitives': primitives})
        doc['nodes'].append({'name': f'mesh_{bone}', 'mesh': len(doc['meshes']) - 1})
        doc['nodes'][bone]['children'].append(len(doc['nodes']) - 1)

    for prefix, animation in clips.items():
        cache = {}

        def trs_of(bone, key):
            if (bone, key) not in cache:
                cache[bone, key] = _trs(animation.transforms[bone][key])
            return cache[bone, key]

        for ci, clip in enumerate(animation.clips):
            name = f'anim_{prefix}' + (str(ci) if len(animation.clips) > 1 else '')
            a = {'name': name, 'samplers': [], 'channels': [],
                 'extras': {'termination_mask': clip.termination, 'loop_mask': clip.loop}}
            times = accessor(np.arange(len(clip.indices), dtype=float) / 30, 'SCALAR')
            for bone in range(n):
                values = [trs_of(bone, row[bone]) for row in clip.indices]
                quats = [v[1] for v in values]
                for j in range(1, len(quats)):
                    if np.dot(quats[j - 1], quats[j]) < 0:
                        quats[j] = (-np.array(quats[j])).tolist()
                for channel, kind, data in (('translation', 'VEC3', [v[0] for v in values]),
                                            ('rotation', 'VEC4', quats), ('scale', 'VEC3', [v[2] for v in values])):
                    a['samplers'].append({'input': times, 'output': accessor(data, kind), 'interpolation': 'LINEAR'})
                    a['channels'].append({'sampler': len(a['samplers']) - 1, 'target': {'node': bone, 'path': channel}})
            doc['animations'].append(a)

    png = io.BytesIO()
    NativeTexture(native).to_image().save(png, format='PNG')
    doc['images'] = [{'name': 'texture', 'uri': 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode()}]
    doc['buffers'] = [{'byteLength': len(binary), 'uri': 'data:application/octet-stream;base64,' + base64.b64encode(binary).decode()}]
    target = Path(target)
    target.write_text(json.dumps(doc, separators=(',', ':')), encoding='utf-8')
    return target


def convert_folder(source, output):
    """Wie der Original-Konverter: alle M-BINs eines Ordners samt passender A–K-BINs umwandeln."""
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    files = {p.name.upper(): p for p in source.iterdir() if p.is_file()}
    written = []
    for name, path in sorted(files.items()):
        m = MODEL.match(name)
        if not m:
            continue
        stem = m.group(1).upper()
        animations = {chr(c): files[f'{chr(c)}{stem}.BIN'].read_bytes()
                      for c in range(ord('A'), ord('K') + 1) if f'{chr(c)}{stem}.BIN' in files}
        written.append(convert_model(path.read_bytes(), animations, output / f'M{stem}.gltf'))
    if not written:
        raise ValueError('Keine Modell-Datei (M###XXXX.BIN) gefunden.')
    return written
