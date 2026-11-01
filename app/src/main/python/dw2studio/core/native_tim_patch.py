"""Write fixed-size indexed TIM pixel data back into a native DW2 model file.

This is NOT a generic 3D OBJ encoder or glTF-atlas importer. The PNG must
match the raw PS1 TIM pixel grid, and indexed images are mapped to the
original 16/256-entry CLUT. Other palette banks, geometry, UVs, animation,
unknown bytes and the original ROM stay unchanged.
"""
from dataclasses import dataclass
from pathlib import Path
from PIL import Image
from dw2studio.assets.tim import TIM, find_tim
from .psx_patch import patch_sectors_copy
from .psx_sector import RAW_SIZE
from .dw2_file_index import _read_lbas

@dataclass(frozen=True)
class TimRegion:
    offset: int
    width: int
    height: int
    bpp: int
    length: int


def regions(model_bytes):
    return tuple(TimRegion(*info) for info in find_tim(model_bytes))


def replace_tim(model_bytes,png,tim_index=0, *, recolor=False, eye_frames=False, palette_mode='protect'):
    """Return fixed-length updated Mxxxx.BIN, preserving all non-TIM bytes."""
    data=bytes(model_bytes)
    found=regions(data)
    if type(tim_index) is not int or not 0<=tim_index<len(found):
        raise ValueError('Kein gültiger TIM-Abschnitt an dieser Position.')
    region=found[tim_index]
    tim=TIM(data[region.offset:])
    if tim.bpp==3:
        raise ValueError('24-Bit-TIM wird hier nicht geschrieben.')
    with Image.open(png) as im:
        if im.size!=(region.width,region.height):
            raise ValueError(f'PNG muss exakt {region.width}×{region.height} Pixel haben. Keine automatische Skalierung.')
        # DW2 hides its true 64 face-selectable palettes in the final 2048
        # 'pixel' bytes of the TIM. A generic TIM encoder corrupts those bytes.
        from .dw2_native_atlas import is_native_dw2_tim, encode_native_atlas
        if is_native_dw2_tim(tim):
            payload=encode_native_atlas(data,region.offset,im,recolor=recolor,eye_frames=eye_frames,palette_mode=palette_mode)
        else:
            payload=encode_native_tim(tim, im, recolor=recolor)

    if len(payload)!=region.length:
        raise ValueError('TIM-Encoder hat die Größe verändert.')
    result=bytearray(data)
    result[region.offset:region.offset+region.length]=payload
    if len(result)!=len(data) or result[:region.offset]!=data[:region.offset] or result[region.offset+region.length:]!=data[region.offset+region.length:]:
        raise RuntimeError('Unzulässige Änderung außerhalb des TIM-Blocks.')
    TIM(result[region.offset:]).to_image() # fail-closed for corrupt replacement
    return bytes(result),region



