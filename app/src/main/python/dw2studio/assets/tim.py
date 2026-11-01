"""PS1 TIM 4/8/16/24 bpp decoder; fixed-layout TIM re-encoder for 4/8/16 bpp."""
import io,struct
from PIL import Image

def color(v):
    a=0 if (v & 0x7fff)==0 else 255
    return ((v&31)*255//31,((v>>5)&31)*255//31,((v>>10)&31)*255//31,a)

def pack_color(c):
    r,g,b,a=c
    if a<128:return 0
    return (r*31//255)|((g*31//255)<<5)|((b*31//255)<<10)

class TIM:
    def __init__(self,data):
        self.data=bytes(data)
        if len(data)<20 or data[:4]!=b'\x10\x00\x00\x00':raise ValueError('Not a TIM file')
        self.flags=struct.unpack_from('<I',data,4)[0]
        self.bpp=self.flags&7
        if self.bpp not in (0,1,2,3):raise ValueError('Unsupported TIM bpp')
        self.has_clut=bool(self.flags&8)
        pos=8;self.palette=[]
        if self.has_clut:
            n=struct.unpack_from('<I',data,pos)[0]
            if n<12 or pos+n>len(data):raise ValueError('Invalid CLUT block')
            _,_,self.cw,self.ch=struct.unpack_from('<4H',data,pos+4)
            self.palette=[color(v[0]) for v in struct.iter_unpack('<H',data[pos+12:pos+n])]
            pos+=n
        self.image_offset=pos
        n=struct.unpack_from('<I',data,pos)[0]
        if n<12 or pos+n>len(data):raise ValueError('Invalid TIM image block')
        _,_,self.words,self.height=struct.unpack_from('<4H',data,pos+4)
        self.pixel_offset=pos+12
        self.end=pos+n
        self.width=self.words*({0:4,1:2,2:1,3:2/3}[self.bpp])
        self.width=int(self.width)

    @property
    def palette_banks(self):
        if self.bpp not in (0,1) or not self.has_clut:return []
        stride=16 if self.bpp==0 else 256
        return [self.palette[i:i+stride] for i in range(0,len(self.palette),stride) if len(self.palette[i:i+stride])==stride]

    def to_image(self, palette_override=None):
        raw=self.data[self.pixel_offset:self.end]
        pal = palette_override if palette_override is not None else (self.palette_banks[0] if self.palette_banks else self.palette)
        if self.bpp==2:
            pixels=[color(v[0]) for v in struct.iter_unpack('<H',raw)]
        elif self.bpp==0:
            pixels=[pal[(v>>shift)&15] for v in raw for shift in (0,4)]
        elif self.bpp==1:
            pixels=[pal[v] for v in raw]
        else:
            pixels=[(*raw[i:i+3],255) for i in range(0,len(raw)-2,3)]
        expected=self.width*self.height
        if len(pixels)<expected:raise ValueError('Incomplete pixel data')
        im=Image.new('RGBA',(self.width,self.height));im.putdata(pixels[:expected]);return im

    def replace_image(self,image):
        im=image.convert('RGBA')
        if im.size!=(self.width,self.height):raise ValueError(f'Image must be {self.width}x{self.height}')
        if self.bpp==3:raise ValueError('24-bit TIM writing not implemented')
        out=bytearray(self.data[:self.end])
        if self.bpp==2:
            pixels=b''.join(struct.pack('<H',pack_color(c)) for c in im.getdata())
        else:
            if not self.has_clut:raise ValueError('Indexed TIM has no CLUT')
            limit=16 if self.bpp==0 else 256
            pal=self.palette[:limit]
            # Quantize to the ORIGINAL palette; preserve CLUT layout and game palette references.
            def nearest(c):
                if c[3]<128:
                    zeros=[i for i,p in enumerate(pal) if p[3]==0]
                    if zeros:return zeros[0]
                return min(range(len(pal)),key=lambda i:sum((pal[i][j]-c[j])**2 for j in range(4)))
            idx=[nearest(c) for c in im.getdata()]
            pixels=bytes(idx) if self.bpp==1 else bytes(idx[i]|(idx[i+1]<<4) for i in range(0,len(idx),2))
        end=self.pixel_offset+len(pixels)
        if end!=self.end:raise ValueError('TIM size mismatch')
        out[self.pixel_offset:end]=pixels
        return bytes(out)

def find_tim(data,limit=1000):
    offsets=[]; start=0
    while len(offsets)<limit:
        i=data.find(b'\x10\x00\x00\x00',start)
        if i<0:break
        try:
            tim=TIM(data[i:]);tim.to_image()
            offsets.append((i,tim.width,tim.height,tim.bpp,tim.end))
        except (ValueError,IndexError,struct.error):pass
        start=i+4
    return offsets


def infer_palette_from_reference(tim, reference):
    """Infer indexed CLUT colors from a pixel-aligned reference atlas.

    Reference must contain the exact same pixel layout and dimensions; otherwise
    this procedure cannot establish a valid color mapping.
    """
    from collections import Counter
    im=reference.convert('RGBA')
    if im.size != (tim.width,tim.height):
        raise ValueError(f'Referenz muss exakt {tim.width}x{tim.height} Pixel haben')
    if tim.bpp not in (0,1) or not tim.has_clut:
        raise ValueError('Nur 4/8-bit TIM mit eingebetteter CLUT unterstützt')
    raw=tim.data[tim.pixel_offset:tim.end]
    indices=[(v>>shift)&15 for v in raw for shift in (0,4)] if tim.bpp==0 else list(raw)
    counts=[Counter() for _ in range(16 if tim.bpp==0 else 256)]
    for index,rgba in zip(indices,im.getdata()):
        counts[index][rgba]+=1
    palette=list(tim.palette)
    for i,c in enumerate(counts):
        if c:palette[i]=c.most_common(1)[0][0]
    return palette

def apply_palette_to_tim(tim,palette):
    """Replace CLUT entries in original TIM without changing its byte length."""
    if not tim.has_clut or tim.bpp not in (0,1):
        raise ValueError('Keine editierbare indizierte TIM-Palette')
    required=16 if tim.bpp==0 else 256
    if len(palette)<required:raise ValueError('Palette ist zu kurz')
    output=bytearray(tim.data[:tim.end])
    for i in range(required):
        struct.pack_into('<H',output,20+i*2,pack_color(palette[i]))
    return bytes(output)
