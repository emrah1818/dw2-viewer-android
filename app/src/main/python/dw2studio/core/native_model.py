"""Conservative DW2 native model layout and fixed-topology OBJ shape roundtrip.

Layout evidence: bundled jype converter (MIT, 2024), dw2_model.cpp/.hpp;
eye rectangles: bundled decomp src/main/anim.c Gfx_AnimateModelTex and
include/main/156C.h GfxTexAnimPart (10-byte entries, VRAM-word X units).
No skeleton, primitive count, UV, or animation reallocation.
"""
from dataclasses import dataclass
from pathlib import Path
import math
import struct

@dataclass(frozen=True)
class Part:
    vertices: int
    normals: int
    vertex_count: int
    normal_count: int
    primitives: tuple

@dataclass(frozen=True)
class Eye:
    destination: tuple
    frames: tuple
    width: int
    height: int


class NativeModel:
    def __init__(self, data):
        self.data = bytes(data)
        if len(data) < 36:
            raise ValueError('Keine vollständige native DW2-Modell-BIN.')
        self.tim_start, self.tim_end, n = struct.unpack_from('<III', data)
        if not 1 <= n <= 256 or not 12+16*n+24 <= self.tim_start < len(data)-20:
            raise ValueError('Ungültiger DW2-Modellkopf / Zeigertabelle.')
        self.blink_offset = 12+16*n
        self.bone_count = n
        pointers = struct.unpack_from(f'<{3*n}I',data,12)
        self.parts = []
        spans = []
        for i in range(n):
            v, normal, primitive = (pointers[i+k*n] for k in range(3))
            counts = []
            for offset in (v, normal):
                self._span(offset, 6)
                count = struct.unpack_from('<I',data,offset)[0]
                if not 1 <= count <= 256:
                    raise ValueError('Unzulässige Anzahl an Vertices / Normalen.')
                self._span(offset, 6+count*6)
                spans.append((offset, offset+6+count*6))
                counts.append(count)
            pos = primitive
            primitives = []
            for corners, length, stp in ((4,20,True),(4,20,False),(3,16,True),(3,16,False)):
                self._span(pos,4)
                count = struct.unpack_from('<I',data,pos)[0]
                pos += 4
                if count > 10000:
                    raise ValueError('Unzulässige Polygonanzahl.')
                self._span(pos,count*length)
                for j in range(count):
                    p = pos+j*length
                    vs = tuple(data[p:p+corners]); ns = tuple(data[p+corners:p+2*corners])
                    if max(vs) >= counts[0] or max(ns) >= counts[1]:
                        raise ValueError('Polygon referenziert ungültigen Vertex / Normale.')
                    uv = tuple(zip(data[p+2*corners:p+4*corners:2],data[p+2*corners+1:p+4*corners:2]))
                    clut = struct.unpack_from('<H',data,p+4*corners)[0]
                    primitives.append((vs, ns, uv, clut, stp))
                pos += count*length
            if not primitives:
                raise ValueError('Leeres Teilmodell.')
            spans.append((primitive,pos))
            self.parts.append(Part(v,normal,*counts,tuple(primitives)))
        ordered = sorted(spans)
        if any(a[1] > b[0] for a,b in zip(ordered,ordered[1:])):
            raise ValueError('Überlappende Geometrieblöcke.')
        if data[self.tim_start:self.tim_start+4] != b'\x10\0\0\0':
            raise ValueError('DW2-TIM-Zeiger ungültig.')

    def _span(self, offset, size):
        if offset < self.blink_offset+24 or size < 0 or offset+size > self.tim_start:
            raise ValueError('Geometriezeiger außerhalb des Modellbereichs.')

    def eyes(self):
        """Two 10-byte blink records, each with three source rectangles."""
        result = []
        for i in range(2):
            pos = self.blink_offset+i*10
            x,y,w,h,*uv = self.data[pos:pos+10]
            if x == 255:
                continue
            if x == 254 or not w or not h:
                raise ValueError('Nicht unterstützte Augen-Metadaten.')
            destination = (x*4,y)
            frames = tuple((uv[j]*4,uv[j+1]) for j in range(0,6,2))
            width = w*4
            if any(a+width > 128 or b+h > 224 for a,b in (destination,*frames)):
                raise ValueError('Augenrechteck außerhalb der DW2-Pixeldaten.')
            result.append(Eye(destination,frames,width,h))
        if not result:
            raise ValueError('Dieses Modell besitzt keine erkannten Augenrechtecke.')
        return tuple(result)

    def _obj_data(self):
        vertices, normals, faces = [], [], []
        for part in self.parts:
            base_v, base_n = len(vertices),len(normals)
            vertices.extend(struct.unpack_from('<hhh',self.data,part.vertices+6+i*6) for i in range(part.vertex_count))
            normals.extend(struct.unpack_from('<hhh',self.data,part.normals+6+i*6) for i in range(part.normal_count))
            for vs,ns,uv,clut,stp in part.primitives:
                order = (0,1,3,2) if len(vs)==4 else (0,1,2)
                faces.append(tuple((base_v+vs[j]+1,base_n+ns[j]+1) for j in order))
        return vertices,normals,faces

    def export_obj(self, destination):
        vertices,normals,faces = self._obj_data()
        lines = ['# DW2 fixed-topology shape template v1',
                 '# Local bone coordinates, native XYZ units. Keep vertex/normal order and faces.',
                 '# Sculpt/move existing vertices only. UV, rig and animations remain native.']
        lines += ['v '+' '.join(map(str,v)) for v in vertices]
        lines += ['vn '+' '.join(f'{c/4096:.9f}' for c in normal) for normal in normals]
        cursor = 0
        for i, part in enumerate(self.parts):
            lines.append(f'g bone_{i:03d}')
            for face in faces[cursor:cursor+len(part.primitives)]:
                lines.append('f '+' '.join(f'{v}//{n}' for v,n in face))
            cursor += len(part.primitives)
        Path(destination).write_text('\n'.join(lines)+'\n',encoding='utf-8')
        return Path(destination)

    def import_obj(self, source):
        vertices,normals,faces = [], [], []
        for line in Path(source).read_text(encoding='utf-8-sig').splitlines():
            items = line.split('#',1)[0].split()
            if not items:
                continue
            if items[0] in ('v','vn'):
                if len(items) != 4:
                    raise ValueError('OBJ-Koordinate muss drei Werte besitzen.')
                value = tuple(float(c) for c in items[1:])
                if not all(math.isfinite(c) for c in value):
                    raise ValueError('Ungültige OBJ-Koordinate.')
                (vertices if items[0]=='v' else normals).append(value)
            elif items[0] == 'f':
                face = []
                for token in items[1:]:
                    values = token.split('/')
                    if len(values)!=3 or values[1] or not values[2]:
                        raise ValueError('Für Rückimport die native OBJ-Vorlage mit v//vn verwenden.')
                    face.append((int(values[0]),int(values[2])))
                faces.append(tuple(face))
            elif items[0] not in ('g','o','s','usemtl','mtllib'):
                raise ValueError('OBJ enthält nicht unterstützte Daten: '+items[0])
        original_v,original_n,original_f = self._obj_data()
        if len(vertices)!=len(original_v) or len(normals)!=len(original_n) or faces!=original_f:
            raise ValueError('Topologie / Reihenfolge verändert. Nur Formänderungen der nativen OBJ-Vorlage sind rückimportierbar; fremde Modelle als Vorschau importieren.')
        out = bytearray(self.data)
        vi=ni=0
        for part in self.parts:
            for offset, count, values, start, scale in ((part.vertices,part.vertex_count,vertices,vi,1),
                                                       (part.normals,part.normal_count,normals,ni,4096)):
                for i in range(count):
                    coords = tuple(round(c*scale) for c in values[start+i])
                    if any(c < -32768 or c > 32767 for c in coords):
                        raise ValueError('Koordinate überschreitet den nativen 16-Bit-Bereich.')
                    struct.pack_into('<hhh',out,offset+6+i*6,*coords)
            vi += part.vertex_count; ni += part.normal_count
        NativeModel(out)
        return bytes(out)


def validate_replacement(original, replacement):
    """Keep the bone interface consumed by the existing animation companion BINs."""
    if len(original)!=len(replacement):
        raise ValueError(f'Native Modell-BIN muss exakt {len(original)} Bytes haben.')
    before,after=NativeModel(original),NativeModel(replacement)
    n=before.bone_count
    if after.bone_count!=n or original[12+12*n:12+16*n]!=replacement[12+12*n:12+16*n]:
        raise ValueError('Knochenanzahl / Hierarchie passt nicht zu den vorhandenen Animationen.')
    return bytes(replacement)
