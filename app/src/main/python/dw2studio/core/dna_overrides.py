"""Portable, versioned DNA combination overrides for DW2 Studio mods.

The companion PC port reads Mods/dna_overrides.json and applies pair results and
species ranks through its dna_overrides interface (version 1).
"""
import json

FORMAT = 'dw2-dna-overrides'
SCHEMA_VERSION = 1
FILENAME = "dna_overrides.json"
RANKS = ('Rookie', 'Champion', 'Ultimate', 'Mega')


def _species(value, label, valid_ids=None):
    if type(value) is not int or not 1 <= value <= 255:
        raise ValueError(f'{label}: Digimon-ID muss 1 bis 255 sein.')
    if valid_ids is not None and value not in valid_ids:
        raise ValueError(f'{label}: Digimon-ID {value} ist nicht vorhanden.')
    return value


def _rank(value):
    if type(value) is not int or not 0 <= value <= 3:
        raise ValueError('Ergebnisstufe muss 0 (Rookie) bis 3 (Mega) sein.')
    return value


def pair_key(a, b):
    """DNA partners are unordered: A+B and B+A are the same rule."""
    return tuple(sorted((_species(a, 'Partner A'), _species(b, 'Partner B'))))


class DnaOverrides:
    """Independent mod data, never modifies the original DIGIMNDT table."""

    def __init__(self, rules=(), valid_ids=None):
        self.valid_ids = None if valid_ids is None else frozenset(valid_ids)
        self.rules = {}
        for rule in rules:
            self.add(rule['a'], rule['b'], rule['result'], rule['rank'])

    def add(self, a, b, result, rank):
        a = _species(a, 'Partner A', self.valid_ids)
        b = _species(b, 'Partner B', self.valid_ids)
        result = _species(result, 'Ergebnis', self.valid_ids)
        _rank(rank)
        if a == b:
            raise ValueError('Zwei unterschiedliche DNA-Partner erforderlich.')
        key = pair_key(a, b)
        if key in self.rules:
            raise ValueError('Für dieses DNA-Paar existiert bereits eine Regel.')
        if any(target == result and other_rank != rank for target, other_rank in self.rules.values()):
            raise ValueError('Die Stufe eines Ergebnis-Digimon muss in allen DNA-Regeln gleich sein.')
        self.rules[key] = (result, rank)

    def set(self, a, b, result, rank):
        """Replace a combination or add it if absent."""
        key = pair_key(a, b)
        previous = self.rules.pop(key, None)
        try:
            self.add(a, b, result, rank)
        except Exception:
            if previous is not None:
                self.rules[key] = previous
            raise

    def remove(self, a, b):
        return self.rules.pop(pair_key(a, b), None) is not None

    def resolve(self, a, b):
        """Return (result species ID, result rank), or None for vanilla fallback."""
        return self.rules.get(pair_key(a, b))

    def to_dict(self):
        return {
            'format': FORMAT,
            'version': SCHEMA_VERSION,
            'rules': [
                {'a': a, 'b': b, 'result': result, 'rank': rank}
                for (a, b), (result, rank) in sorted(self.rules.items())
            ],
        }

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + '\n'

    @classmethod
    def from_dict(cls, data, valid_ids=None):
        if not isinstance(data, dict) or data.get('format') != FORMAT:
            raise ValueError('Keine gültige DNA-Moddatei.')
        if type(data.get('version')) is not int or data['version'] != SCHEMA_VERSION:
            raise ValueError('Unbekannte DNA-Moddateiversion.')
        rules = data.get('rules')
        if not isinstance(rules, list):
            raise ValueError('DNA-Regeln müssen eine Liste sein.')
        for rule in rules:
            if not isinstance(rule, dict) or set(rule) != {'a', 'b', 'result', 'rank'}:
                raise ValueError('Ungültiger DNA-Regeleintrag.')
        return cls(rules, valid_ids)

    @classmethod
    def from_json(cls, content, valid_ids=None):
        return cls.from_dict(json.loads(content), valid_ids)
