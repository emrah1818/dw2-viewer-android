"""Encode DW3 skeletons, rigid geometry and sampled motions as native DW2 files.

Source coordinates/matrices are emitted by the bundled DW3 motion player.
The DW2 matrix stream is written row-major, matching Anim_StepModelAnim.
This encoder needs the variable-size PC-port loader; it is not a PS1 disc writer.
"""
from pathlib import Path
import math
import struct
import numpy as np
from PIL import Image
from .native_model import NativeModel
from .native_anim import parse_anim_file


def triangles(bone):
    return [(face, (0, fan, fan+1)) for face in bone['faces']
            for fan in range(1, len(face['indices'])-1)]


MAX_DEPTH = 7          # depth field 0..7: eight DW2 hierarchy levels
MAX_PART = 256         # vertex / normal / triangle indices are one byte per part
MAX_PARTS = 64
CREASE = 0.5           # cos 60 degrees: sharper bends keep a hard edge


def bone_chunks(bone):
    """Triangles of one DW3 bone in parts of at most 256 triangles and 256 vertices.

    A native vertex index is one byte, so a bone with more vertices is split into sibling parts
    that share the bone's transform; every part keeps only the vertices it uses."""
    tris = triangles(bone)
    if not tris:
        return [[]]
    chunks, cur, used = [], [], set()
    for tri in tris:
        face, corners = tri
        ids = {face['indices'][k] for k in corners}
        if cur and (len(cur) >= MAX_PART or len(used | ids) > MAX_PART):
            chunks.append(cur)
            cur, used = [], set()
        cur.append(tri)
        used |= ids
    chunks.append(cur)
    return chunks


def plan(source):
    """Native part list: [{'src', 'depth', 'chain', 'chunk'}].

    Bones deeper than the eight DW2 levels are attached to their ancestor on level 7 (depth 6),
    and their animation matrix becomes the product of the skipped local matrices ('chain'), so
    the pose stays exact. Large bones become several sibling parts (bone_chunks)."""
    bones = source['bones']
    if not 2 <= len(bones) <= 65 or bones[0]['parent'] != -1:
        raise ValueError('DW3-Skelett benötigt 1–64 Körperknochen und eine Wurzel.')
    children = [[] for _ in bones]
    for i, b in enumerate(bones[1:], 1):
        p = b['parent']
        if type(p) is not int or not 0 <= p < i:
            raise ValueError('Ungültige DW3-Knochenhierarchie.')
        children[p].append(i)
    nodes = []

    def visit(i, depth, chain):
        if depth > MAX_DEPTH:
            depth = MAX_DEPTH          # chain: skipped ancestors below level 7, then this bone
        else:
            chain = [i]
        # The final copy goes immediately before the children: DW2's depth stack then uses the
        # same source transform for their parent.
        for k in range(len(bone_chunks(bones[i]))):
            nodes.append({'src': i, 'depth': depth, 'chain': list(chain), 'chunk': k})
        for child in children[i]:
            if depth >= MAX_DEPTH:
                visit(child, depth + 1, chain + [child])
            else:
                visit(child, depth + 1, [child])
    for child in children[0]:
        visit(child, 0, [child])
    if len(nodes) > MAX_PARTS:
        raise ValueError(f'Das Modell braucht {len(nodes)} DW2-Teile (höchstens {MAX_PARTS}): zu viele Knochen '
                         'oder zu große Teilmeshes.')
    return nodes


def hierarchy(source):
    nodes = plan(source)
    return [n['src'] for n in nodes], [n['depth'] for n in nodes]


def limits_report(source):
    """What the conversion has to do to fit DW2's format limits (shown before export)."""
    nodes = plan(source)
    bones = source['bones']
    deep = sorted({n['src'] for n in nodes if len(n['chain']) > 1})
    split = sorted({n['src'] for n in nodes if len(bone_chunks(bones[n['src']])) > 1})
    return {'parts': len(nodes), 'max_parts': MAX_PARTS, 'flattened_bones': deep, 'split_bones': split,
            'max_depth': max(n['depth'] for n in nodes) + 1}


def source_matrices(source, motion):
    rows = np.asarray(source['motions'][motion]['frames'], dtype=float)
    if rows.ndim != 3 or rows.shape[1:] != (len(source['bones']), 16) or not np.isfinite(rows).all():
        raise ValueError('Ungültige DW3-Motionsdaten.')
    return rows.reshape(len(rows), len(source['bones']), 4, 4).transpose(0, 1, 3, 2)


# DW2 keeps sizes closer together than DW3: over the 106 species both games share (same model code),
# DW2 standing height = 72.47 * DW3 standing height ** 0.40 (fitted on the USA discs; median
# deviation 12 %). Used for species DW2 does not have, so a Rookie stays small and a Mega large.
SIZE_A, SIZE_B = 72.4667, 0.3999
# 'DW3 proportions': one factor for every model, so DW3's own size differences stay (a Renamon
# clearly taller than an Agumon). 0.919 = median DW2/DW3 height of the 12 shared species below
# 1700 DW3 units (Agumon, Patamon, Betamon ...), so small Digimon match DW2 in both modes.
SIZE_LINEAR = 0.9188


def standing_height(points):
    return float(np.ptp(np.asarray(points)[:, 1]))


def source_height(source):
    """Standing height of a DW3 model (first frame of its first motion, axis 1 up)."""
    src_local = source_matrices(source, 0)[0]
    world, pts = [], []
    for i, b in enumerate(source['bones']):
        world.append(src_local[i] if i == 0 else world[b['parent']] @ src_local[i])
        if b['vertices']:
            v = np.asarray(b['vertices'], dtype=float)
            pts.extend((np.c_[v, np.ones(len(v))] @ world[i].T)[:, :3])
    return standing_height(pts)


def natural_scale(source, dw2_height=None, mode='dw2'):
    """Scale that gives a DW3 model its size in battle.
    mode 'dw2': DW2's proportions: the height of the same species in DW2 when the game has it
    (DW2_HEIGHT), otherwise the fitted size curve (large Digimon closer to small ones, as in DW2).
    mode 'dw3': DW3's proportions, one factor for all (SIZE_LINEAR)."""
    h3 = source_height(source)
    if h3 < 1e-6:
        raise ValueError('DW3-Modell ohne Höhe.')
    if mode == 'dw3':
        return SIZE_LINEAR
    if mode != 'dw2':
        raise ValueError('Größenmaßstab: dw2 oder dw3.')
    target = dw2_height if dw2_height else SIZE_A * h3 ** SIZE_B
    return float(target / h3)


def model_height(target, target_animation):
    """Standing height of a native DW2 model in its first pose."""
    from .native_gltf import Animation
    from .rig_animation import parents_from_depths, D
    model = NativeModel(target)
    depths = struct.unpack_from(f'<{model.bone_count}I', target, 12+12*model.bone_count)
    local = Animation(target_animation, model.bone_count).local_pose()
    parents = parents_from_depths(list(depths))
    world, points = [], []
    for i, part in enumerate(model.parts):
        world.append(local[i] if parents[i] < 0 else world[parents[i]] @ local[i])
        v = np.asarray([struct.unpack_from('<hhh', target, part.vertices+6+j*6) for j in range(part.vertex_count)]) @ D
        points.extend((np.c_[v, np.ones(len(v))] @ world[i].T)[:, :3])
    return standing_height(points)


