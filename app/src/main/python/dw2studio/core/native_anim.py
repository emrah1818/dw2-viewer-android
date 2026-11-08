"""Animationskanäle der nativen DW2-Modelle, gelesen wie der Spielcode.

Belege (Decompilation Wyrelade/DW2-PC, CC0):
  * Knochenanimation: src/main/anim.c Anim_StepModelAnim / Anim_SetModelAnim /
    Anim_HasModelAnim. Datei = u32 Relokationsflag, n Zeiger auf Posentabellen
    (je Schlüssel 24 Byte: 3×3 s16 Matrix zeilenweise /4096 + 3 s16 Translation),
    danach die Clip-Tabelle (0 = kein Clip an diesem Index, 1 = Tabellenende).
    Ein Clip besteht aus Zeilen mit je n Schlüsselindizes; jede Zeile gilt
    2 VBlanks (30 Hz), ohne Interpolation. Nach einer Zeile beendet 0xFF den
    Clip (letztes Bild bleibt stehen), 0xFE springt auf den Byte-Offset
    (q[2] << 8 | q[1]) innerhalb des Clips (Schleife ab diesem Bild).
  * Texturanimation: src/main/anim.c Gfx_AnimateModelTex mit
    include/main/156C.h GfxTexAnimPart (10 Byte) und GfxModelTexAnim (42 Byte).
    Der Block liegt direkt hinter den Knochentiefen (model.c Gfx_AttachModel:
    texAnimParts = boneDepths + boneCount). Einträge 0–1: Augen (Blinzeln mit
    Zufallsintervall), Einträge 2–9: 3-Bild-Zyklus (je 8 VBlanks), Ende mit 0xFF
    oder 0xFE; nach 0xFE folgen erweiterte Einträge (2 Rechtecke je Bild,
    eigene Periode und Startphase). Alles sind VRAM-Kopien (DR_MOVE) innerhalb
    der eigenen 128×256-Textur (X in 16-Bit-Wörtern = 4 Pixel).
  * Halbtransparenz: model.c Gfx_AddQuadsGT4 / Gfx_AddTrisGT3. Der erste Quad-
    und Dreiecksblock je Knochen wird mit Halbtransparenz gezeichnet; der
    Mischmodus (ABR) steht in Bit 5–6 des tpage-Worts jeder Fläche.
  * Animationszuordnung: src/main/digidata.c Digi_GetAnimFile – DigiData-Satz
    (40 Byte, MODELDT0/1/2.BIN): +6 Modell-Datei-ID, +8 animFiles[11] (A–K).
"""
from dataclasses import dataclass, field
import struct

TICKS_PER_ROW = 2          # Anim_StepModelAnim: animTimer >= 2
CYCLE_PERIOD = 0x18        # Gfx_AnimateModelTex: texAnimTimer % 0x18, Bild = timer / 8
NO_BLINK_ANIMS = (0x64, 0x0A, 0x14, 0x15, 0x16)   # Gfx_AnimAllowsBlink
SLOTS = 'ABCDEFGHIJK'


# ---------------------------------------------------------------- Knochenanimation
@dataclass
class NativeClip:
    index: int              # Index in der Clip-Tabelle (Spiel: animId % 10)
    offset: int
    rows: list              # Liste von Tupeln (Schlüsselindex je Knochen)
    terminator: int         # 0xFF halten, 0xFE Schleife
    loop_offset: int        # Byte-Offset im Clip (nur 0xFE)

    @property
    def loop_row(self):
        """Zeile, ab der wiederholt wird; None = einmalig (hält letztes Bild)."""
        if self.terminator != 0xFE:
            return None
        return self.loop_offset // max(1, len(self.rows[0])) if self.rows else 0


