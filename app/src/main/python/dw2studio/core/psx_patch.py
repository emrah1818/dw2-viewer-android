"""Conservative Mode-2 Form-1 CD-XA sector patching.

Writes only to a NEW image, only complete allocated user sectors, and
regenerates EDC plus P/Q ECC. No file relocation or filesystem editing.
"""
from pathlib import Path
import os
import shutil
from .psx_sector import RAW_SIZE, SYNC, calculate_edc, inspect_sector

USER_OFFSET = 24
USER_SIZE = 2048


def _ecc_tables():
    fwd = [0] * 256
    back = [0] * 256
    for i in range(256):
        j = (i << 1) ^ (0x11d if i & 0x80 else 0)
        fwd[i] = j
        back[i ^ j] = i
    return fwd, back

_FWD, _BACK = _ecc_tables()


def _ecc(data, major_count, minor_count, major_mult, minor_inc):
    size = major_count * minor_count
    result = bytearray(major_count * 2)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            value = data[index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= value
            b ^= value
            a = _FWD[a]
        a = _BACK[_FWD[a] ^ b]
        result[major] = a
        result[major + major_count] = a ^ b
    return bytes(result)


def regenerate_form1(raw):
    """Return a new 2352-byte Mode-2 Form-1 sector with valid EDC/ECC."""
    sector = bytearray(raw)
    report = inspect_sector(sector)
    if report.mode != 2 or report.form != 1 or not report.subheader_valid:
        raise ValueError('Nur Mode-2-Form-1-Sektoren mit gueltigem XA-Subheader werden unterstuetzt.')
    sector[2072:2076] = calculate_edc(sector[16:2072]).to_bytes(4, 'little')
    # CD-XA Form 1 ECC is computed with the four address bytes zeroed.
    ecc_data = bytearray(sector[12:2076])
    ecc_data[0:4] = b'\0' * 4
    sector[2076:2248] = _ecc(ecc_data, 86, 24, 2, 86)
    ecc_data = bytearray(sector[12:2248])
    ecc_data[0:4] = b'\0' * 4
    sector[2248:2352] = _ecc(ecc_data, 52, 43, 86, 88)
    return bytes(sector)


def validate_form1_ecc(raw):
    report = inspect_sector(raw)
    if report.mode != 2 or report.form != 1 or not report.subheader_valid:
        return False
    return regenerate_form1(raw) == raw


def patch_image_copy(source_path, destination_path, sector_number, payload, *, expected_original=None):
    """Copy and patch exactly one sector's 2048-byte payload, never source.

    expected_original may be supplied for compare-before-write safety.
    """
    source = Path(source_path).resolve()
    destination = Path(destination_path).resolve()
    if source == destination:
        raise ValueError('Originaldatei darf nicht ueberschrieben werden.')
    if len(payload) != USER_SIZE or sector_number < 0:
        raise ValueError('Genau 2048 Nutzdatenbytes und ein gueltiger Sektorindex erforderlich.')
    if source.stat().st_size % RAW_SIZE or sector_number >= source.stat().st_size // RAW_SIZE:
        raise ValueError('Ungueltiges RAW-Image oder Sektorindex.')
    with source.open('rb') as f:
        f.seek(sector_number * RAW_SIZE)
        original = f.read(RAW_SIZE)
    if not validate_form1_ecc(original):
        raise ValueError('Originalsektor ist kein gueltiger Mode-2-Form-1-Sektor mit korrekter EDC/ECC.')
    if expected_original is not None and original[USER_OFFSET:USER_OFFSET + USER_SIZE] != expected_original:
        raise ValueError('Originaldaten stimmen nicht mit der erwarteten Version ueberein.')
    if destination.exists():
        raise FileExistsError('Zieldatei existiert bereits.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.partial')
    if temporary.exists():
        raise FileExistsError('Temporaere Zieldatei existiert bereits.')
    try:
        with source.open('rb') as inp, temporary.open('xb') as out:
            shutil.copyfileobj(inp, out, 1024 * 1024)
        modified = bytearray(original)
        modified[USER_OFFSET:USER_OFFSET + USER_SIZE] = payload
        repaired = regenerate_form1(modified)
        if not validate_form1_ecc(repaired):
            raise RuntimeError('EDC/ECC-Nachpruefung fehlgeschlagen.')
        with temporary.open('r+b') as f:
            f.seek(sector_number * RAW_SIZE)
            f.write(repaired)
            f.flush()
            os.fsync(f.fileno())
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def patch_sectors_copy(source_path, destination_path, replacements, *, expected_originals=None):
    """Atomically patch multiple allocated Mode-2 Form-1 sectors in a new BIN.

    replacements maps absolute sector indices to exactly 2048 bytes. All sectors
    are checked before copying; no sector relocation or filesystem edits occur.
    """
    source = Path(source_path).resolve()
    destination = Path(destination_path).resolve()
    if source == destination:
        raise ValueError('Originaldatei darf nicht ueberschrieben werden.')
    if not replacements:
        raise ValueError('Mindestens ein Ersatzsektor ist erforderlich.')
    if destination.exists():
        raise FileExistsError('Zieldatei existiert bereits.')
    size = source.stat().st_size
    if size % RAW_SIZE:
        raise ValueError('Keine vollstaendige 2352-Byte-RAW-BIN.')
    prepared = {}
    with source.open('rb') as inp:
        for index, payload in replacements.items():
            if type(index) is not int or index < 0 or index >= size // RAW_SIZE:
                raise ValueError(f'Ungueltiger Sektorindex: {index!r}')
            if not isinstance(payload, bytes) or len(payload) != USER_SIZE:
                raise ValueError(f'Sektor {index}: genau 2048 Bytes erforderlich.')
            inp.seek(index * RAW_SIZE)
            original = inp.read(RAW_SIZE)
            if not validate_form1_ecc(original):
                raise ValueError(f'Sektor {index}: EDC/ECC ungueltig oder kein Form 1.')
            if expected_originals is not None and index in expected_originals:
                if original[USER_OFFSET:USER_OFFSET + USER_SIZE] != expected_originals[index]:
                    raise ValueError(f'Sektor {index}: Originaldaten stimmen nicht ueberein.')
            updated = bytearray(original)
            updated[USER_OFFSET:USER_OFFSET + USER_SIZE] = payload
            prepared[index] = regenerate_form1(updated)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.partial')
    if temporary.exists():
        raise FileExistsError('Temporaere Zieldatei existiert bereits.')
    try:
        with source.open('rb') as inp, temporary.open('xb') as out:
            shutil.copyfileobj(inp, out, 1024 * 1024)
        with temporary.open('r+b') as out:
            for index, sector in sorted(prepared.items()):
                out.seek(index * RAW_SIZE)
                out.write(sector)
            out.flush()
            os.fsync(out.fileno())
        with temporary.open('rb') as check:
            for index, sector in prepared.items():
                check.seek(index * RAW_SIZE)
                if check.read(RAW_SIZE) != sector:
                    raise IOError(f'Sektor {index}: Schreibverifikation fehlgeschlagen.')
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination
