"""Native specialty and per-encounter stats; see EIGENSCHAFTEN_v4_0.md."""
import struct
from .battle_skills import BaseTable, EnemyTable, discover_tables

SPECIALTIES = {0:'Water', 1:'Fire', 2:'Nature', 3:'Machine', 4:'Darkness', 5:'None'}
ENEMY_FIELDS = {'hp':(2,'H',0,32767), 'mp':(4,'H',0,32767),
                'exp':(6,'h',0,32767), 'attack':(11,'B',0,255),
                'defense':(12,'H',0,32767), 'speed':(14,'B',0,255)}


def specialty_name(code):
    return SPECIALTIES.get(code, f'Unbekannter Code {code}')


class PropertyRepository:
    def __init__(self, session, entries, filename):
        self.session = session
        self.filename = filename
        self.entry = discover_tables(session, entries, filenames=(filename,))[filename]
        if not any((e.path,e.lba,e.size)==(self.entry.path,self.entry.lba,self.entry.size) for e in entries):
            entries.append(self.entry)

    def specialty(self, identifier, original=False):
        data = self.session.original(self.entry) if original else self.session.current(self.entry)
        table = BaseTable(data)
        if identifier not in table.records:
            raise ValueError('Für dieses Digimon fehlt der Basiseintrag.')
        return data[table.records[identifier][0]+5] & 15

    def change_specialty(self, identifier, code):
        if type(code) is not int or code not in SPECIALTIES:
            raise ValueError('Bitte eine unterstützte Specialty auswählen.')
        data = self.session.current(self.entry)
        table = BaseTable(data)
        self.specialty(identifier)
        out = bytearray(data)
        offset = table.records[identifier][0]+5
        out[offset] = (out[offset]&0xF0)|code
        if out == data:return False
        self.session.stage(self.entry, out, f'Specialty #{identifier:03}: {specialty_name(code)}')
        return True

    def enemies(self, original=False):
        return EnemyTable(self.session.original(self.entry) if original else self.session.current(self.entry))

    def values(self, row, original=False):
        data = self.session.original(self.entry) if original else self.session.current(self.entry)
        return {name:struct.unpack_from('<'+fmt,data,row.offset+offset)[0]
                for name,(offset,fmt,_,_) in ENEMY_FIELDS.items()}

    def enemy_bytes(self, identifier, changes):
        table = self.enemies()
        out = bytearray(table.data)
        for key, fields in changes.items():
            row = table.records.get(key)
            if row is None or row.identifier != identifier:
                raise ValueError('Gegnerzeile gehört nicht zum gewählten Digimon.')
            for name,value in fields.items():
                if name not in ENEMY_FIELDS:raise ValueError('Unbekanntes Gegnerfeld.')
                offset,fmt,lo,hi = ENEMY_FIELDS[name]
                if type(value) is not int or not lo<=value<=hi:
                    raise ValueError(f'{name}: benötigt {lo} bis {hi} (natives Zahlenformat).')
                struct.pack_into('<'+fmt,out,row.offset+offset,value)
        return bytes(out)

    def apply_enemies(self, identifier, changes):
        out=self.enemy_bytes(identifier,changes)
        if out == self.session.current(self.entry):return False
        self.session.stage(self.entry,out,f'Werte/EXP #{identifier:03} · {len(changes)} Begegnung(en)')
        return True
