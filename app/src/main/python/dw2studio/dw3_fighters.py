"""DW3 battle data for the motion mapping: file numbers, the fighters' file, action scripts.

Sources (dw3_decomp, MIT, https://github.com/ReGame-Labs/dw3_decomp):
- config/us/symbols.txt: FILE_SECTORS = 0x80044B78 (s32 first sector per file number),
  FILE_SECTOR_COUNTS = 0x80046DD4 (u16 sectors); the EU tables lie elsewhere.
- include/battle/battle_mode/model.h: FILE_FIGHTERS = 0x1BE (US/JP), 0x1CC (EU); FightersFile,
  FighterEntry {u16 id, u8 index, u8 kind}, FighterInfo (partner 0xC4 bytes) and
  FighterInfoEnemy (0x48 bytes); model/motions/effects = (file number << 16) | archive entry.
- battle_script.c: the game runs script N as archive entry N of FighterInfo.effects.
Nothing here is guessed: a table that does not validate is an error.
"""
from pathlib import Path
import json
import os
import struct
import subprocess
import sys

from .core.disc import Disc

VERSIONS = {
    # executable: (FILE_SECTORS, FILE_SECTOR_COUNTS, FILE_FIGHTERS)
    'SLUS_014.36': (0x80044B78, 0x80046DD4, 0x1BE),
    'SLES_039.36': (0x80044F6C, 0x800474A4, 0x1CC),
}


def _exe(disc):
    for e in disc.entries:
        name = Path(e.path).name.upper().split(';')[0]
        if name in VERSIONS:
            return name, disc.read(e.lba, e.size)
    raise ValueError('DW3-Programm (SLUS_014.36 oder SLES_039.36) nicht gefunden.')


def file_table(disc):
    """{file number: (first sector, sectors)} from the executable's own table."""
    name, exe = _exe(disc)
    if exe[:8] != b'PS-X EXE':
        raise ValueError(f'{name} ist kein PS-X EXE.')
    text = struct.unpack_from('<I', exe, 0x18)[0]
    sectors_at, counts_at, _ = VERSIONS[name]
    count = (counts_at - sectors_at) // 4
    def offset(addr):
        o = addr - text + 0x800
        if not 0x800 <= o < len(exe):
            raise ValueError('DW3-Dateitabelle liegt außerhalb des Programms.')
        return o
    starts = struct.unpack_from(f'<{count}i', exe, offset(sectors_at))
    lengths = struct.unpack_from(f'<{count}H', exe, offset(counts_at))
    table = {fid: (lba, n) for fid, (lba, n) in enumerate(zip(starts, lengths)) if lba > 0 and n > 0}
    if len(table) < 100 or any(lba + n > disc.sector_count for lba, n in table.values()):
        raise ValueError('DW3-Dateitabelle passt nicht zum Abbild.')
    return name, table


def fighters(disc):
    """Every fighter of the fighters' file: id, kind, enemy, model/motions/effects (fid, entry)."""
    name, table = file_table(disc)
    fid = VERSIONS[name][2]
    lba, sectors = table[fid]
    data = disc.read(lba, sectors * 2048)
    base, entries, partners, enemies = struct.unpack_from('<4I', data, 0)
    out = []
    at = entries
    while at + 4 <= len(data):
        ident, index, kind = struct.unpack_from('<HBB', data, at)
        if ident == 0:
            break
        enemy = kind >= 0x3A
        info = enemies + index * 0x48 if enemy else partners + index * 0xC4
        if info + 12 > len(data):
            raise ValueError('DW3-Kämpfertabelle ist abgeschnitten.')
        model, motions, effects, face_ptr = struct.unpack_from('<4I', data, info)
        out.append({'id': ident, 'kind': kind, 'enemy': enemy,
                    'model': (model >> 16, model & 0xFFFF), 'motions': (motions >> 16, motions & 0xFFFF),
                    'effects': (effects >> 16, effects & 0xFFFF), 'face': _face(data, face_ptr - base)})
        at += 4
    if not out:
        raise ValueError('DW3-Kämpfertabelle ist leer.')
    return table, out


def _face(data, at):
    """FighterInfo.face: up to 16 FaceRects of 10 bytes (x, y, w, h in VRAM halfwords relative to the
    model's texture origin; three source frames open / half / closed), ended by an x of 0xFF.
    Rect 0 and 1 are the eyes (getEyesFrame), the others cycle (FIGHTSTG_updateFace)."""
    rects = []
    for i in range(16):
        p = at + i * 10
        if not 0 <= p <= len(data) - 10 or data[p] == 0xFF:
            break
        x, y, w, h, *uv = data[p:p + 10]
        rects.append({'x': x, 'y': y, 'w': w, 'h': h, 'frames': [(uv[0], uv[1]), (uv[2], uv[3]), (uv[4], uv[5])]})
    return rects


def face_for(disc_path, entry):
    """Face rectangles of the fighter that uses the model file at ENTRY, or None."""
    disc = Disc(disc_path)
    try:
        table, rows = fighters(disc)
    finally:
        disc.close()
    fids = [fid for fid, (lba, _) in table.items() if lba == entry.lba]
    if len(fids) != 1:
        return None
    faces = [r['face'] for r in rows if r['model'][0] == fids[0] and r['face']]
    return faces[0] if faces else None


def _converter():
    from dw2studio import dw3_tool
    return dw3_tool.converter()


def script_motions(disc_path, entry, work):
    """Action scripts of the model file at ENTRY (a Disc entry) and the motions each plays.

    Returns {'fighter': {...}, 'scripts': [{'index', 'motions', 'moves', 'hits'}]} or None
    when no fighter of the battle uses this file with its own scripts."""
    disc = Disc(disc_path)
    try:
        table, rows = fighters(disc)
        fids = [fid for fid, (lba, _) in table.items() if lba == entry.lba]
        if len(fids) != 1:
            return None
        fid = fids[0]
        own = [r for r in rows if r['model'][0] == fid and r['effects'][0] == fid]
        if not own:
            return None
        effects = {r['effects'][1] for r in own}
        if len(effects) != 1:
            raise ValueError('Mehrere Skriptarchive für dieselbe DW3-Modelldatei.')
        work = Path(work)
        work.mkdir(parents=True, exist_ok=True)
        source = work / f'fid_{fid:04d}.bin'
        if not source.is_file():
            source.write_bytes(disc.read(entry.lba, entry.size))
    finally:
        disc.close()
    from dw2studio import dw3_tool
    proc = dw3_tool.run(['--scripts', source, effects.pop()], timeout=60)
    if proc.returncode != 0:
        raise ValueError('DW3-Skripte nicht lesbar: ' + (proc.stderr.strip()[:300] or str(proc.returncode)))
    doc = json.loads(proc.stdout)
    return {'fighter': {'fid': fid, 'ids': [r['id'] for r in own], 'enemy': all(r['enemy'] for r in own)},
            'scripts': doc['scripts']}
