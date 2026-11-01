"""Native Digimon World 2 face-CLUT recoloring.

The game uses 64 *physical* palettes of 16 RGB555 colors packed in the
last 2048 bytes of the TIM image data, selected independently by each polygon.
A PNG cannot be written by merely mapping to the *old* colors: to reproduce a
recolored Digimon we must rewrite those RGB555 palettes as well as the nibble
indices, while never changing geometry, UVs, or the PS1 TIM structure.

The GUI defaults to the original v3.1 candidate comparison (palette_v31.py).
The later protect/exact modes remain explicit alternatives.
An edited atlas can have more colors than a PS1 palette can represent. New
colors are explicitly protected when they fit the available RGB555 slots.
Exact mode rejects any palette requiring reduction. Quality is checked both
globally and specifically on edited pixels, so tiny colored eyes cannot
disappear behind a low whole-texture average error.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import struct
from PIL import Image

from dw2studio.assets.tim import TIM


@dataclass(frozen=True)
class PaletteQuality:
    mean_rgb_error: float
    bad_pixel_fraction: float
    alpha_mismatch_fraction: float
    colors_rewritten: int
    palettes_rewritten: int
    pixels_checked: int
    edited_pixels_checked: int = 0
    edited_mean_rgb_error: float = 0.0
    edited_bad_pixel_fraction: float = 0.0
    edited_max_rgb_error: int = 0
    edited_chroma_lost: int = 0


def _raw_color(rgb, *, transparent=False, semi=False):
    if transparent:
        return 0
    r, g, b = (max(0, min(31, (int(v) + 4) // 8)) for v in rgb)
    if r == g == b == 0:
        return 0x8000  # BLACK must be visible, raw zero is transparent
    return r | (g << 5) | (b << 10) | (0x8000 if semi else 0)


def _decode(raw, face_stp):
    r, g, b = ((raw >> k & 31) << 3 for k in (0, 5, 10))
    if not (r or g or b):
        a = 255 if raw & 0x8000 else 0
    else:
        a = 127 if face_stp and raw & 0x8000 else 255
    return (r, g, b, a)


def _desired_group(dst, *, face_stp, old_alpha):
    """Keep the original alpha contract; only palette RGB colors are edited.

    False semi/transparent flags can make body parts disappear in the game.
    Re-coloring is thus permitted, but changing alpha modes is not.
    """
    if old_alpha == 0:
        return 'transparent'
    if old_alpha == 127 and face_stp:
        return 'semi'
    return 'opaque'


def _color_error(a, b):
    return sum((int(a[i]) - int(b[i])) ** 2 for i in range(3))


def _group_palette(colors: list[tuple[int, int, int]], n: int):
    """Weighted deterministic median-cut in PS1's RGB555 color space."""
    if not colors or n < 1:
        return []
    histogram = Counter(tuple(min(31,(v + 4) // 8) * 8 for v in rgb) for rgb in colors)
    if len(histogram) <= n:
        return [v for v, _ in histogram.most_common()]
    # Quantize the *actual samples*, not just unique keys: visible areas get
    # proportionate weight, preserving broad flat colors over tiny artifacts.
    source = Image.new('RGB', (len(colors), 1))
    source.putdata([tuple(int(v) for v in rgb) for rgb in colors])
    reduced = source.quantize(colors=n, method=Image.Quantize.MEDIANCUT,
                              dither=Image.Dither.NONE)
    palette = reduced.getpalette()
    used = sorted(set(reduced.get_flattened_data() if hasattr(reduced, "get_flattened_data") else reduced.getdata()))
    return [tuple(palette[k*3:k*3+3]) for k in used]


def _wanted_word(sample):
    _,_,rgba,stp,old=sample
    category=_desired_group(rgba,face_stp=stp,old_alpha=old[3])
    return _raw_color(rgba[:3],transparent=category=='transparent',semi=category=='semi')


def _sample_edited(sample):
    return _decode(_wanted_word(sample),sample[3]) != sample[4]


def _assign_words(samples,words):
    assignments=[]
    for sample in samples:
        _,old_index,rgba,stp,old=sample
        category=_desired_group(rgba,face_stp=stp,old_alpha=old[3])
        choices=[i for i,raw in enumerate(words)
                 if (raw==0 if category=='transparent' else raw!=0 and
                     _decode(raw,stp)[3]==(127 if category=='semi' else 255))]
        if not choices:raise ValueError('Die native Palette kann die vorhandene Transparenz nicht abbilden.')
        edited=_sample_edited(sample)
        def error(i):
            color=_decode(words[i],stp);value=_color_error(color,rgba)
            if edited:
                wanted=max(rgba[:3])-min(rgba[:3]);actual=max(color[:3])-min(color[:3])
                if wanted>=48 and actual<wanted*.35:value+=1000000
            return value,i!=old_index,i
        assignments.append(min(choices,key=error))
    return assignments


def _install_words(samples,words,original):
    """Reuse exact original entries first; never force a new color onto an old index."""
    unique=list(dict.fromkeys(words))
    if len(unique)>16:raise ValueError('Mehr als 16 Paletteneinträge.')
    palette=list(original);locations={};available=set(range(16))
    for word in unique:
        found=next((i for i in sorted(available) if palette[i]==word),None)
        if found is not None:locations[word]=found;available.remove(found)
    for word in unique:
        if word not in locations:
            index=min(available);available.remove(index);locations[word]=index;palette[index]=word
    indexes=[];assignment_cache={}
    for sample in samples:
        wanted=_wanted_word(sample);old_index=sample[1]
        if wanted in locations:
            indexes.append(old_index if palette[old_index]==wanted else locations[wanted])
        else:
            key=(sample[1],tuple(sample[2]),sample[3],tuple(sample[4]))
            if key not in assignment_cache:assignment_cache[key]=_assign_words([sample],palette)[0]
            indexes.append(assignment_cache[key])
    return palette,indexes


def _palette_from_target(samples, raw_original, *, palette_mode='protect'):
    """Exact RGB555 when possible; otherwise reserve colors of edited pixels.

    The old whole-bank mean-square score could discard a tiny blue iris in
    favor of many gray metal pixels. Protect new words explicitly rather than
    making them compete solely on the number of pixels they cover.
    """
    if palette_mode=='v31':
        from .palette_v31 import palette_from_target
        return palette_from_target(samples,raw_original)
    if palette_mode not in ('protect','exact'):raise ValueError('Unbekannter Palettenmodus.')
    desired=list(dict.fromkeys(_wanted_word(s) for s in samples))
    if len(desired)<=16:return _install_words(samples,desired,raw_original)
    if palette_mode=='exact':
        raise ValueError(f'{len(desired)} benötigte RGB555-Farben in einer Teilpalette, maximal 16. Exakter Import ohne zusätzliche Farbreduktion ist hier nicht möglich.')
    edited=[s for s in samples if _sample_edited(s)]
    pinned=list(dict.fromkeys(_wanted_word(s) for s in edited))
    categorized=defaultdict(list)
    for sample in samples:
        categorized[_desired_group(sample[2],face_stp=sample[3],old_alpha=sample[4][3])].append(sample)
    categories=[c for c in ('transparent','semi','opaque') if categorized[c]]
    def category_word(raw):return 'transparent' if raw==0 else 'semi' if raw&0x8000 and raw&0x7fff else 'opaque'
    pinned_by={c:[raw for raw in pinned if category_word(raw)==c] for c in categories}
    allocations={c:max(1,len(pinned_by[c])) for c in categories}
    can_lock=sum(allocations.values())<=16
    if not can_lock:
        pinned_by={c:[] for c in categories};allocations={c:1 for c in categories}
    edit_count=len(edited);weight=max(8.,len(samples)/max(1,edit_count))
    weighted={c:sum(weight if _sample_edited(s) else 1 for s in categorized[c]) for c in categories}
    slots=16-sum(allocations.values())
    while slots:
        eligible=[c for c in categories if allocations[c]<len(set(_wanted_word(s) for s in categorized[c]))]
        if not eligible:break
        category=max(eligible,key=lambda c:weighted[c]/(allocations[c]+.4))
        allocations[category]+=1;slots-=1
    representatives=[]
    for category in categories:
        if category=='transparent':representatives.append(0);continue
        fixed=pinned_by[category];representatives.extend(fixed)
        remaining=allocations[category]-len(fixed)
        if not remaining:continue
        residual=[s for s in categorized[category] if _wanted_word(s) not in fixed]
        # Bound the weighted sample image. Edited pixels receive comparable
        # weight even when they occupy a small fraction of a shared palette.
        histogram=Counter()
        for sample in residual:
            rgb=_decode(_wanted_word(sample),sample[3])[:3]
            histogram[rgb]+=weight if _sample_edited(sample) else 1
        total=sum(histogram.values());samples_rgb=[]
        scale=min(1.,65536/max(1.,total))
        for rgb,count in sorted(histogram.items()):samples_rgb.extend([rgb]*max(1,round(count*scale)))
        representatives.extend(_raw_color(rgb,semi=category=='semi') for rgb in _group_palette(samples_rgb,remaining))
    palette,indexes=_install_words(samples,representatives,raw_original)
    if can_lock:
        for sample,index in zip(samples,indexes):
            if _sample_edited(sample) and palette[index]!=_wanted_word(sample):raise RuntimeError('Geschützte neue Farbe wurde verändert.')
    return palette,indexes

@dataclass(frozen=True)
class NativeEditReport:
    """Non-editable PNG pixels that must never become PS1 model bytes."""
    palette_storage_ignored: int
    unmapped_texture_ignored: int


def prepare_native_edit(model: bytes, tim_offset: int, image: Image.Image, *, eye_frames=False):
    """Return a safe atlas and an explicit report of skipped paint edits.

    DW2 stores 64 *game palettes* in the physical bytes occupied by atlas rows
    224..255. Image editors often resave those 32 rows with new RGB or alpha,
    even when the user did not intend to edit them. Rejecting the entire PNG is
    counterproductive; writing them as texels would corrupt the model.

    Restore those rows from the true source texture and also restore texels
    without a validated polygon/eye-CLUT mapping. Both regions were never
    writable in DW2. In particular, perform normalization BEFORE the no-op
    comparison, otherwise a change only in the reserved area could needlessly
    requantize every game palette.

    Never sanitize mapped body or eye pixels: visibility/alpha and color
    quality checks for those real texture pixels remain mandatory.
    """
    from .dw2_native_atlas import (PALETTE_BYTES, decode_native_atlas,
                                    face_clut_map, is_native_dw2_tim)
    tim = TIM(model[tim_offset:])
    if not is_native_dw2_tim(tim):
        raise ValueError('Nur originale 4-Bit-DW2-Modelltexturen unterstützt.')
    if image.size != (128, 256):
        raise ValueError('Die native DW2-PNG muss 128×256 Pixel groß sein.')
    cmap = (face_clut_map(model) if not eye_frames else
            __import__('dw2studio.core.dw2_eyes', fromlist=['eye_clut_map']).eye_clut_map(model))
    reference = decode_native_atlas(model, tim_offset,
                                    include_eye_frames=eye_frames).tobytes()
    target = bytearray(image.convert('RGBA').tobytes())
    editable_pixels = (tim.end - tim.pixel_offset - PALETTE_BYTES) * 2
    reserved = unmapped = 0
    for p, mapped in enumerate(cmap):
        # Palette storage takes priority even if an invalid source model's UVs
        # accidentally point into the last 32 texture rows.
        skip_palette = p >= editable_pixels
        if not skip_palette and mapped != -1:
            continue
        pos = p * 4
        if target[pos:pos+4] != reference[pos:pos+4]:
            if skip_palette: reserved += 1
            else: unmapped += 1
            target[pos:pos+4] = reference[pos:pos+4]
    return (Image.frombytes('RGBA', (128, 256), bytes(target)),
            NativeEditReport(reserved, unmapped), cmap, reference)


def native_edit_report(model: bytes, tim_offset: int, image: Image.Image, *, eye_frames=False):
    """Inspect what an edited PNG cannot carry back to the native game."""
    return prepare_native_edit(model, tim_offset, image, eye_frames=eye_frames)[1]


def encode_recolored_native_atlas(model: bytes, tim_offset: int, image: Image.Image, *, eye_frames=False, palette_mode='protect') -> bytes:
    from .dw2_native_atlas import PALETTE_BYTES
    tim = TIM(model[tim_offset:])
    # Ignore PNG modifications in *physical palette storage* (bottom 32 rows)
    # and outside validated body/eye polygons, without touching native bytes.
    safe_image, ignored, cmap, original_atlas = prepare_native_edit(
        model, tim_offset, image, eye_frames=eye_frames
    )
    native = tim.data[tim.pixel_offset:tim.end]
    editable_pixels = (len(native) - PALETTE_BYTES) * 2
    target = safe_image.tobytes()
    if target == original_atlas:
        return tim.data[:tim.end]

    # Reject the OLD v2.1/v2.2 export: it used the dummy TIM palette, which is
    # unrelated to the native face palettes. Recoloring it could otherwise
    # silently destroy the intended appearance.
    dummy = tim.to_image().convert('RGBA').tobytes()
    used = [i for i in range(editable_pixels) if cmap[i] != -1]
    if used:
        dummy_matches = sum(target[i*4:i*4+4] == dummy[i*4:i*4+4] for i in used)
        real_matches = sum(target[i*4:i*4+4] == original_atlas[i*4:i*4+4] for i in used)
        if dummy_matches > len(used) * .70 and dummy_matches > 2.5 * real_matches:
            raise ValueError('Fehlerhafte v2.1/v2.2-TIM-PNG erkannt. Bitte eine aktuelle '
                             'Original-TIM-PNG exportieren und davon ausgehend bearbeiten.')
    # Detect incorrectly indexed PNGs and accidental full-alpha paint operations.
    sample_positions = [i for i in range(editable_pixels) if cmap[i] != -1]
    if not sample_positions:
        raise ValueError('Es wurden keine Texturflächen gefunden.')
    changes_alpha = sum((target[p*4+3] < 64) != (original_atlas[p*4+3] < 64)
                        for p in sample_positions)
    if changes_alpha > len(sample_positions) * 0.01:
        raise ValueError('Die PNG verändert die Transparenz von mehr als 1 % der sichtbaren Texturflächen. '
                         'Bitte das Alpha aus der neu exportierten Original-TIM-Vorlage übernehmen.')
    bad_half_alpha = sum((100 <= target[p*4+3] <= 200) !=
                         (100 <= original_atlas[p*4+3] <= 200) for p in sample_positions)
    if bad_half_alpha > len(sample_positions) * .01:
        raise ValueError('Die PNG verändert die Semitransparenz von Modellflächen. '
                         'Bitte den ursprünglichen Alphakanal beibehalten.')

    palettes_start = tim.end - PALETTE_BYTES
    out = bytearray(tim.data[:tim.end])
    groups = defaultdict(list)
    for pos in sample_positions:
        clut = cmap[pos]
        col = (clut & 63)  # 0 or 1 physical 16-color bank
        row = ((clut >> 6) & 1023)-224
        bank = row*2 + col
        nib = native[pos//2]
        old_index = ((nib >> 4) & 15) if pos & 1 else nib & 15
        old_palette_val = struct.unpack_from('<H', native, len(native)-PALETTE_BYTES + bank*32 + old_index*2)[0]
        old_rgba = _decode(old_palette_val,bool(clut & 0x10000))
        rgba = target[pos*4:pos*4+4]
        groups[bank].append((pos,old_index,rgba,bool(clut & 0x10000),old_rgba))
    for bank, samples in groups.items():
        base = palettes_start + bank*32
        orig_pal = list(struct.unpack_from('<16H',out,base))
        try:proposed, indices = _palette_from_target(samples,orig_pal,palette_mode=palette_mode)
        except ValueError as exc:raise ValueError(f'Teilpalette {bank}: {exc}') from exc
        for s, ix in zip(samples, indices):
            pos = s[0]
            off = tim.pixel_offset + pos // 2
            if pos & 1:
                out[off] = (out[off] & 0xf) | (ix << 4)
            else:
                out[off] = (out[off] & 0xf0) | ix
        struct.pack_into('<16H',out,base,*proposed)
    # MANDATORY: no bytes outside the TIM, including its header, may change.
    if out[:tim.pixel_offset] != tim.data[:tim.pixel_offset]:
        raise RuntimeError('Native TIM-Header wurden unerwartet geändert.')
    return bytes(out)


def measure_native_quality(model: bytes, tim_offset: int, target: Image.Image, *, original_model: bytes | None = None, eye_frames=False) -> PaletteQuality:
    from .dw2_native_atlas import face_clut_map, decode_native_atlas
    actual = decode_native_atlas(model,tim_offset,include_eye_frames=eye_frames).convert('RGBA').tobytes()
    desired = target.convert('RGBA').tobytes()
    cmap = (face_clut_map(model) if not eye_frames else
            __import__("dw2studio.core.dw2_eyes", fromlist=["eye_clut_map"]).eye_clut_map(model))
    pts = [p for p,c in enumerate(cmap[:128*224]) if c != -1 and desired[p*4+3] >= 64]
    if not pts:
        raise ValueError('Die Zieltextur enthält keine sichtbaren Modell-Pixel.')
    error = sum(sum(abs(actual[p*4+k]-desired[p*4+k]) for k in range(3))
                for p in pts)/(len(pts)*3)
    bad = sum(max(abs(actual[p*4+k]-desired[p*4+k]) for k in range(3)) > 48
              for p in pts)/len(pts)
    mask_diff = sum((actual[p*4+3]<64)!=(desired[p*4+3]<64)
                    for p,c in enumerate(cmap[:128*224]) if c != -1)/len([c for c in cmap[:128*224] if c != -1])
    edited=[]
    if original_model is not None:
        old_rgba=decode_native_atlas(original_model,tim_offset,include_eye_frames=eye_frames).tobytes()
        for p in pts:
            wanted=_raw_color(desired[p*4:p*4+3]);before=_raw_color(old_rgba[p*4:p*4+3])
            if wanted!=before:edited.append(p)
    edited_error=sum(sum(abs(actual[p*4+k]-desired[p*4+k]) for k in range(3)) for p in edited)/(max(1,len(edited))*3)
    edited_bad=sum(max(abs(actual[p*4+k]-desired[p*4+k]) for k in range(3))>48 for p in edited)/max(1,len(edited))
    edited_max=max((max(abs(actual[p*4+k]-desired[p*4+k]) for k in range(3)) for p in edited),default=0)
    lost=0
    for p in edited:
        wanted=max(desired[p*4:p*4+3])-min(desired[p*4:p*4+3]);chroma=max(actual[p*4:p*4+3])-min(actual[p*4:p*4+3])
        if wanted>=48 and chroma<wanted*.35:lost+=1
    rewritten_colors = rewritten_palettes = 0
    if original_model is not None:
        old_tim = TIM(original_model[tim_offset:])
        new_tim = TIM(model[tim_offset:])
        old_colors = old_tim.data[old_tim.end-2048:old_tim.end]
        new_colors = new_tim.data[new_tim.end-2048:new_tim.end]
        rewritten_colors = sum(old_colors[j:j+2] != new_colors[j:j+2]
                               for j in range(0, 2048, 2))
        rewritten_palettes = sum(old_colors[j:j+32] != new_colors[j:j+32]
                                 for j in range(0, 2048, 32))
    return PaletteQuality(round(error,2),round(bad,4),round(mask_diff,4),
                          rewritten_colors,rewritten_palettes,len(pts),len(edited),round(edited_error,2),round(edited_bad,4),edited_max,lost)


def preview_native_texture(model: bytes, tim_offset: int, image: Image.Image, *, recolor=True, eye_frames=False, palette_mode='protect'):
    """Encode then decode the *actual* console texture before writing the CD.

    Returning the decoded PNG and per-face CLUT error makes the potentially
    lossy PS1 16-color limits visible and testable before touching a 460 MB BIN.
    """
    from .dw2_native_atlas import decode_native_atlas, encode_native_atlas
    updated_tim = encode_native_atlas(model,tim_offset,image,recolor=recolor,eye_frames=eye_frames,palette_mode=palette_mode)
    original = TIM(model[tim_offset:])
    patched = model[:tim_offset] + updated_tim + model[tim_offset+original.end:]
    predicted = decode_native_atlas(patched,tim_offset,include_eye_frames=eye_frames)
    quality = measure_native_quality(patched,tim_offset,image,original_model=model,eye_frames=eye_frames)
    if quality.alpha_mismatch_fraction > .01:
        raise ValueError('Vorschauprüfung: Transparenz hat sich unzulässig geändert.')
    if palette_mode!='v31' and (quality.edited_chroma_lost or quality.edited_mean_rgb_error>18 or quality.edited_bad_pixel_fraction>.10):
        raise ValueError(f'Die bearbeiteten Farben würden zu stark verändert (Fehler {quality.edited_mean_rgb_error:.1f}/255, starke Abweichungen {quality.edited_bad_pixel_fraction:.1%}, entfärbte Pixel {quality.edited_chroma_lost}). Textur nicht übernommen. Weniger unterschiedliche Farben pro Teilpalette verwenden oder den exakten RGB555-Modus prüfen.')
    if quality.mean_rgb_error > 25 or quality.bad_pixel_fraction > .20:
        raise ValueError(
            f'Die Farben der neuen PNG lassen sich mit den DW2-16-Farben-Paletten '
            f'nicht ausreichend genau darstellen (mittlerer RGB-Fehler '
            f'{quality.mean_rgb_error:.1f}/255; große Abweichungen '
            f'{quality.bad_pixel_fraction:.0%}). Textur nicht geschrieben. '
            'Bitte die Anzahl der Farben reduzieren oder die native TIM-Vorlage bearbeiten.'
        )
    return updated_tim, predicted, quality
