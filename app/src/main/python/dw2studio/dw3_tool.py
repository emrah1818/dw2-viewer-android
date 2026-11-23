"""Start des DW3-Konverters (third_party/dw3_converter) auf jeder Plattform.

Windows/Linux-Studio: tools/dw3_converter/dw3_converter[.exe] neben dem Programm.
Android: libdw3conv.so im nativeLibraryDir (ausführbares Programm, mit dem NDK gebaut);
android_api.configure setzt DW3_CONVERTER.
Web (Pyodide): WebAssembly-Fassung über die JS-Funktion dw3convRun im Worker.
"""
import os
import subprocess
import sys
from pathlib import Path


def converter():
    env = os.environ.get('DW3_CONVERTER')
    if env:
        path = Path(env)
    else:
        root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
        path = root / 'tools' / 'dw3_converter' / ('dw3_converter.exe' if os.name == 'nt' else 'dw3_converter')
    if not path.is_file():
        raise ValueError('DW3-Konverter fehlt (tools/build_dw3_converter.py).')
    return path


def run(args, timeout):
    """Wie subprocess.run(..., capture_output=True, text=True): returncode, stdout, stderr."""
    args = [str(a) for a in args]
    if sys.platform == 'emscripten':
        import json
        import js
        if not hasattr(js, 'dw3convWeb'):
            raise ValueError('DW3-Konverter (WebAssembly) nicht geladen.')
        result = json.loads(js.dw3convWeb(json.dumps(args)))
        return subprocess.CompletedProcess(args, result['returncode'], result['stdout'], result['stderr'])
    return subprocess.run([str(converter()), *args], capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
