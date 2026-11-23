"""Native US DW2 technique tables. All writers patch documented fields only.

Evidence and scope: ATTACKEN_v3_8.md. No savegame or executable engine patch.
"""
from dataclasses import dataclass
import csv
import struct
from .disc import Entry
from .digimon_names import basename, DECODE

FILE_INDEX = {'WAZADATA.BIN': 603, 'DIGIMNDT.BIN': 3180, 'ENEMYSET.BIN': 3183}
CATEGORIES = ('Attack', 'Assist', 'Counter', 'Interrupt')


def power_label(power, *, decimal_comma=True):
    """Normal AP uses half the native power (damage denominator: def * 2).

    A negative power selects healing logic; do not mislabel it as damage AP.
    Zero-power techniques can still have effects, so no promised zero damage.
    """
    if power < 0:
        return f'Heilwert {power} (nativ)'
    if power == 0:
        return '— AP'
    text = f'{power / 2:g}'
    return (text.replace('.', ',') if decimal_comma else text)+' AP'


def skill_label(record, changes=None):
    values = changes or {}
    mp = values.get('mp', record.mp)
    power = values.get('power', record.power)
    return f'{record.identifier:02X} · {record.name} · {mp} MP · {power_label(power)}'


def text_at(data, pointer, limit, tail=None):
    # TAIL: (start, end) of the text area behind the end record, used by techniques
    # 0.17b added (Skill_GetNameText adds the offset to the file base; any offset works).
    if tail and tail[0] <= pointer < tail[1]:
        limit = tail[1]
    elif not 4 <= pointer < limit:
        raise ValueError('WAZADATA-Textzeiger liegt außerhalb des Textblocks.')
    end = data.find(b'\xff', pointer, limit)
    if end < 0:
        raise ValueError('WAZADATA-Text ohne FF-Abschluss.')
    # Control sequences are displayed, never written back through this decoder.
    return ''.join(DECODE.get(b, '\n' if b == 0xFE else f'⟨{b:02X}⟩')
                   for b in data[pointer:end])


@dataclass(frozen=True)
class Skill:
    identifier: int
    offset: int
    name: str
    description: str
    mp: int
    power: int
    category: int
    target: int
    specialty: int
    rank: int
    cast: int


