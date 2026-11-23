"""glTF/GLB-Geometrie lesen und als OBJ für den Rig-Import (RigProject) schreiben.

Liest Dreiecke der Standardszene in Weltkoordinaten (Ruhepose, ohne Skinning),
TEXCOORD_0 und die Basistextur je Material. Jede Knoten-Mesh-Kombination wird
eine OBJ-Gruppe; die Gruppen sind die Einheiten der Knochenzuordnung.
"""
from pathlib import Path
import struct

import numpy as np

from . import gltf_textures as gt

_TYPES = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2), 5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
_COMPONENTS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
_NORMALIZE = {5120: 127., 5121: 255., 5122: 32767., 5123: 65535.}
MAX_TRIANGLES = 50000


def _quat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _local(node):
    if 'matrix' in node:
        return np.array(node['matrix'], dtype=float).reshape(4, 4).T
    m = np.eye(4)
    m[:3, :3] = _quat(node.get('rotation', [0, 0, 0, 1])) * np.array(node.get('scale', [1, 1, 1]))
    m[:3, 3] = node.get('translation', [0, 0, 0])
    return m


class GltfMesh:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.suffix.lower() == '.glb':
            self.doc, self._glb, _ = gt.read_glb(self.path)
        else:
            self.doc, self._glb = gt.document(self.path), None
        self._buffers = {}
        self.groups = []  # (name, positions[N,3], uvs[N,2], triangles[M,3], image index or None)
        scenes = self.doc.get('scenes', [])
        roots = scenes[self.doc.get('scene', 0)].get('nodes', []) if scenes else range(len(self.doc.get('nodes', [])))
        for root in roots:
            self._walk(root, np.eye(4), set())
        if not self.groups:
            raise ValueError('Die 3D-Datei enthält keine Dreiecke.')
        total = sum(len(g[3]) for g in self.groups)
        if total > MAX_TRIANGLES:
            raise ValueError(f'{total} Dreiecke: maximal {MAX_TRIANGLES}. Modell vorher reduzieren.')

    def _buffer(self, index):
        if index not in self._buffers:
            buffer = self.doc['buffers'][index]
            if 'uri' in buffer:
                self._buffers[index] = gt._uri_bytes(self.path, buffer['uri'])
            elif index == 0 and self._glb is not None:
                self._buffers[index] = self._glb
            else:
                raise ValueError('glTF-Puffer ohne Daten.')
        return self._buffers[index]

    def accessor(self, index):
        acc = self.doc['accessors'][index]
        if 'sparse' in acc:
            raise ValueError('Sparse-Accessoren werden nicht unterstützt.')
        fmt, size = _TYPES[acc['componentType']]
        comps = _COMPONENTS[acc['type']]
        count = acc['count']
        if 'bufferView' not in acc:
            return np.zeros((count, comps))
        view = self.doc['bufferViews'][acc['bufferView']]
        data = self._buffer(view.get('buffer', 0))
        start = view.get('byteOffset', 0) + acc.get('byteOffset', 0)
        stride = view.get('byteStride') or size * comps
        if start + stride * (count - 1) + size * comps > len(data):
            raise ValueError('Accessor liegt außerhalb des Puffers.')
        dtype = np.dtype('<' + fmt)
        rows = np.empty((count, comps), dtype=dtype)
        raw = np.frombuffer(data, dtype=np.uint8)
        for c in range(comps):
            offsets = start + np.arange(count) * stride + c * size
            rows[:, c] = raw[(offsets[:, None] + np.arange(size)).reshape(-1)].view(dtype)
        out = rows.astype(float)
        if acc.get('normalized') and acc['componentType'] in _NORMALIZE:
            out = np.maximum(out / _NORMALIZE[acc['componentType']], -1.)
        return out

    def _walk(self, index, parent, seen):
        if index in seen:
            raise ValueError('Zyklische Knotenhierarchie.')
        seen = seen | {index}
        node = self.doc['nodes'][index]
        world = parent @ _local(node)
        if 'mesh' in node:
            mesh = self.doc['meshes'][node['mesh']]
            for p, prim in enumerate(mesh.get('primitives', [])):
                if prim.get('mode', 4) != 4 or 'POSITION' not in prim.get('attributes', {}):
                    continue
                pos = self.accessor(prim['attributes']['POSITION'])[:, :3]
                pos = (np.c_[pos, np.ones(len(pos))] @ world.T)[:, :3]
                uv = (self.accessor(prim['attributes']['TEXCOORD_0'])[:, :2]
                      if 'TEXCOORD_0' in prim['attributes'] else None)
                tri = (self.accessor(prim['indices'])[:, 0].astype(int) if 'indices' in prim
                       else np.arange(len(pos))).reshape(-1, 3)
                if np.linalg.det(world[:3, :3]) < 0:
                    tri = tri[:, ::-1]
                image = None
                if 'material' in prim:
                    mat = self.doc['materials'][prim['material']]
                    tex = mat.get('pbrMetallicRoughness', {}).get('baseColorTexture', {}).get('index')
                    if tex is not None:
                        image = self.doc['textures'][tex].get('source')
                name = node.get('name') or mesh.get('name') or f'node_{index}'
                if len(mesh.get('primitives', [])) > 1:
                    name += f'_{p}'
                # Rigid PS1 exports combine bones into material primitives.
                # Keep each rigid joint separately assignable in DW2's rig UI.
                attrs = prim['attributes']
                if 'skin' in node and 'JOINTS_0' in attrs and 'WEIGHTS_0' in attrs:
                    joints = self.accessor(attrs['JOINTS_0']).astype(int)
                    weights = self.accessor(attrs['WEIGHTS_0'])
                    dominant = np.argmax(weights, axis=1)
                    rigid = np.isclose(weights[np.arange(len(weights)), dominant], 1)
                    ids = joints[np.arange(len(joints)), dominant]
                    if rigid.all() and (ids[tri] == ids[tri[:, :1]]).all():
                        skin = self.doc['skins'][node['skin']]
                        for joint in np.unique(ids[tri[:, 0]]):
                            if not 0 <= joint < len(skin['joints']):
                                raise ValueError('Skin joint outside skeleton')
                            joint_node = self.doc['nodes'][skin['joints'][joint]]
                            label = joint_node.get('name', f'joint_{joint}')
                            selected = tri[ids[tri[:, 0]] == joint]
                            self.groups.append((f'{label}_{name}', pos, uv, selected, image))
                        continue
                self.groups.append((name, pos, uv, tri, image))
        for child in node.get('children', []):
            self._walk(child, world, seen)

    def main_image(self):
        """Bildindex, den die meisten Dreiecke nutzen (oder None)."""
        counts = {}
        for _, _, _, tri, image in self.groups:
            if image is not None:
                counts[image] = counts.get(image, 0) + len(tri)
        return max(counts, key=counts.get) if counts else None

    def image_bytes(self, index):
        return gt.image_bytes(self.path, index)

    def write_obj(self, target):
        """OBJ mit einer Gruppe je Mesh; glTF-UV (v nach unten) wird zu OBJ-UV (v nach oben)."""
        lines = ['# aus glTF erzeugt für die DW2-Knochenzuordnung']
        base = 1
        uv_base = 1
        for name, pos, uv, tri, _ in self.groups:
            lines.append('g ' + ''.join(ch if ch.isalnum() or ch in '_-.' else '_' for ch in name))
            lines += [f'v {x:.6f} {y:.6f} {z:.6f}' for x, y, z in pos]
            if uv is not None:
                lines += [f'vt {u:.6f} {1 - v:.6f}' for u, v in uv]
                lines += [f'f {a + base}/{a + uv_base} {b + base}/{b + uv_base} {c + base}/{c + uv_base}' for a, b, c in tri]
                uv_base += len(uv)
            else:
                lines += [f'f {a + base} {b + base} {c + base}' for a, b, c in tri]
            base += len(pos)
        Path(target).write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return Path(target)
