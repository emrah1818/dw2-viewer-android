"""Composable image edits and verified native relocations with atomic commit."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from .psx_patch import validate_form1_ecc, regenerate_form1


@dataclass(frozen=True)
class FileEdit:
    path: str
    lba: int
    original: bytes
    replacement: bytes
    label: str
    relocate: bool = False


class EditSession:
    def __init__(self, source, sector_size):
        self.source = Path(source).resolve()
        if sector_size not in (2048, 2352):
            raise ValueError('Nur 2048-ISO oder 2352-RAW-BIN unterstützt.')
        self.sector_size = sector_size
        self.stamp = self._stamp()
        if self.stamp[0] % sector_size:
            raise ValueError('Unvollständiges Image.')
        self.edits = {}

    def _stamp(self):
        st = self.source.stat()
        return st.st_size, st.st_mtime_ns, st.st_dev, st.st_ino

    def _check_source(self):
        if self._stamp() != self.stamp:
            raise ValueError('Das Quell-Image wurde außerhalb dieser Sitzung verändert. Bitte neu öffnen.')

    def _payload(self, handle, index):
        if type(index) is not int or index < 0 or (index+1)*self.sector_size > self.stamp[0]:
            raise ValueError('Datei liegt außerhalb des Images.')
        handle.seek(index*self.sector_size)
        raw = handle.read(self.sector_size)
        if self.sector_size == 2048:
            return raw
        if not validate_form1_ecc(raw):
            raise ValueError(f'Sektor {index}: kein gültiger Mode-2-Form-1-Sektor (EDC/ECC).')
        return raw[24:2072]

    def original(self, entry):
        self._check_source()
        if entry.directory or type(entry.size) is not int or entry.size <= 0:
            raise ValueError('Ungültiger Dateieintrag.')
        with self.source.open('rb') as handle:
            return b''.join(self._payload(handle, entry.lba+i)
                            for i in range((entry.size+2047)//2048))[:entry.size]

    def current(self, entry):
        self._check_source()
        edit = self.edits.get((entry.path, entry.lba))
        return edit.replacement if edit else self.original(entry)

    def stage(self, entry, data, label='Datei ersetzt', *, relocate=False):
        data = bytes(data)
        previous = self.edits.get((entry.path,entry.lba))
        relocate=relocate or bool(previous and previous.relocate)
        if not relocate:
            from .native_relocation import is_shared
            relocate=is_shared(self,entry)
        if relocate:
            from .native_relocation import can_relocate
            if not data:raise ValueError('Leere Ersatzdatei.')
            can_relocate(self,entry)
        elif len(data) != entry.size:
            raise ValueError(f'Ersatz muss exakt {entry.size} Bytes haben (erhalten: {len(data)}).')
        original = self.original(entry)
        start, end = entry.lba*2048, entry.lba*2048+entry.size
        key = (entry.path, entry.lba)
        for other_key, other in self.edits.items():
            a, b = other.lba*2048, other.lba*2048+len(other.original)
            if other_key != key and max(a, start) < min(b, end) and not (relocate and other.relocate):
                raise ValueError('Überlappende Dateien können nicht getrennt ersetzt werden.')
        if data == original:
            self.edits.pop(key, None)
        else:
            self.edits[key] = FileEdit(entry.path, entry.lba, original, data,
                                       (previous.label+'; '+label) if previous and label not in previous.label else label,relocate)
        return self.edits.get(key)

    def remove(self, key):
        self.edits.pop(key, None)

    def _sectors(self):
        self._check_source()
        sectors = {}
        with self.source.open('rb') as handle:
            for edit in self.edits.values():
                count = (len(edit.original)+2047)//2048
                originals = [self._payload(handle, edit.lba+i) for i in range(count)]
                if b''.join(originals)[:len(edit.original)] != edit.original:
                    raise ValueError(f'Originaldaten geändert: {edit.path}')
                if edit.relocate:continue
                for i, original in enumerate(originals):
                    begin = i*2048
                    chunk = edit.replacement[begin:begin+2048]
                    if original[:len(chunk)] == chunk:
                        continue
                    index = edit.lba+i
                    updated = bytearray(sectors.get(index, original))
                    updated[:len(chunk)] = chunk
                    sectors[index] = bytes(updated)
        return sectors

    def save(self, destination, *, overwrite=False):
        """Atomically publish a verified full copy. Same-source writes require a backup."""
        destination = Path(destination).resolve()
        if not self.edits:
            raise ValueError('Keine Änderungen vorgemerkt.')
        if destination.exists() and not overwrite:
            raise FileExistsError('Zieldatei existiert bereits. Überschreiben bestätigen.')
        if destination.exists() and not destination.is_file():
            raise ValueError('Ziel ist keine Datei.')
        from .native_relocation import compose
        composed=compose(self,self._sectors());replacements=composed.sectors
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=destination.name+'.', suffix='.partial', dir=destination.parent)
        temporary = Path(temporary_name)
        backup = None
        destination_stamp = destination.stat() if destination.exists() else None
        try:
            with os.fdopen(fd, 'w+b') as out, self.source.open('rb') as inp:
                shutil.copyfileobj(inp, out, 4*1024*1024)
                for index, payload in sorted(replacements.items()):
                    if self.sector_size == 2352:
                        inp.seek(index*2352)
                        raw = bytearray(inp.read(2352))
                        raw[24:2072] = payload
                        block = regenerate_form1(raw)
                    else:
                        block = payload
                    out.seek(index*self.sector_size)
                    out.write(block)
                for index,payload,template_lba in composed.append:
                    if self.sector_size==2048:block=payload
                    else:
                        inp.seek(template_lba*2352);raw=bytearray(inp.read(2352))
                        if not validate_form1_ecc(raw):raise ValueError('Kein gültiger Mode-2-Form-1-Referenzsektor für größere Ersatzdatei.')
                        minutes,remaining=divmod(index+150,75*60);seconds,frames=divmod(remaining,75)
                        def bcd(v):return ((v//10)<<4)|(v%10)
                        raw[12:16]=bytes([bcd(minutes),bcd(seconds),bcd(frames),2]);raw[24:2072]=payload
                        block=regenerate_form1(raw)
                    out.seek(index*self.sector_size);out.write(block)
                out.flush()
                os.fsync(out.fileno())
                if out.seek(0, 2) != composed.total*self.sector_size:
                    raise IOError('Image-Größe stimmt nicht mit dem Schreibplan überein.')
                for index, payload in replacements.items():
                    out.seek(index*self.sector_size)
                    raw = out.read(self.sector_size)
                    actual = raw if self.sector_size == 2048 else raw[24:2072]
                    if actual != payload or (self.sector_size == 2352 and not validate_form1_ecc(raw)):
                        raise IOError(f'Sektor {index}: Schreibprüfung fehlgeschlagen.')
                for index,payload,_ in composed.append:
                    out.seek(index*self.sector_size);raw=out.read(self.sector_size)
                    actual=raw if self.sector_size==2048 else raw[24:2072]
                    if actual!=payload or (self.sector_size==2352 and not validate_form1_ecc(raw)):raise IOError(f'Neuer Sektor {index}: Schreibprüfung fehlgeschlagen.')
            if composed.mapped:
                # Independently parse the new tables/directory references.
                from .native_relocation import NativeLayout
                from .disc import Entry
                check_session=EditSession(temporary,self.sector_size);layout=NativeLayout(check_session)
                for (name,_),(lba,size,file_id) in composed.mapped.items():
                    entry=Entry(name,lba,size,False);found,_=layout.target(entry)
                    if found!=file_id:raise IOError('Dateiumleitung wurde nicht korrekt geschrieben.')
                    edit=next(e for e in self.edits.values() if e.path==name and e.relocate)
                    if check_session.current(entry)!=edit.replacement:raise IOError('Verlagerte Datei stimmt nach dem Schreiben nicht überein.')
            self._check_source()
            if destination_stamp is None:
                if destination.exists():
                    raise FileExistsError('Zieldatei wurde inzwischen angelegt.')
            else:
                now = destination.stat()
                if (now.st_mtime_ns, now.st_size, now.st_ino) != (destination_stamp.st_mtime_ns, destination_stamp.st_size, destination_stamp.st_ino):
                    raise ValueError('Zieldatei wurde inzwischen verändert.')
            if destination == self.source:
                # A unique backup prevents accidentally overwriting an earlier original.
                backup = destination.with_name(destination.name+'.backup-'+next(tempfile._get_candidate_names()))
                with self.source.open('rb') as inp, backup.open('xb') as out:
                    shutil.copyfileobj(inp, out, 4*1024*1024)
                    out.flush()
                    os.fsync(out.fileno())
                self._check_source()
            if overwrite:
                os.replace(temporary, destination)
            else:
                # Atomic create-only publication: a racing new file is never overwritten.
                os.link(temporary, destination)
                temporary.unlink()
            self.last_relocations=composed.mapped
            return destination, backup
        finally:
            temporary.unlink(missing_ok=True)

    def export_project(self, destination):
        """Portable staged native bytes; reopening validates the original model bytes."""
        self._check_source()
        manifest = {'format':'DW2 native edits 1', 'sector_size':self.sector_size,
                    'source_size':self.stamp[0], 'files':[]}
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
            for i, edit in enumerate(self.edits.values()):
                manifest['files'].append({'path':edit.path, 'lba':edit.lba,
                    'size':len(edit.original), 'sha256':hashlib.sha256(edit.original).hexdigest(),
                    'data':f'{i}.bin', 'label':edit.label,'relocate':edit.relocate,'replacement_size':len(edit.replacement)})
                archive.writestr(f'{i}.bin', edit.replacement)
            archive.writestr('project.json', json.dumps(manifest, ensure_ascii=False))

    def import_project(self, source, entries):
        known = {(e.path,e.lba,e.size):e for e in entries if not e.directory}
        pending = []
        with zipfile.ZipFile(source) as archive:
            if archive.getinfo('project.json').file_size > 4*1024*1024:
                raise ValueError('Projektmanifest zu groß.')
            manifest = json.loads(archive.read('project.json'))
            if manifest.get('format') != 'DW2 native edits 1' or manifest.get('sector_size') != self.sector_size or manifest.get('source_size') != self.stamp[0]:
                raise ValueError('Projekt passt nicht zum geöffneten Image.')
            for item in manifest['files']:
                entry = known.get((item['path'],item['lba'],item['size']))
                if entry is None or hashlib.sha256(self.original(entry)).hexdigest() != item['sha256']:
                    raise ValueError('Originaldatei passt nicht zum Projekt: '+item['path'])
                relocate=item.get('relocate',False)
                if type(relocate)is not bool:raise ValueError('Ungültiger Projektmodus.')
                expected=item.get('replacement_size',entry.size)
                if type(expected)is not int or expected<=0 or (not relocate and expected!=entry.size) or expected>65535*2048 or archive.getinfo(item['data']).file_size != expected:
                    raise ValueError('Ungültige Ersatzdateigröße im Projekt.')
                pending.append((entry, archive.read(item['data']), item['label'],relocate))
        before = self.edits.copy()
        try:
            for entry, data, label, relocate in pending:
                self.stage(entry, data, label,relocate=relocate)
        except Exception:
            self.edits = before
            raise
