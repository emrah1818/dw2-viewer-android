"""A game file by its number (the US file table), as an editable session entry.

dw2.pak sessions: the pack index gives every file's LBA. Disc images: SLUS_011.93's table
(dw2_file_index.US). The entry returned is the one the session already lists for that LBA,
so edits made by different editors to the same file stay one edit.
"""
import struct
from .disc import Entry
from .digimon_names import basename


def _allocations(session, entries):
    pak = getattr(session, 'pak', None)
    if pak is not None:
        return {e.id: (e.lba, e.sectors, e.format) for e in pak.entries}
    from .dw2_file_index import US
    exe = {(e.lba, e.size): e for e in entries if not e.directory and basename(e.path) == 'SLUS_011.93'}
    if len(exe) != 1:
        raise ValueError('US-Dateitabelle (SLUS_011.93) nicht gefunden.')
    data = session.current(next(iter(exe.values())))
    count, lbas, sizes = US
    if not data.startswith(b'PS-X EXE') or len(data) < sizes + count * 2:
        raise ValueError('US-Dateitabelle in SLUS_011.93 nicht erkannt.')
    return {i: (struct.unpack_from('<I', data, lbas + i * 4)[0], struct.unpack_from('<H', data, sizes + i * 2)[0], 0)
            for i in range(count)}


def file_entry(session, entries, file_id, label=None):
    """Entry for game file FILE_ID (data files only)."""
    table = _allocations(session, entries)
    if file_id not in table or not table[file_id][1]:
        raise ValueError(f'Spieldatei 0x{file_id:03X} fehlt in der Dateitabelle.')
    lba, sectors, fmt = table[file_id]
    if fmt != 0:
        raise ValueError(f'Spieldatei 0x{file_id:03X} ist Audio/Video und nicht bearbeitbar.')
    same = [e for e in entries if not e.directory and e.lba == lba]
    if same:
        return min(same, key=lambda e: (e.path.startswith('INTERNAL/'), e.path))
    entry = Entry(f'INTERNAL/{label or f"FILE_{file_id:04X}"}.BIN', lba, sectors * 2048, False)
    entries.append(entry)
    return entry
