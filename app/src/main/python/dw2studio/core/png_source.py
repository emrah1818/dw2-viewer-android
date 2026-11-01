"""Keep an imported PNG byte-for-byte, including bit depth, alpha and profiles."""
from io import BytesIO
from pathlib import Path
from PIL import Image

SIGNATURE=b'\x89PNG\r\n\x1a\n'


def verified_png(path):
    payload=Path(path).read_bytes()
    if not payload.startswith(SIGNATURE):raise ValueError('Bitte eine echte PNG-Datei auswählen.')
    with Image.open(BytesIO(payload)) as image:
        if image.format!='PNG':raise ValueError('Keine gültige PNG-Datei.')
        size=image.size;mode=image.mode;profile=bool(image.info.get('icc_profile'));image.verify()
    return payload,{'size':size,'mode':mode,'icc_profile':profile}


def write_bytes_atomic(target,payload):
    target=Path(target);pending=target.with_name(target.name+'.pending')
    try:pending.write_bytes(payload);pending.replace(target)
    finally:pending.unlink(missing_ok=True)
    return target
