"""Read-only ISO9660 reader for 2048-byte ISO and 2352-byte Mode 1/2 raw images."""
from dataclasses import dataclass
from pathlib import Path
import re, struct, hashlib

@dataclass
class Entry:
    path: str
    lba: int
    size: int
    directory: bool

class Disc:
    def __new__(cls, path, **kwargs):
        if cls is Disc and Path(path).suffix.lower() == '.pak':
            from dw2studio.pak_workspace import PakDisc
            return PakDisc(path)
        return super().__new__(cls)

    def __init__(self, path, *, sector_size=None):
        self.source = Path(path)
        suffix = self.source.suffix.lower()
        if suffix == '.cue':
            lines = self.source.read_text(errors='replace').splitlines()
            matches = [re.search(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))\s+BINARY', s, re.I) for s in lines]
            matches = [m for m in matches if m]
            if len(matches) != 1:
                raise ValueError('Only one BINARY track is supported; multi-track CUE requires another backend')
            self.path = self.source.parent / (matches[0].group(1) or matches[0].group(2))
        elif suffix == '.ccd':
            self.path = self.source.with_suffix('.img')
        else:
            self.path = self.source
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self.f = self.path.open('rb')
        size = self.path.stat().st_size
        if sector_size is not None:
            if sector_size not in (2048,2352) or size%sector_size:raise ValueError('Invalid explicit sector size')
            self.sector_size=sector_size
        elif suffix == '.iso' and size % 2048 == 0:
            self.sector_size = 2048
        elif size % 2352 == 0:
            self.sector_size = 2352
        elif size % 2048 == 0:
            self.sector_size = 2048
        else:
            raise ValueError('Unknown sector size (expected 2048 or 2352)')
        self.sector_count = size // self.sector_size
        self.entries = []
        self.volume = ''
        self._parse()

    def close(self): self.f.close()

    def sector(self, lba):
        if lba < 0 or lba >= self.sector_count:
            raise ValueError('Sector outside image')
        self.f.seek(lba * self.sector_size)
        raw = self.f.read(self.sector_size)
        if self.sector_size == 2048:
            return raw
        mode = raw[15]
        if mode == 1: return raw[16:2064]
        if mode == 2:
            if raw[18] & 0x20:
                raise ValueError('Mode 2 Form 2 has 2324 user bytes, not ISO9660 data')
            return raw[24:2072]
        raise ValueError(f'Unsupported CD sector mode {mode} at LBA {lba}')

    def read(self, lba, size):
        if size < 0 or size > 512*1024*1024: raise ValueError('Invalid size')
        out = bytearray()
        for i in range((size+2047)//2048): out.extend(self.sector(lba+i))
        return bytes(out[:size])

    def _parse(self):
        pvd = self.sector(16)
        if pvd[1:6] != b'CD001' or pvd[0] != 1:
            raise ValueError('No ISO9660 primary volume descriptor at LBA 16')
        self.volume = pvd[40:72].decode('ascii', 'replace').strip()
        root = pvd[156:190]
        self._walk(struct.unpack_from('<I',root,2)[0],struct.unpack_from('<I',root,10)[0], '', set(), 0)

    def _walk(self, lba, size, prefix, visited, depth):
        if depth > 24 or (lba,size) in visited: return
        visited.add((lba,size))
        if size > 32*1024*1024: return
        data = self.read(lba,size)
        offset = 0
        while offset < len(data):
            length = data[offset]
            if not length:
                offset = ((offset//2048)+1)*2048; continue
            if length < 34 or offset+length > len(data): break
            rec = data[offset:offset+length]
            name_len = rec[32]
            name = rec[33:33+name_len].decode('ascii','replace')
            offset += length
            if name in ('\x00','\x01'): continue
            name = name.split(';')[0]
            loc = struct.unpack_from('<I',rec,2)[0]
            count = struct.unpack_from('<I',rec,10)[0]
            isdir = bool(rec[25]&2)
            path = prefix + name
            self.entries.append(Entry(path,loc,count,isdir))
            if isdir: self._walk(loc,count,path+'/',visited,depth+1)

    def extract(self, entry, destination):
        if entry.directory: raise ValueError('Cannot extract directory as file')
        dest = Path(destination)
        dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('wb') as out:
            for n in range((entry.size+2047)//2048):
                out.write(self.sector(entry.lba+n)[:max(0,min(2048,entry.size-n*2048))])

    def sha256(self):
        h=hashlib.sha256(); self.f.seek(0)
        for chunk in iter(lambda:self.f.read(4*1024*1024),b''):h.update(chunk)
        return h.hexdigest()


def scan_matches(path, pattern, chunk=32 << 20, margin=4096):
    """Regex über eine große Datei in Blöcken (statt mmap): liefert (Treffer, Puffer, Versatz).

    Absolute Position = Versatz + Treffer.start(). Jeder Puffer enthält davor und danach
    `margin` Bytes Kontext, damit Datensätze um einen Treffer vollständig lesbar sind.
    Läuft auch dort, wo mmap fehlt (Browser/Pyodide), und begrenzt den Speicherbedarf.
    """
    import os
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        base = 0
        while base < size:
            lo = max(0, base - margin)
            hi = min(size, base + chunk + margin)
            f.seek(lo)
            buf = f.read(hi - lo)
            first, last = base - lo, base + chunk - lo
            for m in pattern.finditer(buf):
                if m.start() < first:
                    continue
                if m.start() >= last:
                    break
                yield m, buf, lo
            base += chunk
