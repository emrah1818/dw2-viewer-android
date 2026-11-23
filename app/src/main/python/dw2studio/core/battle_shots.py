"""Battle camera shots of DW2, reproduced from the PC port, and the per-Digimon adjustment.

dw2-pc-port, src/stag3000/camera.c (Stg30_CameraUpdate / Stg30_CameraDraw) and fighter.c:
- Fighter i (0-2 party, 3-5 enemies) stands at x = (i % 3) * 0xA00 - 0xA00, z = (i / 3) * 0x2800 - 0x1400,
  y = 0; party facing 0x800, enemies 0 (Stg30_FighterInit). PS1 axes: y down, 4096 = 360 degrees.
- The camera frame ("super") is RotMatrixYXZ(0, rotY, 0) moved to (originX, originY, originZ); the
  viewpoint (vpx, vpy, vpz) and reference point (vrx, vry, vrz) are in that frame (GsSetRefView2),
  projection H = 0x5DC (see SCREEN).
- Close-up (states 2-7): table by field_1E (battle_camera.closeup). Attacker shots 10-15: three
  random variants (Stg30_CamShotVariant). Target shots 16-21.
- From PC port 1.0, Mods/battle_camera.json (host/modconf.c) changes a Digimon's shots:
  vpz *= distance / 100, vpy -= height, vry -= target, rotY += angle; "closeup" holds the same keys
  for states 2-7.

`fits` projects a cylinder around the Digimon (its measured lowest / highest point and largest
horizontal distance from its origin over standby and attack poses) into each shot; `auto` finds the
smallest adjustment that keeps it on screen. The Studio preview draws the same eye / target points.
"""
import math

import numpy as np

H = 0x5DC
SCREEN = (640, 480)
# The battle screen is 320 x 480 with its centre at (160, 240) (Sys_State.centerX / centerY) and
# GsIDMATRIX2 doubling y: in camera units that is a 640 x 480 picture of square pixels, shown 4:3.
# Checked against the game's own model rectangles (bot command fbox, Gfx_ModelScreenBounds):
# x there = this x / 2, y = this y.
CLOSEUP_ROT = (682, 0, -682, 1365, 2048, 2730)
FORMAT = 1
KEYS = ('distance', 'height', 'target', 'angle')
LIMITS = {'distance': (25, 400), 'height': (-20000, 20000), 'target': (-20000, 20000), 'angle': (-4095, 4095)}


