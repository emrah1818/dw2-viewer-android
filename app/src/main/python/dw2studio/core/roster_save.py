"""US DW2 roster edits in SC saves and raw PS1 memorycards; no RAM scanning.

Source contracts: stag1100/card.c, Stg11SaveList, GameState and DigiRosterEntry.
SC header already belongs to the 0x4000 save; NEVER skip 128 bytes on a card.
Checksum ends with XOR of the version word at 0x3FFC, not the previous word.
"""
from dataclasses import dataclass
from pathlib import Path
import copy, os, struct, tempfile
from .digimon_names import DECODE

SAVE_SIZE=0x4000
CARD_SIZE=0x20000
GAME_ID=b'SLUS-01193'
SAVE_NAME=b'BASLUS-01193 DMW2'  # Stg11_SaveFileName; transfer files are different.
ROSTER=0x200+0x0C+0xE4
STRIDE=0x5C
SLOT_SIZE=0x1058
FIELDS={'exp':(0x10,'i',0,2147483647), 'max_hp':(0x14,'h',1,32767),
        'hp':(0x16,'h',0,32767), 'max_mp':(0x18,'h',0,32767),
        'mp':(0x1A,'h',0,32767), 'attack':(0x1C,'h',0,32767),
        'defense':(0x1E,'h',0,32767), 'speed':(0x20,'h',0,32767),
        'parent1':(0x47,'B',0,255), 'parent2':(0x48,'B',0,255)}


def checksum(data):
    if len(data)!=SAVE_SIZE:raise ValueError('Ein DW2-Save benötigt 16384 Bytes.')
    total=0
    for offset in range(0,0x3FFC,4):
        a,b=struct.unpack_from('<HH',data,offset)
        total=((total^a)+b)&0xFFFF
    return total^struct.unpack_from('<H',data,0x3FFC)[0]


def validate_save(data):
    if len(data)!=SAVE_SIZE or data[:2]!=b'SC' or data[3]!=2:
        raise ValueError('Kein vollständiger DW2-SC-Spielstand mit zwei Blöcken.')
    if struct.unpack_from('<H',data,0x3FFC)[0]!=0x102:
        raise ValueError('US-DW2-Spielstandversion 0x0102 nicht erkannt.')
    if checksum(data)!=struct.unpack_from('<H',data,0x3FFE)[0]:
        raise ValueError('Spielstand-Prüfsumme stimmt nicht. Keine automatische Reparatur unbekannter Daten.')


def next_level_exp(level, maximum, current):
    if level>=maximum:return 99999999
    if level>=62:
        value=826540+(level-61)*65535
    elif level>=31:
        x=level-30;value=x*x*x*20+x*x*60+x*4580+31080
    elif level>=21:
        x=level-20;value=x*x*x*10+x*x*30+x*1220+5880
    elif level>=11:
        x=level-10;value=x*x*x*10//3+x*x*10+x*107+480
    else:
        x=level;value=x*x*x//3+x*x+x*5
    return max(0,value-current)


@dataclass(frozen=True)
class SaveRef:
    key:int
    label:str
    segments:tuple


