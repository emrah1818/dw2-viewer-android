"""Locate the bundled DW2 converter in source or PyInstaller installations."""
from pathlib import Path
import os
import shutil
import sys

EXECUTABLE = "dw2_model_converter.exe"

def converter_candidates(base=None, environ=None):
    env = os.environ if environ is None else environ
    base = Path(base) if base is not None else Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
    roots = [base, base / "tools", base / "tools" / "dw2_model_converter", base / "bin"]
    if getattr(sys, "frozen", False):
        roots.extend([Path(sys.executable).resolve().parent, Path(sys.executable).resolve().parent / "tools"])
    for key in ("DW2_CONVERTER", "DW2_MODEL_CONVERTER"):
        if env.get(key):
            yield Path(env[key]).expanduser()
    for root in roots:
        yield root / EXECUTABLE
    found = shutil.which(EXECUTABLE)
    if found:
        yield Path(found)

def find_converter(base=None, environ=None):
    for path in converter_candidates(base, environ):
        if path.is_file():
            return path.resolve()
    return None
