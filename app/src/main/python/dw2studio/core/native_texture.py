"""DW2 4-bit texture atlas / embedded CLUT editing without growing native files.

Atlas rasterizer ported from jype's MIT converter (2024), image.hpp/image.cpp,
clut_map.cpp and gltf_exporter.cpp. See third_party/dw2_model_converter/LICENSE.
Eye sources follow the 10-byte VRAM move records in the bundled decomp.
"""
from collections import Counter
from pathlib import Path
import struct
from PIL import Image
from .native_model import NativeModel

STP = 1 << 16

class _Line:
    def __init__(self,a,b,y_only=False):
        self.x,self.y=a; self.x1,self.y1=b
        self.dx=abs(self.x1-self.x); self.dy=-abs(self.y1-self.y)
        self.sx=1 if self.x<self.x1 else -1
        self.sy=1 if self.y<self.y1 else -1
        self.e=self.dx+self.dy; self.y_only=y_only
    def __bool__(self):
        return (self.x,self.y)!=(self.x1,self.y1)
    def step(self):
        while self:
            e2=self.e*2
            if e2>self.dy:
                self.e+=self.dy; self.x+=self.sx
                if not self.y_only: break
            if e2<self.dx:
                self.e+=self.dx; self.y+=self.sy
                break


def _triangle(canvas,points,value):
    a,b,c=points
    if a[1]>b[1]:a,b=b,a
    if a[1]>c[1]:a,c=c,a
    if b[1]>c[1]:b,c=c,b
    def rect(x0,y,x1):
        if not (0<=min(x0,x1)<=max(x0,x1)<256 and 0<=y<256):
            raise ValueError('UV außerhalb des unterstützten Texturatlas.')
        canvas[y][min(x0,x1):max(x0,x1)+1]=[value]*(abs(x1-x0)+1)
    l0,l1=_Line(a,b,True),_Line(a,c,True)
    while l0 and l1:
        rect(l0.x,l0.y,l1.x);l0.step();l1.step()
    l0=_Line(b,c,True)
    while l0 and l1:
        rect(l0.x,l0.y,l1.x);l0.step();l1.step()
    rect(l0.x,l0.y,l1.x)
    for start,end in ((a,b),(a,c),(b,c)):
        line=_Line(start,end)
        while line:
            rect(line.x,line.y,line.x);line.step()
        rect(line.x,line.y,line.x)


def _rgba(word,stp=False):
    r,g,b=((word>>shift & 31)*8 for shift in (0,5,10))
    alpha=(255 if word&32768 else 0) if not (r or g or b) else (127 if stp and word&32768 else 255)
    return r,g,b,alpha


