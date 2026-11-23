"""Create-only export for the existing PC-port TexRep texture-pack protocol."""
from pathlib import Path
import re
from .core.dw3_native import hd_name
from .core.png_source import verified_png


def export(native, png, port_dir, pack_name='DW2Studio_HD'):
    payload,info=verified_png(png)
    w,h=info['size']
    if w%128 or h%256 or w//128!=h//256 or not 1<=w//128<=16:
        raise ValueError('HD-PNG benötigt 128×256 mal einen ganzzahligen Faktor 1–16, z. B. 512×1024.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}',pack_name):
        raise ValueError('Packname: Buchstaben, Zahlen, Unterstrich oder Bindestrich.')
    target=Path(port_dir)/'Mods'/'Textures'/pack_name/hd_name(native)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as out:out.write(payload)
    return {'path':str(target),'size':[w,h],'scale':w//128}
