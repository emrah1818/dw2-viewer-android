"""Species type: DIGIMNDT byte +4, low nibble (Digi_GetType).

US codes, checked against the supplied table: Data=0, Vaccine=1, Virus=2.
See TYPEN_v3_9.md. Type editing does not require the technique catalogue.
"""
from .battle_skills import BaseTable, discover_tables

TYPES = {0: 'Data', 1: 'Vaccine', 2: 'Virus'}


def type_name(code):
    return TYPES.get(code, f'Unbekannter Typ (Code {code})')


class TypeRepository:
    def __init__(self, session, entries):
        self.session = session
        self.entry = discover_tables(session, entries, filenames=('DIGIMNDT.BIN',))['DIGIMNDT.BIN']
        if not any((e.path, e.lba, e.size) == (self.entry.path, self.entry.lba, self.entry.size) for e in entries):
            entries.append(self.entry)

    def table(self):
        return BaseTable(self.session.current(self.entry))

    def original_type(self, identifier):
        return BaseTable(self.session.original(self.entry)).type_of(identifier)

    def change(self, identifier, new_type):
        table = self.table()
        old = table.type_of(identifier)
        changed = table.with_type(identifier, new_type)
        if changed == table.data:
            return False
        self.session.stage(self.entry, changed,
            f'Typ #{identifier:03}: {type_name(old)} → {type_name(new_type)}')
        return True
