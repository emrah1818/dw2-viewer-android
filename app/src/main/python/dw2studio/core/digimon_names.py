"""Fixed-size US MODELDT name editing; no text search or image relocation.

Format evidence: Wyrelade's Digi_GetDefaultName/DigiData and RemyRM's
MODELDT0 reader. See NAMEN_FORMAT.md for paths, offsets and scope.
"""
from dataclasses import dataclass
from pathlib import PurePosixPath
import struct
from .disc import Entry

MAX_NAME_LENGTH = 13  # gamedata.c copies 14 bytes, including the FF terminator.
_ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
DECODE = dict(enumerate(_ALPHABET))
DECODE.update({0x42:'&',0x44:'?',0x45:'!',0x46:'/',0x49:'-',0x54:',',
               0x55:'.',0x56:"'",0x59:':',0x5B:'+',0xFD:' '})
ENCODE = {char:value for value,char in DECODE.items()}
FILE_INDEX = {'MODELDT0.BIN':3257,'MODELDT1.BIN':3258,'MODELDT2.BIN':3259}


def basename(path):
    return PurePosixPath(path.replace('\\','/')).name.upper().split(';')[0]


def table_name(identifier):
    if type(identifier) is not int or not 1 <= identifier <= 32767:
        raise ValueError('Ungültige Digimon-ID.')
    index = 0 if identifier < 300 else 2 if 400 <= identifier <= 500 else 1
    return f'MODELDT{index}.BIN'


def encode_name(text):
    if not isinstance(text,str) or not text.strip():
        raise ValueError('Der Name darf nicht leer sein.')
    if text != text.strip():
        raise ValueError('Leerzeichen am Anfang oder Ende bitte entfernen.')
    if len(text) > MAX_NAME_LENGTH:
        raise ValueError(f'Höchstens {MAX_NAME_LENGTH} Zeichen: Das Spiel kopiert Namen in einen 14-Byte-Puffer.')
    unsupported = sorted(set(text)-ENCODE.keys())
    if unsupported:
        raise ValueError('Im US-Zeichensatz nicht unterstützt: '+', '.join(repr(c) for c in unsupported)+'. Bitte A–Z, a–z, 0–9, Leerzeichen oder & ? ! / - , . \' : + verwenden.')
    return bytes(ENCODE[c] for c in text)


def decode_name(data):
    try:return ''.join(DECODE[b] for b in data)
    except KeyError as exc:
        raise ValueError(f'Unbekannter US-Namenscode 0x{exc.args[0]:02X}; keine automatische Ersetzung.') from exc


@dataclass(frozen=True)
class NameRecord:
    identifier: int
    row: int
    pointer: int
    text: str
    raw: bytes


class NameTable:
    def __init__(self,data):
        self.data = bytes(data)
        if not 48 <= len(data) <= 4*1024*1024:raise ValueError('Ungültige MODELDT-Dateigröße.')
        self.records_start,self.pool_end = struct.unpack_from('<II',data)
        if not (8 <= self.pool_end <= self.records_start <= len(data)-40) or self.pool_end%4 or self.records_start%4:
            raise ValueError('MODELDT-Kopf/Blockgrenzen nicht erkannt.')
        self.records = {};self.order=[];cursor=self.records_start
        while cursor+40 <= len(data):
            pointer,packed=struct.unpack_from('<IH',data,cursor);identifier=packed>>1
            if identifier == 0:
                # A complete zero row ends the documented 40-byte record list.
                if data[cursor:cursor+40] != bytes(40):raise ValueError('Ungültiger MODELDT-Endeintrag.')
                break
            if identifier in self.records:raise ValueError('Doppelte Digimon-ID in MODELDT.')
            if not 8 <= pointer < self.pool_end or pointer%4:raise ValueError('Namenszeiger außerhalb des Namensblocks oder falsch ausgerichtet.')
            end=data.find(b'\xff',pointer,self.pool_end)
            if end<0 or end-pointer>MAX_NAME_LENGTH:raise ValueError('Name ohne gültigen FF-Abschluss oder länger als 13 Bytes.')
            raw=bytes(data[pointer:end]);record=NameRecord(identifier,cursor,pointer,decode_name(raw),raw)
            self.records[identifier]=record;self.order.append(record);cursor+=40
            if len(self.records)>4096:raise ValueError('Zu viele MODELDT-Einträge.')
        else:raise ValueError('MODELDT-Abschluss fehlt.')
        if not self.records:raise ValueError('Keine MODELDT-Namenseinträge.')
        # Only zero alignment padding may be reclaimed. No opaque data is reused.
        occupied=bytearray(self.pool_end-8)
        spans=sorted({(r.pointer,r.pointer+len(r.raw)+1) for r in self.order})
        previous=8
        for start,end in spans:
            if start<previous:raise ValueError('Überlappende Namen werden nicht automatisch umgeschrieben.')
            occupied[start-8:end-8]=b'\1'*(end-start);previous=end
        if any(byte and not used for byte,used in zip(data[8:self.pool_end],occupied)):
            raise ValueError('Unbekannte Daten im Namensblock; Umbenennen gesperrt.')

    def record(self,identifier):
        try:return self.records[identifier]
        except KeyError as exc:raise ValueError(f'Digimon-ID {identifier} fehlt in der nativen Namenstabelle.') from exc

    def renamed(self,identifier,text):
        new=encode_name(text);record=self.record(identifier)
        if new == record.raw:return self.data
        out=bytearray(self.data)
        pointers=sorted({r.pointer for r in self.order})
        following=min((p for p in pointers if p>record.pointer),default=self.pool_end)
        aliases=[r for r in self.order if r.pointer==record.pointer]
        if len(aliases)==1 and len(new)+1<=following-record.pointer:
            # Keep all pointers and other strings byte-identical when the slot fits.
            out[record.pointer:following]=(new+b'\xff').ljust(following-record.pointer,b'\0')
        else:
            # Repack within the EXISTING pool only. Identical strings may share
            # aligned offsets; every changed name pointer is updated explicitly.
            pool=bytearray(self.pool_end-8);interned={};used=0
            for row in self.order:
                raw=new if row.identifier==identifier else row.raw
                if raw not in interned:
                    size=(len(raw)+1+3)//4*4
                    if used+size>len(pool):raise ValueError('Der vorhandene Namensspeicher reicht nicht aus. Einen kürzeren Namen wählen oder zuvor einen anderen Namen kürzen.')
                    interned[raw]=8+used;pool[used:used+len(raw)+1]=raw+b'\xff';used+=size
                struct.pack_into('<I',out,row.row,interned[raw])
            out[8:self.pool_end]=pool
        result=bytes(out);check=NameTable(result)
        if len(result)!=len(self.data) or check.records.keys()!=self.records.keys():raise ValueError('Namensprüfung fehlgeschlagen.')
        for row in self.order:
            if check.record(row.identifier).raw != (new if row.identifier==identifier else row.raw):raise ValueError('Andere Namen wurden unerwartet verändert.')
            if result[row.row+4:row.row+40]!=self.data[row.row+4:row.row+40]:raise ValueError('Modell-/Animationszuordnung verändert.')
        if result[self.pool_end:self.records_start]!=self.data[self.pool_end:self.records_start]:raise ValueError('Effektdaten verändert.')
        return result