def fit_scale(source, target, target_animation):
    from .native_gltf import Animation
    from .rig_animation import parents_from_depths, D
    model = NativeModel(target)
    depths = struct.unpack_from(f'<{model.bone_count}I', target, 12+12*model.bone_count)
    local = Animation(target_animation, model.bone_count).local_pose()
    parents = parents_from_depths(list(depths))
    world, points = [], []
    for i, part in enumerate(model.parts):
        world.append(local[i] if parents[i] < 0 else world[parents[i]] @ local[i])
        v = np.asarray([struct.unpack_from('<hhh', target, part.vertices+6+j*6) for j in range(part.vertex_count)]) @ D
        points.extend((np.c_[v, np.ones(len(v))] @ world[i].T)[:, :3])
    src_local = source_matrices(source, 0)[0]
    src_world, src_points = [], []
    for i, b in enumerate(source['bones']):
        src_world.append(src_local[i] if i == 0 else src_world[b['parent']] @ src_local[i])
        if b['vertices']:
            v = np.asarray(b['vertices'], dtype=float)
            src_points.extend((np.c_[v, np.ones(len(v))] @ src_world[i].T)[:, :3])
    # Same standing height as the replaced Digimon (axis 1 is up after D). The largest extent
    # mixed axes: a target long front-to-back (ears, tail) made an upright source far too tall.
    height = np.ptp(np.asarray(points)[:, 1])
    source_height = np.ptp(np.asarray(src_points)[:, 1])
    if height < 1e-6 or source_height < 1e-6:
        size = np.ptp(np.asarray(points), axis=0).max()
        return float(size / max(np.ptp(np.asarray(src_points), axis=0).max(), 1e-9))
    return float(height / source_height)


def face_plan(source, face):
    """DW3 FaceRects (dw3_fighters._face) in source-image pixels.

    A rect's x / w count VRAM halfwords from the model's texture origin (tex_origin); the image that
    shows it is the 4-bit page at that VRAM spot whose polygons cover the rect. Returns
    [{'slot', 'image', 'dst', 'size', 'frames'}] (slot 0/1 eyes, 2.. cycling parts) and the reasons
    for rects that cannot be carried over."""
    pages, origin = source.get('pages'), source.get('tex_origin')
    if not face:
        return [], []
    if not pages or not origin:
        return [], ['DW3-Modell mit dem neuen Konverter erneut öffnen (Seiteninformation fehlt).']
    used = {}   # per image the UV rectangles of its polygons
    for b in source['bones']:
        for f in b['faces']:
            us, vs = [u for u, _ in f['uv']], [v for _, v in f['uv']]
            used.setdefault(f['image'], []).append((min(us), min(vs), max(us), max(vs)))
    out, skipped = [], []
    for slot, r in enumerate(face):
        if not r['w'] or not r['h']:
            continue
        X, Y = origin[0] + r['x'], origin[1] + r['y']
        found = None
        for i, (tp, clut) in enumerate(pages):
            if tp < 0 or (tp >> 7) & 3:
                continue
            px, py = (tp & 15) * 64, (tp >> 4 & 1) * 256
            if not (px <= X and X + r['w'] <= px + 64 and py <= Y and Y + r['h'] <= py + 256):
                continue
            u0, v0 = (X - px) * 4, Y - py
            # polygons that sample the rect: an eye is often one quad whose corners lie on or
            # outside the rect's edges (DW3 Greymon), so corners inside it are not required
            hits = sum(a < u0 + r['w'] * 4 and u0 < c and b < v0 + r['h'] and v0 < d for a, b, c, d in used.get(i, ()))
            frames = []
            for fx, fy in r['frames']:
                FX, FY = origin[0] + fx, origin[1] + fy
                if not (px <= FX and FX + r['w'] <= px + 64 and py <= FY and FY + r['h'] <= py + 256):
                    frames = None
                    break
                frames.append(((FX - px) * 4, FY - py))
            if frames and (found is None or hits > found[0]):
                found = (hits, {'slot': slot, 'image': i, 'dst': (u0, v0), 'size': (r['w'] * 4, r['h']), 'frames': frames})
        if found is None or not found[0]:
            skipped.append(f'Gesichtsteil {slot}: keine Seite des Modells zeigt dieses Rechteck.')
            continue
        out.append(found[1])
    return out, skipped


ATLAS_W, ATLAS_H = 128, 224    # drawable texels of the native 4-bit slot (the last 32 rows: CLUTs)
PAD = 1                        # free texels between packed pages: no bleeding when HD filters


def charts(source, sizes, face=None):
    """The pieces of each page the model uses: polygons that share a UV corner form one chart; the
    charts' rectangles (one texel of margin) that touch are merged, as are those under a face
    rect (its frames are copied there in VRAM, so that chart is never rotated).
    Returns [{'image', 'box': (x0, y0, w, h), 'face': bool}] and {id(face_dict): chart}."""
    out, owner = [], {}
    by_image = {}
    for b in source['bones']:
        for f in b['faces']:
            by_image.setdefault(f['image'], []).append(f)
    face = face or []
    for img in sorted(set(by_image) | {p['image'] for p in face}):
        faces = by_image.get(img, [])
        iw, ih = sizes[img]
        parent = list(range(len(faces)))
        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]; a = parent[a]
            return a
        corner = {}
        for i, f in enumerate(faces):
            for uv in f['uv']:
                j = corner.setdefault(tuple(uv), i)
                parent[find(i)] = find(j)
        boxes = {}
        for i, f in enumerate(faces):
            r = boxes.setdefault(find(i), [1 << 30, 1 << 30, -1, -1, False, []])
            for u, v in f['uv']:
                r[0], r[1], r[2], r[3] = min(r[0], u), min(r[1], v), max(r[2], u), max(r[3], v)
            r[5].append(f)
        items = list(boxes.values())
        for p in (q for q in face if q['image'] == img):
            (u0, v0), (w, h) = p['dst'], p['size']
            items.append([u0, v0, u0 + w - 1, v0 + h - 1, True, []])
        # one texel of margin, then merge rectangles that touch until none do
        rects = [[max(0, int(math.floor(a)) - 1), max(0, int(math.floor(b_)) - 1),
                  min(iw, int(math.ceil(c)) + 2), min(ih, int(math.ceil(d)) + 2), fc, fs] for a, b_, c, d, fc, fs in items]
        merged = True
        while merged:
            merged = False
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    a, b_ = rects[i], rects[j]
                    if a[0] < b_[2] and b_[0] < a[2] and a[1] < b_[3] and b_[1] < a[3]:
                        rects[i] = [min(a[0], b_[0]), min(a[1], b_[1]), max(a[2], b_[2]), max(a[3], b_[3]),
                                    a[4] or b_[4], a[5] + b_[5]]
                        del rects[j]
                        merged = True
                        break
                if merged:
                    break
        for x0, y0, x1, y1, fc, fs in rects:
            for f in fs:
                owner[id(f)] = len(out)
            out.append({'image': img, 'box': (x0, y0, max(1, x1 - x0), max(1, y1 - y0)), 'face': fc})
    return out, owner


