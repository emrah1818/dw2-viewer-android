"""Individual techniques: a copy of an existing technique under a free id, used by one Digimon.

The copy keeps the source's effects, animation parts, sound and flags (all inside its WAZADATA
record, see SkillTable.cloned). Name, description, MP, power, element (specialty), start
animation (F/G/H, cast bits) and the other documented fields are then the copy's own. It is
assigned as the Digimon's learnable technique (DIGIMNDT +2) and/or to its enemy slots in
ENEMYSET. No other Digimon refers to the new id, so nothing else changes.
"""
from .battle_skills import AttackRepository, BaseTable, EnemyTable, SkillTable

# Byte groups of the 68-byte record (EntED40 in include/main/156C.h of the PC port) that can be
# taken over from another technique. Word 0 holds id and value bits, so the cast animation is a
# bit mask there; the other groups are whole byte ranges.
PARTS = {
    'sound': ((0x05, 0x08),),                  # shotXaChannel u8, shotXaFile s16 (Ruf / Ton)
    'effect': ((0x0C, 0x18), (0x2C, 0x44)),    # partsEntry, field_10, field_14, fxFiles[4][3]
    'status': ((0x18, 0x1C),),                 # statusFlags (Zustandseffekte)
    'animation': 'cast',                       # Startanimation F/G/H: Bits 16-17 von Wort 0
}
CAST_MASK = 0x3 << 16


class TechniqueRepository:
    def __init__(self, session, entries):
        self.session = session
        self.attacks = AttackRepository(session, entries)
        self.files = self.attacks.entries

    def tables(self):
        return self.attacks.tables()

    def usage(self, technique):
        skills, base, enemies = self.tables()
        default = [i for i, (off, skill) in base.records.items() if skill == technique]
        found = [(k, r.identifier) for k, r in enemies.records.items() if technique in r.skills]
        users = set(default) | {d for _, d in found}
        return {'technique': technique, 'default_of': default, 'encounters': [list(k) for k, _ in found],
                'digimon': sorted(users), 'shared': len(users) > 1}

    def catalog(self):
        skills, base, enemies = self.tables()
        users = {}
        for i, (off, skill) in base.records.items():
            users.setdefault(skill, set()).add(i)
        for k, r in enemies.records.items():
            for s in r.skills:
                users.setdefault(s, set()).add(r.identifier)
        return [{'id': i, 'name': r.name, 'mp': r.mp, 'power': r.power, 'specialty': r.specialty,
                 'cast': r.cast, 'category': r.category, 'target': r.target, 'rank': r.rank,
                 'users': sorted(users.get(i, ()))} for i, r in sorted(skills.records.items())]

    def create(self, digimon, source, name, *, description=None, values=None, as_default=True, encounters=(), new_id=None):
        skills, base, enemies = self.tables()
        if as_default and digimon not in base.records:
            raise ValueError('Dieses Digimon hat keinen DIGIMNDT-Eintrag für eine erlernbare Technik.')
        encounters = [tuple(k) for k in encounters]
        for key in encounters:
            if key not in enemies.records or enemies.records[key].identifier != digimon:
                raise ValueError('Gegnerplatz gehört nicht zu diesem Digimon.')
        if not as_default and not encounters:
            raise ValueError('Die neue Technik muss mindestens einem Platz zugewiesen werden.')
        new_id = new_id or (skills.free_ids() or [None])[0]
        if new_id is None:
            raise ValueError('Keine freie Technik-ID 1–255 mehr.')
        wazadata = skills.cloned(source, new_id, name, description, values)
        files = {'WAZADATA.BIN': wazadata}
        if as_default:
            files['DIGIMNDT.BIN'] = base.changed(digimon, new_id)
        if encounters:
            changes = {}
            for key in encounters:
                old = enemies.records[key]
                slots = list(old.skills)
                # replace the slot that held SOURCE, else the first empty slot, else slot 1
                pick = slots.index(source) if source in slots else (slots.index(0) if 0 in slots else 0)
                slots[pick] = new_id
                changes[key] = (slots, list(old.rules))
            files['ENEMYSET.BIN'] = enemies.changed(changes, SkillTable(wazadata).records)
        for name_, data in files.items():
            self.session.stage(self.files[name_], data, f'Eigene Technik {new_id} für #{digimon:03}')
        return {'id': new_id, 'files': sorted(files)}

    def edit(self, technique, values=None, name=None, *, digimon):
        """Change an individual technique (one created here). Shared techniques: values only via
        the existing global attack editor, so other Digimon are never changed by accident."""
        info = self.usage(technique)
        if info['shared'] or set(info['digimon']) - {digimon}:
            raise ValueError('Diese Technik nutzen mehrere Digimon. Für Änderungen nur an einem Digimon '
                             'zuerst eine eigene Technik anlegen.')
        skills, _, _ = self.tables()
        if technique not in skills.records:
            raise ValueError('Technik fehlt.')
        data = skills.data
        if name is not None and name != skills.records[technique].name:
            data = _renamed(SkillTable(data), technique, name)
        if values:
            data = SkillTable(data).changed({technique: values})
        if data == skills.data:
            return False
        self.session.stage(self.files['WAZADATA.BIN'], data, f'Technik {technique} bearbeitet')
        return True


