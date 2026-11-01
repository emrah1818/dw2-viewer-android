"""DW2 native 4-bit model texture decoder/encoder.

DW2's Mxxxx.BIN is not a generic TIM: the last 2048 bytes of its 128x256
TIM *image* contain the 1024 PS1 colors selected by each face's CLUT field.
The standard 16-color TIM CLUT is a dummy and is not the game's palette.
This module is a small Python port of jype's MIT-licensed dw2_model.cpp and
clut_map.cpp mapping logic; it never modifies the game palette storage.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import struct
from PIL import Image, ImageDraw
from dw2studio.assets.tim import TIM

PALETTE_BYTES = 2048
DW2_TIM_BYTES = 16448


def is_native_dw2_tim(tim: TIM) -> bool:
    return (tim.bpp == 0 and tim.width == 128 and tim.height == 256
            and tim.end == DW2_TIM_BYTES and tim.pixel_offset == 64
            and tim.has_clut and len(tim.palette) == 16)


def _faces(model: bytes):
    """Get face UV/CLUT from model tables; reject invalid offsets rather than guess."""
    if len(model) < 36:
        raise ValueError('Native DW2-Modellstruktur ist zu kurz.')
    tim_start, tim_end, number = struct.unpack_from('<III', model)
    if not 1 <= number <= 256 or tim_start + DW2_TIM_BYTES > len(model):
        raise ValueError('Keine unterstützte native DW2-Modellstruktur.')
    if len(model) < 12 + 16 * number + 24:
        raise ValueError('DW2-Objekttabelle ist unvollständig.')
    offsets = struct.unpack_from('<' + 'I' * number, model, 12 + number * 8)
    for offset in offsets:
        if offset < 12 or offset >= tim_start:
            raise ValueError('Ungültiger DW2-Primitive-Offset.')
        pos = offset
        for count_group, item_size in ((0, 20), (1, 20), (2, 16), (3, 16)):
            if pos + 4 > tim_start:
                raise ValueError('Primitive-Zähler überschreitet die Modellgrenze.')
            count = struct.unpack_from('<I', model, pos)[0]
            pos += 4
            if count > 100000 or pos + count * item_size > tim_start:
                raise ValueError('Primitive-Daten überschreiten die Modellgrenze.')
            for _ in range(count):
                entry = model[pos:pos + item_size]
                pos += item_size
                if item_size == 20:
                    uv = [(entry[8+i*2], entry[9+i*2]) for i in range(4)]
                    clut = struct.unpack_from('<H', entry, 16)[0]
                    yield ((uv[0], uv[1], uv[2]), clut | (0x10000 if count_group == 0 else 0))
                    yield ((uv[3], uv[2], uv[1]), clut | (0x10000 if count_group == 0 else 0))
                else:
                    uv = [(entry[6+i*2], entry[7+i*2]) for i in range(3)]
                    clut = struct.unpack_from('<H', entry, 12)[0]
                    yield (tuple(uv), clut | (0x10000 if count_group == 2 else 0))


@lru_cache(maxsize=16)
def _cached_face_clut_map(model: bytes) -> tuple[int,...]:
    """Rasterize model UV/CLUT into a 128x256 effective lookup map.

    Like the original converter, the raster is first built at 256x256,
    then each 4x4 block uses its most frequent nonempty face CLUT.
    """
    canvas = Image.new('I', (256, 256), -1)
    draw = ImageDraw.Draw(canvas)
    face_count = 0
    for uv, clut in _faces(model):
        xclut = (clut & 63) << 4
        yclut = (clut >> 6) & 1023
        if xclut not in (0, 16) or not 224 <= yclut < 256:
            raise ValueError('Modell benutzt nicht unterstützte DW2-CLUT-Koordinaten.')
        coords = [(x * 256 // 255, y * 256 // 255) for x, y in uv]
        draw.polygon(coords, fill=clut)
        face_count += 1
    if not face_count:
        raise ValueError('Keine texturierten Flächen im Digimon-Modell.')
    data = list(canvas.get_flattened_data() if hasattr(canvas, "get_flattened_data") else canvas.getdata())
    for top in range(0, 256, 4):
        for left in range(0, 256, 4):
            values = [data[(top+y)*256 + left+x] for y in range(4) for x in range(4)]
            counts = Counter(v for v in values if v != -1)
            value = min((v for v, c in counts.items() if c == max(counts.values())), default=-1) if counts else -1
            for y in range(4):
                for x in range(4):
                    data[(top+y)*256 + left+x] = value
    return tuple(data[y*256+x] for y in range(256) for x in range(128))


def face_clut_map(model: bytes) -> list[int]:
    """Return an independent mutable map; expensive rasterization is cached."""
    return list(_cached_face_clut_map(bytes(model)))


def _decoded_color(raw: int, clut_stp: bool) -> tuple[int, int, int, int]:
    r, g, b = ((raw >> k) & 31 for k in (0, 5, 10))
    stp = bool(raw & 0x8000)
    a = (255 if stp else 0) if not (r or g or b) else (127 if clut_stp and stp else 255)
    return (r << 3, g << 3, b << 3, a)


def _palette(tim: TIM, clut: int):
    if clut == -1:
        return None
    col = (clut & 63) << 4
    row = ((clut >> 6) & 1023) - 224
    if col not in (0, 16) or not 0 <= row < 32:
        raise ValueError('CLUT-Index außerhalb des DW2-Farbspeichers.')
    start = tim.end - PALETTE_BYTES + (row * 32 + col) * 2
    return [_decoded_color(struct.unpack_from('<H', tim.data, start+i*2)[0], bool(clut & 0x10000))
            for i in range(16)]


def decode_native_atlas(model: bytes, tim_offset: int, *, include_eye_frames=False) -> Image.Image:
    tim = TIM(model[tim_offset:])
    if not is_native_dw2_tim(tim):
        raise ValueError('Nur originale 4-Bit-DW2-Modell-TIMs werden unterstützt.')
    cmap = (face_clut_map(model) if not include_eye_frames
            else __import__("dw2studio.core.dw2_eyes", fromlist=["eye_clut_map"]).eye_clut_map(model))
    rgba = bytearray(128 * 256 * 4)
    palettes = {clut: _palette(tim, clut) for clut in set(cmap)}
    original = tim.data[tim.pixel_offset:tim.end]
    for pos, clut in enumerate(cmap):
        if clut == -1:
            continue
        ix = original[pos//2]
        idx = (ix & 15) if pos%2==0 else (ix >> 4)
        rgba[pos*4:pos*4+4] = bytes(palettes[clut][idx])
    return Image.frombytes('RGBA', (128, 256), bytes(rgba))


def encode_native_atlas(model: bytes, tim_offset: int, image: Image.Image, *, recolor=False, eye_frames=False, palette_mode='protect') -> bytes:
    """Map edited RGBA pixels to the existing game CLUT, preserving its bytes.

    The model uses 64 face-selected 16-color palettes. We do NOT quantize one
    global palette; doing so destroys the embedded per-face palette storage
    and makes Digimon invisible in the actual game.
    """
    if recolor:
        from .dw2_palette_recolor import encode_recolored_native_atlas
        return encode_recolored_native_atlas(model, tim_offset, image, eye_frames=eye_frames, palette_mode=palette_mode)
    tim = TIM(model[tim_offset:])
    if not is_native_dw2_tim(tim):
        raise ValueError('Nur originale 4-Bit-DW2-Modell-TIMs werden unterstützt.')
    if image.size != (128, 256):
        raise ValueError('DW2-PNG muss exakt 128×256 Pixel haben.')
    cmap = (face_clut_map(model) if not eye_frames else
            __import__("dw2studio.core.dw2_eyes", fromlist=["eye_clut_map"]).eye_clut_map(model))
    original = tim.data[tim.pixel_offset:tim.end]
    editable = len(original) - PALETTE_BYTES
    original_atlas = decode_native_atlas(model, tim_offset, include_eye_frames=eye_frames).tobytes()
    target = image.convert('RGBA').tobytes()
    # Texture-space rows 224..255 share physical storage with the 64 real
    # palette banks. Never ignore a requested change to a visible reserved
    # pixel silently; modifying it would destroy the model's colors.
    if any(cmap[i] != -1 and target[i*4:i*4+4] != original_atlas[i*4:i*4+4]
           for i in range(editable * 2, len(cmap))):
        raise ValueError('Die unteren 32 Texturzeilen enthalten reservierte DW2-Farbpaletten. '
                         'Dortige Änderungen können nicht sicher ins Spiel geschrieben werden.')
    # Reject the misleading v2.1/v2.2 export which showed the TIM header's
    # dummy 16-color CLUT, not the real model colors. Such files must NOT be
    # reused as texture input even when their resolution is correct.
    dummy = tim.to_image().tobytes()
    sampled = [i for i, c in enumerate(cmap[:editable*2]) if c != -1]
    if sampled:
        old_matches = sum(target[i*4:i*4+4] == dummy[i*4:i*4+4] for i in sampled)
        real_matches = sum(target[i*4:i*4+4] == original_atlas[i*4:i*4+4] for i in sampled)
        if old_matches > len(sampled) * 0.70 and old_matches > real_matches * 2.5:
            raise ValueError(
                'Alte falsch dekodierte TIM-Vorlage aus v2.1/v2.2 erkannt. '
                'Bitte in v2.3 die Original-TIM erneut exportieren und diese PNG bearbeiten.'
            )
    palettes = {clut: _palette(tim, clut) for clut in set(cmap)}
    updated = bytearray(original)
    originally_visible = 0
    subsequently_visible = 0
    for pos, clut in enumerate(cmap):
        if pos >= editable * 2:
            break   # The final 2048 bytes ARE the actual DW2 game palettes.
        if clut == -1:
            continue  # Unused UV space: preserve original native indices.
        palette = palettes[clut]
        old_byte = original[pos//2]
        old = (old_byte & 15) if pos % 2 == 0 else (old_byte >> 4)
        src = original_atlas[pos*4:pos*4+4]
        dst = target[pos*4:pos*4+4]
        originally_visible += src[3] >= 100
        if dst == src:
            new = old  # Preserve byte-for-byte when pixel was not edited.
        else:
            # For visible edited texels, do not choose an invisible palette
            # entry simply because its RGB is close to the requested shade.
            valid = [k for k, c in enumerate(palette) if (c[3] >= 100) == (dst[3] >= 100)]
            if not valid:
                raise ValueError('Farbpalette enthält keine passende Transparenzstufe für das bearbeitete Pixel.')
            new = min(valid, key=lambda k: sum((palette[k][i] - dst[i]) ** 2 for i in range(3)) +
                      (0 if k == old else 1))
        subsequently_visible += palette[new][3] >= 100
        if pos % 2:
            updated[pos//2] = (updated[pos//2] & 15) | (new << 4)
        else:
            updated[pos//2] = (updated[pos//2] & 240) | new
    if originally_visible < 200:
        raise ValueError('Die echte Digimon-Textur konnte nicht zuverlässig zugeordnet werden.')
    if subsequently_visible < originally_visible * 0.75:
        raise ValueError('Die neue Textur würde mehr als 25 % der sichtbaren Digimon-Pixel ausblenden. Schreibvorgang abgebrochen.')
    if updated[-PALETTE_BYTES:] != original[-PALETTE_BYTES:]:
        raise RuntimeError('Interner Fehler: Native Farbpaletten wurden verändert.')
    result = bytearray(tim.data[:tim.end])
    result[tim.pixel_offset:tim.end] = updated
    return bytes(result)
