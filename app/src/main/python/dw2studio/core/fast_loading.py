"""Persistent disc indexes and one prioritized, cancellable converter worker."""
from collections import OrderedDict
from dataclasses import asdict,dataclass
from pathlib import Path
import hashlib,json,os,shutil,tempfile,time
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
    aliases:dict=None   # Eintragsschlüssel (path,lba) -> Zieldateiname (Spielzuordnung A–K aus MODELDT)


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
        source=Path(temp)/'native';output=Path(temp)/'converted';source.mkdir();output.mkdir();disc=Disc(job.image)
        try:
            for entry in job.entries:
                if cancel():raise RuntimeError('Konvertierung abgebrochen')
                name=Path(entry.path.replace('\\','/')).name
                data=job.overrides.get(name)
                target=(job.aliases or {}).get((entry.path,entry.lba),name)
                if data is None:disc.extract(entry,source/target)
                else:(source/target).write_bytes(data)
        finally:disc.close()
        if not any(source.iterdir()):raise ValueError('Keine extrahierten Modell-Dateien gefunden')
        convert(source,output)
        models=candidate_models(output,job.candidate)
        if not models:raise ValueError('Konverter hat kein passendes Modell erzeugt.')
        if models[0].suffix.lower()=='.gltf':json.loads(models[0].read_text(encoding='utf-8'))
        relative=models[0].relative_to(output);target=job.folder/'converted'
        if target.exists():shutil.rmtree(target)
        os.replace(output,target)
        return target/relative
