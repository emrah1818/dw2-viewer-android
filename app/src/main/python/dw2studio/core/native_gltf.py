"""Reiner Python-Konverter: native DW2-Modell-BIN (M…) + A–K-Animationen -> glTF.

Ersetzt auf Android die Windows-EXE (dw2_model_converter von jype, MIT).
Formatlogik wie dort und wie RigProject.export_gltf dieses Projekts:
NativeModel (Geometrie), NativeAnimation (Matrizen/Clips).
Texturen wie auf der PS1: je benutzter Palette (CLUT) eine eigene Textur, jede
Fläche nutzt genau ihre Palette – keine geschätzte Palettenkarte, keine Löcher.
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
from .rig_animation import D, parents_from_depths

SLOTS = 'ABCDEFGHIJK'
MODEL = re.compile(r'^M(\d{3}[A-Z0-9]{4})\.BIN$', re.I)


class Clip:
    def __init__(self, indices, termination, loop, index=0, offset=0):
        self.indices, self.termination, self.loop, self.index, self.offset = indices, termination, loop, index, offset


class Animation:
    """A–K-Animation. Primär exakt nach dem Spielcode (native_anim.parse_anim_file:
    Clip-Tabelle bis 1, Lücken bleiben als Index erhalten); nur wenn das scheitert,
    tolerant wie dw2_anim.cpp des Original-Konverters (legacy=True).

    transforms[bone][key] ist bereits die glTF-Matrix (D·M·D, D·t), M zeilenweise wie auf der PS1.
    """
    def __init__(self, data, bones):
        from .native_anim import parse_anim_file
        data = bytes(data)
        if len(data) < 4 + 4 * bones + 4:
            raise ValueError('Animationsdatei zu kurz.')
        self.legacy, self.table_slots, self.gaps, self.warnings = False, 0, [], []
        try:
            parsed = parse_anim_file(data, bones, strict=False)
            offsets = list(parsed.pose_offsets)
            self.clips = [Clip(tuple(c.rows), c.terminator, c.loop_offset, c.index, c.offset) for c in parsed.clips]
            self.table_slots, self.gaps, self.warnings = parsed.table_slots, parsed.gaps, parsed.warnings
        except ValueError as exc:
            self.legacy = True
            self.warnings = [f'Spielformat nicht lesbar ({exc}); tolerante Konverter-Lesart.']
            offsets, self.clips = self._legacy(data, bones)
            self.table_slots = len(self.clips)
        self.offsets = offsets
        self.transforms = []
        for bone in range(bones):
            count = max(row[bone] for clip in self.clips for row in clip.indices) + 1
            keys = []
            for key in range(count):
                at = offsets[bone] + key * 24
                m = np.eye(4)
                if 0 <= at and at + 24 <= len(data):
                    v = np.array(struct.unpack_from('<12h', data, at), dtype=float)
                    m[:3, :3] = D @ (v[:9].reshape(3, 3) / 4096.) @ D
                    m[:3, 3] = D @ v[9:12]
                keys.append(m)
            self.transforms.append(keys)

    def clip_name(self, prefix, clip, position):
        if self.legacy:
            return f'anim_{prefix}' + (str(position) if len(self.clips) > 1 else '')
        return f'anim_{prefix}' + (str(clip.index) if self.table_slots > 1 else '')

    @staticmethod
    def _legacy(data, bones):
        u32 = lambda o: struct.unpack_from('<I', data, o)[0] if 0 <= o and o + 4 <= len(data) else 1
        offsets = [u32(4 + 4 * i) for i in range(bones)]
        pos = 4 + 4 * bones
        offset = u32(pos); pos += 4
        while offset == 0 and pos + 4 <= len(data):  # Auffüllung überspringen
            offset = u32(pos); pos += 4
        frame_offsets = []
        while offset not in (0, 1) and len(frame_offsets) < 4096:
            frame_offsets.append(offset)
            offset = u32(pos); pos += 4
        clips = []
        for begin in frame_offsets:
            cursor, rows = begin, []
            while cursor < len(data) and data[cursor] not in (0xFE, 0xFF):
                rows.append(tuple(data[cursor:cursor + bones]))
                cursor += bones
                if len(rows) > 100000:
                    break
            if cursor + 3 > len(data) or not rows or any(len(r) != bones for r in rows):
                continue  # unvollständigen Clip auslassen, Rest weiter nutzen
            clips.append(Clip(tuple(rows), data[cursor], struct.unpack_from('<H', data, cursor + 1)[0], len(clips), begin))
        if not clips:
            raise ValueError('Keine lesbaren Animationsclips.')
        return offsets, clips

    def local_pose(self, clip=0, frame=0):
        row = self.clips[clip].indices[frame]
        return [self.transforms[i][k] for i, k in enumerate(row)]


def _trs(matrix):
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


def _tim(native, model):
    """TIM der Modelldatei als Abbild des 32×256-Wort-Texturplatzes (Gfx_LoadTexSlotImage).

    Normale Digimon-Modelle haben genau 128×256 Pixel (4 Bit). Kleinere 4-Bit-TIMs (z. B. das
    Schattenmodell 0x5B) liegen wie im VRAM oben links im Platz; Paletten stehen im Bild selbst,
    weil das Spiel den CLUT-Block bei 4 Bit nicht lädt.
    Rückgabe: Indizes (256×128) und alle 8192 Wörter des Platzes.
    """
    t = model.tim_start
    if t + 20 > len(native) or struct.unpack_from('<I', native, t)[0] != 16:
        raise ValueError('Keine TIM-Datei im Modell.')
    flags = struct.unpack_from('<I', native, t + 4)[0]
    if flags & 7:
        raise ValueError('Nur 4-Bit-Modelltexturen werden unterstützt.')
    img = t + 8 + (struct.unpack_from('<I', native, t + 8)[0] if flags & 8 else 0)
    if img + 12 > len(native):
        raise ValueError('TIM-Bildblock fehlt.')
    w, h = struct.unpack_from('<HH', native, img + 8)
    if not (1 <= w <= 32 and 1 <= h <= 256) or img + 12 + w * h * 2 > len(native):
        raise ValueError(f'Nicht unterstützte DW2-TIM-Größe {w * 4}×{h}.')
    words = np.zeros((256, 32), dtype='<u2')
    words[:h, :w] = np.frombuffer(native, dtype='<u2', count=w * h, offset=img + 12).reshape(h, w)
    raw = words.view(np.uint8).reshape(256, 64)
    # Wie der Original-Konverter: alle Zeilen als Pixel lesen (auch die Palettenzeilen,
    # manche Flächen nutzen sie als Farbquelle).
    indices = np.empty((256, 128), dtype=np.uint8)
    indices[:, 0::2] = raw & 15
    indices[:, 1::2] = raw >> 4
    return indices, words.reshape(-1)


def material_keys(model, native=None):
    """Alle (halbtransparent, CLUT, ABR)-Kombinationen in fester Reihenfolge.

    ABR (PS1-Mischmodus, tpage Bit 5–6) zählt nur bei halbtransparenten Flächen;
    ohne native Bytes wird 0 angenommen (frühere Lesart).
    """
    if native is None:
        return sorted({(bool(stp), clut, 0) for part in model.parts for *_, clut, stp in part.primitives})
    from .native_anim import primitive_modes
    return sorted({(bool(stp), clut, abr) for modes in primitive_modes(native) for stp, clut, abr in modes})


def texture_images(native, indices=None):
    """Je Material eine 128×256-RGBA-Textur, dekodiert mit genau dessen Palette."""
    from PIL import Image
    model = NativeModel(native)
    base, words = _tim(native, model)
    indices = base if indices is None else indices
    images = []
    for stp, clut, _abr in material_keys(model, native):
        x, y = (clut & 63) * 16, (clut >> 6) & 1023
        if x not in (0, 16) or not 0 <= y < 256:
            raise ValueError(f'Unbekannte DW2-CLUT 0x{clut:04X}.')
        bank = y * 32 + x
        w = words[bank + indices.astype(np.int32)].astype(np.uint32)
        rgba = np.zeros((256, 128, 4), dtype=np.uint8)
        r, g, b = (((w >> sh) & 31) * 8 for sh in (0, 5, 10))
        black = (r | g | b) == 0
        flag = (w & 0x8000) != 0
        # PS1-GPU: 0x0000 ist durchsichtig; gesetztes STP-Bit auf halbtransparenter Fläche wird
        # gemischt – auch 0x8000 (Schwarz mit STP). Additiv/subtraktiv ist Schwarz damit unsichtbar.
        alpha = np.where(flag & stp, 127, np.where(black & ~flag, 0, 255))
        rgba[..., 0], rgba[..., 1], rgba[..., 2], rgba[..., 3] = r, g, b, alpha
        images.append(Image.fromarray(rgba, 'RGBA'))
    return images


def convert_model(native, animations, target):
    """native: Bytes der M-BIN; animations: {Präfix 'A'..'K': Bytes}; target: .gltf-Pfad."""
    native = bytes(native)
    model = NativeModel(native)
    n = model.bone_count
    depths = list(struct.unpack_from(f'<{n}I', native, 12 + 12 * n))
    parents = parents_from_depths(depths)
    clips, raw_anims, skipped = {}, {}, {}
    for prefix, data in sorted(animations.items()):
        try:
            clips[prefix] = Animation(data, n)
            raw_anims[prefix] = bytes(data)
        except ValueError as exc:
            skipped[prefix] = str(exc)
            continue  # defekte/fremde Animationsdatei überspringen, Modell trotzdem zeigen

    doc = {'asset': {'version': '2.0', 'generator': 'DW2 3D Viewer Android (jype-Format)'}, 'scene': 0,
           'scenes': [{'nodes': [], 'extras': {'blinking_data': list(native[model.blink_offset:model.blink_offset + 24])}}],
           'nodes': [], 'meshes': [], 'animations': [], 'buffers': [], 'bufferViews': [], 'accessors': [],
           'materials': [], 'textures': [], 'images': [],
           'samplers': [{'magFilter': 9728, 'minFilter': 9728}]}
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

    from .native_anim import primitive_modes
    modes = primitive_modes(native)
    keys = material_keys(model, native)
    for i, (stp, clut, abr) in enumerate(keys):
        doc['materials'].append({'name': f'tex_{i}', 'doubleSided': True,
                                 'pbrMetallicRoughness': {'baseColorTexture': {'index': i}, 'metallicFactor': 0., 'roughnessFactor': 1.},
                                 **({'alphaMode': 'BLEND'} if stp else {'alphaMode': 'MASK', 'alphaCutoff': .1}),
                                 'extras': {'clut': clut, 'semi_transparent': stp, 'abr': abr}})
        doc['textures'].append({'sampler': 0, 'source': i})
    for i, image in enumerate(texture_images(native)):
        png = io.BytesIO()
        image.save(png, format='PNG')
        doc['images'].append({'name': f'texture_{i}', 'uri': 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode()})
    material = {k: i for i, k in enumerate(keys)}

    for bone, part in enumerate(model.parts):
        vertices = np.array([struct.unpack_from('<hhh', native, part.vertices + 6 + i * 6) for i in range(part.vertex_count)], dtype=float) @ D
        normals = np.array([struct.unpack_from('<hhh', native, part.normals + 6 + i * 6) for i in range(part.normal_count)], dtype=float) @ D / 4096
        groups = {}
        for (vs, normal_ids, uv, clut, stp), mode in zip(part.primitives, modes[bone]):
            points, ns, uvs = groups.setdefault(material[(bool(stp), clut, mode[2])], ([], [], []))
            for order in ((2, 1, 0), (1, 2, 3)) if len(vs) == 4 else ((2, 1, 0),):
                for j in order:
                    points.append(vertices[vs[j]])
                    ns.append(normals[normal_ids[j]])
                    uvs.append((uv[j][0] / 128 + .0001, uv[j][1] / 256 + .0001))
        primitives = []
        for mat, (points, ns, uvs) in sorted(groups.items()):
            primitives.append({'attributes': {'POSITION': accessor(points, 'VEC3'), 'NORMAL': accessor(ns, 'VEC3'),
                                              'TEXCOORD_0': accessor(uvs, 'VEC2')}, 'material': mat, 'mode': 4})
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
            name = animation.clip_name(prefix, clip, ci)
            loop_row = clip.loop // n if clip.termination == 0xFE and clip.loop % n == 0 else None
            a = {'name': name, 'samplers': [], 'channels': [],
                 'extras': {'termination_mask': clip.termination, 'loop_mask': clip.loop, 'loop_row': loop_row,
                            'game_anim_id': SLOTS.index(prefix) * 10 + clip.index if prefix in SLOTS else None}}
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

    doc['scenes'][0]['extras']['dw2_native'] = native_payload(native, model, depths, clips, raw_anims, skipped)
    doc['buffers'] = [{'byteLength': len(binary), 'uri': 'data:application/octet-stream;base64,' + base64.b64encode(binary).decode()}]
    target = Path(target)
    target.write_text(json.dumps(doc, separators=(',', ':')), encoding='utf-8')
    return target


def native_payload(native, model, depths, clips, raw_anims, skipped=None):
    """Rohdaten für den originalgetreuen Player im Viewer (viewer.js NativeAnimator).

    Enthält nur Daten dieses Modells: Animationsdateien unverändert, die 128×256-
    Texturwörter (VRAM-Abbild der Modelltextur) und den texAnimParts-Block.
    """
    from .native_anim import parse_tex_anim
    anims = []
    for prefix, animation in clips.items():
        for ci, clip in enumerate(animation.clips):
            anims.append({'name': animation.clip_name(prefix, clip, ci), 'file': prefix, 'clip': ci,
                          'index': clip.index, 'id': SLOTS.index(prefix) * 10 + clip.index if prefix in SLOTS else -1,
                          'offset': clip.offset, 'rows': len(clip.indices), 'terminator': clip.termination, 'loop': clip.loop,
                          'legacy': animation.legacy})
    tim = model.tim_start
    try:
        tex = parse_tex_anim(native)
        tex_info = {'region': base64.b64encode(tex.region).decode(), 'eyes': len(tex.eyes), 'cycles': len(tex.cycles),
                    'extended': len(tex.extended), 'warnings': tex.warnings, 'palette': tex.touches_palette()}
    except (ValueError, struct.error) as exc:
        tex_info = {'region': '', 'eyes': 0, 'cycles': 0, 'extended': 0, 'warnings': [str(exc)], 'palette': False}
    return {'format': 1, 'bones': model.bone_count, 'depths': depths,
            'files': {p: base64.b64encode(d).decode() for p, d in raw_anims.items()},
            'file_warnings': {p: a.warnings for p, a in clips.items() if a.warnings},
            'skipped': skipped or {}, 'anims': anims,
            'vram': base64.b64encode(_tim(native, model)[1].tobytes()).decode(),
            'texanim': tex_info}


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