def fighter_pos(i):
    return ((i % 3) * 0xA00 - 0xA00, 0, (i // 3) * 0x2800 - 0x1400)


def fighter_facing(i):
    return 0x800 if i < 3 else 0


def _rot_y(a):
    t = a * 2 * math.pi / 4096
    c, s = math.cos(t), math.sin(t)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def shots(i, closeup_field=None):
    """Every camera setup the game uses for fighter I: [(name, frame dict)], before adjustment."""
    out = []
    if closeup_field is not None:
        from .battle_camera import closeup
        c = closeup(closeup_field)
        out.append(('closeup', {'origin': ((i % 3) * 0xA00 - 0xA00, 0, (i // 3) * 0x2800 - 0x1400),
                                'rotY': CLOSEUP_ROT[i], 'vp': (0, -0xC30, c['distance']),
                                'vr': (0, -c['look_height'], 0), 'kind': 'closeup'}))
    state = 10 + i
    for variant in range(3):   # Rand_Next() & 3: 0 and 3 give the default shot
        vpy, vpz, vry, rot = -0x514, 0x2EE0, -0x578, 0xAA
        ox, oz = (state - 10) * 0xA00 - 0xC80, -0x1400
        if variant == 1:
            rot, ox, vpz = 0x38, (state - 10) * 0xA00 - 0xA00, 0x34BC
        elif variant == 2:
            vpy, ox, oz, vpz = -0x1914, (state - 10) * 0xA00 - 0xA00, -0xF00, 0x34BC
        if state >= 13:
            rot, ox, oz = 0x800 - rot, ox - 0x1E00, -oz
        out.append((f'attack{variant}', {'origin': (ox, 0, oz), 'rotY': rot, 'vp': (0, vpy, vpz),
                                         'vr': (0, vry, 0), 'kind': 'shot'}))
    state = 16 + i
    if state < 19:
        rot, ox, oz = 0xAA, (state - 16) * 0xA00 - 0xA00, -0x1400
    else:
        rot, ox, oz = 0x755, (state - 19) * 0xA00 - 0xA00, 0x1400
    out.append(('target', {'origin': (ox, 0, oz), 'rotY': rot, 'vp': (0, -0x5DC, 0x2EE0),
                           'vr': (0, -0x640, 0), 'kind': 'shot'}))
    return out


def adjusted(frame, adj):
    """The port's Host_BattleCamAdjust on one frame."""
    if not adj:
        return frame
    f = dict(frame)
    vp, vr = list(frame['vp']), list(frame['vr'])
    vp[2] = int(vp[2] * adj.get('distance', 100) / 100)
    vp[1] -= adj.get('height', 0)
    vr[1] -= adj.get('target', 0)
    f.update(vp=tuple(vp), vr=tuple(vr), rotY=frame['rotY'] + adj.get('angle', 0))
    return f


def eye_target(frame):
    """World eye and look-at point (PS1 axes) of a frame."""
    r = _rot_y(frame['rotY'])
    o = np.asarray(frame['origin'], float)
    return r @ np.asarray(frame['vp'], float) + o, r @ np.asarray(frame['vr'], float) + o


def project(frame, points):
    """Screen coordinates (640 x 480 camera units, centre 0) and depth of world points (PS1 axes)."""
    eye, target = eye_target(frame)
    f = target - eye
    f /= np.linalg.norm(f)
    right = np.cross(np.array([0., 1., 0.]), f)
    if np.linalg.norm(right) < 1e-6:
        right = np.array([1., 0., 0.])
    right /= np.linalg.norm(right)
    down = np.cross(f, right)
    d = np.asarray(points, float) - eye
    z = d @ f
    return np.c_[H * (d @ right) / np.maximum(z, 1e-6), H * (d @ down) / np.maximum(z, 1e-6)], z


def cylinder(i, box, n=16):
    """World points (PS1 axes) of fighter I. BOX: (lowest y, highest y, radius) in up-positive model
    units: a cylinder; or (low, high, radius, points): the measured model points (y up, model axes),
    turned to the fighter's facing and moved to its spot."""
    if len(box) > 3 and box[3] is not None:
        pts = np.asarray(box[3], float) * np.array([1., -1., -1.])     # glTF axes -> PS1 model axes
        return (_rot_y(fighter_facing(i)) @ pts.T).T + np.asarray(fighter_pos(i), float)
    low, high, radius = box[:3]
    x, _, z = fighter_pos(i)
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n
        for y in (low, (low + high) / 2, high):
            pts.append((x + radius * math.cos(a), -y, z + radius * math.sin(a)))
    pts.append((x, -high, z))
    return np.asarray(pts)


def fits(frame, i, box, margin=0.96):
    """(fits, share of the screen the cylinder uses); fits = every point in front and on screen."""
    xy, z = project(frame, cylinder(i, box))
    half = np.array(SCREEN) / 2 * margin
    inside = bool(np.all(z > 0) and np.all(np.abs(xy) <= half))
    use = float(np.max(np.abs(xy) / (np.array(SCREEN) / 2))) if np.all(z > 0) else math.inf
    return inside, use


def check(box, adj=None, closeup_adj=None, closeup_field=None, positions=range(6)):
    """Every shot of every battle position: [{'position', 'shot', 'fits', 'use'}]."""
    rows = []
    for i in positions:
        for name, frame in shots(i, closeup_field):
            a = closeup_adj if frame['kind'] == 'closeup' else adj
            ok, use = fits(adjusted(frame, a), i, box)
            rows.append({'position': i, 'shot': name, 'fits': ok, 'use': round(use, 3)})
    return rows


def auto(box, reference_box=None):
    """Smallest adjustment that keeps BOX in every attack / target shot of every position.

    The look-at and view height follow the Digimon's middle once it is taller than the shot's own
    look-at height; then the distance grows in 5 % steps. A Digimon that already fits keeps the
    game's shots (None)."""
    if all(r['fits'] for r in check(box) if r['shot'] != 'closeup'):
        return None
    low, high = box[0], box[1]
    middle = (low + high) / 2
    lift = int(max(0, middle - 0x578))
    adj = {'distance': 100, 'height': lift, 'target': lift, 'angle': 0}
    for d in range(100, 401, 5):
        adj['distance'] = d
        if all(r['fits'] for r in check(box, adj)):
            return adj
    adj['distance'] = 400
    return adj


def auto_closeup(box, field):
    """Same for the close-up at FIELD_1E."""
    if all(r['fits'] for r in check(box, closeup_field=field) if r['shot'] == 'closeup'):
        return None
    from .battle_camera import closeup
    c = closeup(field)
    lift = int(max(0, (box[0] + box[1]) / 2 - c['look_height']))
    adj = {'distance': 100, 'height': 0, 'target': lift, 'angle': 0}
    for d in range(100, 401, 5):
        adj['distance'] = d
        rows = [r for r in check(box, closeup_adj=adj, closeup_field=field) if r['shot'] == 'closeup']
        if all(r['fits'] for r in rows):
            return adj
    adj['distance'] = 400
    return adj


def validate(entry):
    """One Digimon's setting as written to Mods/battle_camera.json."""
    if not isinstance(entry, dict):
        raise ValueError('Kameraeinstellung: Objekt erwartet.')
    out = {}
    for key in KEYS:
        if key in entry and entry[key] is not None:
            v = entry[key]
            lo, hi = LIMITS[key]
            if type(v) is not int or not lo <= v <= hi:
                raise ValueError(f'Kamera „{key}“: ganze Zahl {lo}–{hi}.')
            out[key] = v
    if entry.get('closeup'):
        out['closeup'] = {k: v for k, v in validate(entry['closeup']).items() if k != 'closeup'}
    return out


def dumps(cams):
    import json
    return json.dumps({'format': FORMAT, 'digimon': {str(k): validate(v) for k, v in sorted(cams.items())}},
                      indent=1) + '\n'


def loads(text):
    import json
    doc = json.loads(text)
    if not isinstance(doc, dict) or type(doc.get('format')) is not int or doc['format'] < 1:
        raise ValueError('battle_camera.json: Feld "format" fehlt.')
    if doc['format'] > FORMAT:
        raise ValueError(f'battle_camera.json hat Format {doc["format"]}; dieses Studio kennt Format {FORMAT}.')
    out = {}
    for k, v in (doc.get('digimon') or {}).items():
        ident = int(k)
        if not 1 <= ident <= 255:
            raise ValueError(f'battle_camera.json: Digimon-ID {ident} außerhalb 1–255.')
        out[ident] = validate(v)
    return out


def model_box(model, animations, radius_from=1, points=False):
    """(lowest y, highest y, horizontal radius), y up. Heights over every given animation file;
    the radius over the first RADIUS_FROM files only (the standby pose: an attack lunge moves the
    Digimon out of its spot, which no shot of the game keeps in frame)."""
    import struct
    from .native_model import NativeModel
    from .native_gltf import Animation
    from .rig_animation import parents_from_depths, D
    m = NativeModel(model)
    depths = struct.unpack_from(f'<{m.bone_count}I', model, 12 + 12 * m.bone_count)
    parents = parents_from_depths(list(depths))
    verts = []
    for part in m.parts:
        v = np.asarray([struct.unpack_from('<hhh', model, part.vertices + 6 + j * 6)
                        for j in range(part.vertex_count)], float)
        verts.append(np.c_[v @ D, np.ones(len(v))] if len(v) else np.zeros((0, 4)))
    low, high, radius = math.inf, -math.inf, 0.
    sample = []
    for n_file, data in enumerate(animations):
        a = Animation(data, m.bone_count)
        for clip in range(len(a.clips)):
            count = len(a.clips[clip].indices)
            for f in range(0, count, max(1, count // 12)):
                local = a.local_pose(clip, f)
                world = []
                for b in range(m.bone_count):
                    world.append(local[b] if parents[b] < 0 else world[parents[b]] @ local[b])
                    if len(verts[b]):
                        p = verts[b] @ world[b].T
                        low, high = min(low, p[:, 1].min()), max(high, p[:, 1].max())
                        if n_file < radius_from:
                            radius = max(radius, float(np.sqrt(p[:, 0] ** 2 + p[:, 2] ** 2).max()))
                            if points:
                                sample.append(p[::max(1, len(p) // 24), :3])
    if not math.isfinite(low):
        raise ValueError('Modell ohne Bewegungsdaten: Größe nicht messbar.')
    if points:
        pts = np.concatenate(sample) if sample else np.zeros((0, 3))
        # the highest point of the attack poses, above the model's centre, stays in the check
        pts = np.r_[pts, [[0., high, 0.], [0., low, 0.]]]
        return float(low), float(high), radius, pts
    return float(low), float(high), radius


def preview(frame, i):
    """Eye and target relative to fighter I in its own model axes, glTF convention (y up, z flipped),
    for the Studio's 3D view."""
    eye, target = eye_target(frame)
    home = np.asarray(fighter_pos(i), float)
    r = _rot_y(fighter_facing(i))
    flip = np.array([1., -1., -1.])
    to_model = lambda p: (r.T @ (p - home)) * flip
    return {'eye': [round(float(v), 1) for v in to_model(eye)],
            'target': [round(float(v), 1) for v in to_model(target)],
            'projection': H, 'screen': list(SCREEN)}
