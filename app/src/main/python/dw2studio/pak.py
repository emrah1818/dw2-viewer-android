"""Read-only reader for the DW2 PC-port PAK v1 container.

Only index and payload bytes are read. This module never writes to the PAK.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import struct

MAGIC = b'DW2PAK\x1a\x00'
HEADER_SIZE = 80
ENTRY_SIZE = 64

@dataclass(frozen=True)
class PakEntry:
    id: int
    lba: int
    sectors: int
    format: int
    offset: int
    size: int
    sha256: bytes

class PakFile:
    def __init__(self, path):
        self.path = Path(path)
        self.entries = []
        with self.path.open('rb') as stream:
            header = stream.read(HEADER_SIZE)
            if len(header) != HEADER_SIZE or header[:8] != MAGIC:
                raise ValueError('Not a DW2 PC-port PAK v1')
            version, header_size, count, index_offset, entry_size, _flags = struct.unpack_from('<6I', header, 8)
            if version != 1 or header_size != HEADER_SIZE or entry_size != ENTRY_SIZE:
                raise ValueError('Unsupported PAK layout')
            length = self.path.stat().st_size
            if count > 100000 or index_offset < HEADER_SIZE or index_offset + count * ENTRY_SIZE > length:
                raise ValueError('Invalid or truncated PAK index')
            stream.seek(index_offset)
            for _ in range(count):
                raw = stream.read(ENTRY_SIZE)
                file_id, lba, sectors, fmt = struct.unpack_from('<4I', raw)
                offset, size = struct.unpack_from('<2Q', raw, 16)
                if size == 0 or offset > length or size > length - offset:
                    raise ValueError(f'PAK entry {file_id} exceeds file bounds')
                self.entries.append(PakEntry(file_id, lba, sectors, fmt, offset, size, raw[32:64]))
        self.by_id = {entry.id: entry for entry in self.entries}
        if len(self.by_id) != len(self.entries):
            raise ValueError('Duplicate PAK IDs')

    def read(self, file_id, verify=True):
        entry = self.by_id[file_id]
        with self.path.open('rb') as stream:
            stream.seek(entry.offset)
            payload = stream.read(entry.size)
        if verify and hashlib.sha256(payload).digest() != entry.sha256:
            raise ValueError(f'PAK entry {file_id} failed SHA-256 verification')
        return payload

    def extract(self, file_id, destination, verify=True):
        destination = Path(destination)
        if destination.exists():
            raise FileExistsError(destination)
        payload = self.read(file_id, verify=verify)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(payload)
        return destination

    def summary(self):
        return {'path': str(self.path), 'count': len(self.entries),
                'size': self.path.stat().st_size}
