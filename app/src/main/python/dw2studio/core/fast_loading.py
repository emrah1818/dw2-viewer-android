"""Persistent disc indexes and one prioritized, cancellable converter worker."""
from collections import OrderedDict
from dataclasses import asdict,dataclass
from pathlib import Path
import hashlib,json,os,shutil,tempfile,time,threading
try:
    from PyQt6.QtCore import QThread,pyqtSignal
except ImportError:  # Android/Web: nur die Qt-freien Funktionen werden benutzt
    QThread=object
    def pyqtSignal(*_a,**_k):
        return None
from .disc import Disc,Entry
from .catalog import build_catalog
from .recovery import recover_entries
from .auto_models import cache_key,candidate_models,convert_models


def image_stamp(path):
    path=Path(path).resolve();st=path.stat()
    return [str(path),st.st_size,st.st_mtime_ns]


def scan_image(source,cache,scanner=None):
    started=time.perf_counter();disc=Disc(source)
    try:
        stamp=image_stamp(disc.path);folder=Path(cache)/'indexes';folder.mkdir(parents=True,exist_ok=True)
        name=hashlib.sha256(str(disc.path.resolve()).encode()).hexdigest()+'.json';index=folder/name
        try:
            doc=json.loads(index.read_text(encoding='utf-8'))
            if doc['format']!=1 or doc['stamp']!=stamp or doc['sector_size']!=disc.sector_size:raise ValueError('Index veraltet')
            entries=[]
            if len(doc['entries'])>100000:raise ValueError('Index zu groß')
            for row in doc['entries']:
                e=Entry(**row)
                if type(e.lba)is not int or type(e.size)is not int or e.lba<0 or e.size<0 or e.lba+(e.size+2047)//2048>disc.sector_count:raise ValueError('Ungültiger Indexeintrag')
                entries.append(e)
            cached=True
        except (OSError,ValueError,KeyError,TypeError):
            found=list(disc.entries)+(scanner or recover_entries)(disc.path,disc.sector_size)
            unique={}
            for e in found:
                key=(e.lba,e.size,Path(e.path.replace('\\','/')).name.upper())
                if key not in unique or e.path.startswith('AAA/'):unique[key]=e
            entries=list(unique.values());cached=False
            pending=index.with_suffix('.pending')
            try:
                pending.write_text(json.dumps({'format':1,'stamp':stamp,'sector_size':disc.sector_size,'entries':[asdict(e) for e in entries]},separators=(',',':')),encoding='utf-8');pending.replace(index)
            finally:pending.unlink(missing_ok=True)
        from .edit_session import EditSession
        from .digimon_names import NameRepository
        names={};name_error=''
        try:names=NameRepository(EditSession(disc.path,disc.sector_size),entries).names()
        except (ValueError,OSError) as exc:name_error=str(exc)
        catalog=build_catalog(entries)
        for candidate in catalog:
            if candidate.id in names:candidate.name=names[candidate.id];candidate.verified_name=True
        if image_stamp(disc.path)!=stamp:raise ValueError('Image wurde während der Analyse verändert.')
        return entries,catalog,{'path':str(disc.path.resolve()),'sector_size':disc.sector_size,'cache_key':cache_key(disc.path),'cached':cached,'seconds':time.perf_counter()-started,'name_error':name_error}
    finally:disc.close()


@dataclass
class ModelRequest:
    key:str
    image:str
    entries:list
    folder:Path
    candidate:object
    converter:str
    overrides:dict
    aliases:dict=None   # (path,lba) -> one destination name or several MODELDT slot names


def extract_request(job, source, cancel=lambda:False):
    """Read a physical file once, then materialize all of its logical slots.

    Conflicting destination names are rejected instead of silently overwriting
    another file. This is shared by the direct and queued conversion paths.
    """
    disc = Disc(job.image)
    written = {}
    try:
        for entry in job.entries:
            if cancel():
                raise RuntimeError('Konvertierung abgebrochen')
            name = Path(entry.path.replace('\\', '/')).name
            destinations = (job.aliases or {}).get((entry.path, entry.lba), name)
            if isinstance(destinations, str):
                destinations = [destinations]
            origin = (entry.path, entry.lba, entry.size)
            pending = []
            for target in destinations:
                if not isinstance(target, str) or Path(target).name != target or '\\' in target or target in ('.', '..'):
                    raise ValueError('Ungültiger Konvertierungs-Dateiname.')
                key = target.upper()
                if key in written:
                    if written[key] != origin:
                        raise ValueError(f'Widersprüchliche Modell-Dateizuordnung: {target}.')
                    continue
                written[key] = origin
                pending.append(target)
            if not pending:
                continue
            data = job.overrides.get(name)
            first = source / pending[0]
            if data is None:
                disc.extract(entry, first)
            else:
                first.write_bytes(data)
            for target in pending[1:]:
                shutil.copyfile(first, source / target)
    finally:
        disc.close()


