"""Format limits of DW2 native models, checked before a mod is exported (Abschnitt 15).

The encoders keep to these limits by themselves (dw3_native.plan: split parts, flatten levels);
this is the last check on the finished bytes, also for models that came from elsewhere
(imported mods, the glTF path). Protective, never relaxing: a file that breaks a limit is refused.
"""
import struct

from .native_model import NativeModel

MAX_PARTS = 64
MAX_DEPTH = 7          # depth word per part: 0..7 (eight levels)
MAX_INDEX = 256        # vertex / normal indices are one byte


def model_problems(data):
    """List of plain-language problems; empty if the model keeps every limit."""
    try:
        model = NativeModel(data)
    except ValueError as exc:
        return [f'Modell nicht lesbar: {exc}']
    n = model.bone_count
    out = []
    if n > MAX_PARTS:
        out.append(f'{n} Modellteile (höchstens {MAX_PARTS}).')
    depths = struct.unpack_from(f'<{n}I', data, 12 + 12 * n)
    last = -1
    for i, d in enumerate(depths):
        if d > MAX_DEPTH:
            out.append(f'Teil {i}: Hierarchieebene {d + 1} (höchstens {MAX_DEPTH + 1}).')
        elif d > last + 1:
            out.append(f'Teil {i}: Ebene springt von {last + 1} auf {d + 1} (kein Elternteil).')
        last = min(d, MAX_DEPTH)
    if depths and depths[0] != 0:
        out.append('Das erste Teil muss auf Ebene 1 liegen.')
    return out


def check_staged(session):
    """Problems of every staged native model, by edit label."""
    out = []
    for edit in session.edits.values():
        data, original = edit.replacement, edit.original
        try:
            NativeModel(original)
        except Exception:
            continue                         # not a model file
        for p in model_problems(data):
            out.append(f'{edit.label}: {p}')
    return out