class SkillTable:
    def _text(self, data, pointer, start):
        # Texts behind the end record: only after a complete 68-byte zero end row.
        tail = None
        if pointer >= start:
            end = self._find_end(data, start)
            if end is not None and pointer >= end + 68:
                tail = (end + 68, len(data))
        return text_at(data, pointer, start, tail)

    @staticmethod
    def _find_end(data, start):
        at = start
        while at + 2 <= len(data):
            if struct.unpack_from('<h', data, at)[0] == 0:
                return at
            at += 68
        return None

    def __init__(self, data):
        self.data = bytes(data)
        if not 72 <= len(data) <= 4*1024*1024:
            raise ValueError('WAZADATA-Dateigröße nicht erkannt.')
        start = struct.unpack_from('<I', data)[0]
        if start % 4 or not 4 <= start <= len(data)-68:
            raise ValueError('WAZADATA-Datensatzzeiger ungültig.')
        self.records_start = start
        self.records = {}
        offset = start
        while offset < len(data):
            # The ISO file may end exactly after its final complete record.
            # The game loads whole CD sectors, whose zero padding supplies the
            # stop ID outside the logical file. Do not require or append a
            # fictitious 68-byte row inside that file (DW2-TT e6/e9 screenshots).
            # An explicit stop requires only the two bytes the game actually
            # tests, not a complete record's unused fields.
            remaining = len(data)-offset
            if remaining < 2:
                raise ValueError(f'WAZADATA-Technik-ID bei 0x{offset:X} abgeschnitten ({remaining}/2 Bytes).')
            identifier = struct.unpack_from('<h', data, offset)[0]
            if identifier == 0:
                self.end_kind = 'zero_id'
                break
            if remaining < 68:
                raise ValueError(f'WAZADATA-Datensatz bei 0x{offset:X} unvollständig ({remaining}/68 Bytes).')
            if identifier < 0 or identifier in self.records:
                raise ValueError('Ungültige/doppelte Technik-ID in WAZADATA.')
            bits = struct.unpack_from('<I', data, offset)[0]
            name, desc = struct.unpack_from('<II', data, offset+0x24)
            self.records[identifier] = Skill(identifier, offset,
                self._text(data, name, start), self._text(data, desc, start), data[offset+4],
                struct.unpack_from('<h', data, offset+8)[0], (bits >> 18) & 3,
                (bits >> 20) & 15, (bits >> 24) & 15, bits >> 28, (bits >> 16) & 3)
            offset += 68
        else:
            self.end_kind = 'file_end'
        self.end_offset = offset
        if not self.records:
            raise ValueError('Keine Techniken in WAZADATA gefunden.')

    def changed(self, changes):
        out = bytearray(self.data)
        fields = {'mp': (0, 255), 'power': (-32768, 32767), 'category': (0, 3),
                  'target': (0, 15), 'specialty': (0, 15), 'rank': (0, 15), 'cast': (0, 3)}
        packed = {'category': (18, 3), 'target': (20, 15), 'specialty': (24, 15),
                  'rank': (28, 15), 'cast': (16, 3)}
        for identifier, values in changes.items():
            if identifier not in self.records:
                raise ValueError(f'Technik {identifier} fehlt in WAZADATA.')
            record = self.records[identifier]
            for field, value in values.items():
                if field not in fields or type(value) is not int or not fields[field][0] <= value <= fields[field][1]:
                    raise ValueError(f'Ungültiger Technikwert: {field}.')
                if field == 'mp':
                    out[record.offset+4] = value
                elif field == 'power':
                    struct.pack_into('<h', out, record.offset+8, value)
                else:
                    shift, mask = packed[field]
                    bits = struct.unpack_from('<I', out, record.offset)[0]
                    struct.pack_into('<I', out, record.offset, (bits & ~(mask << shift)) | (value << shift))
        result = bytes(out)
        SkillTable(result)
        return result

    def free_ids(self):
        # DIGIMNDT/ENEMYSET and the roster store technique ids as one byte.
        return [i for i in range(1, 256) if i not in self.records]

    def cloned(self, source, new_id, name, description=None, values=None):
        """Copy of technique SOURCE (all 68 bytes: effects, parts, XA sound, flags) as NEW_ID.

        Skill_FindById (src/main/skill.c) scans the 68-byte records up to an id of 0 and every
        Skill_Get* reads the record found, so the copy is independent of SOURCE. The new name
        (and description, if given) go behind a full zero end row; the copy's text offsets
        point there. Other records and texts keep their bytes."""
        from .digimon_names import encode_name
        if source not in self.records:
            raise ValueError(f'Technik {source} fehlt in WAZADATA.')
        if type(new_id) is not int or not 1 <= new_id <= 255 or new_id in self.records:
            raise ValueError('Neue Technik-ID muss frei und 1–255 sein (einbytekodiert in DIGIMNDT/ENEMYSET).')
        encoded = _encode_text(name, 17, 'Technikname')
        desc = _encode_text(description, 120, 'Beschreibung', allow_newline=True) if description else None
        end = self._find_end(self.data, self.records_start)
        if end is None:
            raise ValueError('WAZADATA ohne Endeintrag.')
        tail = self.data[end + 68:] if len(self.data) >= end + 68 else b''
        if tail and any(tail[:4]) and end + 68 > len(self.data):
            raise ValueError('WAZADATA-Ende nicht erkannt.')
        out = bytearray(self.data[:end])
        record = bytearray(self.data[self.records[source].offset:self.records[source].offset + 68])
        struct.pack_into('<h', record, 0, new_id)
        out += record
        out += bytes(68)                              # end row: id 0
        old_tail = bytes(tail).rstrip(b'\0')
        base = len(out)
        out += old_tail                               # texts added earlier keep their offsets
        shift = base - (end + 68)
        if shift and old_tail:
            # earlier tail texts moved by one record: fix the offsets that point into them
            for rec in list(self.records.values()):
                for field in (0x24, 0x28):
                    at = rec.offset + field
                    if at >= end:
                        continue
                    pointer = struct.unpack_from('<I', out, at)[0]
                    if end + 68 <= pointer < end + 68 + len(old_tail):
                        struct.pack_into('<I', out, at, pointer + shift)
        name_at = len(out)
        out += encoded + b'\xff'
        struct.pack_into('<I', out, end + 0x24, name_at)
        if desc is not None:
            desc_at = len(out)
            out += desc + b'\xff'
            struct.pack_into('<I', out, end + 0x28, desc_at)
        out += bytes(-len(out) % 4)
        if len(out) < len(self.data):
            # same length as before when it fits: the port's version-1 loader keeps the file size
            out += bytes(len(self.data) - len(out))
        result = SkillTable(bytes(out))
        if values:
            return result.changed({new_id: values})
        return result.data


def _encode_text(text, limit, what, allow_newline=False):
    from .digimon_names import ENCODE
    if not isinstance(text, str) or not text.strip() or text != text.strip():
        raise ValueError(f'{what}: nicht leer, ohne Leerzeichen am Anfang/Ende.')
    if len(text) > limit:
        raise ValueError(f'{what}: höchstens {limit} Zeichen.')
    out = bytearray()
    for c in text:
        if c == '\n' and allow_newline:
            out.append(0xFE)
        elif c in ENCODE:
            out.append(ENCODE[c])
        else:
            raise ValueError(f'{what}: Zeichen {c!r} gibt es im US-Zeichensatz nicht.')
    return bytes(out)


