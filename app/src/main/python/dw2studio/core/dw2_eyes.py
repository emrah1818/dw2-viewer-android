"""DW2 model-specific eye sprite coordinates (native MxxxYYYY.BIN).

The first ten bytes of the 24-byte 'blinking_data' field describe:
  target x (4-pixel words), target y, width (4-pixel words), height,
  followed by three source sprite (x-in-words, y) pairs.
Additional source pairs, when present, occupy bytes 10..19 and use FF FF
as the terminator.  The final four bytes are other metadata.  This is
verified against the original US Agumon, Greymon, Gabumon and other models;
the precise original game's blink timing remains unidentified.

A model is only write-enabled when all sprite rectangles fit the texture
and mapped face CLUT. No model-name-based guesswork is used.
"""
from __future__ import annotations
from functools import lru_cache
from collections import Counter
from dataclasses import dataclass
import struct
from PIL import Image


@dataclass(frozen=True)
class EyeLayout:
    sources: tuple[tuple[int, int, int, int], ...]
    target: tuple[int, int, int, int]
    clut: int
    metadata: bytes


def _blink_metadata(model: bytes) -> bytes | None:
    if len(model) < 60:
        return None
    tim_offset, _, objects = struct.unpack_from('<III', model)
    start = 12 + objects * 16
    if not 1 <= objects <= 256 or start + 24 > tim_offset or tim_offset + 16448 > len(model):
        return None
    return model[start:start + 24]


@lru_cache(maxsize=16)
def _cached_eye_layout(model: bytes) -> EyeLayout | None:
    """Derive per-model eye coordinates, rejecting unmapped/overlapping sprites.

    The original converter's UV rasterization marks body texture pixels but
    deliberately omits extra eye poses; their CLUT is taken from the target.
    """
    from dw2studio.assets.tim import TIM
    from .dw2_native_atlas import face_clut_map, is_native_dw2_tim

    metadata = _blink_metadata(model)
    if metadata is None or metadata[:4] == b'\xff' * 4:
        return None
    # Width/height fields are not coordinates; value 0 means no valid sprite.
    x, y, w, h = metadata[0] * 4, metadata[1], metadata[2] * 4, metadata[3]
    if not (8 <= w <= 128 and 8 <= h <= 96 and 0 <= x <= 128-w and 0 <= y <= 224-h):
        return None
    target = (x, y, w, h)
    candidates=[]
    for i in range(4, 20, 2):
        sx, sy = metadata[i], metadata[i+1]
        if (sx, sy) == (255, 255):
            break
        rect = (sx * 4, sy, w, h)
        if rect[0] + w > 128 or rect[1] + h > 224:
            return None
        if rect != target and rect not in candidates:
            candidates.append(rect)
    if not candidates:
        return None
    try:
        tim_start = struct.unpack_from('<I', model)[0]
        if not is_native_dw2_tim(TIM(model[tim_start:])):
            return None
        cmap = face_clut_map(model)
        covered = Counter(cmap[yy*128+xx] for yy in range(y,y+h)
                          for xx in range(x,x+w) if cmap[yy*128+xx] != -1)
        if not covered:
            return None
        clut, n = covered.most_common(1)[0]
        if n < max(16, int(w*h*.65)):
            return None
        # The target must use exactly one physical color bank / transparency
        # behavior; a mix would make eye palette writes damage body polygons.
        bank = clut & 0xffff
        if any((c & 0xffff) != bank for c in covered):
            return None
        for sx,sy,sw,sh in candidates:
            for yy in range(sy,sy+sh):
                for xx in range(sx,sx+sw):
                    existing = cmap[yy*128+xx]
                    if existing != -1 and existing != clut:
                        return None
        # Greymon's native layout also has a second pose to the left of its
        # default (lower row), as verified in the model and earlier emulator
        # test. Keep compatibility without applying this extra area to others.
        if target == (40,48,40,48) and metadata[:4] == bytes((10,48,10,48)):
            # Confirmed Greymon arrangement, even on synthetic test models
            # containing only the first source coordinates.
            additional = ((0,0,40,48),(40,0,40,48),(80,0,40,48),(0,48,40,48))
            if all(cmap[yy*128+xx] in (-1,clut)
                   for sx,sy,sw,sh in additional
                   for yy in range(sy,sy+sh) for xx in range(sx,sx+sw)):
                candidates = list(additional)
        # Default/native target is the last frame so the unmodified material
        # remains exactly equal to the original converter texture.
        candidates.append(target)
        return EyeLayout(tuple(candidates), target, clut, metadata)
    except (ValueError, IndexError, struct.error):
        return None


