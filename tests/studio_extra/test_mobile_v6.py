"""Android/Web 6.0: nur PS1-Image (dw2.pak wird abgewiesen), DW3-Konverter-Aufruf (dw3_tool.py),
DW3-Abbild öffnen und umwandeln, Bewegungsüberblendung ohne SciPy.

Läuft in der Testsammlung des Mod Studios (tools/run_studio_tests.sh) mit selbst erstellten Daten.
"""
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest
from fixtures017 import make_pak
import android_api as api


def call(method, *args):
    reply = json.loads(api.call(method, json.dumps(args)))
    assert reply['ok'], reply
    return reply.get('data')


def fail(method, *args):
    reply = json.loads(api.call(method, json.dumps(args)))
    assert not reply['ok']
    return reply['error']


def test_pak_is_refused_in_the_mobile_version(tmp_path):
    api.configure(str(tmp_path / 'store'), '')
    pak = make_pak(tmp_path)
    assert 'nur PS1-Images' in fail('open_image', str(pak))
    assert 'mod_zip_export' not in api._METHODS

def test_dw3_tool_uses_env_converter(tmp_path, monkeypatch):
    """Android: DW3_CONVERTER zeigt auf libdw3conv.so im nativeLibraryDir (hier: nativer Build)."""
    from dw2studio import dw3_tool
    exe = Path('tools/dw3_converter/dw3_converter').resolve()
    if not exe.is_file():
        pytest.skip('nativer Konverter nicht gebaut (tools/build_dw3conv.sh native)')
    lib = tmp_path / 'lib'
    lib.mkdir()
    (lib / 'libdw3conv.so').write_bytes(exe.read_bytes())
    os.chmod(lib / 'libdw3conv.so', 0o755)
    api.configure(str(tmp_path / 'store'), str(lib))
    assert os.environ['DW3_CONVERTER'] == str(lib / 'libdw3conv.so')
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fixture_dw3 import mini_model
    (tmp_path / 'mini.bin').write_bytes(mini_model())
    proc = dw3_tool.run([tmp_path / 'mini.bin', tmp_path / 'out'], timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / 'out' / 'model.glb').is_file()
    assert json.loads((tmp_path / 'out' / 'native_source.json').read_text())['format'] == 1
    monkeypatch.delenv('DW3_CONVERTER')


def test_blend_matrix_without_scipy_matches_reference():
    import numpy as np
    from dw2studio.core.dw3_native import _blend_matrix
    a = np.eye(4)
    b = np.eye(4)
    b[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]   # 90° um z
    b[:3, 3] = [10, 0, 0]
    m = _blend_matrix(a, b, .5)
    c = np.cos(np.pi / 4)
    assert np.allclose(m[:3, :3], [[c, -c, 0], [c, c, 0], [0, 0, 1]])
    assert np.allclose(m[:3, 3], [5, 0, 0])


def test_dw3_disc_open_prepare_with_converter(tmp_path):
    """DW3-Weg wie in der App: open_dw3 -> Katalog -> prepare_dw3 (Konverter) -> GLB."""
    exe = Path('tools/dw3_converter/dw3_converter').resolve()
    if not exe.is_file():
        pytest.skip('nativer Konverter nicht gebaut')
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fixture_dw3 import make_dw3_iso
    lib = tmp_path / 'lib'
    lib.mkdir()
    (lib / 'libdw3conv.so').write_bytes(exe.read_bytes())
    os.chmod(lib / 'libdw3conv.so', 0o755)
    api.configure(str(tmp_path / 'store'), str(lib))
    info = call('open_dw3', str(make_dw3_iso(tmp_path)))
    assert [m['name'] for m in info['models']] == ['M001TEST']
    model = call('prepare_dw3', 0)
    assert Path(model['path']).read_bytes()[:4] == b'glTF'
    assert model['url'].startswith('dw3/') and model['url'].endswith('/model.glb')
    out = call('export_dw3', 0)
    with zipfile.ZipFile(out['path']) as z:
        assert {'model.glb', 'native_source.json'} <= set(z.namelist())
    os.environ.pop('DW3_CONVERTER', None)