def copy_parts(repo, technique, source, parts, *, digimon):
    """Take effect / sound / status / animation bytes of SOURCE into the individual TECHNIQUE."""
    import struct
    info = repo.usage(technique)
    if info['shared'] or set(info['digimon']) - {digimon}:
        raise ValueError('Diese Technik nutzen mehrere Digimon. Teile nur in eine eigene Technik übernehmen.')
    if not parts or set(parts) - set(PARTS):
        raise ValueError('Teile: ' + ', '.join(sorted(PARTS)) + '.')
    skills, _, _ = repo.tables()
    for t in (technique, source):
        if t not in skills.records:
            raise ValueError(f'Technik {t} fehlt.')
    if technique == source:
        raise ValueError('Quelle und Ziel sind dieselbe Technik.')
    dst, src = skills.records[technique].offset, skills.records[source].offset
    out = bytearray(skills.data)
    for part in parts:
        spec = PARTS[part]
        if spec == 'cast':
            word = struct.unpack_from('<I', out, dst)[0]
            word = (word & ~CAST_MASK) | (struct.unpack_from('<I', out, src)[0] & CAST_MASK)
            struct.pack_into('<I', out, dst, word)
            continue
        for a, b in spec:
            out[dst + a:dst + b] = skills.data[src + a:src + b]
    out = bytes(out)
    SkillTable(out)
    if out == skills.data:
        return False
    repo.session.stage(repo.files['WAZADATA.BIN'], out,
                       f'Technik {technique}: {", ".join(sorted(parts))} von {source}')
    return True


def assign(repo, technique, digimon_ids):
    """One technique as the learnable technique (DIGIMNDT +2) of several Digimon, one undo step."""
    skills, base, _ = repo.tables()
    if technique not in skills.records or not 1 <= technique <= 255:
        raise ValueError('Technik muss eine vorhandene ID 1–255 sein.')
    ids = list(dict.fromkeys(digimon_ids or ()))
    if not ids:
        raise ValueError('Mindestens ein Digimon wählen.')
    missing = [d for d in ids if d not in base.records]
    if missing:
        raise ValueError('Ohne DIGIMNDT-Eintrag: ' + ', '.join(f'#{d:03}' for d in missing))
    data = base.data
    for d in ids:
        data = BaseTable(data).changed(d, technique)
    if data == base.data:
        return []
    repo.session.stage(repo.files['DIGIMNDT.BIN'], data,
                       f'Technik {technique} für ' + ', '.join(f'#{d:03}' for d in ids))
    return ids


def id_budget(repo):
    """Technique ids are one byte in DIGIMNDT, ENEMYSET and the save roster: 1–255 only."""
    skills, base, enemies = repo.tables()
    used = set(skills.records)
    referenced = {s for _, s in base.records.values()} | {s for r in enemies.records.values() for s in r.skills}
    return {'free': skills.free_ids(), 'free_count': len(skills.free_ids()), 'max_id': 255,
            'existing': len([i for i in used if 1 <= i <= 255]),
            'unreferenced': sorted(i for i in used if 1 <= i <= 255 and i not in referenced),
            'reason': 'Technik-IDs sind in DIGIMNDT (+2), ENEMYSET (Fertigkeiten) und im Spielstand je '
                      'ein Byte. Mehr als 255 IDs sind ohne Port-Änderung nicht sicher möglich. '
                      'Nicht zugeordnete Techniken werden nur angezeigt, nie automatisch wiederverwendet '
                      '(Spielstände können sie gelernt haben).'}


def _renamed(table, technique, name):
    """New name text behind the end row; only the record's name offset changes."""
    import struct
    from .battle_skills import _encode_text
    encoded = _encode_text(name, 17, 'Technikname')
    end = table._find_end(table.data, table.records_start)
    out = bytearray(table.data)
    if len(out) < end + 68:
        out += bytes(end + 68 - len(out))
    out = bytearray(bytes(out).rstrip(b'\0')) if len(out) > end + 68 else out
    if len(out) < end + 68:
        out += bytes(end + 68 - len(out))
    at = len(out)
    out += encoded + b'\xff'
    out += bytes(-len(out) % 4)
    if len(out) < len(table.data):
        out += bytes(len(table.data) - len(out))
    struct.pack_into('<I', out, table.records[technique].offset + 0x24, at)
    SkillTable(bytes(out))
    return bytes(out)