class _Shelves:
    """Skyline bottom-left packing in the 128 x 224 native area (each rectangle where its top edge
    ends lowest, then leftmost), PAD texels apart."""
    def __init__(self):
        self.sky = [[0, 0, ATLAS_W]]            # segments: x, height so far, width

    def place(self, w, h, align=1):
        if w > ATLAS_W or h > ATLAS_H:
            return None
        best = None
        xs = sorted({sg[0] for sg in self.sky} | {-(-sg[0] // align) * align for sg in self.sky})
        for x in xs:
            if x % align or x + w > ATLAS_W:
                continue
            top = max(sg[1] for sg in self.sky if sg[0] < x + w and x < sg[0] + sg[2])
            if top + h > ATLAS_H:
                continue
            if best is None or (top + h, x) < (best[1] + h, best[0]):
                best = (x, top)
        if best is None:
            return None
        x, y = best
        x1, top = min(ATLAS_W, x + w + PAD), y + h + PAD
        out = []
        for sx, sh, sw in self.sky:            # cut [x, x1) out, raise it to top
            if sx + sw <= x or x1 <= sx:
                out.append([sx, sh, sw])
                continue
            if sx < x:
                out.append([sx, sh, x - sx])
            if sx + sw > x1:
                out.append([x1, sh, sx + sw - x1])
        out.append([x, top, x1 - x])
        out.sort()
        merged = []
        for sg in out:
            if merged and merged[-1][1] == sg[1] and merged[-1][0] + merged[-1][2] == sg[0]:
                merged[-1][2] += sg[2]
            else:
                merged.append(sg)
        self.sky = merged
        return x, y


def tile_uv(tile, u, v):
    """Source texel (u, v) of a chart -> its atlas texel (texel centres kept in place)."""
    x, y, tw, th, cx, cy, cw, ch, rot = tile
    fu, fv = (u - cx + .5) / cw, (v - cy + .5) / ch
    if rot:                                  # stored transposed: source v runs along atlas x
        return (x + min(tw - 1, max(0, int(fv * tw))), y + min(th - 1, max(0, int(fu * th))))
    return (x + min(tw - 1, max(0, int(fu * tw))), y + min(th - 1, max(0, int(fv * th))))


def _face_box(tile, part):
    """The 4-texel aligned atlas rectangle a face rect covers in its chart's tile (a transposed
    tile holds it transposed: the frames are stored the same way, so the DR_MOVE copy still fits)."""
    x, y, tw, th, cx, cy, cw, ch, rot = tile
    (u0, v0), (w, h) = part['dst'], part['size']
    if rot:
        a0, a1 = (v0 - cy) * tw / ch, (v0 + h - cy) * tw / ch
        b0, b1 = (u0 - cx) * th / cw, (u0 + w - cx) * th / cw
    else:
        a0, a1 = (u0 - cx) * tw / cw, (u0 + w - cx) * tw / cw
        b0, b1 = (v0 - cy) * th / ch, (v0 + h - cy) * th / ch
    ax0 = (x + int(math.floor(a0))) // 4 * 4
    ax1 = -(-(x + int(math.ceil(a1))) // 4) * 4
    ay0, ay1 = y + int(math.floor(b0)), y + int(math.ceil(b1))
    return ax0, ay0, max(ax1, ax0 + 4) - ax0, max(ay1, ay0 + 1) - ay0


def layout(chart_list, face=None):
    """Pack every chart at one common scale (the largest that fits, at most 1: the 1x atlas never
    magnifies), so no chart is squeezed more in one direction than in the other; a chart may be
    stored transposed. Returns (scale, tiles, frame_slots):
    tiles[c] = (x, y, w, h, cx, cy, cw, ch, rotated), frame_slots[p] = three (x, y) for face
    part p (copied by DR_MOVE, so x is 4-texel aligned)."""
    face = face or []
    def attempt(s, policy):
        shelves, tiles = _Shelves(), [None] * len(chart_list)
        dims = []
        for c in chart_list:
            cw, ch = c['box'][2:]
            w, h = max(1, round(cw * s)), max(1, round(ch * s))
            rot = ((policy == 'wide' and h > w) or (policy == 'tall' and w > h) or w > ATLAS_W)
            dims.append((h, w, rot) if rot else (w, h, rot))
        for i in sorted(range(len(chart_list)), key=lambda i: (-max(dims[i][:2]), -dims[i][0] * dims[i][1])):
            w, h, rot = dims[i]
            at = shelves.place(w, h)
            if at is None:
                return None
            tiles[i] = (at[0], at[1], w, h, *chart_list[i]['box'], rot)
        slots = []
        for part in face:
            c = next(i for i, ch_ in enumerate(chart_list) if ch_['face'] and ch_['image'] == part['image'] and
                     ch_['box'][0] <= part['dst'][0] and ch_['box'][1] <= part['dst'][1] and
                     part['dst'][0] + part['size'][0] <= ch_['box'][0] + ch_['box'][2] and
                     part['dst'][1] + part['size'][1] <= ch_['box'][1] + ch_['box'][3])
            _, _, pw, ph = _face_box(tiles[c], part)
            got = []
            for _ in range(3):
                at = shelves.place(pw, ph, 4)
                if at is None or pw > 255 * 4:
                    return None
                got.append(at)
            slots.append((c, got))
        return tiles, slots
    best = None
    for policy in ('need', 'wide', 'tall'):
        got = attempt(1.0, policy)
        if got is not None:
            return 1.0, got[0], got[1]
        lo, hi, keep = 0.0, 1.0, None
        for _ in range(20):
            mid = (lo + hi) / 2
            got = attempt(mid, policy)
            if got is None:
                hi = mid
            else:
                lo, keep = mid, got
        if keep is not None and (best is None or lo > best[0]):
            best = (lo, keep)
    if best is None:
        raise ValueError('Texturseiten passen nicht in den 128×224-Atlas.')
    return best[0], best[1][0], best[1][1]


def _load_pages(source, folder):
    names = source['images']
    if not 1 <= len(names) <= 64:
        raise ValueError('Nicht unterstützte Anzahl Texturseiten.')
    pages = []
    for name in names:
        path = (Path(folder)/name).resolve()
        if not path.is_relative_to(Path(folder).resolve()):
            raise ValueError('Texturpfad außerhalb des DW3-Modells.')
        with Image.open(path) as image:
            pages.append(image.convert('RGBA'))
    return pages


def chart_triangles(source, owner, chart):
    """(source UV corners, face) of every fan triangle drawn from CHART, as the encoder emits them."""
    out = []
    for b in source['bones']:
        for f in b['faces']:
            if owner.get(id(f)) != chart:
                continue
            uv = f['uv']
            for fan in range(1, len(uv) - 1):
                out.append(((uv[0], uv[fan], uv[fan + 1]), f))
    return out


def render_tile(page, tile, tris, k, dilate=True):
    """The HD picture of one chart (tile w*K x h*K, RGBA) as the game samples it.

    The game's UVs are the source UVs rounded to the 1x atlas grid (tile_uv): a polygon corner moves
    by up to half an atlas texel. A plain upscale of the source would then show the polygon a strip of
    its neighbour texels (the bright edge lines) and shift its picture. Here every HD pixel under a
    triangle is mapped back through that triangle (atlas corners -> exact source corners, barycentric)
    to the source texel the original polygon shows there, so the game's sample positions read the
    original texels. Pixels under no triangle (gaps between polygons, the margin) take the colour of
    the nearest covered pixel (DILATE), so filtering at an edge never reaches unrelated texels."""
    x, y, tw, th, cx, cy, cw, ch, rot = tile
    W, H = tw * k, th * k
    src = np.asarray(page).astype(np.uint8)
    region = page.crop((cx, cy, cx + cw, cy + ch))
    if rot:
        region = region.transpose(Image.Transpose.TRANSPOSE)
    base = np.asarray(region.resize((W, H), Image.Resampling.NEAREST)).copy()
    out = base.copy()
    best = np.full((H, W), -np.inf)
    for (s0, s1, s2), _ in tris:
        S = np.asarray([s0, s1, s2], float)
        A = np.asarray([tile_uv(tile, *s0), tile_uv(tile, *s1), tile_uv(tile, *s2)], float)
        A = (A - (x, y)) * k                                  # HD pixel units, tile origin
        m = np.array([[A[1, 0] - A[0, 0], A[2, 0] - A[0, 0]], [A[1, 1] - A[0, 1], A[2, 1] - A[0, 1]]])
        det = np.linalg.det(m)
        x0, x1 = int(max(0, np.floor(A[:, 0].min()) - 1)), int(min(W, np.ceil(A[:, 0].max()) + 1))
        y0, y1 = int(max(0, np.floor(A[:, 1].min()) - 1)), int(min(H, np.ceil(A[:, 1].max()) + 1))
        if x1 <= x0 or y1 <= y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1) + .5, np.arange(y0, y1) + .5)
        lo_u, hi_u = S[:, 0].min(), S[:, 0].max()
        lo_v, hi_v = S[:, 1].min(), S[:, 1].max()
        if abs(det) < 1e-9:      # degenerate in the atlas (a sliver): the source triangle's centre colour
            t = S.mean(0)
            col = src[int(min(max(t[1], lo_v), max(lo_v, hi_v - 1e-3))), int(min(max(t[0], lo_u), max(lo_u, hi_u - 1e-3)))]
            near = (np.abs(gx - A[:, 0].mean()) <= max(1, np.ptp(A[:, 0]) / 2 + .5)) & \
                   (np.abs(gy - A[:, 1].mean()) <= max(1, np.ptp(A[:, 1]) / 2 + .5))
            sel = near & (best[y0:y1, x0:x1] < -1)
            out[y0:y1, x0:x1][sel] = col
            best[y0:y1, x0:x1][sel] = -1
            continue
        inv = np.linalg.inv(m)
        dx, dy = gx - A[0, 0], gy - A[0, 1]
        b1 = inv[0, 0] * dx + inv[0, 1] * dy
        b2 = inv[1, 0] * dx + inv[1, 1] * dy
        b0 = 1 - b1 - b2
        inside = np.minimum(np.minimum(b0, b1), b2)            # > 0: inside, edge = 0
        # a pixel half outside an edge still counts (the GPU covers it): within 0.75 px of the triangle
        slack = 0.75 / max(np.sqrt(abs(det)), 1e-9)
        sel = (inside > -slack) & (inside > best[y0:y1, x0:x1])
        if not sel.any():
            continue
        tu = b0 * S[0, 0] + b1 * S[1, 0] + b2 * S[2, 0]
        tv = b0 * S[0, 1] + b1 * S[1, 1] + b2 * S[2, 1]
        # the texels the original polygon shows: [min, max) of its UVs (PS1: the far edge excluded)
        tu = np.clip(tu, lo_u, max(lo_u, hi_u - 1e-3)).astype(int)
        tv = np.clip(tv, lo_v, max(lo_v, hi_v - 1e-3)).astype(int)
        tu = np.clip(tu, 0, src.shape[1] - 1)
        tv = np.clip(tv, 0, src.shape[0] - 1)
        block = out[y0:y1, x0:x1]
        block[sel] = src[tv[sel], tu[sel]]
        best[y0:y1, x0:x1][sel] = inside[sel]
    if dilate:
        covered = best > -np.inf
        if covered.any() and not covered.all():
            for _ in range(2 * k + 2):           # grow the covered area into the gaps, 1 px a step
                if covered.all():
                    break
                grown = covered.copy()
                for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                    sh = np.roll(covered, (dy, dx), (0, 1))
                    shp = np.roll(out, (dy, dx), (0, 1))
                    if dy == 1: sh[0] = False
                    if dy == -1: sh[-1] = False
                    if dx == 1: sh[:, 0] = False
                    if dx == -1: sh[:, -1] = False
                    take = sh & ~grown
                    out[take] = shp[take]
                    grown |= take
                covered = grown
    return Image.fromarray(out, 'RGBA')


def atlas(source, folder, hd_scale=4, face=None):
    """The used parts (charts) of all source pages in one atlas, with independent native
    16-colour CLUTs per page.

    Only what the polygons sample goes in (most of a 256 x 256 DW3 page is other models' texels or
    empty), all charts at one common scale. HD keeps the original RGBA pixels (an exact copy where
    the HD tile has the chart's own size, LANCZOS otherwise); the native 1x quantizes each page to
    15 colours. The native last 32 rows hold 64 palettes, not drawable texture pixels.
    FACE (face_plan): the open frame goes into the page; every frame of every face part, scaled
    like its chart and in that page's palette, goes into free atlas space, 4-pixel aligned (a VRAM
    halfword), so Gfx_AnimateModelTex can copy it with DR_MOVE.
    Returns tim, hd, tiles (per chart), records, owner ({id(face dict): chart}), scale."""
    face = face or []
    if hd_scale not in (1,2,4,8,16):
        raise ValueError('Nicht unterstützte HD-Skalierung.')
    pages = _load_pages(source, folder)
    chart_list, owner = charts(source, [p.size for p in pages], face)
    scale, tiles, slots = layout(chart_list, face)
    hd = Image.new('RGBA', (128*hd_scale, 256*hd_scale))
    indices = np.zeros((256,128), dtype=np.uint8)
    palettes = [[0x8000] + [0]*15 for _ in pages]
    variants, hd_frames = {}, {}
    def with_frame(img, part, k):
        (sx, sy), (w, h) = part['frames'][k], part['size']
        out = img.copy()
        out.paste(img.crop((sx, sy, sx + w, sy + h)), part['dst'])
        return out
    def region_of(img, t):
        x, y, tw, th, cx, cy, cw, ch, rot = t
        r = img.crop((cx, cy, cx + cw, cy + ch))
        return r.transpose(Image.Transpose.TRANSPOSE) if rot else r
    for i, rgba in enumerate(pages):
        mine = [f for f in face if f['image'] == i]
        for part in mine:                       # the page shows the open frame
            rgba = with_frame(rgba, part, 0)
        here = [c for c, ch_ in enumerate(chart_list) if ch_['image'] == i]
        if not here:
            continue
        thumbs, tris_of = {}, {}
        kw = max(hd_scale, 4)                   # the 1x tile is the average of this picture
        for c in here:
            t = tiles[c]
            tris_of[c] = chart_triangles(source, owner, c)
            tile_img = render_tile(rgba, t, tris_of[c], kw)
            size = (t[2]*hd_scale, t[3]*hd_scale)
            hd.paste(tile_img if tile_img.size == size else tile_img.resize(size, Image.Resampling.BOX),
                     (t[0]*hd_scale, t[1]*hd_scale))
            thumbs[c] = tile_img.resize(t[2:4], Image.Resampling.BOX)
        # one palette for the page: quantize the opaque texels of all its charts together
        texels = np.concatenate([np.asarray(im).reshape(-1, 4) for im in thumbs.values()])
        texels = texels[texels[:, 3] >= 128] if np.any(texels[:, 3] >= 128) else texels
        strip = Image.fromarray(texels.reshape(1, -1, 4).astype(np.uint8), 'RGBA')
        opaque = np.ones((1, len(texels)), bool)
        # the page's own colours when they fit (a DW3 page is 4-bit: at most 16): averaged texels
        # snap back to them, so a rare colour (Growlmon's white chest) is never merged away;
        # otherwise median cut
        own = {}
        for c in here:
            x0, y0, cw0, ch0 = chart_list[c]['box']
            px0 = np.asarray(rgba.crop((x0, y0, x0 + cw0, y0 + ch0))).reshape(-1, 4)
            for col in map(tuple, px0[px0[:, 3] >= 128, :3].tolist()):
                own[col] = own.get(col, 0) + 1
        while 15 < len(own) <= 64:   # one too many (16 opaque): the rarer of the closest pair goes
            cols = list(own)
            arr = np.asarray(cols, float)
            d = ((arr[:, None] - arr[None]) ** 2).sum(-1) + np.eye(len(cols)) * 1e9
            a, b = np.unravel_index(int(np.argmin(d)), d.shape)
            gone = cols[a] if own[cols[a]] < own[cols[b]] else cols[b]
            keep = cols[b] if gone == cols[a] else cols[a]
            own[keep] += own.pop(gone)
        if 0 < len(own) <= 15:
            ref = Image.new('P', (1, 1))
            colours = sorted(own)
            ref.putpalette([v for c3 in colours for v in c3] + list(colours[0]) * (256 - len(colours)))
            quant = strip.convert('RGB').quantize(palette=ref, dither=Image.Dither.NONE)
            quant.putpalette([v for c3 in colours for v in c3])
        else:
            quant = strip.convert('RGB').quantize(colors=15, dither=Image.Dither.NONE)
        rgb = (quant.getpalette() or []) + [0]*45
        pal = [0]
        for c in range(15):
            r,g,b = rgb[c*3:c*3+3]
            word = (r>>3) | ((g>>3)<<5) | ((b>>3)<<10)
            alpha=np.asarray(strip)[:,:,3][(np.asarray(quant)==c)&opaque]
            if np.any((alpha>=128)&(alpha<255)):word|=0x8000
            pal.append(word or 0x8000)  # opaque black must not become transparent
        def index_pixels(img_thumb):
            q = img_thumb.convert('RGB').quantize(palette=quant, dither=Image.Dither.NONE)
            px = np.asarray(q).astype(np.uint8)+1
            px[np.asarray(img_thumb)[:,:,3] < 128] = 0
            return px
        for c in here:
            x, y, tw, th = tiles[c][:4]
            indices[y:y+th, x:x+tw] = index_pixels(thumbs[c])
        for p_i, part in enumerate(face):
            if part['image'] != i:
                continue
            c = slots[p_i][0]
            t = tiles[c]
            variants[p_i], hd_frames[p_i] = [], []
            for k in range(3):        # the whole HD atlas as it looks with frame k in this tile
                tile_img = render_tile(with_frame(rgba, part, k), t, tris_of[c], kw)
                variants[p_i].append(index_pixels(tile_img.resize(t[2:4], Image.Resampling.BOX)))
                frame_hd = hd.copy()
                size = (t[2]*hd_scale, t[3]*hd_scale)
                frame_hd.paste(tile_img if tile_img.size == size else tile_img.resize(size, Image.Resampling.BOX),
                               (t[0]*hd_scale, t[1]*hd_scale))
                hd_frames[p_i].append(frame_hd)
        palettes[i] = pal
    records = []
    for p_i, part in enumerate(face):
        c, slot = slots[p_i]
        x, y, tw, th = tiles[c][:4]
        ax0, ay0, pw, ph = _face_box(tiles[c], part)
        sources = []
        for k in range(3):
            patch = indices[ay0:ay0+ph, ax0:ax0+pw].copy()
            tile = variants[p_i][k]
            for yy in range(ay0, ay0 + ph):
                for xx in range(ax0, ax0 + pw):
                    if x <= xx < x + tw and y <= yy < y + th:
                        patch[yy - ay0, xx - ax0] = tile[yy - y, xx - x]
            sx, sy = slot[k]
            indices[sy:sy+ph, sx:sx+pw] = patch
            sources.append((sx, sy))
            # the HD picture holds the same frame (the port copies it there like the 1x texels
            # when the eye blinks: TexRep_OnMove), the page's HD tile drawn with frame k
            hd.paste(hd_frames[p_i][k].crop((ax0 * hd_scale, ay0 * hd_scale, (ax0 + pw) * hd_scale, (ay0 + ph) * hd_scale)),
                     (sx * hd_scale, sy * hd_scale))
        records.append({'slot': part['slot'], 'dst': (ax0, ay0), 'size': (pw, ph), 'frames': sources})
    raw = bytearray((indices[:,0::2] | (indices[:,1::2]<<4)).tobytes())
    for i,pal in enumerate(palettes):
        struct.pack_into('<16H', raw, (224+i//2)*64 + (i%2)*32, *pal)
    tim = struct.pack('<II I4H', 16, 0, 12+len(raw), 0, 0, 32, 256) + raw
    return tim, hd, tiles, records, owner, scale


def atlas_scale(source, folder, face=None):
    sizes = []
    for name in source['images']:
        with Image.open(Path(folder)/name) as image:
            sizes.append(image.size)
    return layout(charts(source, sizes, face)[0], face)[0]


def auto_hd_scale(source, folder, with_face=False, face=None):
    """Smallest HD factor (2, 4, 8 or 16) at which every used chart gets at least two HD pixels per
    source texel (the 1x atlas holds it at layout()'s scale s; HD is that times the factor): every
    source texel is then kept exactly, as a block of 2-3+ pixels whose size varies by at most one.
    16 = 2048 x 4096, the largest the port takes."""
    s = atlas_scale(source, folder, face if with_face else None)
    need = 2 / max(s, 1e-6)
    for k in (2, 4, 8, 16):
        if k >= need - 1e-6:
            return k
    return 16


def face_records(records):
    """Gfx_AnimateModelTex list: entries 0/1 the eyes (0xFF when unused), then cycling parts, 0xFF
    ends. 10 bytes: dstX, dstY, w, h (x / w in VRAM halfwords = 4 texels), three source corners."""
    def rec(r):
        (dx, dy), (w, h) = r['dst'], r['size']
        out = [dx // 4, dy, w // 4, h]
        for fx, fy in r['frames']:
            out += [fx // 4, fy]
        if any(not 0 <= v <= 253 for v in out):
            raise ValueError('Gesichtsrechteck außerhalb des DW2-Bereichs.')
        return bytes(out)
    eyes = {r['slot']: r for r in records if r['slot'] < 2}
    rest = [r for r in records if r['slot'] >= 2][:8]
    out = bytearray()
    for k in range(2):
        out += rec(eyes[k]) if k in eyes else bytes([255]) + bytes(9)
    for r in rest:
        out += rec(r)
    out += bytes([255])
    out += bytes(-len(out) % 4)
    return bytes(out)


def encode_model(source, folder, scale=1., hd_scale=4, face=None):
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Ungültige Skalierung.')
    nodes = plan(source)
    order, depths = [x['src'] for x in nodes], [x['depth'] for x in nodes]
    parts, face_notes = face_plan(source, face)
    if not hd_scale:
        hd_scale = auto_hd_scale(source, folder, bool(parts), parts)
    try:
        tim, hd, tiles, records, owner, tex_scale = atlas(source, folder, hd_scale, parts)
    except ValueError as exc:
        if not parts:
            raise
        face_notes.append(str(exc))
        tim, hd, tiles, records, owner, tex_scale = atlas(source, folder, hd_scale, [])
    n = len(order)
    out = bytearray(12 + 16*n)
    out += face_records(records)
    def block(data):
        out.extend(bytes((-len(out))%4));at=len(out);out.extend(data);return at
    pointers = [[],[],[]]
    triangle_count = 0
    for node in nodes:
        bone = node['src']
        b = source['bones'][bone]
        part = bone_chunks(b)[node['chunk']]
        all_vertices = np.rint(np.asarray(b['vertices'], dtype=float)*scale).astype(np.int64)
        used = sorted({f['indices'][k] for f, c in part for k in c})
        if any(type(v) is not int or not 0 <= v < len(all_vertices) for v in used):
            raise ValueError('Ungültiger Vertexindex.')
        remap = {v: i for i, v in enumerate(used)}
        vertices = all_vertices[used] if used else all_vertices[:0]
        if len(vertices) > 256 or not len(vertices) or np.abs(vertices).max() > 32767:
            raise ValueError(f'DW3-Knochen {bone}: 1–256 Vertices im 16-Bit-Bereich erforderlich.')
        normals, normal_ids, prims = [], {}, [[],[]]
        # Smooth shading: each corner gets the area-weighted mean normal of the part's faces at that
        # vertex, unless the face bends away by more than CREASE (a hard edge keeps the face normal).
        # One normal per triangle (until 1.0) lit every face flat: the faceted look in battle.
        face_n, vert_sum = [], np.zeros((len(vertices), 3))
        for face, corners in part:
            ids = [remap[face['indices'][k]] for k in corners]
            v = vertices[ids].astype(float)
            n_area = np.cross(v[1]-v[0], v[2]-v[0])
            face_n.append(n_area/max(np.linalg.norm(n_area),1e-9))
            for i in ids:
                vert_sum[i] += n_area
        vert_n = vert_sum/np.maximum(np.linalg.norm(vert_sum,axis=1,keepdims=True),1e-9)
        def normal_index(nv):
            key = tuple(int(c) for c in np.rint(nv*4096))
            if key not in normal_ids:
                if len(normals) >= 256:
                    return None
                normal_ids[key] = len(normals); normals.append(key)
            return normal_ids[key]
        for fi, (face, corners) in enumerate(part):
            img = face['image']
            if type(img) is not int or not 0 <= img < len(source['images']) or id(face) not in owner:
                raise ValueError('Ungültige Materialzuordnung.')
            tile = tiles[owner[id(face)]]
            cx,cy,cw,ch = tile[4:8]
            ids = [remap[face['indices'][k]] for k in corners]
            fn = face_n[fi]
            corner_n = []
            for i in ids:
                nv = vert_n[i] if float(vert_n[i] @ fn) >= CREASE else fn
                k = normal_index(nv)
                if k is None:              # table full: the face normal, which is often shared
                    k = normal_index(fn)
                if k is None:              # still full: the closest stored normal (shading only)
                    table = np.asarray(normals, dtype=float)
                    k = int(np.argmax(table @ nv))
                corner_n.append(k)
            uv=[]
            for k in corners:
                u,v=face['uv'][k]
                if not cx <= u < cx+cw or not cy <= v < cy+ch:
                    raise ValueError('Wiederholende DW3-UVs müssen vor dem Import aufgeteilt werden.')
                uv.append(tile_uv(tile, u, v))
            clut = ((224+img//2)<<6) | (img%2)
            abr = face['abr']
            if type(abr) is not int or not 0 <= abr <= 4:
                raise ValueError('Ungültiger PS1-Mischmodus.')
            # Input faces are CCW in the exported GLB; DW2 stores reversed triangles.
            rev=(2,1,0)
            payload=bytes(ids[k] for k in rev)+bytes(corner_n[k] for k in rev)+bytes(c for k in rev for c in uv[k])+struct.pack('<HH',clut,((abr-1)<<5) if abr else 0)
            prims[0 if abr else 1].append(payload)
            triangle_count+=1
        if not normals or not any(prims):
            raise ValueError('DW3-Teilmodell ohne Geometrie.')
        pointers[0].append(block(struct.pack('<IH',len(vertices),0)+vertices.astype('<i2').tobytes()))
        pointers[1].append(block(struct.pack('<IH',len(normals),0)+np.asarray(normals,dtype='<i2').tobytes()))
        pointers[2].append(block(struct.pack('<3I',0,0,len(prims[0]))+b''.join(prims[0])+struct.pack('<I',len(prims[1]))+b''.join(prims[1])))
    for i,table in enumerate(pointers):
        struct.pack_into(f'<{n}I',out,12+i*n*4,*table)
    struct.pack_into(f'<{n}I',out,12+12*n,*depths)
    out.extend(bytes((-len(out))%4));tim_start=len(out);out.extend(tim)
    struct.pack_into('<III',out,0,tim_start,0,n)
    NativeModel(out)
    return bytes(out),hd,{'bones':n,'triangles':triangle_count,'scale':scale,'textures':len(source['images']),
                          'charts':len(tiles),'texture_scale':round(tex_scale,3),'hd_scale':hd_scale,
                          'face_parts':len(records),'eyes':sum(r['slot'] < 2 for r in records),'face_notes':face_notes}


def _quat(m):
    """Unit quaternion (x, y, z, w) of rotation matrix M (Shepperd; numerically stable)."""
    t = np.trace(m)
    if t > 0:
        r = np.sqrt(1 + t) * 2
        q = [(m[2, 1] - m[1, 2]) / r, (m[0, 2] - m[2, 0]) / r, (m[1, 0] - m[0, 1]) / r, r / 4]
    else:
        i = int(np.argmax([m[0, 0], m[1, 1], m[2, 2]]))
        j, k = (i + 1) % 3, (i + 2) % 3
        r = np.sqrt(1 + m[i, i] - m[j, j] - m[k, k]) * 2
        q = [0., 0., 0., (m[k, j] - m[j, k]) / r]
        q[i] = r / 4
        q[j] = (m[j, i] + m[i, j]) / r
        q[k] = (m[k, i] + m[i, k]) / r
    q = np.array(q, dtype=float)
    return q / np.linalg.norm(q)


def _quat_matrix(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _slerp_matrix(ra, rb, w):
    """Shortest-arc slerp between rotation matrices (same result as scipy's Slerp, without SciPy,
    which is not available in the Android app and the web version)."""
    qa, qb = _quat(ra), _quat(rb)
    d = float(np.dot(qa, qb))
    if d < 0:
        qb, d = -qb, -d
    if d > 0.9995:
        q = qa + w * (qb - qa)
    else:
        th = np.arccos(min(d, 1.))
        q = (np.sin((1 - w) * th) * qa + np.sin(w * th) * qb) / np.sin(th)
    return _quat_matrix(q / np.linalg.norm(q))


def _blend_matrix(a, b, w):
    """A pose between bone matrices A and B (4x4, W in 0..1): rotation by slerp, scale and position
    linear (like DW3's FIGHTSTG_blendBone, which interpolates angle, scale and position)."""
    out = np.eye(4)
    def polar(m):
        u, sv, vt = np.linalg.svd(m[:3, :3])
        r = u @ vt
        if np.linalg.det(r) < 0:
            u[:, -1] *= -1
            r = u @ vt
        return r, r.T @ m[:3, :3]
    ra, sa = polar(a)
    rb, sb = polar(b)
    rot = _slerp_matrix(ra, rb, w)
    out[:3, :3] = rot @ ((1 - w) * sa + w * sb)
    out[:3, 3] = (1 - w) * a[:3, 3] + w * b[:3, 3]
    return out


def encode_animation(source, mapping, scale=1., loops=(), step=1):
    """mapping: native clip index -> DW3 motion index (0.95: one whole motion; LOOPS: the clips that
    loop from their start), or -> an ACTION dict (dw3_actions: segments of motions with frame ranges,
    repeats, blends, and a hold or a loop back to any frame). No semantic labels inferred.
    STEP > 1 (PS1 image, smaller files): only every STEP-th DW3 frame becomes a pose and is held
    for STEP game frames, so the motion keeps its length with fewer distinct poses."""
    step=int(step)
    if not 1<=step<=8:
        raise ValueError('Bildschritt 1–8.')
    nodes=plan(source);order=[x['src'] for x in nodes];n=len(order)
    if not mapping or any(type(i)is not int or not 0<=i<10 for i in mapping):
        raise ValueError('DW2-Datei benötigt Clip-Indizes 0–9.')
    keys=[[] for _ in order];lookup=[{} for _ in order];clips={}
    index_of={m['id']:i for i,m in enumerate(source['motions'])}
    cache={}
    def matrices(motion):
        if motion not in cache:
            cache[motion]=source_matrices(source,motion)
        return cache[motion]
    def node_matrix(frame,b):
        matrix=frame[nodes[b]['chain'][0]]
        for c in nodes[b]['chain'][1:]:
            matrix=matrix@frame[c]
        return matrix
    def row_of(mats):
        row=[]
        for b,src in enumerate(order):
            matrix=mats[b]
            values=np.rint(np.r_[matrix[:3,:3].ravel()*4096,matrix[:3,3]*scale]).astype(np.int64)
            if np.any(values < -32768) or np.any(values > 32767):
                raise ValueError('Animationsmatrix außerhalb des 16-Bit-Bereichs.')
            raw=struct.pack('<12h',*values)
            if raw not in lookup[b]:
                if len(keys[b])>=254:
                    raise ValueError(f'Knochen {src}: mehr als 254 unterschiedliche Posen in einer DW2-Datei. '
                                     'Weniger oder kürzere Abschnitte bzw. Übergänge verwenden.')
                lookup[b][raw]=len(keys[b]);keys[b].append(raw)
            row.append(lookup[b][raw])
        return bytes(row)
    for index,motion in sorted(mapping.items()):
        if isinstance(motion,dict):
            from ..dw3_actions import frames_of, validate, motion_table
            validate(motion,motion_table(source))
            table=motion_table(source)
            seq,loop_row=frames_of(motion,table)
            idle=1 if 1 in table else min(table)
            rows=[];shown=[]
            for k,(mid,f,prev,w) in enumerate(seq):
                if step>1 and k%step:      # PS1 reduction: hold every STEP-th pose
                    rows.append(rows[-1]);shown.append(shown[-1]);continue
                frame=matrices(index_of[mid])[f]
                mats=[node_matrix(frame,b) for b in range(n)]
                if prev is not None:
                    if prev[0]=='row':      # DW3's opening blend: from the pose that shows
                        start=shown[prev[1]]
                    elif prev[0]=='idle':
                        start=None if mid==idle else [node_matrix(matrices(index_of[idle])[table[idle]['lead']],b) for b in range(n)]
                    else:
                        pf=matrices(index_of[prev[0]])[prev[1]]
                        start=[node_matrix(pf,b) for b in range(n)]
                    if start is not None:
                        mats=[_blend_matrix(start[b],mats[b],w) for b in range(n)]
                rows.append(row_of(mats));shown.append(mats)
            if loop_row is not None:
                if loop_row*n>0xFFFF:
                    raise ValueError('Loop-Beginn zu weit hinten (DW2: 16-Bit-Zeilenversatz).')
                clips[index]=b''.join(rows)+b'\xfe'+struct.pack('<H',loop_row*n)
            else:
                clips[index]=b''.join(rows)+b'\xff\0\0'
            continue
        if type(motion)is not int or not 0<=motion<len(source['motions']):
            raise ValueError('Unbekannte DW3-Motion.')
        all_frames=matrices(motion)
        frames=[all_frames[min(len(all_frames)-1,(i//step)*step)] for i in range(len(all_frames))]
        rows=[row_of([node_matrix(frame,b) for b in range(n)]) for frame in frames]
        clips[index]=b''.join(rows)+(b'\xfe\0\0' if index in loops else b'\xff\0\0')
    slots=max(mapping)+1
    out=bytearray(4+4*n+4*(slots+1))
    struct.pack_into('<I',out,4+4*n+4*slots,1)
    for b in range(n):
        struct.pack_into('<I',out,4+4*b,len(out));out.extend(b''.join(keys[b]))
    for index,data in clips.items():
        struct.pack_into('<I',out,4+4*n+4*index,len(out));out.extend(data)
    parse_anim_file(out,n)
    return bytes(out)


def fnv(data):
    value=0xcbf29ce484222325
    for b in data:
        value=((value^b)*0x100000001b3)&0xffffffffffffffff
    return value


def hd_name(model):
    m=NativeModel(model)
    # Gfx_LoadTexSlotImage uploads the complete 32x256-word TIM pixel block.
    flags=struct.unpack_from('<I',model,m.tim_start+4)[0]
    if flags&7:raise ValueError('HD-Modelltextur muss 4-Bit-TIM sein.')
    start=m.tim_start+8
    if flags&8:start+=struct.unpack_from('<I',model,start)[0]
    w,h=struct.unpack_from('<HH',model,start+8)
    if (w,h)!=(32,256):raise ValueError('HD-Modelltextur benötigt einen vollständigen 128×256-Slot.')
    raw=model[start+12:start+12+w*h*2]
    if len(raw)!=w*h*2:raise ValueError('TIM-Pixelblock abgeschnitten.')
    return f'{fnv(struct.pack("<2i",w,h)+raw):016x}_{w}x{h}_m0.png'


def simplify_source(source, cell):
    """Vertex clustering per bone (PS1 image, controlled optimisation): vertices within CELL source
    units of each other merge to their mean; faces that collapse are dropped. UVs stay per corner,
    so textures keep their placement. Returns a new source dict (the input is not changed)."""
    import copy
    if cell <= 0:
        return source
    out = copy.deepcopy(source)
    for b in out['bones']:
        verts = np.asarray(b['vertices'], dtype=float)
        if not len(verts) or not b['faces']:
            continue
        keys = {}
        remap = []
        for v in verts:
            k = tuple(np.floor(v / cell).astype(int))
            remap.append(keys.setdefault(k, len(keys)))
        sums = np.zeros((len(keys), 3))
        counts = np.zeros(len(keys))
        for i, k in enumerate(remap):
            sums[k] += verts[i]
            counts[k] += 1
        b['vertices'] = (sums / counts[:, None]).tolist()
        faces = []
        for f in b['faces']:
            idx = [remap[i] for i in f['indices']]
            if len(idx) == 3 and len(set(idx)) < 3:
                continue
            if len(idx) == 4 and len(set(idx)) < 3:
                continue
            nf = dict(f)
            nf['indices'] = idx
            faces.append(nf)
        if not faces:
            # a small part would vanish completely (a finger, an ear tip): keep it as it is
            b['vertices'] = verts.tolist()
            continue
        b['faces'] = faces
    return out


def triangle_total(source):
    return sum(len(triangles(b)) for b in source['bones'])


def quality_report(source, folder, native, hd, face=None, original=None):
    """Measured DW3 -> DW2 losses of one import, against the DW3 original (ORIGINAL: the source
    before a PS1 reduction, default SOURCE). Geometry: vertices / triangles / bones. Texture: every
    texel the polygons sample, read back through the atlas the way the game reads it (1x: native
    4-bit TIM with its palette; HD: the HD picture), as PSNR in dB (99 = identical) and the share
    of texels that differ; UV error in source texels (the 1x atlas is an integer grid)."""
    from .native_model import NativeModel
    original = original or source
    parts = face_plan(source, face)[0] if face else []
    k = hd.width // 128 if hd is not None else 1
    tim, hd_check, tiles, _, owner, scale = atlas(source, folder, k if k in (1, 2, 4, 8, 16) else 4, parts)
    m = NativeModel(native)
    raw = np.frombuffer(native[m.tim_start + 20:m.tim_start + 20 + 16384], np.uint8).reshape(256, 64)
    idx = np.zeros((256, 128), np.uint8)
    idx[:, 0::2], idx[:, 1::2] = raw & 15, raw >> 4
    hda = np.asarray(hd.convert('RGBA') if hd is not None else hd_check).astype(np.int32)
    pages = _load_pages(source, folder)
    chart_list, _ = charts(source, [p.size for p in pages], parts)
    err1 = errh = 0.
    n = diff1 = diffh = 0
    seen = set()
    # every source texel whose centre lies in a polygon, read where the game reads it: the source
    # point mapped through that triangle onto the rounded atlas UVs (as the GPU interpolates them)
    for c, t in enumerate(tiles):
        x, y, tw, th, cx, cy, cw, ch, rot = t
        img = chart_list[c]['image']
        page = np.asarray(pages[img]).astype(np.int32)
        words = np.frombuffer(raw[224 + img // 2].tobytes()[(img % 2) * 32:(img % 2) * 32 + 32], '<u2')
        pal = np.stack([(words & 31) << 3, (words >> 5 & 31) << 3, (words >> 10 & 31) << 3], 1).astype(np.int32)
        for (s0, s1, s2), f in chart_triangles(source, owner, c):
            S = np.asarray([s0, s1, s2], float)
            A = np.asarray([tile_uv(t, *s0), tile_uv(t, *s1), tile_uv(t, *s2)], float)
            mt = np.array([[S[1, 0] - S[0, 0], S[2, 0] - S[0, 0]], [S[1, 1] - S[0, 1], S[2, 1] - S[0, 1]]])
            if abs(np.linalg.det(mt)) < 1e-9:
                continue
            u0, u1 = int(S[:, 0].min()), int(np.ceil(S[:, 0].max()))
            v0, v1 = int(S[:, 1].min()), int(np.ceil(S[:, 1].max()))
            gu, gv = np.meshgrid(np.arange(u0, u1) + .5, np.arange(v0, v1) + .5)
            inv = np.linalg.inv(mt)
            du, dv = gu - S[0, 0], gv - S[0, 1]
            b1 = inv[0, 0] * du + inv[0, 1] * dv
            b2 = inv[1, 0] * du + inv[1, 1] * dv
            b0 = 1 - b1 - b2
            sel = (np.minimum(np.minimum(b0, b1), b2) >= 0)
            if not sel.any():
                continue
            tu, tv = gu[sel].astype(int), gv[sel].astype(int)
            ok = (tu < page.shape[1]) & (tv < page.shape[0])
            tu, tv = tu[ok], tv[ok]
            B = np.stack([b0[sel][ok], b1[sel][ok], b2[sel][ok]], 1)
            P = B @ A                                     # atlas texel units, interpolated
            key = [(img, a_, b_) for a_, b_ in zip(tu.tolist(), tv.tolist())]
            fresh = np.array([kk not in seen for kk in key], bool)
            seen.update(key)
            ref = page[tv, tu]
            keep = (ref[:, 3] >= 128) & fresh
            if not keep.any():
                continue
            ref, P = ref[keep], P[keep]
            ax = np.clip(P[:, 0].astype(int), x, x + tw - 1)
            ay = np.clip(P[:, 1].astype(int), y, y + th - 1)
            c1 = pal[idx[ay, ax]]
            hx = np.clip((P[:, 0] * k).astype(int), x * k, (x + tw) * k - 1)
            hy = np.clip((P[:, 1] * k).astype(int), y * k, (y + th) * k - 1)
            c2 = hda[np.clip(hy, 0, hda.shape[0] - 1), np.clip(hx, 0, hda.shape[1] - 1), :3]
            r = ref[:, :3] & ~7                     # 15-bit colour (the PS1's): what 1x can hold at best
            err1 += float(((c1 - r) ** 2).sum()) / 3
            errh += float(((c2 - ref[:, :3]) ** 2).sum()) / 3
            diff1 += int(np.any(c1 != r, 1).sum())
            diffh += int(np.any(c2 != ref[:, :3], 1).sum())
            n += len(ref)
    psnr = lambda e: 99.0 if e == 0 else round(10 * math.log10(255 ** 2 / e), 1)
    uv = []
    for b in source['bones']:
        for f in b['faces']:
            x, y, tw, th, cx, cy, cw, ch, rot = t = tiles[owner[id(f)]]
            for u, v in f['uv']:
                ax, ay = tile_uv(t, u, v)
                su = (ay - y + .5) * cw / th if rot else (ax - x + .5) * cw / tw
                sv = (ax - x + .5) * ch / tw if rot else (ay - y + .5) * ch / th
                uv.append(math.hypot(su - .5 + cx - u, sv - .5 + cy - v))
    uv = np.asarray(uv) if uv else np.zeros(1)
    sizes = [list(p.size) for p in pages]
    no_hd = hd is None
    out = {
        'source': {'bones': len(original['bones']) - 1, 'vertices': sum(len(b['vertices']) for b in original['bones']),
                   'triangles': triangle_total(original), 'pages': sizes},
        'converted': {'parts': len(m.parts), 'vertices': sum(p.vertex_count for p in m.parts),
                      'triangles': triangle_total(source)},
        'texture': {'scale': round(scale, 3), 'charts': len(tiles), 'rotated': int(sum(t[8] for t in tiles)),
                    'atlas': [128, 224], 'hd': [hda.shape[1], hda.shape[0]], 'hd_factor': k,
                    'texels': n, 'psnr_1x': psnr(err1 / max(n, 1)), 'psnr_hd': psnr(errh / max(n, 1)),
                    'changed_1x': round(diff1 / max(n, 1), 3), 'changed_hd': round(diffh / max(n, 1), 3)},
        'uv': {'mean': round(float(uv.mean()), 2), 'max': round(float(uv.max()), 2)},
        'face': {'parts': len(parts), 'eyes': sum(p['slot'] < 2 for p in parts)},
    }
    if no_hd:   # PS1 image: no HD texture exists
        out['texture'].update(hd=None, hd_factor=None, psnr_hd=None, changed_hd=None)
    return out
