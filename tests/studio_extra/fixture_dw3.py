"""Selbst erstelltes Mini-Modell im Archivformat, das third_party/dw3_converter liest.

Nur für Tests des Konverter-Aufrufs (Android-Binärdatei, WebAssembly): ein Knochen, ein Dreieck,
keine Textur, keine Motion. Kein Spielinhalt.
"""
import struct


def archive(entries):
    head = 4 * len(entries)
    out, offsets = bytearray(), []
    for e in entries:
        offsets.append(head + len(out))
        out += e
        out += bytes((-len(out)) % 4)
    return struct.pack(f'<{len(entries)}I', *offsets) + bytes(out)


def mini_model():
    verts = struct.pack('<3h', 3, 0, 0) + struct.pack('<9h', 0, 0, 0, 100, 0, 0, 0, -100, 0)
    normals = struct.pack('<3h', 0, 0, 0)
    commands = bytes([0x80, 0x00, 0, 1, 2, 0xFF])
    mesh = archive([verts, normals, commands, b'\0' * 4, b'\0' * 4, b'\0' * 4])        # erster Offset 0x18
    key = struct.pack('<4h', 0, 0, 0, 30000)
    keys = archive([key, key, struct.pack('<4h', 4096, 4096, 4096, 30000), b'\0' * 8])  # erster Offset 0x10
    bones = struct.pack('<5I', 0, 1, 0, 1, 2)
    return archive([bones, mesh, keys])


def _dir_record(name, lba, size, directory=False):
    ident = name.encode()
    length = 33 + len(ident)
    rec = bytearray(length + (length % 2))
    rec[0] = len(rec)
    struct.pack_into('<I', rec, 2, lba); struct.pack_into('>I', rec, 6, lba)
    struct.pack_into('<I', rec, 10, size); struct.pack_into('>I', rec, 14, size)
    rec[25] = 2 if directory else 0
    rec[32] = len(ident)
    rec[33:33 + len(ident)] = ident
    return bytes(rec)


def make_dw3_iso(folder):
    """Kleines ISO9660-Abbild in der Form einer DW3-Disc: SLUS_014.36 (leer) und ein Modell
    M001TEST.BIN (mini_model). Kein Spielinhalt."""
    from pathlib import Path
    files = {'SLUS_014.36': b'PS-X EXE'.ljust(2048, b'\0'), 'M001TEST.BIN': mini_model()}
    sectors = [bytearray(2048) for _ in range(40)]
    root = _dir_record('\x00', 18, 2048, True) + _dir_record('\x01', 18, 2048, True)
    lba = 20
    for name, data in files.items():
        root += _dir_record(name + ';1', lba, len(data))
        for i in range((len(data) + 2047) // 2048):
            chunk = data[i * 2048:(i + 1) * 2048]
            sectors[lba + i][:len(chunk)] = chunk
        lba += (len(data) + 2047) // 2048
    sectors[18][:len(root)] = root
    pvd = sectors[16]
    pvd[0] = 1; pvd[1:6] = b'CD001'; pvd[40:72] = b'DW3TEST'.ljust(32)
    pvd[156:190] = _dir_record('\x00', 18, 2048, True)[:34].ljust(34, b'\0')
    path = Path(folder) / 'dw3_test.iso'
    path.write_bytes(b''.join(bytes(s) for s in sectors))
    return path


if __name__ == '__main__':
    import sys
    open(sys.argv[1], 'wb').write(mini_model())