@dataclass
class NativeAnimFile:
    bones: int
    pose_offsets: tuple
    clips: list
    key_counts: tuple
    table_slots: int        # Anzahl Einträge der Clip-Tabelle (inkl. Lücken)
    gaps: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def parse_anim_file(data, bones, strict=True):
    """Liest eine A–K-Datei exakt nach Anim_StepModelAnim. strict=False toleriert defekte Clips."""
    data = bytes(data)
    if not 1 <= bones <= 256 or len(data) < 4 + 4 * bones + 4:
        raise ValueError('Animationsdatei zu kurz.')
    if data[:4] != bytes(4):
        raise ValueError('Animationskopf: Relokationsflag ist nicht 0.')
    poses = struct.unpack_from(f'<{bones}I', data, 4)
    table = 4 + 4 * bones
    head_end = table
    entries, pos = [], table
    while True:
        if pos + 4 > len(data):
            raise ValueError('Clip-Tabelle ohne Abschluss (1).')
        value = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        if value == 1:
            break
        entries.append(value)
        if len(entries) > 64:
            raise ValueError('Clip-Tabelle zu lang (falsche Knochenzahl?).')
    head_end = pos
    for p in poses:
        if not head_end <= p < len(data) or (p - head_end) % 2:
            raise ValueError('Posentabelle außerhalb der Datei (falsche Knochenzahl?).')
    warnings, clips, gaps = [], [], []
    maximum = [0] * bones
    for index, begin in enumerate(entries):
        if begin == 0:
            gaps.append(index)
            continue
        try:
            if not head_end <= begin < len(data):
                raise ValueError(f'Clip {index}: Zeiger außerhalb der Datei.')
            cursor, rows = begin, []
            while True:
                if cursor + bones > len(data):
                    raise ValueError(f'Clip {index}: unvollständige Zeile.')
                rows.append(tuple(data[cursor:cursor + bones]))
                cursor += bones
                if cursor >= len(data):
                    raise ValueError(f'Clip {index}: Ende ohne 0xFF/0xFE.')
                if data[cursor] in (0xFE, 0xFF):
                    break
                if len(rows) > 20000:
                    raise ValueError(f'Clip {index}: zu lang.')
            if cursor + 3 > len(data):
                raise ValueError(f'Clip {index}: Abschluss abgeschnitten.')
            term = data[cursor]
            loop = data[cursor + 1] | (data[cursor + 2] << 8)
            clip = NativeClip(index, begin, rows, term, loop)
            if term == 0xFE:
                if loop % bones or loop // bones >= len(rows):
                    raise ValueError(f'Clip {index}: Schleifenziel {loop} liegt nicht auf einer Zeile.')
            for row in rows:
                for b, k in enumerate(row):
                    if k > maximum[b]:
                        maximum[b] = k
            clips.append(clip)
        except ValueError as exc:
            if strict:
                raise
            warnings.append(str(exc))
    for b, p in enumerate(poses):
        if p + (maximum[b] + 1) * 24 > len(data):
            raise ValueError(f'Knochen {b}: Schlüssel {maximum[b]} außerhalb der Datei.')
    if not clips:
        raise ValueError('Keine lesbaren Animationsclips.')
    return NativeAnimFile(bones, poses, clips, tuple(m + 1 for m in maximum), len(entries), gaps, warnings)


def pose_matrix(data, offset, key):
    """Roh-Schlüssel: (3×3 Matrix zeilenweise in 1/4096, Translation)."""
    v = struct.unpack_from('<12h', data, offset + key * 24)
    return [list(v[0:3]), list(v[3:6]), list(v[6:9])], list(v[9:12])


def matrix_flags(data, anim):
    """Zählt Schlüssel mit Skalierung, Scherung oder Spiegelung (nicht als reine Drehung darstellbar)."""
    import numpy as np
    blocks = [np.frombuffer(data, dtype='<i2', count=12 * k, offset=p).reshape(k, 12)
              for p, k in zip(anim.pose_offsets, anim.key_counts) if k]
    if not blocks:
        return {'keys': 0, 'scaled_keys': 0, 'sheared_keys': 0, 'mirrored_keys': 0}
    keys = np.concatenate(blocks).astype(float)
    m = keys[:, :9].reshape(-1, 3, 3) / 4096.
    cols = np.transpose(m, (0, 2, 1))
    norms = np.linalg.norm(cols, axis=2)
    scaled = np.any(np.abs(norms - 1) > .02, axis=1)
    unit = cols / np.maximum(norms[..., None], 1e-9)
    dots = np.abs(np.einsum('kij,klj->kil', unit, unit))
    off = dots[:, [0, 0, 1], [1, 2, 2]]
    sheared = np.any(off > .02, axis=1)
    mirrored = np.linalg.det(m) < 0
    return {'keys': int(len(m)), 'scaled_keys': int(scaled.sum()), 'sheared_keys': int(sheared.sum()),
            'mirrored_keys': int(mirrored.sum())}


