"""Native DW2 family transfer embedded in an ordinary animated glTF/GLB.

The native M and A-K files are preserved, rather than attempting to treat
glTF vertex/animation data as executable game format. A content digest
prevents silently importing an embedded original after the glTF was edited.
Larger target assets use verified loader/ISO relocation at image export.
"""
from dataclasses import dataclass
from pathlib import Path
import base64,copy,hashlib,json,re,struct
from . import gltf_textures as gt
from .native_model import NativeModel
from .rig_animation import NativeAnimation,parents_from_depths
from ..assets.tim import TIM

KEY='DW2_native_transfer'
FORMAT='DW2 native transfer 1'
FILE=re.compile(r'^([A-KM])(\d{3})([A-Z0-9]{4})\.BIN$',re.I)
MAX_NATIVE=64*1024*1024


def role(entry):
    match=FILE.fullmatch(Path(entry.path.replace('\\','/')).name)
    if not match:raise ValueError('Keine native DW2-Modell-/Animationsdatei: '+entry.path)
    return match.group(1).upper()


def view_digest(path):
    """Hash scene JSON plus all referenced buffer/image bytes, ignoring paths.

    Packing buffers into GLB changes the document layout. The viewer refreshes
    this digest on its own verified exports; arbitrary external edits do not.
    """
    path=Path(path);doc=copy.deepcopy(gt.document(path))
    extra=doc.get('extras',{})
    if isinstance(extra,dict):
        extra.pop(KEY,None)
        if not extra:doc.pop('extras',None)
    binary=gt.read_glb(path)[1] if path.suffix.lower()=='.glb' else None
    for i,buffer in enumerate(doc.get('buffers',[])):
        uri=buffer.pop('uri',None)
        raw=gt._uri_bytes(path,uri) if uri is not None else binary if i==0 else None
        length=buffer.get('byteLength')
        if raw is None or type(length)is not int or length<0 or len(raw)<length:raise ValueError('Unvollständiger Modellpuffer.')
        buffer['dw2_content_sha256']=hashlib.sha256(raw[:length]).hexdigest()
    for i,image in enumerate(doc.get('images',[])):
        raw=gt.image_bytes(path,i)
        image.pop('uri',None);image.pop('bufferView',None);image.pop('mimeType',None)
        image['dw2_content_sha256']=hashlib.sha256(raw).hexdigest()
    return hashlib.sha256(json.dumps(doc,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def _validate_family(files):
    if 'M' not in files:raise ValueError('Austausch benötigt eine native Modell-Datei.')
    if set(files)-set('ABCDEFGHIJKM'):raise ValueError('Unbekannte native Dateirolle.')
    model=NativeModel(files['M']);_texture_end(model)
    depths=list(struct.unpack_from(f'<{model.bone_count}I',files['M'],12+12*model.bone_count));parents_from_depths(depths)
    animations={r:NativeAnimation(data,model.bone_count) for r,data in files.items() if r!='M'}
    return model,animations


def _texture_end(model):
    """Use the parsed TIM blocks, not the unverified second header word.

    The original jype reader seeks to tim_start and reads the TIM blocks;
    it never compares the header's tim_end field. The v3.6 equality check
    imposed a condition that the reference reader does not require. Retain
    the original header verbatim and calculate the actual texture boundary
    both for validation and for trimming allocation padding during transfer.
    """
    from .dw2_native_atlas import is_native_dw2_tim
    tim=TIM(model.data[model.tim_start:])
    if not is_native_dw2_tim(tim):raise ValueError('Keine vollständige native 128×256-DW2-TIM-Textur am Modellzeiger.')
    return model.tim_start+tim.end


def make_payload(source,files):
    """source is the catalog candidate, files maps M/A-K roles to current bytes."""
    files={r:bytes(data) for r,data in files.items()}
    _validate_family(files)
    if sum(map(len,files.values()))>MAX_NATIVE:raise ValueError('Native Austauschdaten zu groß.')
    if not 0<=source.id<=999 or not re.fullmatch('[A-Z0-9]{4}',source.code):raise ValueError('Ungültige Quellkennung.')
    return {'format':FORMAT,'source':{'id':source.id,'code':source.code,'name':source.name},
            'files':{r:{'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'base64':base64.b64encode(data).decode('ascii')} for r,data in sorted(files.items())}}


def attach_payload(path,payload):
    """Keep all ordinary glTF scene data, adding only optional extras metadata."""
    path=Path(path);payload=copy.deepcopy(payload);payload.pop('view_sha256',None)
    payload['view_sha256']=view_digest(path)
    if path.suffix.lower()=='.glb':
        doc,binary,chunks=gt.read_glb(path)
        if not isinstance(doc.get('extras',{}),dict):raise ValueError('Modell-extras sind kein Objekt.')
        doc.setdefault('extras',{})[KEY]=payload;gt.write_glb(path,doc,binary,chunks)
    elif path.suffix.lower()=='.gltf':
        doc=gt.document(path)
        if not isinstance(doc.get('extras',{}),dict):raise ValueError('Modell-extras sind kein Objekt.')
        doc.setdefault('extras',{})[KEY]=payload
        from .png_source import write_bytes_atomic
        write_bytes_atomic(path,json.dumps(doc,ensure_ascii=False,separators=(',',':')).encode())
    else:raise ValueError('Austauschdaten benötigen GLTF oder GLB.')
    return path


def export_exchange(source,target,payload):
    """Export one self-contained glTF/GLB, with atomic final publication.

    Existing external buffers and PNG/JPEG data are embedded verbatim; no
    sidecar native files or image files need to travel with this export.
    """
    import tempfile
    from .model_export import export_model
    from .png_source import write_bytes_atomic,SIGNATURE
    source=Path(source).resolve();target=Path(target).resolve()
    if source==target:raise ValueError('Quelldatei bitte nicht überschreiben.')
    if source.suffix.lower() not in ('.gltf','.glb') or target.suffix.lower() not in ('.gltf','.glb'):raise ValueError('Austausch-Export benötigt GLTF oder GLB.')
    doc=copy.deepcopy(gt.document(source));binary=gt.read_glb(source)[1] if source.suffix.lower()=='.glb' else None
    for i,buffer in enumerate(doc.get('buffers',[])):
        raw=gt._uri_bytes(source,buffer['uri']) if 'uri' in buffer else binary if i==0 else None
        length=buffer.get('byteLength')
        if raw is None or type(length)is not int or length<0 or len(raw)<length:raise ValueError('Unvollständiger Modellpuffer.')
        buffer['uri']='data:application/octet-stream;base64,'+base64.b64encode(raw[:length]).decode('ascii')
    for i,image in enumerate(doc.get('images',[])):
        if 'uri' not in image:continue
        raw=gt.image_bytes(source,i)
        mime='image/png' if raw.startswith(SIGNATURE) else 'image/jpeg' if raw.startswith(b'\xff\xd8') else None
        if mime is None:raise ValueError('Austausch unterstützt PNG-/JPEG-Modelltexturen.')
        image['uri']='data:'+mime+';base64,'+base64.b64encode(raw).decode('ascii')
    with tempfile.TemporaryDirectory(prefix='dw2-exchange-') as folder:
        temporary=Path(folder)/'model.gltf';temporary.write_text(json.dumps(doc,ensure_ascii=False),encoding='utf-8')
        if target.suffix.lower()=='.glb':
            packed=Path(folder)/'model.glb';export_model(temporary,packed);temporary=packed
        attach_payload(temporary,payload)
        # The final read checks all embedded bytes and the visible scene hash.
        read_transfer(temporary)
        target.parent.mkdir(parents=True,exist_ok=True);write_bytes_atomic(target,temporary.read_bytes())
    return target


@dataclass(frozen=True)
class Transfer:
    source:dict
    files:dict
    payload:dict


def read_transfer(path):
    path=Path(path)
    if path.suffix.lower() not in ('.gltf','.glb'):raise ValueError('Für Animationen bitte GLTF oder GLB wählen; OBJ enthält keine Animationen.')
    doc=gt.document(path);extra=doc.get('extras',{})
    payload=extra.get(KEY) if isinstance(extra,dict) else None
    if not isinstance(payload,dict) or payload.get('format')!=FORMAT:
        raise ValueError('Diese GLTF/GLB enthält keine nativen DW2-Austauschdaten. Das Quell-Digimon bitte mit Viewer v3.6 oder neuer erneut als GLTF/GLB exportieren. Ältere oder fremde Dateien können über Externe 3D-Datei ansehen geöffnet werden.')
    source=payload.get('source');items=payload.get('files')
    if not isinstance(source,dict) or type(source.get('id'))is not int or not 0<=source['id']<=999 or not isinstance(source.get('code'),str) or not re.fullmatch('[A-Z0-9]{4}',source['code']) or not isinstance(source.get('name'),str):raise ValueError('Ungültige Austausch-Quellkennung.')
    if not isinstance(items,dict) or not 1<=len(items)<=12:raise ValueError('Ungültige Austausch-Dateiliste.')
    files={};total=0
    for r,item in items.items():
        if r not in 'ABCDEFGHIJKM' or len(r)!=1 or not isinstance(item,dict):raise ValueError('Ungültige Austausch-Dateirolle.')
        size=item.get('size');encoded=item.get('base64')
        if type(size)is not int or size<=0 or size>MAX_NATIVE or not isinstance(encoded,str) or len(encoded)>4*((size+2)//3):raise ValueError('Ungültige Austausch-Dateigröße.')
        total+=size
        if total>MAX_NATIVE:raise ValueError('Native Austauschdaten zu groß.')
        try:data=base64.b64decode(encoded,validate=True)
        except ValueError as exc:raise ValueError('Ungültige Base64-Austauschdaten.') from exc
        if len(data)!=size or hashlib.sha256(data).hexdigest()!=item.get('sha256'):raise ValueError('Austausch-Prüfsumme stimmt nicht: '+r)
        files[r]=data
    _validate_family(files)
    if payload.get('view_sha256')!=view_digest(path):
        raise ValueError('Modell, Textur oder Animation der GLTF/GLB wurde nach dem Austausch-Export verändert. Die eingebetteten Spieldaten stimmen damit nicht mehr überein. Native Änderungen im Viewer bearbeiten und neu exportieren; eine allgemeine Blender-Rückkonvertierung ist hier nicht enthalten.')
    return Transfer(source,files,payload)


@dataclass(frozen=True)
class TransferPlan:
    transfer:Transfer
    changes:tuple
    rows:tuple
    errors:tuple
    source_bones:int
    target_bones:int
    relocated:tuple=()


def _trim_zero_tail(data,used):
    # Never remove unknown non-zero trailing data. Internal native offsets
    # remain unchanged; this only removes unused allocation tail bytes.
    return data[:used] if not any(data[used:]) else data


def plan_transfer(transfer,entries,session):
    """Validate an entire family before staging anything; map A->A etc.

    Different skeletons are allowed because every companion is replaced.
    Larger files use relocation; required target clip IDs must remain present.
    """
    targets={}
    for entry in entries:
        r=role(entry)
        if r in targets:raise ValueError('Mehrdeutiger Ziel-Dateiplatz: '+r)
        targets[r]=entry
    if 'M' not in targets:raise ValueError('Keine native Zieldatei vorhanden.')
    original={r:session.current(e) for r,e in targets.items()}
    donor,animations=_validate_family(transfer.files);target=NativeModel(original['M'])
    errors=[];rows=[];changes=[];relocated=[]
    missing=set(targets)-set(transfer.files);extra=set(transfer.files)-set(targets)
    if missing:errors.append('Quell-Animationen fehlen für Zielplätze: '+', '.join(sorted(missing)))
    if extra:errors.append('Für diese Quell-Animationen hat das Ziel keinen Dateiplatz: '+', '.join(sorted(extra)))
    for r in sorted(set(targets)|set(transfer.files),key=lambda r:(r!='M',r)):
        if r not in targets or r not in transfer.files:
            rows.append((r,len(transfer.files.get(r,b'')),targets[r].size if r in targets else 0,'Dateiplatz fehlt'));continue
        data=transfer.files[r];entry=targets[r]
        if r=='M':used=_texture_end(donor);description=f'Modell, Texturen, {donor.bone_count} Knochen'
        else:
            animation=animations[r]
            used=max([offset+len(frames)*24 for offset,frames in zip(animation.offsets,animation.transforms)])
            # Clip streams may follow the matrix blocks. Locate their exact
            # offsets through the original pointer table, as NativeAnimation.
            pos=4+donor.bone_count*4
            while struct.unpack_from('<I',data,pos)[0]==0:pos+=4
            for clip in animation.clips:
                begin=struct.unpack_from('<I',data,pos)[0];pos+=4
                used=max(used,begin+len(clip.indices)*donor.bone_count+3)
            old=NativeAnimation(original[r],target.bone_count)
            description=f'{len(animation.clips)} Clips · Ziel benötigt {len(old.clips)}'
            if len(animation.clips)<len(old.clips):errors.append(f'{r}: Quelle hat {len(animation.clips)} Clips, Ziel benötigt mindestens {len(old.clips)}.')
        data=_trim_zero_tail(data,used)
        fits=len(data)<=entry.size
        if not fits:
            from .native_relocation import can_relocate
            try:
                can_relocate(session,entry);relocated.append((entry.path,entry.lba))
                status=' · neuer Dateibereich'
            except (ValueError,OSError) as exc:
                errors.append(f'{r}: Dateiverlagerung nicht möglich: {exc}');status=' · Dateitabelle nicht geprüft'
        else:status=' · passt'
        rows.append((r,len(data),entry.size,description+status))
        changes.append((entry,data.ljust(entry.size,b'\0') if fits else data,'Digimon ersetzt: '+transfer.source['name']+' · '+r))
    return TransferPlan(transfer,tuple(changes),tuple(rows),tuple(errors),donor.bone_count,target.bone_count,tuple(relocated))


def apply_plan(plan,session):
    """Commit all M/A-K replacements as a reversible native edit group."""
    if plan.errors:raise ValueError('\n'.join(plan.errors))
    before=session.edits.copy()
    try:
        for entry,data,label in plan.changes:
            if (entry.path,entry.lba) in plan.relocated:session.stage(entry,data,label,relocate=True)
            else:session.stage(entry,data,label)
    except Exception:
        session.edits=before;raise
    return len(plan.changes)
