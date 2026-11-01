"""Read-only PlayStation CD-ROM XA Mode-2 sector validation.

EDC algorithm from the publicly documented CD-ROM polynomial 0xD8018001.
This module does not change image data or claim to repair EDC/ECC.
"""
from dataclasses import dataclass
from pathlib import Path

RAW_SIZE = 2352
SYNC = bytes([0]) + bytes([0xFF]) * 10 + bytes([0])


def _table():
    result = []
    for i in range(256):
        value = i
        for _ in range(8):
            value = (value >> 1) ^ (0xD8018001 if value & 1 else 0)
        result.append(value)
    return tuple(result)

_EDC_TABLE = _table()


def calculate_edc(data):
    """Calculate CD-ROM EDC (not Ethernet CRC-32)."""
    edc = 0
    for byte in data:
        edc = (edc >> 8) ^ _EDC_TABLE[(edc ^ byte) & 0xFF]
    return edc


@dataclass(frozen=True)
class SectorReport:
    sector_number: int
    mode: int
    form: int | None
    subheader_valid: bool | None
    edc_valid: bool | None
    stored_edc: int | None
    computed_edc: int | None


def inspect_sector(raw, sector_number=0):
    if len(raw) != RAW_SIZE:
        raise ValueError('Ein RAW-Sektor muss genau 2352 Bytes enthalten.')
    if raw[:12] != SYNC:
        raise ValueError(f'Sektor {sector_number}: ungueltiges CD-Sync-Muster.')
    mode = raw[15]
    if mode != 2:
        return SectorReport(sector_number, mode, None, None, None, None, None)
    subheader_valid = raw[16:20] == raw[20:24]
    form = 2 if raw[18] & 0x20 else 1
    if form == 1:
        data_end, edc_start = 2072, 2072
    else:
        data_end, edc_start = 2348, 2348
    computed = calculate_edc(raw[16:data_end])
    stored = int.from_bytes(raw[edc_start:edc_start + 4], 'little')
    return SectorReport(sector_number, mode, form, subheader_valid, stored == computed, stored, computed)


def inspect_image(image_path, *, start_sector=0, count=100):
    """Inspect a bounded slice of a RAW BIN; never write to it."""
    image = Path(image_path)
    size = image.stat().st_size
    if size % RAW_SIZE:
        raise ValueError('Keine vollstaendige 2352-Byte-RAW-BIN.')
    total = size // RAW_SIZE
    if start_sector < 0 or count < 0 or start_sector > total or count > total - start_sector:
        raise ValueError('Sektorbereich liegt ausserhalb des Images.')
    reports = []
    with image.open('rb') as source:
        source.seek(start_sector * RAW_SIZE)
        for index in range(start_sector, start_sector + count):
            reports.append(inspect_sector(source.read(RAW_SIZE), index))
    return reports
