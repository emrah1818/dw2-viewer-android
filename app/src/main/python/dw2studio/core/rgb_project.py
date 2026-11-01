"""Portable full-color viewer projects; preserve model and PNG files verbatim."""
from pathlib import Path,PurePosixPath
import json,os,re,stat,tempfile,zipfile
from .mini_assets import create_workcopy
from .model_replacements import active_replacement

KEY=re.compile(r'^\d{3}[A-Z0-9]{4}$')


def save_rgb_project(destination,models):
    """models maps stable Digimon IDs/codes to active editable models."""
    if not models:raise ValueError('Keine Vollfarbmodelle vorhanden.')
    destination=Path(destination).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=destination.name+'.',suffix='.pending',dir=destination.parent);os.close(fd)
    try:
        manifest={'format':'DW2 Full Color Viewer 1','models':{}}
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as archive:
            for key,source in sorted(models.items()):
                if not KEY.fullmatch(key):raise ValueError('Ungültige Digimon-Kennung.')
                source=Path(source).resolve();base=source.parent
                manifest['models'][key]=f'{key}/{source.name}'
                for path in sorted(base.rglob('*')):
                    if not path.is_file():continue
                    if not path.resolve().is_relative_to(base) or path.is_symlink():raise ValueError('Unsicherer Projektpfad.')
                    archive.write(path,PurePosixPath(key)/path.relative_to(base).as_posix())
            archive.writestr('viewer.json',json.dumps(manifest,ensure_ascii=False))
        os.replace(temp,destination)
    finally:Path(temp).unlink(missing_ok=True)
    return destination


def load_rgb_project(source,root,allowed_keys):
    """Validate and stage everything before atomically publishing each mapping.

    Roll back old registry entries if a later publication fails. No native
    ImageSession is modified by this project format.
    """
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rgb-load-',dir=root) as temp:
        extracted=Path(temp)
        with zipfile.ZipFile(source) as archive:
            members=archive.infolist()
            if len(members)>20000 or sum(i.file_size for i in members)>2*1024**3:raise ValueError('Viewer-Projekt überschreitet die Lesegrenzen.')
            seen=set()
            for info in members:
                name=PurePosixPath(info.filename)
                if name.is_absolute() or '..' in name.parts or '\\' in info.filename or info.filename in seen or stat.S_ISLNK(info.external_attr>>16):raise ValueError('Unsicherer oder doppelter Archivpfad.')
                seen.add(info.filename)
            if archive.getinfo('viewer.json').file_size>1024*1024:raise ValueError('Projektmanifest zu groß.')
            manifest=json.loads(archive.read('viewer.json'))
            if manifest.get('format')!='DW2 Full Color Viewer 1' or not isinstance(manifest.get('models'),dict):raise ValueError('Kein Vollfarben-Viewer-Projekt.')
            for key,path in manifest['models'].items():
                if not KEY.fullmatch(key) or key not in allowed_keys:raise ValueError('Projekt passt nicht zur Digimon-Liste: '+str(key))
                if not isinstance(path,str) or not path.startswith(key+'/') or '..' in PurePosixPath(path).parts:raise ValueError('Ungültiger Modellpfad.')
            archive.extractall(extracted)
        staged={};previous={}
        for key,path in manifest['models'].items():
            staged[key]=create_workcopy(extracted/path,root/key)
            mf=root/key/'replacement.json';previous[key]=mf.read_bytes() if mf.exists() else None
        published=[]
        try:
            for key,model in staged.items():
                mf=root/key/'replacement.json';payload=json.dumps({'model':model.relative_to(root/key).as_posix(),'native_rom_patch':False})
                pending=mf.with_suffix('.pending');pending.write_text(payload);pending.replace(mf);published.append(key)
        except Exception:
            for key in published:
                mf=root/key/'replacement.json'
                if previous[key] is None:mf.unlink(missing_ok=True)
                else:mf.write_bytes(previous[key])
            raise
        return staged


def list_rgb_models(root,keys):
    return {key:model for key in keys if (model:=active_replacement(Path(root)/key)) is not None}
