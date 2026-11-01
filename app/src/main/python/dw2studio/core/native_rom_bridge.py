"""Validated, non-destructive bridge from viewer Digimon to native DW2 TIM in a CD image.

Native 3D geometry is deliberately NOT encoded here. Only the PS1 TIM payload
inside an existing MxxxYYYY.BIN may be updated. A new image is always created.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from PIL import Image

from .disc import Disc
from .native_tim_patch import regions, patch_model_tim_image_copy
from .dw2_file_index import _read_lbas
from dw2studio.assets.tim import TIM


@dataclass(frozen=True)
class NativeTextureInfo:
    entry: object
    region: object
    tim_index: int
    image_path: Path
    native_bytes: bytes


def raw_image_path(source):
    """Resolve a single-track CUE and reject unsupported image layouts."""
    disc = Disc(source)
    try:
        if disc.sector_size != 2352:
            raise ValueError('ROM-Texturpatch unterstützt bisher nur 2352-Byte-RAW-BIN/CUE, keine 2048-ISO.')
        return disc.path.resolve()
    finally:
        disc.close()


def native_model_entry(entries, digimon):
    filename = f'M{int(digimon.id):03d}{str(digimon.code).upper()}.BIN'
    matches = [e for e in entries if not e.directory and
               e.path.replace('\\', '/').split('/')[-1].upper() == filename]
    unique = {(e.lba, e.size): e for e in matches}
    if not unique:
        raise ValueError(f'Native Modelldatei {filename} ist im Image nicht vorhanden.')
    if len(unique) != 1:
        raise ValueError(f'{filename} kommt mehrfach an verschiedenen Stellen vor. Automatisches Schreiben verweigert.')
    return next(iter(unique.values()))


def native_texture_info(source, entries, digimon, tim_index=0):
    image = raw_image_path(source)
    entry = native_model_entry(entries, digimon)
    if not entry.size or entry.lba < 0 or entry.lba + (entry.size + 2047)//2048 > image.stat().st_size//2352:
        raise ValueError('Native Modelldatei liegt außerhalb des Spiel-Images.')
    original = b''.join(_read_lbas(image, entry.lba, (entry.size + 2047)//2048))[:entry.size]
    found = regions(original)
    if not 0 <= tim_index < len(found):
        raise ValueError('Dieses Modell enthält keine unterstützte native TIM-Textur.')
    return NativeTextureInfo(entry, found[tim_index], tim_index, image, original)


def native_png(source, entries, digimon, output, tim_index=0, *, eye_frames=False, overwrite=False):
    """Export native indexed pixels, NOT the converter's rearranged glTF atlas."""
    info = native_texture_info(source, entries, digimon, tim_index)
    output = Path(output).resolve()
    if output == info.image_path:
        raise ValueError('Spieldatei darf nicht überschrieben werden.')
    # Der Datei-Dialog hat das Überschreiben bereits bestätigt (overwrite=True).
    if output.exists() and not overwrite:
        raise FileExistsError(f'PNG existiert bereits: {output}')
    if output.suffix.lower() != '.png':
        raise ValueError('Ziel muss eine .png-Datei sein.')
    from .dw2_native_atlas import decode_native_atlas, is_native_dw2_tim
    tim = TIM(info.native_bytes[info.region.offset:])
    out = (decode_native_atlas(info.native_bytes, info.region.offset,include_eye_frames=eye_frames)
           if is_native_dw2_tim(tim) else tim.to_image())
    output.parent.mkdir(parents=True, exist_ok=True)
    out.save(output, 'PNG')
    return output, info