def discover_tables(session,entries):
    """Use actual directory entries; US private index is a checked fallback."""
    result=[]
    for name in FILE_INDEX:
        aliases=[e for e in entries if not e.directory and basename(e.path)==name]
        physical={}
        for e in aliases:
            key=(e.lba,e.size)
            if key not in physical or e.path.upper().startswith('AAA/'):physical[key]=e
        if len(physical)>1:raise ValueError(f'{name} ist mehrfach an verschiedenen Positionen vorhanden; keine eindeutige Zuordnung.')
        result.extend(physical.values())
    missing=[name for name in FILE_INDEX if not any(basename(e.path)==name for e in result)]
    executables={(e.lba,e.size):e for e in entries if not e.directory and basename(e.path)=='SLUS_011.93'}
    if missing and len(executables)==1:
        executable=next(iter(executables.values()));data=session.current(executable)
        count=3675;lba_base=0x33F94;size_base=0x37900
        if not data.startswith(b'PS-X EXE') or len(data)<size_base+count*2:
            raise ValueError('US-Dateitabelle in SLUS_011.93 nicht erkannt.')
        total=session.stamp[0]//session.sector_size
        # Validate every allocation before trusting any hard-coded index position.
        allocations=[]
        for i in range(count):
            lba=struct.unpack_from('<I',data,lba_base+4*i)[0];sectors=struct.unpack_from('<H',data,size_base+2*i)[0]
            if sectors and (lba>=total or sectors>total-lba):raise ValueError('Ungültige US-Dateitabelle: Bereich außerhalb des Images.')
            allocations.append((lba,sectors))
        for name in missing:
            lba,sectors=allocations[FILE_INDEX[name]]
            if not sectors:continue
            candidate=Entry('INTERNAL/'+name,lba,sectors*2048,False)
            NameTable(session.current(candidate))  # Never infer a writable file from an index alone.
            result.append(candidate)
    return result


class NameRepository:
    def __init__(self,session,entries):
        self.session=session;self.entries=list(discover_tables(session,entries))
        # Keep discovered allocations addressable by the existing .dw2mod loader.
        known={(e.path,e.lba,e.size) for e in entries}
        for e in self.entries:
            if (e.path,e.lba,e.size) not in known:entries.append(e)

    def lookup(self,identifier):
        name=table_name(identifier)
        found=[e for e in self.entries if basename(e.path)==name]
        if len(found)!=1:raise ValueError(f'{name} wurde im Spiel-Image nicht eindeutig gefunden. Es wird kein Name auf Verdacht ersetzt.')
        entry=found[0];table=NameTable(self.session.current(entry));table.record(identifier)
        return entry,table

    def names(self):
        result={}
        for entry in self.entries:
            table=NameTable(self.session.current(entry))
            for identifier,row in table.records.items():
                if table_name(identifier)!=basename(entry.path):raise ValueError('Digimon-ID gehört nicht zur gefundenen MODELDT-Datei.')
                if row.text:result[identifier]=row.text
        return result

    def rename(self,identifier,text):
        entry,table=self.lookup(identifier);before=table.record(identifier).text
        changed=table.renamed(identifier,text)
        original=self.session.original(entry);original_table=NameTable(original);updated=NameTable(changed)
        if updated.records.keys()==original_table.records.keys() and all(updated.record(i).raw==r.raw for i,r in original_table.records.items()):
            # Removing all name edits should also undo any earlier pool repack,
            # while preserving independent changes outside name bytes/pointers.
            restored=bytearray(changed)
            if (updated.pool_end,updated.records_start)==(original_table.pool_end,original_table.records_start):
                restored[8:updated.pool_end]=original[8:updated.pool_end]
                for row in original_table.order:struct.pack_into('<I',restored,row.row,row.pointer)
                if bytes(restored)==original:changed=original
        if changed!=table.data:self.session.stage(entry,changed,f'Name #{identifier:03}: {before} → {text}')
        return changed!=table.data

    def original_name(self,identifier):
        entry,_=self.lookup(identifier)
        return NameTable(self.session.original(entry)).record(identifier).text