def build_model(job,convert,cancel=lambda:False):
    """Qt-freie Konvertierung eines Digimon (gleiches Cache-Layout wie die Desktop-Warteschlange)."""
    existing=candidate_models(job.folder/'converted',job.candidate)
    if existing:
        try:
            if existing[0].suffix.lower()=='.gltf':json.loads(existing[0].read_text(encoding='utf-8'))
            return existing[0]
        except ValueError:pass
    job.folder.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='conversion-',dir=job.folder) as temp:
        source=Path(temp)/'native';output=Path(temp)/'converted';source.mkdir();output.mkdir()
        extract_request(job, source, cancel)
        if not any(source.iterdir()):raise ValueError('Keine extrahierten Modell-Dateien gefunden')
        convert(source,output)
        models=candidate_models(output,job.candidate)
        if not models:raise ValueError('Konverter hat kein passendes Modell erzeugt.')
        if models[0].suffix.lower()=='.gltf':json.loads(models[0].read_text(encoding='utf-8'))
        relative=models[0].relative_to(output);target=job.folder/'converted'
        if target.exists():shutil.rmtree(target)
        os.replace(output,target)
        return target/relative


class DiscReader(QThread):
    done=pyqtSignal(object,object,object);failed=pyqtSignal(str)
    def __init__(self,path,cache):super().__init__();self.path=path;self.cache=cache
    def run(self):
        try:
            result=scan_image(self.path,self.cache)
            if not self.isInterruptionRequested():self.done.emit(*result)
        except Exception as exc:
            if not self.isInterruptionRequested():self.failed.emit(str(exc))


class ConversionQueue(QThread):
    ready=pyqtSignal(str,str,float);failed=pyqtSignal(str,str)
    def __init__(self):
        super().__init__();self.condition=threading.Condition();self.jobs=OrderedDict();self.priority=None;self.active=None;self.active_cancelled=False
    def submit(self,request,foreground=True):
        with self.condition:
            if foreground:
                previous=self.priority;self.priority=request.key
                if self.active is not None and self.active!=request.key:self.active_cancelled=True
                if previous and previous!=self.active:self.jobs.pop(previous,None)
            if request.key!=self.active or self.active_cancelled:self.jobs[request.key]=request
            self.condition.notify_all()
    def cancelled(self):
        with self.condition:return self.isInterruptionRequested() or self.active_cancelled or (self.priority is not None and self.priority!=self.active)
    def clear(self):
        with self.condition:self.jobs.clear();self.priority=None;self.active_cancelled=True;self.condition.notify_all()
    def stop(self):
        self.requestInterruption()
        with self.condition:self.condition.notify_all()
    def run(self):
        while not self.isInterruptionRequested():
            with self.condition:
                while not self.jobs and not self.isInterruptionRequested():self.condition.wait(.2)
                if self.isInterruptionRequested():return
                key=self.priority if self.priority in self.jobs else next(iter(self.jobs));job=self.jobs.pop(key);self.active=key;self.active_cancelled=False
            started=time.perf_counter()
            try:
                result=self.convert(job)
                if not self.cancelled():self.ready.emit(job.key,str(result),time.perf_counter()-started)
            except Exception as exc:
                if not self.cancelled():self.failed.emit(job.key,str(exc))
            finally:
                with self.condition:
                    if self.priority==key and key not in self.jobs:self.priority=None
                    self.active=None
    def convert(self,job):
        existing=candidate_models(job.folder/'converted',job.candidate)
        if existing:
            try:
                if existing[0].suffix.lower()=='.gltf':json.loads(existing[0].read_text(encoding='utf-8'))
                return existing[0]
            except ValueError:pass
        job.folder.mkdir(parents=True,exist_ok=True)
        # A cancelled conversion never publishes a half-written glTF cache entry.
        with tempfile.TemporaryDirectory(prefix='conversion-',dir=job.folder) as temp:
            source=Path(temp)/'native';output=Path(temp)/'converted';source.mkdir()
            extract_request(job, source, self.cancelled)
            convert_models(job.converter,source,output,cancel=self.cancelled)
            if self.cancelled():raise RuntimeError('Konvertierung abgebrochen')
            models=candidate_models(output,job.candidate)
            if not models:raise ValueError('Konverter hat kein passendes Modell erzeugt.')
            if models[0].suffix.lower()=='.gltf':json.loads(models[0].read_text(encoding='utf-8'))
            relative=models[0].relative_to(output);target=job.folder/'converted'
            if target.exists():shutil.rmtree(target)
            os.replace(output,target)
            return target/relative
