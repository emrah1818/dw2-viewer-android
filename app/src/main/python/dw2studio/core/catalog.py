"""Catalog inferred from filenames; never assume filenames encode stats or model geometry."""
import re
from dataclasses import dataclass, field
from collections import defaultdict
import json
from pathlib import Path
from functools import lru_cache

@lru_cache(maxsize=1)
def _names():
    return {entry["id"]:entry["name"] for entry in json.loads((Path(__import__("os").environ.get("DW2_DATA_DIR") or Path(__file__).resolve().parents[2]/"data")/"digimon_names.json").read_text(encoding="utf-8"))}

KNOWN={"AGUM":"Agumon","BETA":"Betamon","GREY":"Greymon","DEVI":"Devimon (unverified)","AIRD":"Airdramon","TYRA":"Tyrannomon","MERA":"Meramon","SEAD":"Seadramon","NUME":"Numemon","MTGR":"MetalGreymon (unverified)"}
MODEL_NAME=re.compile(r"^M(?P<id>\d{3})(?P<code>[A-Z0-9]{4})\.BIN$",re.I)
@dataclass
class DigimonCandidate:
    id: int
    code: str
    name: str
    files: list=field(default_factory=list)
    verified_name: bool=False

def build_catalog(entries):
    found={}
    # Cheat DMC IDs correspond to the numeric model-file IDs, including gaps.
    cheat_names=_names()
    for entry in entries:
        filename=entry.path.replace('\\','/').rsplit('/',1)[-1].upper()
        m=MODEL_NAME.fullmatch(filename)
        if not m:continue
        identifier=int(m.group('id'));code=m.group('code')
        key=(identifier,code)
        if key not in found:
            found[key]=DigimonCandidate(identifier,code,cheat_names.get(identifier,KNOWN.get(code,f'Unbekannt ({code})')),[],identifier in cheat_names)
        found[key].files.append(entry)
    return sorted(found.values(),key=lambda x:(x.id,x.code))