class BaseTable:
    def __init__(self, data):
        self.data = bytes(data)
        self.records = {}
        for offset in range(0, len(data)-17, 18):
            identifier = struct.unpack_from('<h', data, offset)[0]
            if identifier == 0:
                break
            if identifier < 0 or identifier in self.records:
                raise ValueError('Ungültige/doppelte Digimon-ID in DIGIMNDT.')
            self.records[identifier] = (offset, data[offset+2])
        else:
            raise ValueError('DIGIMNDT-Endeintrag fehlt.')
        if not self.records:
            raise ValueError('DIGIMNDT enthält keine Digimon.')

    def changed(self, identifier, skill):
        if identifier not in self.records:
            raise ValueError('Dieses Digimon besitzt keinen DIGIMNDT-Standardeintrag.')
        if type(skill) is not int or not 1 <= skill <= 255:
            raise ValueError('Standard-Attacke benötigt eine vorhandene einbytekodierte Technik-ID.')
        out = bytearray(self.data)
        out[self.records[identifier][0]+2] = skill
        return bytes(out)

    def type_of(self, identifier):
        if identifier not in self.records:
            raise ValueError(f'Digimon #{identifier:03} besitzt keinen DIGIMNDT-Eintrag.')
        return self.data[self.records[identifier][0]+4] & 0x0F

    def with_type(self, identifier, new_type):
        self.type_of(identifier)
        if type(new_type) is not int or new_type not in (0, 1, 2):
            raise ValueError('Als Digimon-Typ sind nur Data, Vaccine und Virus unterstützt.')
        out = bytearray(self.data)
        offset = self.records[identifier][0]+4
        out[offset] = (out[offset] & 0xF0) | new_type
        return bytes(out)


@dataclass(frozen=True)
class Encounter:
    set_id: int
    slot: int
    identifier: int
    offset: int
    level: int
    skills: tuple
    rules: tuple

    @property
    def key(self):
        return self.set_id, self.slot


class EnemyTable:
    def __init__(self, data):
        self.data = bytes(data)
        self.records = {}
        seen = set()
        for offset in range(0, len(data)-99, 100):
            set_id = data[offset]
            if set_id == 0:
                break
            if set_id in seen:
                raise ValueError('Doppelte Gegnergruppen-ID in ENEMYSET.')
            seen.add(set_id)
            for slot in range(3):
                row = offset+8+slot*30
                identifier = struct.unpack_from('<h', data, row)[0]
                if identifier < 0:
                    raise ValueError('Ungültige Digimon-ID in ENEMYSET.')
                if identifier:
                    self.records[set_id, slot] = Encounter(set_id, slot, identifier, row,
                        data[row+10], tuple(data[row+15:row+18]),
                        tuple(tuple(data[row+18+3*i:row+21+3*i]) for i in range(4)))
        else:
            raise ValueError('ENEMYSET-Endeintrag fehlt.')
        if not seen:
            raise ValueError('ENEMYSET enthält keine Gegnergruppen.')

    def for_digimon(self, identifier):
        return [r for r in self.records.values() if r.identifier == identifier]

    def changed(self, changes, catalogue):
        out = bytearray(self.data)
        for key, (skills, rules) in changes.items():
            if key not in self.records:
                raise ValueError('Gegnerbegegnung wurde nicht gefunden.')
            old = self.records[key]
            if len(skills) != 3 or any(type(i) is not int or not 0 <= i <= 255 for i in skills):
                raise ValueError('ENEMYSET speichert drei einbytekodierte Attacken pro Gegner.')
            for i in skills:
                if i and i not in catalogue:
                    raise ValueError(f'Technik-ID {i} fehlt im geöffneten Spiel.')
            if len(rules) != 4 or any(len(r) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in r) for r in rules):
                raise ValueError('Eine Begegnung benötigt vier KI-Regeltripel.')
            # Validate active rules. Bytes behind the first stop marker are opaque.
            for condition, action, target in rules:
                if action == 0:
                    break
                if action not in (1, 2, 3, 4):
                    raise ValueError('KI-Aktion muss Slot 1–3, Abwehr (4) oder Ende (0) sein.')
                if action <= 3 and not skills[action-1]:
                    raise ValueError(f'Eine aktive KI-Regel verweist auf den leeren Attacken-Slot {action}.')
            if not any(skills):
                raise ValueError('Mindestens eine Gegner-Attacke beibehalten.')
            out[old.offset+15:old.offset+18] = bytes(skills)
            out[old.offset+18:old.offset+30] = bytes(v for rule in rules for v in rule)
        return bytes(out)


PARSERS = {'WAZADATA.BIN': SkillTable, 'DIGIMNDT.BIN': BaseTable, 'ENEMYSET.BIN': EnemyTable}


