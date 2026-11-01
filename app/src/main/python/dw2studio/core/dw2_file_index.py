"""Read DW2's private LBA/size table, ported from acemon33 DW2-TT DW2Slus.cs.

Supports US SLUS_011.93 and JAP table layouts. The index is read from the
actual game executable, whose data spans raw Mode-2 Form-1 sectors. This module
never guesses the file lengths: index entries contain allocated 2048-byte
sector counts, which may include trailing padding.
"""
from dataclasses import dataclass
from pathlib import Path
from .psx_sector import RAW_SIZE, inspect_sector

SLUS_LBA = 0xDC80
SLUS_SECTORS = 318
SLUS_USER_SIZE = 2048
US = (3675, 0x33F94, 0x37900)
JAP = (3655, 0x316A8, 0x34FC4)
KNOWN_NAMES = {
    3358:'STAG1100.PRO', 402:'STAG2000.PRO',
    403:'STAG3000.PRO', 3405:'STAG3500.PRO', 410:'STAG4000.PRO',
    603:'WAZADATA.BIN', 3180:'DIGIMNDT.BIN',3183:'ENEMYSET.BIN',
    3257:'MODELDT0.BIN',3369:'STMAPDAT.BIN',3616:'DATA4000.BIN',
    315:'PGFTWN00.BIN',417:'FIGHT000.BIN',
}

@dataclass(frozen=True)
class IndexedFile:
    index: int
    lba: int
    sectors: int
    name: str

    @property
    def capacity(self):
        return self.sectors * SLUS_USER_SIZE


def _read_lbas(image, lba, count):
    with Path(image).open('rb') as stream:
        stream.seek(lba * RAW_SIZE)
        for i in range(count):
            raw = stream.read(RAW_SIZE)
            report = inspect_sector(raw, lba+i)
            if report.mode != 2 or report.form != 1 or not report.subheader_valid or not report.edc_valid:
                raise ValueError(f'Sektor {lba+i} hat kein gültiges Mode-2-Form-1-Datenformat.')
            yield raw[24:2072]


def read_index(image, version='US'):
    image = Path(image)
    image_size = image.stat().st_size
    if image_size % RAW_SIZE:
        raise ValueError('DW2-TT benötigt ein vollständiges RAW-BIN mit 2352-Byte-Sektoren.')
    version = version.upper()
    if version not in ('US','JAP'):
        raise ValueError('Nur die dokumentierten DW2-US-/JAP-Indextabellen werden unterstützt.')
    count, lba_off, size_off = US if version == 'US' else JAP
    # DW2-TT starts at raw byte 0xDC80 (a user-data offset), not an LBA.
    start_lba, initial = divmod(SLUS_LBA, RAW_SIZE)
    if initial != 0:
        raise RuntimeError('Unerwartetes SLUS-Alignment.')
    data = b''.join(_read_lbas(image, start_lba, SLUS_SECTORS))
    if size_off + count * 2 > len(data) or lba_off + count * 4 > len(data):
        raise ValueError('SLUS-Datentabelle ist unvollständig.')
    total_sectors = image_size // RAW_SIZE
    files=[]
    for i in range(count):
        lba = int.from_bytes(data[lba_off+4*i:lba_off+4*i+4], 'little')
        sectors = int.from_bytes(data[size_off+2*i:size_off+2*i+2], 'little')
        if sectors and (lba >= total_sectors or sectors > total_sectors - lba):
            raise ValueError(f'Index {i}: Dateibereich außerhalb des Images (LBA {lba}, {sectors} Sektoren).')
        files.append(IndexedFile(i, lba, sectors, KNOWN_NAMES.get(i, f'INDEX_{i:04d}.BIN')))
    return files


