"""Compose DW2 native-file relocation with private loader and ISO references.

US table offsets: dw2_file_index.py / acemon33 DW2-TT DW2Slus.cs.
Loader contract: decomp main/cd.c Cd_GetFileLba/Cd_GetFileSectors and cdread.c.
Directory records are validated in both endian representations before patching.
Every relocated asset receives its own allocation; donors remain independent.
"""
from dataclasses import dataclass
from pathlib import Path
import json,re,struct
from .dw2_file_index import US

NATIVE=re.compile(rb'[A-KM]\d{3}[A-Z0-9]{4}\.BIN;1')


@dataclass(frozen=True)
class Record:
    offset:int  # logical user-data byte offset of the ISO directory record
    name:str
    lba:int
    size:int


def _basename(entry):return entry.path.replace('\\','/').split('/')[-1].upper()


class NativeLayout:
    def __init__(self,session):
        self.session=session;self.total=session.stamp[0]//session.sector_size
        # SLUS_011.93 starts at LBA 24 in the documented US image. Verify
        # its identity and the complete table instead of scanning for numbers.
        self.exe_lba=24
        with session.source.open('rb') as handle:
            first=session._payload(handle,self.exe_lba)
            if first[:8]!=b'PS-X EXE':raise ValueError('US-DW2-Dateitabelle nicht erkannt (SLUS_011.93).')
            self.count,self.lba_offset,self.size_offset=US
            length=self.size_offset+self.count*2
            self.exe=b''.join(session._payload(handle,self.exe_lba+i) for i in range((length+2047)//2048))
        self.entries=[]
        for i in range(self.count):
            lba=struct.unpack_from('<I',self.exe,self.lba_offset+4*i)[0]
            count=struct.unpack_from('<H',self.exe,self.size_offset+2*i)[0]
            if count and (lba<0 or lba+count>self.total):raise ValueError('Private DW2-Dateitabelle enthält einen Bereich außerhalb des Images.')
            self.entries.append((lba,count))
        # 0x18 is the executable's disc LBA, NOT a private-table file ID.
        from .disc import Disc
        disc=Disc(session.source,sector_size=session.sector_size)
        try:
            executable=[e for e in disc.entries if _basename(e)=='SLUS_011.93' and not e.directory]
            if len(executable)!=1 or executable[0].lba!=self.exe_lba or executable[0].size<length:
                raise ValueError('SLUS_011.93 und Dateitabellenadresse passen nicht zum US-Layout.')
        finally:disc.close()
        self.file_ids=json.loads((Path(__import__('os').environ.get('DW2_DATA_DIR') or Path(__file__).resolve().parents[2]/'data')/'native_file_ids_us.json').read_text())
        self.records=[]
        from .disc import scan_matches
        total_bytes=__import__('os').path.getsize(session.source)
        for match,data,off in scan_matches(session.source,NATIVE):
                start=match.start()+off-33
                if start<0:continue
                sector,within=divmod(start,session.sector_size)
                user=0 if session.sector_size==2048 else 24
                if not user<=within<user+2048:continue
                at=start-off
                if at<0 or at+33>len(data):continue
                n=data[at];name=match.group();size_name=len(name)
                if n<33+size_name or within+n>user+2048 or start+n>total_bytes or data[at+32]!=size_name or data[at+25]&2:continue
                lba=struct.unpack_from('<I',data,at+2)[0];size=struct.unpack_from('<I',data,at+10)[0]
                if struct.unpack_from('>I',data,at+6)[0]!=lba or struct.unpack_from('>I',data,at+14)[0]!=size:continue
                if not size or lba+(size+2047)//2048>self.total:continue
                self.records.append(Record(sector*2048+within-user,name[:-2].decode(),lba,size))
        # Verify PVD; only data-track BIN/ISO is supported by this writer.
        with session.source.open('rb') as handle:
            self.pvd=session._payload(handle,16)
        if self.pvd[:7]!=b'\x01CD001\x01':raise ValueError('ISO9660-Volumendeskriptor nicht erkannt.')
        size=struct.unpack_from('<I',self.pvd,80)[0]
        if struct.unpack_from('>I',self.pvd,84)[0]!=size or not 0<size<=self.total:raise ValueError('Ungültige ISO9660-Volumegröße.')

    def target(self,entry):
        count=(entry.size+2047)//2048
        matches=[i for i,(lba,n) in enumerate(self.entries) if lba==entry.lba and n==count]
        # Documented US file IDs disambiguate legitimately shared allocations.
        records=[r for r in self.records if (r.name,r.lba,r.size)==(_basename(entry),entry.lba,entry.size)]
        if not records:raise ValueError('Verifizierter ISO-Dateieintrag fehlt: '+_basename(entry))
        known=self.file_ids.get(_basename(entry))
        if known in matches:index=known
        elif known is not None:
            raise ValueError('Dokumentierte DW2-Datei-ID passt nicht zum ISO-Dateieintrag: '+_basename(entry))
        elif len(matches)==1:index=matches[0]
        else:
            raise ValueError('DW2-Datei-ID ist für diesen Dateiplatz nicht eindeutig: '+_basename(entry))
        return index,records

    def shared(self,entry):
        count=(entry.size+2047)//2048
        return sum(lba==entry.lba and n==count for lba,n in self.entries)>1 or any(r.lba==entry.lba and r.name!=_basename(entry) for r in self.records)


def layout(session):
    session._check_source()
    cached=getattr(session,'_native_layout',None)
    if cached is None:session._native_layout=cached=NativeLayout(session)
    return cached


def can_relocate(session,entry):
    layout(session).target(entry)


def is_shared(session,entry):
    if not re.fullmatch(r'[A-KM]\d{3}[A-Z0-9]{4}\.BIN',_basename(entry)):return False
    try:return layout(session).shared(entry)
    except (ValueError,OSError):return False  # ordinary fixed-size workflow


@dataclass(frozen=True)
class Result:
    sectors:dict
    append:tuple
    total:int
    mapped:dict


def compose(session,sectors):
    edits=[e for e in session.edits.values() if e.relocate]
    if not edits:return Result(sectors,(),session.stamp[0]//session.sector_size,{})
    info=layout(session);sectors=dict(sectors);append=[];cursor=info.total;mapped={};writes={}
    with session.source.open('rb') as handle:
        def patch(offset,data):
            for i,value in enumerate(data):
                pos=offset+i
                if pos in writes and writes[pos]!=value:raise ValueError('Widersprüchliche Dateitabellenänderungen.')
                writes[pos]=value
        for edit in edits:
            from .disc import Entry
            entry=Entry(edit.path,edit.lba,len(edit.original),False);index,records=info.target(entry)
            count=(len(edit.replacement)+2047)//2048
            if not 1<=count<=65535:raise ValueError('Ersatz überschreitet den nativen 16-Bit-Sektorzähler.')
            new_lba=cursor
            for i in range(count):append.append((cursor+i,edit.replacement[i*2048:(i+1)*2048].ljust(2048,b'\0'),edit.lba))
            cursor+=count
            patch(info.exe_lba*2048+info.lba_offset+4*index,struct.pack('<I',new_lba))
            patch(info.exe_lba*2048+info.size_offset+2*index,struct.pack('<H',count))
            for record in records:
                patch(record.offset+2,struct.pack('<I',new_lba)+struct.pack('>I',new_lba))
                patch(record.offset+10,struct.pack('<I',len(edit.replacement))+struct.pack('>I',len(edit.replacement)))
            mapped[(edit.path,edit.lba)]=(new_lba,len(edit.replacement),index)
        if cursor!=info.total:
            if session.sector_size==2352 and cursor+150>=100*60*75:raise ValueError('RAW-MSF-Sektoradresse überschreitet das CD-Adressformat.')
            for lba in range(16,min(80,info.total)):
                raw=session._payload(handle,lba)
                if raw[1:6]!=b'CD001':break
                if raw[0] in (1,2):patch(lba*2048+80,struct.pack('<I',cursor)+struct.pack('>I',cursor))
                if raw[0]==255:break
        # User payload edits may coexist, but cannot overlap metadata patches.
        for pos,value in writes.items():
            lba,offset=divmod(pos,2048)
            if lba not in sectors:sectors[lba]=session._payload(handle,lba)
            original=session._payload(handle,lba)
            if sectors[lba][offset]!=original[offset] and sectors[lba][offset]!=value:raise ValueError('Dateitabellen-Patch überlappt eine andere Änderung.')
            data=bytearray(sectors[lba]);data[offset]=value;sectors[lba]=bytes(data)
    return Result(sectors,tuple(append),cursor,mapped)
