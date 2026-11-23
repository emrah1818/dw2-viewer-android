#!/usr/bin/env bash
# Führt die Testsammlung des DW2 Mod Studios (Repo emrah1818/dw2-dw3-viewer, Tag STUDIO_TAG) gegen den
# Python-Kern DIESER App aus: der Studio-Stand wird geholt, app/src/main/python darübergelegt und
# SciPy, PyQt6 und VTK werden gesperrt (gibt es in der App/Web-Version nicht). Tests, die das
# Desktop-Fenster (Qt/VTK) brauchen, werden ausgelassen; alle anderen müssen bestehen.
#   tools/run_studio_tests.sh [pytest-Optionen]   (Arbeitsordner: STUDIO_TEST_DIR)
set -euo pipefail
cd "$(dirname "$0")/.."
STUDIO_TAG=$(cat tools/STUDIO_TAG)
WORK=${STUDIO_TEST_DIR:-build/studio-tests}
rm -rf "$WORK"
git -c advice.detachedHead=false clone -q --depth 1 --branch "$STUDIO_TAG" https://github.com/emrah1818/dw2-dw3-viewer "$WORK"
rm -rf "$WORK/dw2studio"
cp -r app/src/main/python/dw2studio "$WORK/"
cp app/src/main/python/*.py "$WORK/"
mkdir -p "$WORK/tools/dw3_converter"
[ -x build/dw3conv/dw3_converter ] && cp build/dw3conv/dw3_converter "$WORK/tools/dw3_converter/"
cp tests/studio_extra/*.py "$WORK/tests/"
# Oberfläche der App statt der des Studios (für die JS-Tests des Studios)
rm -rf "$WORK/www" && cp -r app/src/main/assets/www "$WORK/www" && echo '{"type":"module"}' > "$WORK/www/package.json"
cat > "$WORK/tests/sitecustomize_block.py" <<'PY'
import builtins
_real = builtins.__import__
BLOCK = ('scipy', 'PyQt6', 'vtk', 'vtkmodules')
def _imp(name, *a, **k):
    if name.split('.')[0] in BLOCK:
        raise ImportError('in der Android-/Web-Version nicht vorhanden: ' + name)
    return _real(name, *a, **k)
builtins.__import__ = _imp
PY
# Desktop-only Tests (Qt-Fenster, VTK-Renderer, PyInstaller, Studio-Hauptfenster)
DESKTOP="test_desktop_v40.py test_eye_vtk_v25.py test_rig_gui_v8.py test_viewer_v30.py test_017_hd_and_ui.py test_eye_frames_v25.py test_eye_variants_v26.py test_rig_upstream_v8.py"
# DNA als PC-Port-Mod (dna_overrides.json): die mobile Fassung schreibt DNA-Regeln stattdessen ins
# Image (dna_image.py, eigene Tests in tests/studio_extra/test_dna_image.py)
DESKTOP="$DESKTOP test_dna_integration.py"
IGNORE=""; for t in $DESKTOP; do IGNORE="$IGNORE --ignore=tests/$t"; done
cd "$WORK"
cat > tests/conftest.py <<'PY'
import importlib.util, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import sitecustomize_block  # noqa: F401  (vor allen anderen Importen)
SKIPPED = []
DESKTOP_ONLY = ('nicht vorhanden', 'dw2studio.renderer', 'dw2studio.gui', "No module named 'studio'", "No module named 'desktop'")

def pytest_ignore_collect(collection_path, config):
    # Testdateien, die schon beim Import das Desktop-Fenster (Qt/VTK) brauchen, auslassen und melden.
    p = str(collection_path)
    if not (p.endswith('.py') and os.path.basename(p).startswith('test_')):
        return None
    spec = importlib.util.spec_from_file_location('_probe_' + os.path.basename(p)[:-3], p)
    try:
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    except ImportError as exc:
        if any(k in str(exc) for k in DESKTOP_ONLY):
            SKIPPED.append(os.path.basename(p))
            return True
    except Exception:
        return None
    return None

def pytest_terminal_summary(terminalreporter):
    terminalreporter.write_line('Nur Desktop (Qt/VTK), ausgelassen: ' + (', '.join(sorted(SKIPPED)) or '-'))
PY
# Einzeltests nur für Desktop-Teile: Qt-Warteschlange der Konvertierung, trimesh-Export, VTK-Renderer
DESELECT="--deselect tests/test_field_models.py::test_shared_slots_edited_texture_and_queued_path
 --deselect tests/test_replacements_v2.py::test_real_mesh_gltf_glb_roundtrip
 --deselect tests/test_replacements_v2.py::test_glb_animation_durations_preserved"
python -m pytest -q -p no:cacheprovider tests $IGNORE $DESELECT "$@"
for t in tests/*.mjs; do node "$t"; done