def _pack(rgba,stp=False):
    r,g,b,a=rgba
    if a<64: return 0
    word=(r//8)|((g//8)<<5)|((b//8)<<10)
    if word==0 or (stp and a<192):word|=32768
    return word


class NativeTexture:
    def __init__(self,data):
        self.model=NativeModel(data);self.data=bytes(data)
        t=self.model.tim_start
        if t+0x4040>len(data) or struct.unpack_from('<II',data,t)!=(16,8):
            raise ValueError('Nicht unterstützte DW2-TIM-Struktur.')
        if struct.unpack_from('<I',data,t+8)[0]!=44 or struct.unpack_from('<I',data,t+52)[0]!=16396 or struct.unpack_from('<HH',data,t+60)!=(32,256):
            raise ValueError('DW2 erwartet 128×256, 4-Bit und eingebettete Paletten.')
        self.pixels=t+64
        self.palette=t+0x4040-2048
        self.words=list(struct.unpack_from('<1024H',data,self.palette))
        self.indices=[]
        for byte in data[self.pixels:self.palette]:
            self.indices.extend((byte&15,byte>>4))
        canvas=[[-1]*256 for _ in range(256)]
        for part in self.model.parts:
            for vs,ns,uv,clut,stp in part.primitives:
                x=(clut&63)*16; y=(clut>>6)&1023
                if x not in (0,16) or not 224<=y<255:
                    raise ValueError('Unbekannte DW2-CLUT-Zuordnung.')
                value=clut | (STP if stp else 0)
                for order in ((2,1,0),(1,2,3)) if len(vs)==4 else ((2,1,0),):
                    points=[(uv[j][0]*256//255,uv[j][1]*256//255) for j in order]
                    _triangle(canvas,points,value)
        for y in range(0,256,4):
            for x in range(0,256,4):
                counts=Counter(canvas[j][i] for i in range(x,x+4) for j in range(y,y+4) if canvas[j][i]!=-1)
                value=min(counts, key=lambda v:(-counts[v],v)) if counts else -1
                for j in range(y,y+4):canvas[j][x:x+4]=[value]*4
        self.mapping=[canvas[y][x] for y in range(224) for x in range(128)]
        try:
            self.eyes=self.model.eyes()
        except ValueError:
            self.eyes=()
        # Blink source tiles aren't necessarily referenced by polygons; inherit the
        # corresponding destination palette, not a guessed palette bank.
        for eye in self.eyes:
            dx,dy=eye.destination
            for sx,sy in eye.frames:
                for y in range(eye.height):
                    for x in range(eye.width):
                        dst=(dy+y)*128+dx+x; src=(sy+y)*128+sx+x
                        value=self.mapping[dst]
                        if self.mapping[src]==-1 and value!=-1:self.mapping[src]=value
        self._original_image=self.to_image()

    def _bank(self,value):
        return (((value>>6)&1023)-224)*32+(value&63)*16

    def to_image(self):
        colors=[]
        for i,value in enumerate(self.mapping):
            colors.append((0,0,0,0) if value==-1 else _rgba(self.words[self._bank(value)+self.indices[i]],bool(value&STP)))
        colors.extend([(0,0,0,0)]*(128*32))
        image=Image.new('RGBA',(128,256));image.putdata(colors)
        return image

    def _eye_positions(self):
        if not self.eyes:
            raise ValueError('Keine vollständig erkannten Augenrechtecke; keine automatische Ersetzung möglich.')
        positions=set()
        for eye in self.eyes:
            for x,y in (eye.destination,*eye.frames):
                positions.update((y+j)*128+x+i for j in range(eye.height) for i in range(eye.width))
        for eye in self.eyes:
            dx,dy=eye.destination
            for sx,sy in eye.frames:
                for y in range(eye.height):
                    for x in range(eye.width):
                        dst=self.mapping[(dy+y)*128+dx+x]
                        src=self.mapping[(sy+y)*128+sx+x]
                        if dst!=-1 and src!=-1 and dst!=src:
                            raise ValueError('Augenquelle und Ziel verwenden unterschiedliche Paletten. Keine eindeutige automatische Ersetzung.')
        if any(self.mapping[i]==-1 for i in positions):
            raise ValueError('Augenpalette nicht eindeutig zugeordnet. Keine ungesicherte Ersetzung.')
        return positions

    def replace(self,png,*,eyes_only=False):
        with Image.open(png) as image:
            if image.size!=(128,256):
                raise ValueError('PNG muss exakt 128×256 sein. Zuerst „PNG exportieren“ im 3D-Viewer verwenden.')
            incoming=list(image.convert('RGBA').get_flattened_data()) if hasattr(image,'get_flattened_data') else list(image.convert('RGBA').getdata())
        original=list(self._original_image.get_flattened_data()) if hasattr(self._original_image,'get_flattened_data') else list(self._original_image.getdata())
        allowed=self._eye_positions() if eyes_only else set(range(128*224))
        desired={}
        for i,value in enumerate(self.mapping):
            rgba=incoming[i] if i in allowed else original[i]
            if value==-1:
                if rgba!=original[i]:
                    raise ValueError('PNG verändert einen Bereich ohne gesicherte CLUT-Zuordnung.')
                continue
            bank=self._bank(value)
            # Preserve original STP and duplicate palette indices on unchanged pixels.
            word=self.words[bank+self.indices[i]] if rgba==original[i] else _pack(rgba,bool(value&STP))
            desired.setdefault(bank,{}).setdefault(word,[]).append(i)
        if not eyes_only and any(incoming[i]!=original[i] for i in range(128*224,128*256)):
            raise ValueError('Die unteren 32 Atlaszeilen sind für Paletten reserviert und dürfen nicht bemalt werden.')
        out=bytearray(self.data);words=self.words.copy();indices=self.indices.copy()
        for bank,colors in desired.items():
            if len(colors)>16:
                raise ValueError(f'Palette {bank//16}: {len(colors)} Farben nach 15-Bit-Umrechnung. Maximal 16 Farben pro Palette; PNG vorher reduzieren.')
            assigned={}
            used=set()
            # Reuse entries first, leaving unchanged source colors intact.
            for word in colors:
                matches=[j for j in range(16) if words[bank+j]==word]
                if matches:
                    assigned[word]=matches[0];used.add(matches[0])
            free=[j for j in range(16) if j not in used]
            for word in colors:
                if word not in assigned:
                    index=free.pop(0);words[bank+index]=word;assigned[word]=index
            for word,positions in colors.items():
                for i in positions:
                    previous=indices[i]
                    if words[bank+previous]!=word:indices[i]=assigned[word]
        if eyes_only:
            # Palette edits must not recolor any non-eye pixel, including other banks.
            for i,value in enumerate(self.mapping):
                if value!=-1 and i not in allowed:
                    b=self._bank(value)
                    if _rgba(words[b+indices[i]],bool(value&STP))!=original[i]:
                        raise ValueError('Augen teilen sich eine Palette mit dem Körper; Ersatz würde andere Bereiche ändern.')
        for i in range(0,len(indices),2):out[self.pixels+i//2]=indices[i]|indices[i+1]<<4
        struct.pack_into('<1024H',out,self.palette,*words)
        if len(out)!=len(self.data):raise RuntimeError('Unerwartete Modellgrößenänderung.')
        return bytes(out)