def encode_native_tim(tim, image, *, recolor=False):
    """Encode within original TIM bounds. Optional 16/256-color palette replacement.

    Recoloring is only permitted for a single-bank indexed TIM because
    modifying one bank of a multi-bank CLUT has unknown game-side effects.
    PlayStation 15-bit RGB and binary transparency impose hardware limits.
    """
    from .dw2_native_atlas import is_native_dw2_tim
    if is_native_dw2_tim(tim):
        raise ValueError('DW2-TIM enthält 2048 Bytes echte Face-CLUTs im Pixelblock. '
                         'Nur replace_tim mit vollständigen Modellbytes darf diese Textur schreiben.')
    if not recolor or tim.bpp == 2:
        return tim.replace_image(image)
    if tim.bpp not in (0, 1) or not tim.has_clut or len(tim.palette_banks) != 1:
        raise ValueError('Neue Farben werden nur bei indizierten TIMs mit einer Palette unterstützt.')
    rgba = image.convert('RGBA')
    if rgba.size != (tim.width, tim.height):
        raise ValueError(f'Native TIM-Größe muss {tim.width} × {tim.height} sein.')
    if rgba.tobytes() == tim.to_image().tobytes():
        # Preserve original palette and index bytes for no-op round trips.
        return tim.data[:tim.end]
    pixels = list(rgba.get_flattened_data() if hasattr(rgba, "get_flattened_data") else rgba.getdata())
    transparent = any(c[3] < 128 for c in pixels)
    max_colors = 16 if tim.bpp == 0 else 256
    available = max_colors - int(transparent)
    opaque = [c[:3] for c in pixels if c[3] >= 128]
    if not opaque:
        palette = [(0, 0, 0, 0)]
        indexes = [0] * len(pixels)
    else:
        source = Image.new('RGB', (len(opaque), 1))
        source.putdata(opaque)
        reduced = source.quantize(colors=available, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        raw_palette = reduced.getpalette()
        native = list(reduced.get_flattened_data() if hasattr(reduced, "get_flattened_data") else reduced.getdata())
        colors = max(native) + 1
        palette = ([(0, 0, 0, 0)] if transparent else []) + [
            (*raw_palette[i*3:i*3+3], 255) for i in range(colors)
        ]
        shift = int(transparent)
        it = iter(native)
        indexes = [0 if c[3] < 128 else next(it) + shift for c in pixels]
    if len(palette) > max_colors:
        raise RuntimeError('Palette ist größer als das native TIM-Format erlaubt.')
    from dw2studio.assets.tim import pack_color
    import struct
    result = bytearray(tim.data[:tim.end])
    for i, rgba_color in enumerate(palette):
        struct.pack_into('<H', result, 20 + i * 2, pack_color(rgba_color))
    if tim.bpp == 0:
        if len(indexes) % 2:
            raise ValueError('Ungültige 4-Bit-TIM-Breite.')
        image_bytes = bytes(indexes[i] | (indexes[i+1] << 4) for i in range(0, len(indexes), 2))
    else:
        image_bytes = bytes(indexes)
    if tim.pixel_offset + len(image_bytes) != tim.end:
        raise ValueError('TIM-Pixelgröße ist nicht unverändert geblieben.')
    result[tim.pixel_offset:tim.end] = image_bytes
    TIM(result).to_image()  # Ensure the resulting palette/image decodes.
    return bytes(result)


def patch_model_tim_image_copy(image,entry,png,output,tim_index=0, *, recolor=False,eye_frames=False,palette_mode='protect'):
    """Patch TIM pixels in a recovered native model as new Mode-2-Form-1 RAW BIN."""
    image=Path(image)
    if image.stat().st_size%RAW_SIZE:
        raise ValueError('Native TIM-Rückschreibung benötigt eine 2352-Byte-RAW-BIN.')
    if entry.directory or not Path(entry.path).name.upper().startswith('M') or not Path(entry.path).name.upper().endswith('.BIN'):
        raise ValueError('Es muss eine native DW2-Modell-BIN (Mxxxx.BIN) sein.')
    if entry.lba < 0 or entry.size <= 0 or entry.lba+(entry.size+2047)//2048 > image.stat().st_size//RAW_SIZE:
        raise ValueError('Modell-Eintrag außerhalb des Images.')
    allocated=b''.join(_read_lbas(image,entry.lba,(entry.size+2047)//2048))
    original=allocated[:entry.size]
    changed,region=replace_tim(original,png,tim_index,recolor=recolor,eye_frames=eye_frames,palette_mode=palette_mode)
    patched=changed+allocated[entry.size:]
    sectors={}
    for i in range(0,len(allocated),2048):
        if patched[i:i+2048]!=allocated[i:i+2048]:
            sectors[entry.lba+i//2048]=patched[i:i+2048]
    if not sectors:
        raise ValueError('PNG führt zu keiner Änderung der TIM-Pixelindizes.')
    out=patch_sectors_copy(image,output,sectors)
    return out,region,len(sectors)
