"""DW3 disc discovery and isolated native model/texture/animation conversion."""
from dataclasses import asdict
import hashlib
import json
import struct
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from .core.disc import Disc, Entry
from .core.recovery import recover_entries

MODEL_NAME = re.compile(r'^M\d{3}[A-Z0-9_]{1,12}\.(?:BIN|PRO)$', re.I)


class Dw3Disc:
    def __init__(self, path, cache):
        disc = Disc(path)
        try:
            if not any(e.path.upper().endswith(('SLUS_014.36', 'SLES_039.36')) for e in disc.entries):
                raise ValueError('DW3 USA (SLUS_014.36) oder DW2003 Europa (SLES_039.36) erforderlich.')
            self.path = disc.path.resolve()
            st = self.path.stat()
            self.stamp = (st.st_size, st.st_mtime_ns)
            self.key = hashlib.sha256(f'native-source-v2:{self.path}:{self.stamp}'.encode()).hexdigest()
            self.cache = Path(cache) / 'dw3' / self.key
            self.cache.mkdir(parents=True, exist_ok=True)
            self.sector_size = disc.sector_size
            index = self.cache / 'index.json'
            try:
                doc = json.loads(index.read_text(encoding='utf-8'))
                if doc['format'] != 1 or len(doc['entries']) > 100000:
                    raise ValueError('Invalid DW3 index')
                entries = [Entry(**e) for e in doc['entries']]
                if any(e.lba < 0 or e.size <= 0 or e.lba + (e.size + 2047) // 2048 > disc.sector_count for e in entries):
                    raise ValueError('Invalid DW3 extent')
            except (OSError, ValueError, TypeError, KeyError):
                found = list(disc.entries) + recover_entries(self.path, disc.sector_size)
                entries = list({(Path(e.path).name, e.lba, e.size): e for e in found if not e.directory}.values())
                temp = index.with_suffix('.pending')
                temp.write_text(json.dumps({'format': 1, 'entries': [asdict(e) for e in entries]}), encoding='utf-8')
                temp.replace(index)
            self.entries = sorted([e for e in entries if MODEL_NAME.fullmatch(Path(e.path).name)], key=lambda e: e.path)
            if not self.entries:
                raise ValueError('Keine DW3-Modelleinträge gefunden.')
            # names from the game's DIGNAM text (read only; cached next to the index)
            from . import dw3_names
            try:
                self.names = dw3_names.load_or_build(self.cache, 'v1', disc, self.entries)
            except (OSError, ValueError, KeyError, struct.error) as e:
                self.names = {'version': 1, 'note': f'Namen nicht lesbar: {e}', 'models': []}
        finally:
            disc.close()

    def catalog(self):
        rows = {m['id']: m for m in (getattr(self, 'names', None) or {}).get('models', [])}
        out = []
        for i, e in enumerate(self.entries):
            item = {'id': i, 'name': Path(e.path).stem, 'size': e.size}
            m = rows.get(i)
            if m and m.get('path') == e.path:
                item.update({'digimon': m['name'], 'code': m['code'], 'file': m['file'], 'file_number': m['file_number'],
                             'fighter_ids': m['fighter_ids'], 'name_index': m['name_index'], 'aliases': m['aliases'],
                             'variant': m['variant'], 'status': m['status'], 'status_text': m['status_text']})
            else:
                item.update({'digimon': Path(e.path).stem, 'code': Path(e.path).stem, 'aliases': [], 'variant': '',
                             'status': 'unreadable', 'status_text': 'Namenstext nicht lesbar'})
            thumb = self.cache / 'thumbs' / f'{i}.png'
            if thumb.is_file():
                item['thumb'] = thumb.relative_to(self.cache.parents[1]).as_posix() + f'?v={thumb.stat().st_mtime_ns}'
            out.append(item)
        return out

    def save_thumb(self, identifier, png):
        """A small preview the viewer rendered of model IDENTIFIER (PNG bytes, at most 256 KB)."""
        if type(identifier) is not int or not 0 <= identifier < len(self.entries):
            raise ValueError('Unknown DW3 model')
        if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png) > 256 * 1024:
            raise ValueError('Vorschaubild muss ein PNG bis 256 KB sein.')
        folder = self.cache / 'thumbs'
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f'{identifier}.tmp'
        tmp.write_bytes(png)
        tmp.replace(folder / f'{identifier}.png')
        return True

    def prepare(self, identifier):
        if type(identifier) is not int or not 0 <= identifier < len(self.entries):
            raise ValueError('Unknown DW3 model')
        st = self.path.stat()
        if (st.st_size, st.st_mtime_ns) != self.stamp:
            raise ValueError('DW3-Image wurde verändert. Bitte erneut öffnen.')
        entry = self.entries[identifier]
        from dw2studio import dw3_tool
        if sys.platform != 'emscripten':
            dw3_tool.converter()   # fehlt der Konverter, vor dem Auslesen melden
        target = self.cache / f'model_{identifier:04d}'
        result = target / 'model.glb'
        source_json = target / 'native_source.json'
        if result.is_file() and source_json.is_file() and b'"lead_blend"' not in source_json.read_bytes():
            # converted before 0.96: no page data (1.0) or no motion end / loop point, convert again
            shutil.rmtree(target, ignore_errors=True)
        if not result.is_file():
            with tempfile.TemporaryDirectory(prefix='dw3-', dir=self.cache) as tmp:
                tmp = Path(tmp)
                disc = Disc(self.path)
                try:
                    disc.extract(entry, tmp / 'source.bin')
                finally:
                    disc.close()
                proc = dw3_tool.run([tmp / 'source.bin', tmp / 'out'], timeout=120)
                if proc.returncode != 0 or not (tmp / 'out/model.glb').is_file():
                    raise ValueError('DW3-Konvertierung fehlgeschlagen: ' + (proc.stderr.strip()[:1000] or str(proc.returncode)))
                # Only publish a complete conversion directory.
                (tmp / 'out').rename(target)
        return {'path': str(result), 'name': Path(entry.path).stem,
                'url': result.relative_to(self.cache.parents[1]).as_posix()}