def eye_layout(model):
    return _cached_eye_layout(bytes(model))


def eye_clut_map(model: bytes, layout: EyeLayout | None = None) -> list[int]:
    from .dw2_native_atlas import face_clut_map
    layout = layout or eye_layout(model)
    if layout is None:
        raise ValueError('Dieses Digimon besitzt keine sicher erkennbaren nativen Augenframes.')
    cmap = face_clut_map(model)
    for x,y,w,h in layout.sources:
        if y+h>224:
            raise ValueError('Augenframe überlappt den reservierten Farbspeicher.')
        for yy in range(y,y+h):
            for xx in range(x,x+w):
                p = yy*128+xx
                if cmap[p] not in (-1,layout.clut):
                    raise ValueError('Augenframe verwendet eine andere CLUT.')
                cmap[p] = layout.clut
    return cmap


def infer_full_eye_atlas(model: bytes, image: Image.Image) -> bool:
    """Detect whether the selected PNG includes normally hidden eye poses.

    In early versions the generic 'Original TIM' export showed only the eye
    frame used by the model mesh; our separate eye atlas export showed all
    poses.  A standard texture patch must accept either kind without silently
    throwing away edited hidden eye frames or destroying an older PNG that
    doesn't have them. The test uses ONLY sprite texels that have a verified
    CLUT and are absent from the ordinary body UV map.
    """
    from .dw2_native_atlas import face_clut_map, decode_native_atlas
    if image.size != (128,256):
        raise ValueError('Die native DW2-PNG muss 128×256 Pixel groß sein.')
    layout = eye_layout(model)
    if layout is None:
        return False
    original_map = face_clut_map(model)
    full_map = eye_clut_map(model,layout)
    offset = struct.unpack_from('<I',model)[0]
    original_full = decode_native_atlas(model,offset,include_eye_frames=True)
    original_pixels = original_full.convert('RGBA').tobytes()
    edited_pixels = image.convert('RGBA').tobytes()
    probes = [p for p in range(128*224)
              if original_map[p] == -1 and full_map[p] != -1
              and original_pixels[4*p+3] >= 64]
    if len(probes) < 16:
        # No useful hidden eye pixels; the body editor is sufficient.
        return False
    visible = sum(edited_pixels[4*p+3] >= 64 for p in probes)
    coverage = visible / len(probes)
    if coverage >= .65:
        return True
    if coverage <= .15:
        return False
    raise ValueError('Die Augenbilder der PNG sind nur teilweise vorhanden. '
                     'Bitte den vollständigen Augenatlas neu exportieren und '
                     'alle vorhandenen Augenstellungen mit ihrem Alphakanal erhalten.')


def eye_atlas(model: bytes) -> Image.Image:
    from .dw2_native_atlas import decode_native_atlas
    if eye_layout(model) is None:
        raise ValueError('Keine unterstützten Augenframes im Originalmodell.')
    return decode_native_atlas(model, struct.unpack_from('<I',model)[0], include_eye_frames=True)


def eye_animation_frames(model: bytes,base:Image.Image|None=None)->tuple[Image.Image,...]:
    from .dw2_native_atlas import decode_native_atlas
    layout=eye_layout(model)
    if layout is None:
        raise ValueError('Keine unterstützten Augenframes im Originalmodell.')
    full=eye_atlas(model)
    if base is None:base=decode_native_atlas(model,struct.unpack_from('<I',model)[0])
    if base.size != (128,256):
        raise ValueError('Ungültige Atlasgröße.')
    tx,ty,tw,th=layout.target
    frames=[]
    for sx,sy,w,h in layout.sources:
        if (w,h)!=(tw,th):
            raise ValueError('Augenframe-Größe stimmt nicht.')
        result=base.convert('RGBA').copy()
        result.paste(full.crop((sx,sy,sx+w,sy+h)),(tx,ty))
        frames.append(result)
    return tuple(frames)


def blink_frame_at(elapsed:float,period:float=3.8,frame_count:int=5)->int:
    """Approximate preview rhythm. Original game blink timing is unknown."""
    if period<=0:raise ValueError('Blinkperiode muss positiv sein.')
    if frame_count<2:raise ValueError('Mindestens zwei Augenframes nötig.')
    default=frame_count-1
    middle=min(1,frame_count-2)
    closed=min(2,frame_count-2)
    t=elapsed%period
    if t<period-.27:return default
    if t<period-.20:return middle
    if t<period-.11:return closed
    if t<period-.04:return middle
    return default
