"""Safe project-level model replacement staging; not a native DW2 encoder."""
from pathlib import Path
from urllib.parse import unquote
import json
import shutil

_ALLOWED={'.obj','.gltf','.glb'}

def _local_dependency(root, name):
    name=unquote(name.strip().strip('"'))
    if not name or name.startswith(('data:','/','\\')) or '://' in name or '\\' in name:
        raise ValueError(f'Unsichere oder ungültige Referenz: {name}')
    path=(root/name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f'Fehlende oder unzulässige Begleitdatei: {name}')
    return path

_MTL_MAPS=('map_kd','map_ka','map_ks','map_d','bump','map_bump','norm','disp')

def _obj_name(raw):
    """Wavefront-Pfad normalisieren: Windows-Backslashes und %20 sind in OBJ/MTL üblich."""
    return unquote(raw.strip().strip('\"')).replace('\\','/')

def _resolve_obj_ref(base, name):
    """Datei innerhalb von *base* suchen.

    Absolute Pfade (z. B. von Blender/Max auf einem anderen PC exportiert) werden
    über den reinen Dateinamen aufgelöst. Gibt None zurück, wenn nichts Passendes
    und Sicheres existiert, statt den ganzen Import scheitern zu lassen.
    """
    name=_obj_name(name)
    if not name or '://' in name or name.startswith('data:'):return None
    candidates=[name]
    if name.startswith('/') or (len(name)>1 and name[1]==':'):
        candidates=[name.rsplit('/',1)[-1]]
    elif name.startswith('./'):
        candidates.append(name[2:])
    base=Path(base).resolve()
    for candidate in candidates+[name.rsplit('/',1)[-1]]:
        try:path=(base/candidate).resolve()
        except (OSError,ValueError):continue
        if path.is_file() and path.is_relative_to(base):return path
    return None

def _mtl_names(line):
    """Dateinamen einer mtllib-Zeile; Leerzeichen im Dateinamen werden unterstützt."""
    rest=line.strip()[7:].strip()
    return rest

def _map_name(tokens):
    """Texturdatei einer map_*-Zeile: Optionen (-s 1 1 1 …) überspringen."""
    args=tokens[1:]
    i=0;last=None;at=None
    option_arity={'-s':3,'-o':3,'-t':3,'-mm':2,'-bm':1,'-boost':1,'-texres':1,'-clamp':1,'-blendu':1,'-blendv':1,'-cc':1,'-imfchan':1,'-type':1}
    while i<len(args):
        a=args[i]
        if a.lower() in option_arity:
            i+=1+option_arity[a.lower()];continue
        last=' '.join(args[i:]);at=i+1;break
    return at,last

def obj_dependencies(source):
    """Return (files, skipped): files = [(Pfad relativ zur OBJ, absolute Datei)].

    Fehlende MTL- oder Texturdateien führen NICHT mehr zum Abbruch; das Modell
    wird dann ohne diese Textur importiert und die Namen werden gemeldet.
    """
    source=Path(source).resolve()
    base=source.parent
    files={};skipped=[]
    try:text=source.read_text(encoding='utf-8',errors='replace')
    except OSError as exc:raise ValueError(f'OBJ kann nicht gelesen werden: {exc}')
    for line in text.splitlines():
        if not line.strip().lower().startswith('mtllib '):continue
        rest=_mtl_names(line)
        whole=_resolve_obj_ref(base,rest)
        names=[rest] if whole else rest.split()
        for name in names:
            mtl=whole if whole else _resolve_obj_ref(base,name)
            if mtl is None:
                skipped.append(_obj_name(name));continue
            files[mtl.relative_to(base).as_posix()]=mtl
            for mline in mtl.read_text(encoding='utf-8',errors='replace').splitlines():
                tokens=mline.strip().split()
                if len(tokens)<2 or tokens[0].lower() not in _MTL_MAPS:continue
                _,ref=_map_name(tokens)
                if not ref:continue
                # Pfade in der MTL gelten relativ zur MTL-Datei.
                texture=_resolve_obj_ref(mtl.parent,ref) or _resolve_obj_ref(base,ref)
                if texture is None:skipped.append(_obj_name(ref));continue
                files[texture.relative_to(base).as_posix()]=texture
    return files,sorted(set(skipped))

