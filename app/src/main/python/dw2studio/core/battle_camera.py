"""Battle close-up camera and hit-effect height of a Digimon (MODELDT, per species).

dw2-pc-port (read only):
- src/stag3000/camera.c, Stg30_CameraUpdate states 2-7: h = field_1E < 0x300 ? 0 : field_1E - 0x300,
  h /= 256, then Stg30_CloseUpVpz[h] (distance) and Stg30_CloseUpVry[h] (look-at height), tables of
  nine. The index is not checked, so field_1E must stay below 0x300 + 9 * 256 = 0xC00.
- DigiData (include/main/156C.h): field_1E s16 at +0x1E, hitFxOffsetY s16 at +0x20 (the height the
  hit effects of stag0000/3000/3500 start at, Digi_GetHitFxOffsetY).
Calibration (202 original Digimon of the US game, measured with this module): field_1E follows the
standing height (r = 0.76); a fit gives 0.5479 per unit of standing height and 0.0760 per unit of
attack reach; hitFxOffsetY = 0.6130 * field_1E (r = 0.79). The automatic value starts from the
replaced slot's own (hand-tuned) values and adds only the height difference.
"""
import struct
import numpy as np

STAND, REACH, HIT = 0.5479, 0.0760, 0.6130
FIELD_MAX = 0x300 + 9 * 256 - 1     # last value the nine-entry tables cover
FIELD_MIN, HIT_MIN, HIT_MAX = 0x100, 0, 0x900


# src/stag3000/camera.c (Stg30_CameraUpdate states 2-7, Stg30_CameraDraw): viewpoint (0, -0xC30, vpz),
# reference point (0, vry, 0) in the fighter's frame, projection 0x5DC (Stg30_CameraInit) on 320x240.
CLOSEUP_VPZ = (7495, 7595, 8620, 9064, 9944, 11496, 12728, 14424, 17096)
CLOSEUP_VRY = (-304, -304, -572, -596, -728, -832, -888, -1008, -1176)
CLOSEUP_VPY = -0xC30
PROJECTION = 0x5DC


def closeup(field):
    """The command / target close-up for FIELD_1E in native units (y up): what the preview shows."""
    b = bucket(field)
    if not 0 <= b < 9:
        raise ValueError('Kamerawert außerhalb der 9 Stufen.')
    return {'bucket': b, 'distance': CLOSEUP_VPZ[b], 'eye_height': -CLOSEUP_VPY, 'look_height': -CLOSEUP_VRY[b],
            'projection': PROJECTION, 'screen': [640, 480]}


def bucket(field):
    h = 0 if field < 0x300 else field - 0x300
    return h // 256


def _pose_heights(model, animation, clip=0, frames=None):
    from .native_model import NativeModel
    from .native_gltf import Animation
    from .rig_animation import parents_from_depths, D
    m = NativeModel(model)
    depths = struct.unpack_from(f'<{m.bone_count}I', model, 12 + 12 * m.bone_count)
    parents = parents_from_depths(list(depths))
    a = Animation(animation, m.bone_count)
    if clip >= len(a.clips):
        return []
    verts = []
    for part in m.parts:
        v = np.asarray([struct.unpack_from('<hhh', model, part.vertices + 6 + j * 6) for j in range(part.vertex_count)], float)
        verts.append(np.c_[v @ D, np.ones(len(v))] if len(v) else np.zeros((0, 4)))
    count = len(a.clips[clip].indices)
    out = []
    for f in (range(count) if frames is None else [f for f in frames if f < count]):
        local = a.local_pose(clip, f)
        world, ys = [], []
        for i in range(m.bone_count):
            world.append(local[i] if parents[i] < 0 else world[parents[i]] @ local[i])
            if len(verts[i]):
                ys.append((verts[i] @ world[i].T)[:, 1])
        y = np.concatenate(ys) if ys else np.zeros(1)
        out.append((float(y.min()), float(y.max())))
    return out


def measure(model, standby, attacks):
    """(standing height, attack reach) above the standby pose's lowest point."""
    pose = _pose_heights(model, standby, 0, [0])
    if not pose:
        raise ValueError('Standby-Animation ohne Bild.')
    ground, top = pose[0]
    reach = top
    for animation in attacks:
        for low, high in _pose_heights(model, animation, 0):
            reach = max(reach, high)
    return top - ground, reach - ground


def suggest(slot_field, slot_hit, slot_heights, new_heights):
    stand = new_heights[0] - slot_heights[0]
    reach = new_heights[1] - slot_heights[1]
    field = int(round(slot_field + STAND * stand + REACH * reach))
    field = max(FIELD_MIN, min(FIELD_MAX, field))
    hit = int(round(slot_hit + HIT * (field - slot_field)))
    return field, max(HIT_MIN, min(HIT_MAX, hit))


class CameraRepository:
    def __init__(self, session, entries):
        from .digimon_names import NameRepository
        self.session, self.entries = session, entries
        self.names = NameRepository(session, entries)

    def values(self, digimon, original=False):
        entry, table = self.names.lookup(digimon)
        row = table.record(digimon).row
        data = self.session.original(entry) if original else self.session.current(entry)
        field, hit = struct.unpack_from('<hh', data, row + 0x1E)
        return {'field_1E': field, 'hit_fx_y': hit, 'bucket': bucket(field)}

    def set(self, digimon, field, hit, label=None):
        if type(field) is not int or not FIELD_MIN <= field <= FIELD_MAX:
            raise ValueError(f'Kamerahöhe muss {FIELD_MIN}–{FIELD_MAX} sein (Kameratabelle des Spiels hat 9 Stufen).')
        if type(hit) is not int or not HIT_MIN <= hit <= HIT_MAX:
            raise ValueError(f'Treffereffekt-Höhe muss {HIT_MIN}–{HIT_MAX} sein.')
        entry, table = self.names.lookup(digimon)
        row = table.record(digimon).row
        before = self.session.current(entry)
        out = bytearray(before)
        struct.pack_into('<hh', out, row + 0x1E, field, hit)
        if bytes(out) == before:
            return False
        self.session.stage(entry, bytes(out), label or f'Kamera / Treffereffekt #{digimon:03}')
        return True