def write_native_png_image_copy(source, entries, digimon, png, output, *, tim_index=0, recolor=True,eye_frames=False):
    """Write the PNG to a NEW RAW image, preserving every byte outside its TIM.

    The native PNG must have the exact raw PS1 TIM pixel layout (not necessarily
    the same layout as a converted glTF texture); no unsafe resize or UV remap.
    """
    info = native_texture_info(source, entries, digimon, tim_index)
    with Image.open(png) as incoming:
        if incoming.format != 'PNG':
            raise ValueError('Als native TIM-Ersatztextur wird eine PNG-Datei benötigt.')
        if incoming.size != (info.region.width, info.region.height):
            raise ValueError(
                f'Die native Textur muss {info.region.width} × {info.region.height} Pixel haben. '
                f'Die glTF-Textur kann ein anderes Atlas-Layout besitzen. '
                f'Bitte zunächst die Original-TIM-Vorlage exportieren und diese bearbeiten.'
            )
    target = Path(output).resolve()
    if target.exists():
        raise FileExistsError(f'Ziel existiert bereits: {target}')
    if target == info.image_path:
        raise ValueError('Original-BIN darf nicht überschrieben werden.')
    # Preflight the *native PS1 color result* before copying a 460 MB image.
    # In v2.3 new blue/orange textures were approximated using the original
    # palettes and became purple/yellow inside the game. A palette-aware
    # re-encode plus decoded-image check now guards against this regression.
    from .dw2_native_atlas import is_native_dw2_tim
    native_tim = TIM(info.native_bytes[info.region.offset:])
    if is_native_dw2_tim(native_tim):
        from .dw2_palette_recolor import preview_native_texture
        with Image.open(png) as desired:
            expected_tim, _, quality = preview_native_texture(
                info.native_bytes, info.region.offset, desired, recolor=recolor,eye_frames=eye_frames
            )
        if expected_tim == native_tim.data[:native_tim.end]:
            raise ValueError('Die PNG enthält keine wirksamen Änderungen an nativen Textur- oder Augenpixeln. '
                             'Die reservierten Farbpaletten-Zeilen und unbenutzte Flächen werden ignoriert.')
    else:
        quality = None
    # Only publish the final image after readback validation succeeded.
    pending = target.with_name(target.name + '.tim-verification-partial')
    if pending.exists():
        raise FileExistsError(f'Unvollständiger alter Arbeitsstand vorhanden: {pending}')
    try:
        result, region, sector_count = patch_model_tim_image_copy(
            info.image_path, info.entry, png, pending, tim_index, recolor=recolor,eye_frames=eye_frames
        )
        # Verify that no geometry/animation bytes changed in the extracted M file.
        d = Disc(result)
        try:
            changed = d.read(info.entry.lba, info.entry.size)
        finally:
            d.close()
        a, b = region.offset, region.offset + region.length
        if changed[:a] != info.native_bytes[:a] or changed[b:] != info.native_bytes[b:]:
            raise RuntimeError('Validierungsfehler: Änderungen außerhalb des TIM-Blocks gefunden.')
        if changed[a:b] == info.native_bytes[a:b]:
            raise ValueError('Die PNG enthält keine gegenüber dem Image geänderten Pixel/Farben.')
        if quality is not None:
            # The image written to the disc must reproduce exactly what the
            # preflight showed, not merely have valid CD EDC/ECC checksums.
            from .dw2_palette_recolor import preview_native_texture
            with Image.open(png) as desired:
                expected_tim, _, post_quality = preview_native_texture(
                    info.native_bytes, info.region.offset, desired, recolor=recolor,eye_frames=eye_frames
                )
            if changed[a:b] != expected_tim or post_quality != quality:
                raise RuntimeError('Die BIN enthält nach dem Schreiben andere Farbdaten als die Vorschau.')
        pending.replace(target)
    except BaseException:
        pending.unlink(missing_ok=True)
        raise
    return target, info, sector_count


def write_cue_for_image(source_cue, output_bin):
    """Copy a one-BINARY-track CUE while referencing the new BIN filename.

    CD track metadata stays exactly as in the original CUE. The new CUE is
    optional because some emulators accept a raw BIN directly.
    """
    import re
    cue = Path(source_cue)
    if cue.suffix.lower() != '.cue' or not cue.is_file():
        return None
    text = cue.read_text(encoding='utf-8-sig', errors='replace')
    pattern = re.compile(r'(?im)^(\s*FILE\s+)(?:"[^"]+"|\S+)(\s+BINARY\s*)$')
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError('CUE mit mehreren Tracks/Quelldateien kann nicht automatisch umgeschrieben werden.')
    out = Path(output_bin).with_suffix('.cue')
    if out.exists():
        raise FileExistsError(f'CUE existiert bereits: {out}')
    patched = pattern.sub(lambda m: f'{m.group(1)}"{Path(output_bin).name}"{m.group(2)}', text, count=1)
    out.write_text(patched, encoding='utf-8')
    return out
