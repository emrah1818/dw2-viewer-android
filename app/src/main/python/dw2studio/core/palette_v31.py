"""Palettenverfahren aus dem ausgelieferten Viewer v3.1.

Unverändert übernommene Auswahl zwischen Index-Rekolorierung und Median-Cut.
Bewusst separat vom später hinzugefügten Modus protect/exact gehalten.
Quelle: DW2_3D_Viewer_v3_1/dw2studio/core/dw2_palette_recolor.py.
"""
from collections import Counter, defaultdict
from PIL import Image
from .dw2_palette_recolor import _raw_color, _decode, _desired_group, _color_error


def _group_palette(colors: list[tuple[int, int, int]], n: int):
    """Weighted deterministic median-cut in PS1's RGB555 color space."""
    if not colors or n < 1:
        return []
    histogram = Counter(tuple(((v + 4) // 8) * 8 for v in rgb) for rgb in colors)
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


def palette_from_target(samples, raw_original):
    """Return proposed 16 RGB555 palette entries and nibble index per pixel."""
    # Each sample is (pixel_position, old_index, desired_rgba, face_stp, old_rgba).
    by_index = defaultdict(list)
    for _, old_index, rgba, _, _ in samples:
        by_index[old_index].append(rgba[:3])
    # Candidate 1: remap palette colors, preserving existing pixel nibbles.
    direct = list(raw_original)
    for ix, pixels in by_index.items():
        avg = tuple(sum(c[k] for c in pixels) // len(pixels) for k in range(3))
        old = raw_original[ix]
        # Preserve whether an index renders transparent/semitransparent.
        direct[ix] = _raw_color(avg, transparent=(old == 0),
                                semi=bool(old & 0x8000 and old & 0x7fff))
    direct_assignment = [s[1] for s in samples]

    # Candidate 2: re-index into an optimized 16-color RGB555 palette.
    # Alpha-mode classes cannot share the same palette entry on STP polygons.
    categorized = defaultdict(list)
    for s in samples:
        pos, ix, rgba, stp, old_rgba = s
        cat = _desired_group(rgba, face_stp=stp, old_alpha=old_rgba[3])
        categorized[cat].append(s)
    categories = [c for c in ('transparent','semi','opaque') if categorized[c]]
    allocations = {c: 1 for c in categories}
    slots = 16 - len(categories)
    while slots:
        eligible = [c for c in categories if allocations[c] <
                    len(set(tuple((v+4)//8 for v in s[2][:3]) for s in categorized[c]))]
        if not eligible:
            break
        c = max(eligible, key=lambda v: len(categorized[v]) / (allocations[v] + 0.4))
        allocations[c] += 1
        slots -= 1
    optimized = []
    for category in categories:
        if category == 'transparent':
            optimized.append(0)
            continue
        colors = [s[2][:3] for s in categorized[category]]
        representatives = _group_palette(colors, allocations[category])
        optimized.extend(_raw_color(v, semi=(category == 'semi')) for v in representatives)
    optimized += [raw_original[i] for i in range(16)][:16-len(optimized)]
    optimized = optimized[:16]
    assignments = []
    for pos, old_index, rgba, stp, old_rgba in samples:
        target_category = _desired_group(rgba, face_stp=stp, old_alpha=old_rgba[3])
        choices = [i for i, raw in enumerate(optimized) if
                   ((raw == 0 and target_category == 'transparent') or
                    (raw != 0 and target_category == 'opaque' and
                     _decode(raw,stp)[3] == 255) or
                    (raw != 0 and target_category == 'semi' and
                     _decode(raw,stp)[3] == 127))]
        if not choices:
            raise ValueError('Die native Palette kann die vorhandene Transparenz nicht abbilden.')
        assignments.append(min(choices,key=lambda k: _color_error(_decode(optimized[k],stp),rgba)))

    def score(palette, indexes):
        return sum(_color_error(_decode(palette[ix], s[3]),s[2])
                   for s, ix in zip(samples,indexes))
    if score(direct,direct_assignment) <= score(optimized,assignments):
        return direct, direct_assignment
    return optimized, assignments