def discover_tables(session, entries, *, filenames=None):
    filenames = tuple(FILE_INDEX) if filenames is None else tuple(filenames)
    if not filenames or any(name not in FILE_INDEX for name in filenames):
        raise ValueError('Unbekannte native Datentabelle angefordert.')
    result = {}
    for name in filenames:
        physical = {}
        for entry in entries:
            if not entry.directory and basename(entry.path) == name:
                physical.setdefault((entry.lba, entry.size), entry)
        if len(physical) > 1:
            raise ValueError(f'{name} mehrfach an verschiedenen Positionen; Zuordnung nicht eindeutig.')
        if physical:
            result[name] = next(iter(physical.values()))
    missing = set(filenames)-result.keys()
    if missing:
        exe = {(e.lba, e.size): e for e in entries if not e.directory and basename(e.path) == 'SLUS_011.93'}
        if len(exe) == 1:
            data = session.current(next(iter(exe.values())))
            from .dw2_file_index import US
            count, lbas, sizes = US
            if not data.startswith(b'PS-X EXE') or len(data) < sizes+count*2:
                raise ValueError('US-Dateitabelle in SLUS_011.93 nicht erkannt.')
            allocations = []
            total = session.stamp[0]//session.sector_size
            for i in range(count):
                lba = struct.unpack_from('<I', data, lbas+i*4)[0]
                sectors = struct.unpack_from('<H', data, sizes+i*2)[0]
                if sectors and (lba >= total or sectors > total-lba):
                    raise ValueError('US-Dateitabelle verweist außerhalb des Images.')
                allocations.append((lba, sectors))
            for name in missing:
                lba, sectors = allocations[FILE_INDEX[name]]
                if sectors:
                    result[name] = Entry('INTERNAL/'+name, lba, sectors*2048, False)
    missing = set(filenames)-result.keys()
    if missing:
        raise ValueError('Native Attackentabellen fehlen: '+', '.join(sorted(missing))+'. Unterstützt wird das US-Spiel SLUS_011.93.')
    for name, entry in result.items():
        PARSERS[name](session.current(entry))
    return result


@dataclass(frozen=True)
class AttackPlan:
    identifier: int
    default: object
    encounters: dict
    techniques: dict


class AttackRepository:
    def __init__(self, session, entries):
        self.session = session
        self.entries = discover_tables(session, entries)
        known = {(e.path, e.lba, e.size) for e in entries}
        for entry in self.entries.values():
            if (entry.path, entry.lba, entry.size) not in known:
                entries.append(entry)

    def tables(self):
        return tuple(PARSERS[n](self.session.current(self.entries[n])) for n in FILE_INDEX)

    def preview(self, plan):
        skills, base, enemies = self.tables()
        files = {}
        if plan.default is not None:
            if plan.default not in skills.records:
                raise ValueError('Standard-Attacke fehlt im Technikkatalog.')
            data = base.changed(plan.identifier, plan.default)
            if data != base.data:
                files['DIGIMNDT.BIN'] = data
        for key in plan.encounters:
            if key not in enemies.records or enemies.records[key].identifier != plan.identifier:
                raise ValueError('Gegneränderung gehört zu einem anderen Digimon.')
        if plan.encounters:
            data = enemies.changed(plan.encounters, skills.records)
            if data != enemies.data:
                files['ENEMYSET.BIN'] = data
        if plan.techniques:
            data = skills.changed(plan.techniques)
            if data != skills.data:
                files['WAZADATA.BIN'] = data
        return files

    def apply(self, plan):
        files = self.preview(plan)  # all tables validated before the first mutation.
        before = self.session.edits.copy()
        try:
            for name, data in files.items():
                self.session.stage(self.entries[name], data,
                    f'Attacken #{plan.identifier:03} · '+('globale Technikwerte' if name == 'WAZADATA.BIN' else 'Digimon-Zuordnung / Gegner-KI'))
        except Exception:
            self.session.edits = before
            raise
        return len(files)

    def export_csv(self, path, techniques=None):
        skills, _, _ = self.tables()
        if techniques:
            skills = SkillTable(skills.changed(techniques))
        with open(path, 'w', encoding='utf-8-sig', newline='') as out:
            writer = csv.writer(out, delimiter=';')
            writer.writerow(['ID', 'Hex', 'Name', 'Kategorie', 'MP', 'Power (nativ)', 'AP', 'Zielcode',
                             'Elementcode', 'Rangcode', 'Animationscode', 'Beschreibung'])
            for r in skills.records.values():
                writer.writerow([r.identifier, f'{r.identifier:02X}', r.name, CATEGORIES[r.category],
                    r.mp, r.power, (str(r.power / 2).replace('.', ',') if r.power > 0 else ''),
                    r.target, r.specialty, r.rank, r.cast, r.description])
