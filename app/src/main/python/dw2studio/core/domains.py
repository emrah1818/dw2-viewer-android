"""Domains, their floors and enemy groups (US).

Formats from dw2-pc-port (read only, nothing of it is changed):
- Domain table: archive entry 0xA of file 0xE20, rows of 0x14 bytes (Stg40DungEntry,
  include/main/156C.h; Stg40_InitDungeonEntry, src/stag4000/stag4000.c), the first s16 the
  domain's dungeon file. The list ends at a row whose file is 0.
- Dungeon file: u32 offsets of its floors up to a 0 (Stg40_LoadDungFile/Stg40_RelocDungFile,
  src/stag4000/dungfile.c). A floor (Stg40DungFloor, include/stag4000/stag4000.h): name offset
  at +0 (bytes up to FF), enemySets[5] (u8 set ids) at +0x2F. Stg40_SpawnEnemyParties
  (src/stag4000/spawn.c) reads enemySets[k] for a layout's pick k when k != 0.
- ENEMYSET.BIN (file 0xC6F): 100-byte groups up to an id of 0 (Enemy_FindSetById,
  src/main/gamedata.c). Header: id u8 +0, AI type bits 8-11 and pace bits 12-15 of word +0,
  map Digimon s16 +2, liked gift u8 +4, dungeon BGM bits 8-11 and boss bits 12-15 of word +4,
  points per level s16 +6 (Enemy_GetSetSummary). Three members of 30 bytes from +8
  (DigiInitRow): Digimon u16 +0, HP u16 +2, MP u16 +4, level u8 +10, attack u8 +11,
  defense u16 +12, speed u8 +14, techniques u8 +15..+17, four AI rules +18..+29.
"""
import struct
from .digimon_names import DECODE
from .game_files import file_entry

DOMAIN_FILE, DOMAIN_ENTRY, ROW = 0xE20, 0xA, 0x14
ENEMYSET = 0xC6F
GROUP = 100
MEMBER_FIELDS = {  # name: (offset in the 30-byte member, struct format, min, max)
    'digimon': (0, '<H', 0, 0x7FFF), 'hp': (2, '<H', 0, 9999), 'mp': (4, '<H', 0, 9999),
    'level': (10, '<B', 0, 99), 'attack': (11, '<B', 0, 255), 'defense': (12, '<H', 0, 999),
    'speed': (14, '<B', 0, 255)}
HEADER_FIELDS = ('map_digimon', 'ai', 'pace', 'liked_gift', 'dungeon_bgm', 'boss', 'points_per_level')


def _text(data, at):
    end = data.find(b'\xff', at)
    if end < 0 or end - at > 64:
        raise ValueError('Etagenname ohne FF-Abschluss.')
    return ''.join(DECODE.get(b, '?') for b in data[at:end])


class DomainTable:
    def __init__(self, archive):
        if len(archive) < 4 * (DOMAIN_ENTRY + 1):
            raise ValueError('Domain-Tabelle (0xE20) zu kurz.')
        count = struct.unpack_from('<I', archive, 0)[0] // 4
        if count <= DOMAIN_ENTRY:
            raise ValueError('Domain-Tabelle: Eintrag 0xA fehlt.')
        start = struct.unpack_from('<I', archive, 4 * DOMAIN_ENTRY)[0]
        if not 4 * count <= start <= len(archive) - ROW:
            raise ValueError('Domain-Tabelle: Eintrag 0xA außerhalb der Datei.')
        self.rows = []
        at = start
        while at + ROW <= len(archive):
            file_id = struct.unpack_from('<h', archive, at)[0]
            if file_id == 0:
                break
            if file_id < 0:
                raise ValueError('Domain-Tabelle: ungültige Dateinummer.')
            self.rows.append(file_id)
            at += ROW
        if not self.rows:
            raise ValueError('Domain-Tabelle ist leer.')


class DungeonFile:
    def __init__(self, data):
        self.data = bytes(data)
        self.floors = []
        k = 0
        while True:
            if 4 * k + 4 > len(data):
                raise ValueError('Domain-Datei: Etagenliste ohne Abschluss.')
            offset = struct.unpack_from('<I', data, 4 * k)[0]
            if offset == 0:
                break
            if not 4 * k + 4 <= offset <= len(data) - 0x34:
                raise ValueError('Domain-Datei: Etage außerhalb der Datei.')
            name = struct.unpack_from('<I', data, offset)[0]
            if not name < len(data):
                raise ValueError('Domain-Datei: Etagenname außerhalb der Datei.')
            self.floors.append({'offset': offset, 'name': _text(data, name), 'sets': list(data[offset + 0x2F:offset + 0x34])})
            k += 1
            if k > 200:
                raise ValueError('Domain-Datei: zu viele Etagen.')

    def with_sets(self, floor, sets):
        if not 0 <= floor < len(self.floors):
            raise ValueError('Diese Etage gibt es nicht.')
        if len(sets) != 5 or any(type(v) is not int or not 0 <= v <= 255 for v in sets):
            raise ValueError('Eine Etage hat fünf Gruppenplätze (0 = leer, sonst Gruppen-ID 1–255).')
        out = bytearray(self.data)
        at = self.floors[floor]['offset'] + 0x2F
        out[at:at + 5] = bytes(sets)
        return bytes(out)


