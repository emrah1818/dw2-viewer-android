"""PNG resolution policy: full-size project previews, explicit native reduction."""
from PIL import Image

SCALES=(1,2,3,4)
MAX_EDGE=8192
MAX_PIXELS=16*1024*1024
FILTERS={'BOX':Image.Resampling.BOX,'NEAREST':Image.Resampling.NEAREST}


def validate_bounds(size):
    width,height=size
    if min(width,height)<1 or max(width,height)>MAX_EDGE or width*height>MAX_PIXELS:
        raise ValueError('PNG zu groß: maximal 8192 Pixel je Achse und 16 Megapixel insgesamt.')


def read_png(path):
    with Image.open(path) as image:
        if image.format!='PNG':raise ValueError('Bitte eine echte PNG-Datei auswählen.')
        validate_bounds(image.size)
        return image.convert('RGBA').copy()


def native_scale(size,target=(128,256)):
    validate_bounds(size)
    for factor in SCALES:
        if size==(target[0]*factor,target[1]*factor):return factor
    allowed=', '.join(f'{target[0]*k}×{target[1]*k}' for k in SCALES)
    raise ValueError(f'PNG-Größe {size[0]}×{size[1]} passt nicht zum Atlas. Erlaubt: {allowed} Pixel; beide Achsen müssen denselben Faktor haben.')


def reduce_for_native(image,target=(128,256),method='BOX'):
    """Caller must disclose reduction. This does NOT create native HD textures."""
    factor=native_scale(image.size,target)
    if method not in FILTERS:raise ValueError('Unbekannter Verkleinerungsfilter.')
    rgba=image.convert('RGBA')
    return rgba.copy() if factor==1 else rgba.resize(target,FILTERS[method])


def validate_preview_size(size,previous):
    validate_bounds(size)
    if size[0]*previous[1]!=size[1]*previous[0]:
        raise ValueError(f'Abmessungen haben ein anderes Seitenverhältnis. Bisher {previous[0]}×{previous[1]}, neu {size[0]}×{size[1]}. Den Atlas proportional skalieren.')


def export_template(image,path,factor=1):
    if factor not in SCALES:raise ValueError('Vorlagen-Faktor muss 1, 2, 3 oder 4 sein.')
    result=image.resize((image.width*factor,image.height*factor),Image.Resampling.NEAREST) if factor!=1 else image
    result.save(path,'PNG')