def extract_indexed_file(image, entry, output):
    """Export an indexed file, including allocated end padding, to new path."""
    image = Path(image).resolve()
    output = Path(output).resolve()
    if image == output or output.exists() or entry.sectors <= 0:
        raise ValueError('Ziel existiert bereits, ist das Original oder Dateieintrag ist leer.')
    if image.stat().st_size % RAW_SIZE:
        raise ValueError('Kein RAW-BIN-Image.')
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + '.partial')
    if partial.exists():
        raise FileExistsError(partial)
    try:
        with partial.open('xb') as dst:
            for payload in _read_lbas(image, entry.lba, entry.sectors):
                dst.write(payload)
        partial.rename(output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return output


def replace_indexed_file_copy(image, entry, replacement, output, *, pad=False):
    """Patch an indexed allocation into a *new* image; never relocate the file.

    DW2-TT's ability to append files and modify the executable's tables is NOT
    part of this operation. Unless pad=True, the new file must occupy exactly
    the original allocated number of sectors.
    """
    from .psx_patch import patch_sectors_copy
    data=Path(replacement).read_bytes()
    if not data:
        raise ValueError('Ersatzdatei ist leer.')
    if entry.sectors <= 0:
        raise ValueError('Indexeintrag ist leer.')
    if pad:
        if len(data) > entry.capacity:
            raise ValueError('Ersatzdatei ist größer als reservierter Bereich.')
        data=data.ljust(entry.capacity,b'\x00')
    elif len(data) != entry.capacity:
        raise ValueError(f'Ersatz benötigt genau {entry.capacity} Bytes (oder bewusstes Padding).')
    sectors={entry.lba+i:data[2048*i:2048*(i+1)] for i in range(entry.sectors)}
    return patch_sectors_copy(image,output,sectors)


def relocate_indexed_file_copy(image, entry, replacement, output, *, version='US'):
    """DW2-TT style append-and-reindex to a new RAW image.

    The private SLUS index is rewritten to point at newly appended Mode-2 Form-1
    sectors. Existing sectors stay untouched. This mirrors DW2Image.WriteFile
    for over-capacity replacements. No ISO9660 directory or file size update is
    implied; only DW2's own internal index is supported. Experimental: emulator
    validation is essential, particularly for entries with additional pointers.
    """
    import shutil, os
    from .psx_patch import regenerate_form1, validate_form1_ecc
    from .psx_sector import SYNC
    image=Path(image).resolve();output=Path(output).resolve()
    source=Path(replacement).resolve()
    if output.exists():
        raise FileExistsError(output)
    if image==output or image==source or output==source:
        raise ValueError('Quell- und Ziel-Dateien dürfen nicht identisch sein.')
    if entry.index == 0x18:
        raise ValueError('SLUS-Sondereintrag kann nicht durch allgemeine Relokation ersetzt werden.')
    if image.stat().st_size%RAW_SIZE:
        raise ValueError('Kein vollständiges RAW-BIN.')
    refs=read_index(image,version=version)
    if not 0 <= entry.index < len(refs) or entry!=refs[entry.index]:
        raise ValueError('Indexeintrag passt nicht zur gewählten BIN.')
    size=source.stat().st_size
    if not size:
        raise ValueError('Leere Ersatzdatei.')
    new_count=(size+2047)//2048
    if new_count>65535:
        raise ValueError('Datei überschreitet das 16-Bit-Sektorlimit.')
    new_lba=image.stat().st_size//RAW_SIZE
    if new_lba+new_count>=450000:
        raise ValueError('Neue CD-Länge übersteigt den konservativen 100-Minuten-Rahmen.')
    # Verify that the final written structure is based on valid source sectors.
    template_lba=entry.lba if entry.sectors else SLUS_LBA//RAW_SIZE
    with image.open('rb') as inp:
        inp.seek(template_lba*RAW_SIZE)
        template=inp.read(RAW_SIZE)
    if not validate_form1_ecc(template):
        raise ValueError('Kein gültiger Mode-2-Form-1-Referenzsektor.')
    count,lba_off,size_off=US if version.upper()=='US' else JAP
    changes={lba_off+4*entry.index:new_lba.to_bytes(4,'little'),
             size_off+2*entry.index:new_count.to_bytes(2,'little')}
    # Prepare SLUS sector modifications before touching a destination.
    slus_sectors={}
    with image.open('rb') as inp:
        for offset, raw in changes.items():
            for j,val in enumerate(raw):
                logical=offset+j
                sector=SLUS_LBA//RAW_SIZE+logical//2048
                if sector not in slus_sectors:
                    inp.seek(sector*RAW_SIZE)
                    existing=inp.read(RAW_SIZE)
                    if not validate_form1_ecc(existing):
                        raise ValueError('SLUS-Tabellensektor hat ungültige EDC/ECC.')
                    slus_sectors[sector]=bytearray(existing)
                slus_sectors[sector][24+logical%2048]=val
    repaired={sector:regenerate_form1(data) for sector,data in slus_sectors.items()}
    output.parent.mkdir(parents=True,exist_ok=True)
    part=output.with_name(output.name+'.partial')
    if part.exists():
        raise FileExistsError(part)
    try:
        with image.open('rb') as inp,part.open('xb') as dst:
            shutil.copyfileobj(inp,dst,4*1024*1024)
            with source.open('rb') as content:
                for i in range(new_count):
                    lba=new_lba+i
                    minutes,rem=divmod(lba+150,75*60)
                    seconds,frames=divmod(rem,75)
                    def bcd(x):return ((x//10)<<4)|(x%10)
                    raw=bytearray(template)
                    raw[12:16]=bytes([bcd(minutes),bcd(seconds),bcd(frames),2])
                    data=content.read(2048)
                    raw[24:2072]=data.ljust(2048,b'\0')
                    updated=regenerate_form1(raw)
                    if not validate_form1_ecc(updated):
                        raise RuntimeError('Neu erzeugter Sektor ist ungültig.')
                    dst.write(updated)
            for lba,raw in repaired.items():
                dst.seek(lba*RAW_SIZE)
                dst.write(raw)
            dst.flush();os.fsync(dst.fileno())
        refs_new=read_index(part,version)
        mapped=refs_new[entry.index]
        if mapped.lba!=new_lba or mapped.sectors!=new_count:
            raise RuntimeError('DW2-Dateitabelle wurde nach dem Schreiben nicht korrekt eingelesen.')
        with part.open('rb') as check:
            for lba,expected in repaired.items():
                check.seek(lba*RAW_SIZE)
                if check.read(RAW_SIZE)!=expected:
                    raise IOError('SLUS-Schreibverifikation fehlgeschlagen.')
            for i in range(new_count):
                check.seek((new_lba+i)*RAW_SIZE)
                if not validate_form1_ecc(check.read(RAW_SIZE)):
                    raise IOError('Angehängter Sektor hat ungültige EDC/ECC.')
        part.rename(output)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return output,new_lba,new_count
