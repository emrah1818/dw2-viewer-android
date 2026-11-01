"""Recover ISO9660 directory records hidden from the primary volume tree.
Read-only; each recovered record is validated against ISO9660 little/big endian fields.
"""
import mmap, re, struct
from pathlib import Path
from dw2studio.core.disc import Entry

PATTERN = re.compile(rb"[A-Z0-9_\-]{1,20}\.[A-Z0-9_]{1,5};1")

def recover_entries(image_path, sector_size=2352):
    image_path = Path(image_path)
    total_sectors = image_path.stat().st_size // sector_size
    results = {}
    with image_path.open('rb') as stream:
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            for match in PATTERN.finditer(mm):
                name_bytes = match.group()
                pos = match.start()
                start = pos - 33
                if start < 0 or (pos // sector_size) != (start // sector_size):
                    continue
                # Records must lie inside a CD sector's user-data area.
                within = start % sector_size
                if sector_size == 2352 and not (24 <= within and within + 33 + len(name_bytes) <= 2072):
                    continue
                record_len = mm[start]
                if record_len < 33 + len(name_bytes) or record_len > 255:
                    continue
                if mm[start+32] != len(name_bytes):
                    continue
                lba = struct.unpack_from('<I', mm, start+2)[0]
                size = struct.unpack_from('<I', mm, start+10)[0]
                if lba >= total_sectors or size > 200_000_000 or size == 0:
                    continue
                if struct.unpack_from('>I',mm,start+6)[0] != lba:
                    continue
                if struct.unpack_from('>I',mm,start+14)[0] != size:
                    continue
                if mm[start+25] & 2:
                    continue
                name = name_bytes.decode('ascii').split(';')[0]
                key = (name,lba,size)
                results[key] = Entry('RECOVERED/'+name, lba, size, False)
    return sorted(results.values(),key=lambda e:(e.path,e.lba))