# ---------------------------------------------------------------- Texturanimation
@dataclass
class TexAnim:
    eyes: list = field(default_factory=list)       # [{'dst':(x,y), 'size':(w,h), 'frames':[(x,y)*3]}]
    cycles: list = field(default_factory=list)     # gleiche Form, 3 Bilder, Periode 24 VBlanks
    extended: list = field(default_factory=list)   # [{'rects':[(dx,dy,w,h),(dx2,dy2,w2,h2)], 'period', 'phase', 'frames':[[(x,y),(x2,y2)]...]}]
    region: bytes = b''
    region_start: int = 0
    terminated: bool = True
    warnings: list = field(default_factory=list)

    @property
    def any(self):
        return bool(self.eyes or self.cycles or self.extended)

    def touches_palette(self):
        rects = [(e['dst'][0], e['dst'][1], *e['size']) for e in self.eyes + self.cycles]
        rects += [r for e in self.extended for r in e['rects']]
        return any(y + h > 224 for x, y, w, h in rects if w and h)


def _geometry_start(native, bones):
    pointers = struct.unpack_from(f'<{3 * bones}I', native, 12)
    return min(pointers)


def _rect_ok(x, y, w, h):
    return x + w <= 32 and y + h <= 256


def parse_tex_anim(native):
    """Liest den texAnimParts-Block hinter den Knochentiefen wie Gfx_AnimateModelTex."""
    native = bytes(native)
    tim, _, n = struct.unpack_from('<III', native)
    start = 12 + 16 * n
    end = min(_geometry_start(native, n), tim)
    region = native[start:end]
    out = TexAnim(region_start=start)

    def entry(i):
        o = i * 10
        return region[o:o + 10] if o + 10 <= len(region) else None

    def frames(raw, count):
        return [(raw[4 + 2 * f], raw[5 + 2 * f]) for f in range(count)]

    used = 0
    for i in range(2):
        raw = entry(i)
        if raw is None:
            out.warnings.append('Augenblock unvollständig.')
            out.terminated = False
            out.region = region
            return out
        used = (i + 1) * 10
        if raw[0] == 0xFF:
            continue
        rec = {'dst': (raw[0], raw[1]), 'size': (raw[2], raw[3]), 'frames': frames(raw, 3)}
        if not all(_rect_ok(x, y, raw[2], raw[3]) for x, y in [rec['dst']] + rec['frames']):
            out.warnings.append(f'Augenrechteck {i} außerhalb der Modelltextur.')
        out.eyes.append(rec)
    i, marker = 2, None
    while True:
        o = i * 10
        if o >= len(region):
            out.terminated = False
            out.warnings.append('Texturanimationsblock ohne 0xFF/0xFE-Abschluss.')
            break
        if region[o] in (0xFF, 0xFE):
            marker = region[o]
            used = o + 1
            break
        if i >= 10:
            out.warnings.append('Mehr als 8 Zyklus-Einträge (Spiel liest maximal 8).')
            out.terminated = False
            break
        raw = entry(i)
        if raw is None:
            out.terminated = False
            out.warnings.append('Zyklus-Eintrag abgeschnitten.')
            break
        rec = {'dst': (raw[0], raw[1]), 'size': (raw[2], raw[3]), 'frames': frames(raw, 3)}
        if not all(_rect_ok(x, y, raw[2], raw[3]) for x, y in [rec['dst']] + rec['frames']):
            out.warnings.append(f'Zyklus-Rechteck {i} außerhalb der Modelltextur.')
        out.cycles.append(rec)
        used = o + 10
        i += 1
    if marker == 0xFE:
        q = used   # GfxModelTexAnim beginnt beim Byte hinter 0xFE
        for c in range(10):
            if q >= len(region):
                out.warnings.append('Erweiterte Texturanimation ohne 0xFF-Abschluss.')
                out.terminated = False
                break
            if region[q] == 0xFF:
                used = q + 1
                break
            if q + 42 > len(region):
                out.warnings.append('Erweiterter Eintrag abgeschnitten.')
                out.terminated = False
                break
            raw = region[q:q + 42]
            period = raw[8]
            if not period:
                out.warnings.append(f'Erweiterter Eintrag {c}: Periode 0 (Spiel würde hängen).')
            count = max(1, (period + 1) // 2)
            if count > 8:
                out.warnings.append(f'Erweiterter Eintrag {c}: Periode {period} > 16 (mehr als 8 Bilder).')
            uv = raw[10:42]
            fr = [[(uv[4 * f], uv[4 * f + 1]), (uv[4 * f + 2], uv[4 * f + 3])] for f in range(min(8, count))]
            rec = {'rects': [(raw[0], raw[1], raw[2], raw[3]), (raw[4], raw[5], raw[6], raw[7])],
                   'period': period, 'phase': raw[9], 'frames': fr}
            if not all(_rect_ok(*r) for r in rec['rects']):
                out.warnings.append(f'Erweitertes Rechteck {c} außerhalb der Modelltextur.')
            out.extended.append(rec)
            q += 42
            used = q
        else:
            out.warnings.append('Mehr als 10 erweiterte Einträge.')
    out.region = region[:used]
    # DR_MOVE kopiert dauerhaft: liegt eine Quelle auf dem Ziel, bleibt nach dem
    # Wechsel das zuletzt kopierte Bild stehen (so auch im Spiel).
    for kind, recs in (('Augen', out.eyes), ('Zyklus', out.cycles)):
        for r in recs:
            if r['dst'] in r['frames'] and len(set(r['frames'])) > 1:
                out.warnings.append(f'{kind}: eine Quelle liegt auf dem Ziel {r["dst"]} (Bild wird nicht wiederhergestellt).')
    return out


# ---------------------------------------------------------------- Flächen / Mischmodi
def primitive_modes(native):
    """Je Knochen und Fläche: (halbtransparent, clut, abr). abr = tpage Bit 5–6."""
    from .native_model import NativeModel
    model = NativeModel(native)
    result = []
    pointers = struct.unpack_from(f'<{3 * model.bone_count}I', native, 12)
    for bone in range(model.bone_count):
        pos = pointers[2 * model.bone_count + bone]
        modes = []
        for corners, length, stp in ((4, 20, True), (4, 20, False), (3, 16, True), (3, 16, False)):
            count = struct.unpack_from('<I', native, pos)[0]
            pos += 4
            for j in range(count):
                p = pos + j * length
                clut, tpage = struct.unpack_from('<HH', native, p + 4 * corners)
                modes.append((stp, clut, (tpage >> 5) & 3 if stp else 0))
            pos += count * length
        result.append(modes)
    return result


# ---------------------------------------------------------------- Zuordnung über MODELDT
def file_id_names():
    import json
    import os
    from pathlib import Path
    folder = os.environ.get('DW2_DATA_DIR') or Path(__file__).resolve().parents[2] / 'data'
    ids = json.loads((Path(folder) / 'native_file_ids_us.json').read_text())
    return ids, {v: k for k, v in ids.items()}


def digidata_row(table_bytes, row):
    """DigiData-Satz: (Modell-Datei-ID, [11 Animations-Datei-IDs])."""
    model_file = struct.unpack_from('<h', table_bytes, row + 6)[0]
    anims = list(struct.unpack_from('<11h', table_bytes, row + 8))
    return model_file, anims


def game_anim_slots(session, entries, digimon_id, model_name, repo=None):
    """Animationsdateien so, wie das Spiel sie für diese Digimon-ID lädt.

    Rückgabe: (slots {'A': Dateiname}, info). Leere slots, wenn die Tabelle nicht lesbar ist.
    """
    from .digimon_names import NameRepository
    info = {'source': 'none', 'model_file_match': None, 'unknown_ids': []}
    try:
        _, names = file_id_names()
        repo = repo or NameRepository(session, entries)
        entry, table = repo.lookup(digimon_id)
        record = table.record(digimon_id)
        model_file, anims = digidata_row(table.data, record.row)
    except (ValueError, OSError, KeyError) as exc:
        info['error'] = str(exc)
        return {}, info
    info['source'] = 'MODELDT'
    info['model_file'] = names.get(model_file, model_file)
    info['model_file_match'] = names.get(model_file) == model_name.upper()
    slots = {}
    for i, fid in enumerate(anims):
        if fid <= 0:
            continue
        name = names.get(fid)
        if name is None:
            info['unknown_ids'].append(fid)
            continue
        slots[SLOTS[i]] = name
    return slots, info