def _obj_refs(source):
    """Relative Begleitdateien (MTL + Texturen), die tatsächlich existieren."""
    files,_=obj_dependencies(source)
    return sorted(files)


def _rewrite_references(obj, staged_obj, source_base):
    """Schreibt die Kopie so um, dass alle Verweise relativ und portabel sind.

    Backslashes, %20 und absolute Pfade des ursprünglichen PCs würden sonst beim
    späteren Laden (trimesh/VTK) nicht mehr gefunden.
    """
    from os.path import relpath
    source_base=Path(source_base).resolve()
    staged_obj=Path(staged_obj)
    lines=[]
    for line in Path(obj).read_text(encoding='utf-8',errors='replace').splitlines():
        if line.strip().lower().startswith('mtllib '):
            rest=_mtl_names(line)
            whole=_resolve_obj_ref(source_base,rest)
            found=[whole] if whole else [m for m in (_resolve_obj_ref(source_base,n) for n in rest.split()) if m]
            if found:
                line='mtllib '+' '.join(m.relative_to(source_base).as_posix() for m in found)
        lines.append(line)
    staged_obj.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    files,_=obj_dependencies(obj)
    for rel,mtl in files.items():
        if mtl.suffix.lower()!='.mtl':continue
        out=[]
        for mline in mtl.read_text(encoding='utf-8',errors='replace').splitlines():
            tokens=mline.strip().split()
            if len(tokens)>=2 and tokens[0].lower() in _MTL_MAPS:
                at,ref=_map_name(tokens)
                if ref:
                    texture=_resolve_obj_ref(mtl.parent,ref) or _resolve_obj_ref(source_base,ref)
                    if texture is not None:
                        new=relpath(texture,mtl.parent).replace('\\','/')
                        mline=' '.join(tokens[:at]+[new])
            out.append(mline)
        target=staged_obj.parent/rel
        target.write_text('\n'.join(out)+'\n',encoding='utf-8')

def _gltf_refs(source):
    from .gltf_textures import document
    doc=document(source)
    return [x['uri'] for x in doc.get('buffers',[])+doc.get('images',[]) if x.get('uri') and not x['uri'].startswith('data:')]

def stage_model(source, destination):
    """Copy model and all local dependencies; validate before changing existing draft."""
    source=Path(source).resolve(); destination=Path(destination).resolve()
    if source.suffix.lower() not in _ALLOWED:raise ValueError('Erlaubt: OBJ, glTF oder GLB')
    if not source.is_file():raise FileNotFoundError(source)
    skipped=[]
    files={source.name:source}
    if source.suffix.lower()=='.obj':
        extra,skipped=obj_dependencies(source)
        files.update(extra)
    else:
        refs=_gltf_refs(source)
        for ref in refs:
            dependency=_local_dependency(source.parent,ref)
            rel=dependency.relative_to(source.parent)
            files[rel.as_posix()]=dependency
    # Validate first; then copy into a new isolated project folder.
    destination.mkdir(parents=True,exist_ok=True)
    for rel,src in files.items():
        out=(destination/rel).resolve()
        if not out.is_relative_to(destination):raise ValueError('Ungültiger Zielpfad')
        out.parent.mkdir(parents=True,exist_ok=True)
        if src!=out:shutil.copy2(src,out)
    if source.suffix.lower()=='.obj':
        _rewrite_references(source,destination/source.name,source.parent)
    manifest={'model':source.name,'files':sorted(files),'skipped_references':skipped,'native_dw2_compatible':False,
              'note':'Projekt-Ersatz; kein nativer DW2-Rückkonverter vorhanden'}
    (destination/'model_import.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    return destination/source.name,manifest