class EnemyGroups:
    def __init__(self, data):
        self.data = bytes(data)
        self.groups = {}
        at = 0
        while True:
            if at + 1 > len(data):
                raise ValueError('ENEMYSET ohne Endeintrag.')
            if data[at] == 0:
                break
            if at + GROUP > len(data):
                raise ValueError('ENEMYSET-Gruppe abgeschnitten.')
            if data[at] in self.groups:
                raise ValueError('Doppelte Gegnergruppen-ID in ENEMYSET.')
            self.groups[data[at]] = at
            at += GROUP
        self.end = at
        if not self.groups:
            raise ValueError('ENEMYSET enthält keine Gegnergruppen.')

    def group(self, set_id):
        if set_id not in self.groups:
            raise ValueError(f'Gegnergruppe {set_id} gibt es nicht.')
        at = self.groups[set_id]
        d = self.data
        w0, w4 = struct.unpack_from('<II', d, at)
        header = {'map_digimon': struct.unpack_from('<h', d, at + 2)[0], 'ai': (w0 >> 8) & 15, 'pace': (w0 >> 12) & 15,
                  'liked_gift': d[at + 4], 'dungeon_bgm': (w4 >> 8) & 15, 'boss': (w4 >> 12) & 15,
                  'points_per_level': struct.unpack_from('<h', d, at + 6)[0]}
        members = []
        for slot in range(3):
            row = at + 8 + 30 * slot
            m = {k: struct.unpack_from(fmt, d, row + o)[0] for k, (o, fmt, _, _) in MEMBER_FIELDS.items()}
            m['skills'] = list(d[row + 15:row + 18])
            m['rules'] = [list(d[row + 18 + 3 * i:row + 21 + 3 * i]) for i in range(4)]
            members.append(m)
        return {'id': set_id, 'header': header, 'members': members}

    def changed(self, set_id, header=None, members=None, *, digimon_ids=None, skill_ids=None):
        """Bytes with the group's header/members replaced. Unknown bytes stay as they are."""
        if set_id not in self.groups:
            raise ValueError(f'Gegnergruppe {set_id} gibt es nicht.')
        at = self.groups[set_id]
        out = bytearray(self.data)
        if header:
            for k, v in header.items():
                if k not in HEADER_FIELDS or type(v) is not int:
                    raise ValueError(f'Unbekanntes Gruppenfeld: {k}.')
            h = {**self.group(set_id)['header'], **header}
            for k in ('ai', 'pace', 'dungeon_bgm', 'boss'):
                if not 0 <= h[k] <= 15:
                    raise ValueError(f'{k} muss 0–15 sein (4-Bit-Feld).')
            if not 0 <= h['liked_gift'] <= 255 or not -32768 <= h['points_per_level'] <= 32767:
                raise ValueError('Geschenk 0–255, Punkte pro Level als 16-Bit-Wert.')
            if digimon_ids is not None and h['map_digimon'] not in digimon_ids:
                raise ValueError('Kartenfigur muss ein vorhandenes Digimon sein.')
            w0, w4 = struct.unpack_from('<II', out, at)
            w0 = (w0 & ~0xFF00) | (h['ai'] << 8) | (h['pace'] << 12)
            w4 = (w4 & ~0xFF00) | (h['dungeon_bgm'] << 8) | (h['boss'] << 12)
            struct.pack_into('<II', out, at, w0, w4)
            out[at] = set_id
            struct.pack_into('<h', out, at + 2, h['map_digimon'])
            out[at + 4] = h['liked_gift']
            struct.pack_into('<h', out, at + 6, h['points_per_level'])
        for slot, member in enumerate(members or []):
            if member is None:
                continue
            if not 0 <= slot <= 2:
                raise ValueError('Eine Gruppe hat drei Gegnerplätze.')
            row = at + 8 + 30 * slot
            for k, v in member.items():
                if k in MEMBER_FIELDS:
                    o, fmt, lo, hi = MEMBER_FIELDS[k]
                    if type(v) is not int or not lo <= v <= hi:
                        raise ValueError(f'Gegner {slot + 1}: {k} muss {lo}–{hi} sein.')
                    if k == 'digimon' and digimon_ids is not None and v and v not in digimon_ids:
                        raise ValueError(f'Gegner {slot + 1}: Digimon {v} gibt es nicht.')
                    struct.pack_into(fmt, out, row + o, v)
                elif k == 'skills':
                    if len(v) != 3 or any(type(i) is not int or not 0 <= i <= 255 for i in v):
                        raise ValueError(f'Gegner {slot + 1}: drei Technik-IDs 0–255.')
                    if skill_ids is not None and any(i and i not in skill_ids for i in v):
                        raise ValueError(f'Gegner {slot + 1}: unbekannte Technik-ID.')
                    out[row + 15:row + 18] = bytes(v)
                elif k == 'rules':
                    if len(v) != 4 or any(len(r) != 3 or any(type(x) is not int or not 0 <= x <= 255 for x in r) for r in v):
                        raise ValueError(f'Gegner {slot + 1}: vier KI-Regeln aus je drei Bytes.')
                    out[row + 18:row + 30] = bytes(x for r in v for x in r)
                else:
                    raise ValueError(f'Unbekanntes Gegnerfeld: {k}.')
            skills, rules = list(out[row + 15:row + 18]), [out[row + 18 + 3 * i:row + 21 + 3 * i] for i in range(4)]
            if struct.unpack_from('<H', out, row)[0]:
                if not struct.unpack_from('<H', out, row + 2)[0] or not out[row + 10]:
                    raise ValueError(f'Gegner {slot + 1}: ein besetzter Platz braucht HP und Level ab 1.')
                for cond, action, target in rules:
                    if action == 0:
                        break
                    if action <= 3 and not skills[action - 1]:
                        raise ValueError(f'Gegner {slot + 1}: KI-Regel verweist auf leeren Technikplatz {action}.')
        result = bytes(out)
        EnemyGroups(result)
        return result

    def cloned(self, source_id, new_id):
        """A copy of group SOURCE_ID under the free id NEW_ID, before the end marker."""
        if source_id not in self.groups:
            raise ValueError(f'Gegnergruppe {source_id} gibt es nicht.')
        if type(new_id) is not int or not 1 <= new_id <= 255 or new_id in self.groups:
            raise ValueError('Neue Gruppen-ID muss frei und 1–255 sein.')
        at = self.groups[source_id]
        row = bytearray(self.data[at:at + GROUP])
        row[0] = new_id
        tail = self.data[self.end:]
        if len(tail) > GROUP and not any(tail[:GROUP + 1]):
            # write into the zero padding behind the end marker: same file length, a zero
            # id still follows (Enemy_FindSetById stops there)
            out = self.data[:self.end] + bytes(row) + tail[GROUP:]
        else:
            # no room: one more group; the old end marker (zero id) follows the new row
            out = self.data[:self.end] + bytes(row) + (tail if tail[:1] == b'\0' else bytes(GROUP))
        result = bytes(out)
        EnemyGroups(result)
        return result

    def free_ids(self):
        return [i for i in range(1, 256) if i not in self.groups]


