"""Read-only PAK mount using the existing DW2 editors and native converter.

Names come from the bundled USA file-ID map; table parsers validate the bytes.
No ISO is fabricated and the original PAK is never rewritten.
"""
import bisect
import hashlib
import json
import os
from pathlib import Path
from .pak import PakFile
from .core.disc import Entry
from .core.edit_session import EditSession, FileEdit


class PakDisc:
    def __init__(self, path):
        self.source = self.path = Path(path).resolve()
        self.pak = PakFile(self.path)
        self.sector_size = 2048
        self.sector_count = max(e.lba + e.sectors for e in self.pak.entries)
        self.volume = 'DW2 PAK'
        root = Path(os.environ.get('DW2_DATA_DIR') or Path(__file__).resolve().parent.parent / 'data')
        names = json.loads((root / 'native_file_ids_us.json').read_text(encoding='utf-8'))
        from .core.digimon_names import FILE_INDEX as name_ids
        from .core.battle_skills import FILE_INDEX as battle_ids
        names.update(name_ids)
        names.update(battle_ids)
        by_id = {}
        for name, identifier in names.items():
            if identifier in by_id and by_id[identifier] != name:
                raise ValueError('Ambiguous bundled PAK file names')
            by_id[identifier] = name
        self.entries = [Entry('PAK/' + by_id.get(e.id, f'INDEX_{e.id:04X}.BIN'), e.lba, e.size, False)
                        for e in self.pak.entries if e.format == 0]
        self.allocations = sorted((e for e in self.pak.entries if e.format == 0), key=lambda e: e.lba)
        self.starts = [e.lba for e in self.allocations]

    def close(self):
        pass

    def read(self, lba, size):
        i = bisect.bisect_right(self.starts, lba) - 1
        if i < 0:
            raise ValueError('LBA is not part of a PAK data allocation')
        e = self.allocations[i]
        offset = (lba - e.lba) * 2048
        if size < 0 or offset + size > e.size:
            raise ValueError('Read exceeds PAK allocation')
        return self.pak.read(e.id)[offset:offset + size]

    def extract(self, entry, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as out:
            out.write(self.read(entry.lba, entry.size))


class PakSession(EditSession):
    def __init__(self, path):
        self.disc = PakDisc(path)
        self.pak = self.disc.pak
        self.source = self.disc.path
        self.sector_size = 2048
        self.stamp = self._stamp()
        self.edits = {}
        self.hd_files = {}

    def original(self, entry):
        self._check_source()
        if entry.directory:
            raise ValueError('Cannot read a directory')
        return self.disc.read(entry.lba, entry.size)

    def stage(self, entry, data, label='Datei ersetzt', *, relocate=False):
        data = bytes(data)
        if not data or len(data) > 2*1024*1024:
            raise ValueError('PAK-Ersatz benötigt 1 Byte bis 2 MiB.')
        original = self.original(entry)
        key = (entry.path, entry.lba)
        for other_key, edit in self.edits.items():
            if key != other_key and max(entry.lba * 2048, edit.lba * 2048) < min(entry.lba * 2048 + entry.size, edit.lba * 2048 + len(edit.original)):
                raise ValueError('Überlappende PAK-Dateien können nicht getrennt ersetzt werden.')
        if data == original:
            self.edits.pop(key, None)
        else:
            self.edits[key] = FileEdit(entry.path, entry.lba, original, data, label, len(data) != entry.size)
        return self.edits.get(key)

    def save(self, destination, *, overwrite=False):
        raise ValueError('PAK bleibt unverändert. Bitte „PC-Port-Mod exportieren“ verwenden.')

    def active_hd_files(self):
        result={}
        for edit in self.edits.values():
            result.update(self.hd_files.get(hashlib.sha256(edit.replacement).hexdigest(),{}))
        return result

    def export_project(self, destination):
        import zipfile
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'base.dw2mod'
            super().export_project(base)
            with zipfile.ZipFile(base) as src, zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as out:
                doc=json.loads(src.read('project.json'))
                for name in src.namelist():
                    if name!='project.json':out.writestr(name,src.read(name))
                doc['hd_files']=[]
                for sha,files in self.hd_files.items():
                    if not any(hashlib.sha256(e.replacement).hexdigest()==sha for e in self.edits.values()):continue
                    for name,data in files.items():
                        ref=f'hd/{len(doc["hd_files"])}.png'
                        out.writestr(ref,data)
                        doc['hd_files'].append({'model_sha256':sha,'path':name,'data':ref})
                out.writestr('project.json',json.dumps(doc))

    def import_project(self, source, entries):
        import zipfile
        import io
        from PIL import Image
        staged={}
        with zipfile.ZipFile(source) as archive:
            if archive.getinfo('project.json').file_size>4*1024*1024:raise ValueError('Projektmanifest zu groß.')
            doc=json.loads(archive.read('project.json'))
            rows=doc.get('hd_files',[])
            if len(rows)>64:raise ValueError('Zu viele HD-Texturen im Projekt.')
            for row in rows:
                name=row['path']
                if not name.startswith('Textures/DW2Studio_015/') or Path(name).name!=name.split('/')[-1] or '..' in name or '\\' in name:
                    raise ValueError('Ungültiger HD-Texturpfad.')
                if archive.getinfo(row['data']).file_size>32*1024*1024:raise ValueError('HD-Textur zu groß.')
                data=archive.read(row['data'])
                with Image.open(io.BytesIO(data)) as image:
                    if image.format!='PNG' or image.width>2048 or image.height>4096:raise ValueError('Ungültige HD-PNG.')
                    image.verify()
                staged.setdefault(row['model_sha256'],{})[name]=data
        super().import_project(source,entries)
        self.hd_files.update(staged)


def open_workspace(path):
    from .core.catalog import build_catalog
    from .core.digimon_names import NameRepository
    session = PakSession(path)
    entries = session.disc.entries
    catalog = build_catalog(entries)
    names = NameRepository(session, entries).names()
    for c in catalog:
        if c.id in names:
            c.name, c.verified_name = names[c.id], True
    stamp = f'{session.source}:{session.stamp}'
    return session, entries, catalog, hashlib.sha256(stamp.encode()).hexdigest()
