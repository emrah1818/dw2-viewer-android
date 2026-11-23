"""Digivolve level per Digimon: Studio side of a planned PC-port interface (format 1).

The original game decides in Stg20_DigivolveRuleTbl (src/stag2000/labinfo.c): Rookie from level
11, Champion 21, Ultimate 31, Mega never, the same for every species. The PC port from 1.0 reads
Mods/digivolve_levels.json (host/modconf.c) and announces "digivolve_levels": 1 in its --mod-api
output; for a listed Digimon the lab then uses its own minimum level. Mega stays locked. Older
ports ignore the file.

File format 1 (UTF-8 JSON):
    {"format": 1, "levels": {"<digimon id 1-255>": <minimum level 1-99>, ...}}
Readers must refuse a higher "format" and ignore unknown keys.
"""
import json
from pathlib import Path

FORMAT = 1
FILENAME = 'digivolve_levels.json'
DEFAULT = {0: 11, 1: 21, 2: 31}     # stage (DIGIMNDT rank) -> level the game uses today


def validate(levels):
    if not isinstance(levels, dict):
        raise ValueError('Digitationslevel: Zuordnung Digimon → Level erwartet.')
    out = {}
    for key, value in levels.items():
        try:
            ident = int(key)
        except (TypeError, ValueError):
            raise ValueError(f'Digitationslevel: ungültige Digimon-ID {key!r}.')
        if not 1 <= ident <= 255:
            raise ValueError(f'Digitationslevel: Digimon-ID {ident} außerhalb 1–255.')
        if type(value) is not int or not 1 <= value <= 99:
            raise ValueError(f'Digitationslevel für #{ident:03}: 1–99 erlaubt.')
        out[ident] = value
    return dict(sorted(out.items()))


def dumps(levels):
    return json.dumps({'format': FORMAT, 'levels': {str(k): v for k, v in validate(levels).items()}},
                      indent=1, ensure_ascii=False) + '\n'


def loads(text):
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise ValueError(f'{FILENAME} ist kein gültiges JSON: {exc}')
    if not isinstance(doc, dict) or type(doc.get('format')) is not int:
        raise ValueError(f'{FILENAME}: Feld "format" fehlt.')
    if doc['format'] > FORMAT:
        raise ValueError(f'{FILENAME} hat Format {doc["format"]}; dieses Studio kennt Format {FORMAT}.')
    if doc['format'] < 1:
        raise ValueError(f'{FILENAME}: Format {doc["format"]} ungültig.')
    return validate(doc.get('levels', {}))


def port_supports(port_dir):
    """True only if the port's dw2_mod_api.json announces the interface."""
    try:
        doc = json.loads((Path(port_dir) / 'dw2_mod_api.json').read_text(encoding='utf-8'))
        return int(doc.get('digivolve_levels', 0)) >= FORMAT
    except (OSError, ValueError, TypeError, AttributeError):
        return False