class RosterSave:
    def __init__(self, path):
        self.path=Path(path).resolve()
        self.original=self.path.read_bytes()
        self.raw=bytearray(self.original)
        self.refs=[]
        if len(self.raw)==SAVE_SIZE and self.raw[:2]==b'SC':
            self.refs=[SaveRef(0,self.path.name,((0,SAVE_SIZE),))]
        elif len(self.raw)==SAVE_SIZE+128 and self.raw[128:130]==b'SC' and self.raw[12:32].rstrip(b'\0')==SAVE_NAME:
            self.refs=[SaveRef(0,self.path.name,((128,SAVE_SIZE),))]
        elif len(self.raw)==CARD_SIZE and self.raw[:2]==b'MC':
            occupied={}
            for first in range(15):
                rec=self.directory(first)
                if rec[0]!=0x51:continue
                chain=self.chain(first)
                for slot in chain:
                    if slot in occupied:raise ValueError('Memorycard-Dateiketten überlappen sich.')
                    occupied[slot]=first
                if rec[12:32].rstrip(b'\0')!=SAVE_NAME:continue
                if len(chain)!=2 or struct.unpack_from('<I',rec,4)[0]!=SAVE_SIZE:
                    raise ValueError('DW2-Datei benötigt eine gültige Zwei-Block-Kette.')
                self.refs.append(SaveRef(first,f'Memorycard-Datei {first+1}: '+rec[12:32].rstrip(b'\0').decode('ascii','replace'),
                    tuple(((s+1)*8192,8192) for s in chain)))
        else:raise ValueError('Unterstützt: RAW-Memorycard .mcd/.mcr (128 KiB), DW2-SC-Save (16 KiB) und .mcs (128-Byte-Kopf + SC-Save). Kein Savestate.')
        if not self.refs:raise ValueError('Kein US-DW2-Spielstand auf dieser Memorycard gefunden.')
        for ref in self.refs:validate_save(self.payload(ref.key))

    def directory(self, slot):
        rec=self.raw[(slot+1)*128:(slot+2)*128]
        check=0
        for value in rec[:127]:check^=value
        if check!=rec[127]:raise ValueError(f'Memorycard-Verzeichnisprüfsumme in Block {slot+1} ungültig.')
        return rec

    def chain(self, first):
        chain=[];slot=first
        while True:
            if slot in chain or not 0<=slot<15:raise ValueError('Memorycard-Verknüpfung zirkulär/ungültig.')
            rec=self.directory(slot)
            if rec[0] not in ((0x51,) if not chain else (0x52,0x53)):
                raise ValueError('Memorycard-Dateikettenstatus ungültig.')
            chain.append(slot)
            nxt=struct.unpack_from('<H',rec,8)[0]
            if nxt==0xFFFF:
                if len(chain)>1 and rec[0]!=0x53:raise ValueError('Letzter Memorycard-Block falsch markiert.')
                return chain
            if rec[0]==0x53:raise ValueError('Letzter Memorycard-Block verweist weiter.')
            slot=nxt

    def clone(self):return copy.deepcopy(self)

    def ref(self, key):
        return next(r for r in self.refs if r.key==key)

    def payload(self,key,original=False):
        data=self.original if original else self.raw
        return b''.join(data[start:start+size] for start,size in self.ref(key).segments)

    def put_payload(self,key,data):
        offset=0
        for start,size in self.ref(key).segments:
            self.raw[start:start+size]=data[offset:offset+size];offset+=size

    def record(self,key,original=False):
        file,slot,row=key
        if not (0<=slot<3 and 0<=row<36):raise ValueError('Ungültiger Spielstand-/Digimonplatz.')
        data=self.payload(file,original)
        if not struct.unpack_from('<I',data,0x200+slot*4)[0]:raise ValueError('Dieser Spielstandplatz ist leer.')
        offset=ROSTER+slot*SLOT_SIZE+row*STRIDE
        state,identifier=data[offset:offset+2]
        if state not in range(1,6) or identifier==0:raise ValueError('Kein belegter Digimonplatz.')
        raw_name=data[offset+0x4C:offset+0x5A].split(b'\xff',1)[0]
        result={'key':key,'id':identifier,'level':data[offset+13],'max_level':data[offset+15],
                'name':''.join(DECODE.get(c,f'⟨{c:02X}⟩') for c in raw_name)}
        result.update({name:struct.unpack_from('<'+fmt,data,offset+at)[0] for name,(at,fmt,_,_) in FIELDS.items()})
        return result

    def records(self, identifier):
        rows=[]
        for ref in self.refs:
            for slot in range(3):
                for row in range(36):
                    try:r=self.record((ref.key,slot,row))
                    except ValueError:continue
                    if r['id']==identifier:rows.append(r)
        return rows

    def change(self,key,fields):
        record=self.record(key)
        values={**record,**fields}
        for name,value in fields.items():
            if name not in FIELDS:raise ValueError('Unbekanntes Spielstandfeld.')
            _,_,lo,hi=FIELDS[name]
            if type(value) is not int or not lo<=value<=hi:raise ValueError(f'{name}: benötigt {lo} bis {hi}.')
        if values['hp']>values['max_hp'] or values['mp']>values['max_mp']:
            raise ValueError('Aktuelle HP/MP dürfen ihre Maximalwerte nicht überschreiten.')
        data=bytearray(self.payload(key[0]));offset=ROSTER+key[1]*SLOT_SIZE+key[2]*STRIDE
        for name,value in fields.items():
            at,fmt,_,_=FIELDS[name];struct.pack_into('<'+fmt,data,offset+at,value)
        self.put_payload(key[0],data)

    def restore(self,key):
        source=self.payload(key[0],True)
        data=bytearray(self.payload(key[0]));offset=ROSTER+key[1]*SLOT_SIZE+key[2]*STRIDE
        data[offset:offset+STRIDE]=source[offset:offset+STRIDE]
        self.put_payload(key[0],data)

    @property
    def dirty(self):return self.raw!=self.original

    def output(self):
        result=self.clone()
        for ref in self.refs:
            data=bytearray(result.payload(ref.key))
            if data==self.payload(ref.key,True):continue
            struct.pack_into('<H',data,0x3FFE,checksum(data))
            validate_save(data);result.put_payload(ref.key,data)
        return bytes(result.raw)

    def export(self,path):
        target=Path(path).resolve()
        if target==self.path or target.exists():raise ValueError('Bitte einen neuen Dateinamen für die bearbeitete Memorycard/den Spielstand wählen.')
        if self.path.read_bytes()!=self.original:raise ValueError('Die Quelldatei wurde außerhalb des Viewers verändert. Bitte neu öffnen.')
        data=self.output();target.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(dir=target.parent,prefix=target.name+'.',suffix='.partial')
        temporary=Path(name)
        try:
            with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
            # Windows rename refuses an existing destination, including on
            # removable filesystems without hardlinks. POSIX uses no-clobber link.
            from .safe_publish import publish_new
            publish_new(temporary,target)
        finally:temporary.unlink(missing_ok=True)
        return target
