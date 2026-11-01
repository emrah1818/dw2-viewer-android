"""Ruft den DW2-Konverter als native Android-Bibliothek (libdw2conv.so) per ctypes auf."""
from pathlib import Path
import ctypes
import os

_lib = None


def _load(native_dir):
    global _lib
    if _lib is not None:
        return _lib
    candidates = []
    if os.environ.get('DW2_CONVERTER_LIB'):
        candidates.append(Path(os.environ['DW2_CONVERTER_LIB']))
    if native_dir:
        candidates.append(Path(native_dir) / 'libdw2conv.so')
    for path in candidates:
        if path.is_file():
            lib = ctypes.CDLL(str(path))
            lib.dw2_convert.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            lib.dw2_convert.restype = ctypes.c_int
            _lib = lib
            return lib
    raise FileNotFoundError('Konverter-Bibliothek libdw2conv.so fehlt.')


def convert(native_dir, source, output):
    source, output = Path(source), Path(output)
    if not source.is_dir() or not any(source.iterdir()):
        raise ValueError('Keine extrahierten Modell-Dateien gefunden')
    output.mkdir(parents=True, exist_ok=True)
    code = _load(native_dir).dw2_convert(str(source).encode(), str(output).encode())
    if code:
        raise RuntimeError(f'Konverter fehlgeschlagen (Code {code}).')