class DomainRepository:
    """Reads and stages domain floors and enemy groups through the session."""

    def __init__(self, session, entries):
        self.session, self.entries = session, entries
        archive = session.current(file_entry(session, entries, DOMAIN_FILE, 'DOMAINS_0E20'))
        self.table = DomainTable(archive)
        self.enemyset = file_entry(session, entries, ENEMYSET, 'ENEMYSET')

    def groups(self):
        return EnemyGroups(self.session.current(self.enemyset))

    def dungeon(self, index):
        if not 0 <= index < len(self.table.rows):
            raise ValueError('Diese Domain gibt es nicht.')
        entry = file_entry(self.session, self.entries, self.table.rows[index], f'DOMAIN_{index:02d}')
        return entry, DungeonFile(self.session.current(entry))

    def overview(self):
        groups = self.groups()
        out = []
        for i, fid in enumerate(self.table.rows):
            _, dungeon = self.dungeon(i)
            floors = [{'floor': k, 'name': f['name'], 'sets': f['sets'],
                       'unknown': [s for s in f['sets'] if s and s not in groups.groups]} for k, f in enumerate(dungeon.floors)]
            out.append({'index': i, 'file': fid, 'name': floors[0]['name'] if floors else f'Domain {i}', 'floors': floors})
        return out

    def set_floor(self, index, floor, sets):
        groups = self.groups()
        missing = [s for s in sets if s and s not in groups.groups]
        if missing:
            raise ValueError(f'Gegnergruppe(n) {missing} gibt es nicht.')
        entry, dungeon = self.dungeon(index)
        data = dungeon.with_sets(floor, list(sets))
        if data == dungeon.data:
            return False
        self.session.stage(entry, data, f'Domain {index} / Etage {floor + 1}: Gegnergruppen')
        return True

    def set_group(self, set_id, header=None, members=None, digimon_ids=None, skill_ids=None):
        groups = self.groups()
        data = groups.changed(set_id, header, members, digimon_ids=digimon_ids, skill_ids=skill_ids)
        if data == groups.data:
            return False
        self.session.stage(self.enemyset, data, f'Gegnergruppe {set_id}')
        return True

    def clone_group(self, source_id, new_id=None):
        groups = self.groups()
        new_id = new_id or (groups.free_ids() or [None])[0]
        if new_id is None:
            raise ValueError('Keine freie Gruppen-ID mehr (1–255).')
        self.session.stage(self.enemyset, groups.cloned(source_id, new_id), f'Gegnergruppe {new_id} (Kopie von {source_id})')
        return new_id

    def usage(self, set_id):
        return [{'domain': d['index'], 'name': d['name'], 'floor': f['floor']}
                for d in self.overview() for f in d['floors'] if set_id in f['sets']]
