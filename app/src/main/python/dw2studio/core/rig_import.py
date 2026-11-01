"""Manual rigid-face retargeting of OBJ meshes into existing DW2 model slots.

Uses the native vertex/normal/quad/triangle layout directly documented by the
bundled MIT jype converter. New geometry must fit BEFORE the original TIM;
image/file size, bone depths, native animation clip structure remain fixed.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import struct
import numpy as np
from .native_model import NativeModel,validate_replacement
from .rig_animation import D,NativeAnimation,BoneAdjustment,parents_from_depths,rotation_xyz


@dataclass(frozen=True)
class ObjFace:
    vertices: tuple
    uv: tuple
    group: str
    material: str


class ObjMesh:
    def __init__(self,path):
        self.path=Path(path).resolve();self.vertices=[];self.texcoords=[];self.faces=[]
        if self.path.stat().st_size>128*1024*1024:raise ValueError('OBJ ist größer als 128 MiB.')
        self.sha256=hashlib.sha256(self.path.read_bytes()).hexdigest()
        group='Modell';material=''
        def index(value,count):
            i=int(value);i=i-1 if i>0 else count+i
            if i<0 or i>=count:raise ValueError('OBJ-Index außerhalb der vorhandenen Daten.')
            return i
        for line_number,line in enumerate(self.path.read_text(encoding='utf-8-sig').splitlines(),1):
            tokens=line.split('#',1)[0].split()
            if not tokens:continue
            kind=tokens[0]
            try:
                if kind=='v':
                    if len(tokens)!=4:raise ValueError('Drei Vertexkoordinaten erforderlich.')
                    self.vertices.append(tuple(map(float,tokens[1:])))
                elif kind=='vt':
                    if len(tokens)<3:raise ValueError('Zwei UV-Koordinaten erforderlich.')
                    self.texcoords.append(tuple(map(float,tokens[1:3])))
                elif kind in ('o','g'):group=' '.join(tokens[1:]) or 'Modell'
                elif kind=='usemtl':material=' '.join(tokens[1:])
                elif kind=='f':
                    if len(tokens) not in (4,5):raise ValueError('OBJ vor Import in Dreiecke/Vierecke zerlegen.')
                    corners=[];uv=[]
                    for corner in tokens[1:]:
                        ids=corner.split('/');corners.append(index(ids[0],len(self.vertices)))
                        uv.append(index(ids[1],len(self.texcoords)) if len(ids)>1 and ids[1] else -1)
                    for order in ((0,1,2),) if len(corners)==3 else ((0,1,2),(0,2,3)):
                        self.faces.append(ObjFace(tuple(corners[i] for i in order),tuple(uv[i] for i in order),group,material))
                elif kind not in ('vn','s','mtllib'):
                    raise ValueError('Nicht unterstütztes OBJ-Element: '+kind)
            except (ValueError,IndexError) as exc:raise ValueError(f'OBJ-Zeile {line_number}: {exc}') from exc
        self.vertices=np.asarray(self.vertices,dtype=float)
        if self.vertices.ndim!=2 or self.vertices.shape[1]!=3 or not len(self.faces):raise ValueError('OBJ enthält keine gültigen Dreiecke.')
        if not np.isfinite(self.vertices).all() or not np.isfinite(np.asarray(self.texcoords)).all():raise ValueError('OBJ enthält nicht endliche Koordinaten.')
        if len(self.faces)>50000:raise ValueError('Mehr als 50.000 Dreiecke: Modell vor dem Rigging reduzieren.')
        self.groups=sorted(set(face.group for face in self.faces))

    @property
    def face_indices(self):return np.array([face.vertices for face in self.faces],dtype=int)


class RigProject:
    def __init__(self,mesh,model,animations):
        self.mesh=mesh;self.original=bytes(model);self.model=NativeModel(model)
        begin=min(min(p.vertices,p.normals) for p in self.model.parts);budget=self.model.tim_start-begin
        minimum=16*len(mesh.faces)+40*self.model.bone_count
        if minimum>budget:raise ValueError(f'OBJ ist für diesen Zielplatz zu groß: mindestens {minimum} Geometriebytes, nur {budget} verfügbar. Polygonzahl vor dem Rigging reduzieren.')
        self.depths=list(struct.unpack_from(f'<{self.model.bone_count}I',model,12+12*self.model.bone_count))
        self.parents=parents_from_depths(self.depths)
        if not animations:raise ValueError('Keine nativen A–K-Animationen vorhanden. Rigging benötigt eine belegte Referenzpose.')
        self.animations={name:NativeAnimation(data,self.model.bone_count) for name,data in sorted(animations.items())}
        self.reference_name=next(iter(self.animations));self.reference_clip=0;self.reference_frame=0
        self.assignment=np.full(len(mesh.faces),-1,dtype=int)
        self.settings=[BoneAdjustment(label=f'Knochen {i:02d}') for i in range(self.model.bone_count)]
        self.scale=1.;self.rotation=[0.,0.,0.];self.offset=[0.,0.,0.]
        self.blink_records=None
        self.palette_by_bone=[int(part.primitives[0][3]) for part in self.model.parts]
        self.uv_mode='atlas256'
        self.texture_png=None
        self.target_hash=hashlib.sha256(model).hexdigest()

    def source_vertices(self):
        if not np.isfinite([self.scale,*self.rotation,*self.offset]).all() or self.scale<=0:raise ValueError('Ungültige Modelltransformation.')
        with np.errstate(over='ignore',invalid='ignore'):
            result=self.mesh.vertices@rotation_xyz(self.rotation).T*self.scale+self.offset
        if not np.isfinite(result).all():raise ValueError('Transformation erzeugt ungültige Koordinaten; Skalierung reduzieren.')
        return result

    def reference_world(self):
        return self.animations[self.reference_name].world_pose(self.depths,self.reference_clip,self.reference_frame)

    def adjusted_animations(self):
        signature=json.dumps([asdict(s) for s in self.settings],sort_keys=True)
        if signature!=getattr(self,'_animation_signature',None):
            self._animation_cache={name:NativeAnimation(animation.adjusted(self.settings),self.model.bone_count) for name,animation in self.animations.items()}
            self._animation_signature=signature
        return self._animation_cache

    def binding_world(self):
        return self.adjusted_animations()[self.reference_name].world_pose(self.depths,self.reference_clip,self.reference_frame)

    def adjusted_animation_bytes(self):
        return {name:animation.data for name,animation in self.adjusted_animations().items()}

    def preview(self,name,clip,frame):
        original_bind=self.binding_world()
        animation=self.adjusted_animations()[name]
        pose=animation.world_pose(self.depths,clip,frame)
        vertices=self.source_vertices();triangles=vertices[self.mesh.face_indices].copy()
        for bone in range(self.model.bone_count):
            selected=np.where(self.assignment==bone)[0]
            if not len(selected):continue
            local=np.concatenate([triangles[selected],np.ones((*triangles[selected].shape[:2],1))],axis=2)@np.linalg.inv(original_bind[bone]).T
            triangles[selected]=(local@pose[bone].T)[:,:,:3]
        return triangles,pose

    def _blink_bytes(self):
        if self.blink_records is None:return self.original[self.model.blink_offset:self.model.blink_offset+20]
        if len(self.blink_records)!=2:raise ValueError('Genau zwei Augenrecords erforderlich.')
        out=bytearray()
        for record in self.blink_records:
            if not record['enabled']:out+=bytes([255,0,0,0,0,0,0,0,0,0]);continue
            values=[record[k] for k in ('x','y','w','h','open_x','open_y','half_x','half_y','closed_x','closed_y')]
            if any(type(v) is not int for v in values):raise ValueError('Augenpositionen müssen ganze Pixelwerte sein.')
            x,y,w,h,ox,oy,hx,hy,cx,cy=values
            if not w or not h or any(v%4 for v in (x,w,ox,hx,cx)):raise ValueError('Augen-X und Breite müssen durch 4 teilbar sein.')
            if any(a<0 or b<0 or a+w>128 or b+h>224 for a,b in ((x,y),(ox,oy),(hx,hy),(cx,cy))):raise ValueError('Augenrechteck außerhalb 128×224 Nutzpixel.')
            out+=bytes([x//4,y,w//4,h,ox//4,oy,hx//4,hy,cx//4,cy])
        return bytes(out)

    def build_native(self):
        if np.any(self.assignment<0) or np.any(self.assignment>=self.model.bone_count):raise ValueError('Jede Modellfläche muss einem vorhandenen Knochen zugeordnet sein.')
        vertices=self.source_vertices();bind=self.binding_world()
        # Keep all unknown header/texture-animation bytes before the first geometry block.
        begin=min(min(p.vertices,p.normals) for p in self.model.parts)
        cursor=(begin+3)//4*4;out=bytearray(self.original);out[cursor:self.model.tim_start]=bytes(self.model.tim_start-cursor)
        pointers=[[],[],[]]
        def block(data):
            nonlocal cursor
            start=cursor;end=start+len(data)
            if end>self.model.tim_start:raise ValueError(f'Geometrie benötigt mindestens {end-begin} Bytes; im Ziel sind nur {self.model.tim_start-begin} verfügbar. Polygonzahl reduzieren.')
            out[start:end]=data;cursor=(end+3)//4*4
            return start
        for bone in range(self.model.bone_count):
            ids=np.where(self.assignment==bone)[0];points=[];normals=[];point_map={};normal_map={};primitives=[]
            inverse=np.linalg.inv(bind[bone]);clut=self.palette_by_bone[bone]
            if (clut&63) not in (0,1) or not 224<=((clut>>6)&1023)<255:raise ValueError('Ungültige Zielpalette.')
            for face_id in ids:
                face=self.mesh.faces[face_id];world=vertices[list(face.vertices)]
                local=(np.c_[world,np.ones(3)]@inverse.T)[:,:3]@D
                local=np.rint(local)
                if not np.isfinite(local).all() or np.any(local<-32768) or np.any(local>32767):raise ValueError('Vertex überschreitet den nativen 16-Bit-Bereich; Modell einpassen.')
                normal=np.cross(local[1]-local[0],local[2]-local[0]);length=np.linalg.norm(normal)
                if length<1e-8:raise ValueError(f'Dreieck {face_id} fällt im PS1-Koordinatenraster zusammen. Modell vergrößern oder Geometrie bereinigen.')
                normal_key=tuple(np.rint(normal/length*4096).astype(int))
                if normal_key not in normal_map:normal_map[normal_key]=len(normals);normals.append(normal_key)
                vi=[];uv=[]
                for corner in range(3):
                    key=(face.vertices[corner],tuple(np.rint(local[corner]).astype(int)))
                    if key not in point_map:point_map[key]=len(points);points.append(key[1])
                    vi.append(point_map[key]);index=face.uv[corner]
                    if index<0:raise ValueError('OBJ enthält Flächen ohne UVs. Texturkoordinaten im 3D-Editor anlegen.')
                    u,v=self.mesh.texcoords[index]
                    if not 0<=u<=1 or not 0<=v<=1:raise ValueError('Wiederholende UVs außerhalb 0–1 werden nicht übernommen.')
                    y=round((1-v)*(223 if self.uv_mode=='fit224' else 255));x=round(u*127)
                    if not 0<=y<224:raise ValueError('UV liegt in reservierten Palettezeilen. „UV auf 224 Pixel einpassen“ wählen oder UVs korrigieren.')
                    uv.append((x,y))
                if len(points)>256 or len(normals)>256:raise ValueError(f'Knochen {bone}: maximal 256 Vertices/Normalen.')
                # Native winding is reversed by jype on export. Reverse on import too.
                order=(2,1,0);normal_id=normal_map[normal_key]
                primitives.append(bytes(vi[i] for i in order)+bytes([normal_id]*3)+bytes(c for i in order for c in uv[i])+struct.pack('<HH',clut,0))
            if not points:
                points=[(0,0,0)];normals=[(0,0,4096)];primitives=[bytes(12)+struct.pack('<HH',clut,0)]
            if any(v<-32768 or v>32767 for point in points for v in point):raise ValueError('Vertex überschreitet 16-Bit-Bereich; Skalierung reduzieren.')
            pointers[0].append(block(struct.pack('<IH',len(points),struct.unpack_from('<H',self.original,self.model.parts[bone].vertices+4)[0])+b''.join(struct.pack('<hhh',*p) for p in points)))
            pointers[1].append(block(struct.pack('<IH',len(normals),struct.unpack_from('<H',self.original,self.model.parts[bone].normals+4)[0])+b''.join(struct.pack('<hhh',*p) for p in normals)))
            pointers[2].append(block(struct.pack('<4I',0,0,0,len(primitives))+b''.join(primitives)))
        for i,table in enumerate(pointers):struct.pack_into(f'<{self.model.bone_count}I',out,12+i*self.model.bone_count*4,*table)
        out[self.model.blink_offset:self.model.blink_offset+20]=self._blink_bytes()
        result=validate_replacement(self.original,bytes(out))
        if self.texture_png:
            from .native_texture import NativeTexture
            result=NativeTexture(result).replace(self.texture_png)
        return result,{'geometry_used':cursor-begin,'geometry_budget':self.model.tim_start-begin,'triangles':len(self.mesh.faces),'bones':self.model.bone_count}

    def save(self,path):
        doc={'format':'DW2 Rig 1','obj_sha256':self.mesh.sha256,'target_sha256':self.target_hash,
             'assignment':self.assignment.tolist(),'bones':[asdict(s) for s in self.settings],
             'scale':self.scale,'rotation':self.rotation,'offset':self.offset,'palette_by_bone':self.palette_by_bone,
             'reference_name':self.reference_name,'reference_clip':self.reference_clip,'reference_frame':self.reference_frame,
             'uv_mode':self.uv_mode,'blink_records':self.blink_records,'texture_png':self.texture_png}
        Path(path).write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')

    def load(self,path):
        doc=json.loads(Path(path).read_text(encoding='utf-8'))
        if doc.get('format')!='DW2 Rig 1' or doc.get('obj_sha256')!=self.mesh.sha256 or doc.get('target_sha256')!=self.target_hash:raise ValueError('Zuordnung passt nicht zu OBJ und aktueller Zielmodellfassung.')
        if not isinstance(doc['assignment'],list) or any(type(v)is not int for v in doc['assignment']):raise ValueError('Flächenzuordnung muss ganze Knochen-IDs enthalten.')
        assignment=np.asarray(doc['assignment'],dtype=int)
        if assignment.shape!=self.assignment.shape or np.any(assignment< -1) or np.any(assignment>=self.model.bone_count):raise ValueError('Ungültige Flächenzuordnung.')
        settings=[BoneAdjustment(**item) for item in doc['bones']]
        if len(settings)!=len(self.settings):raise ValueError('Falsche Knochenzahl.')
        for setting in settings:setting.validate()
        name=doc['reference_name'];clip=doc['reference_clip'];frame=doc['reference_frame']
        if name not in self.animations or not 0<=clip<len(self.animations[name].clips) or not 0<=frame<len(self.animations[name].clips[clip].indices):raise ValueError('Ungültige Referenzpose.')
        values=[doc['scale'],*doc['rotation'],*doc['offset']]
        if len(doc['rotation'])!=3 or len(doc['offset'])!=3 or not np.isfinite(values).all() or doc['scale']<=0:raise ValueError('Ungültige Transformation.')
        palettes=doc['palette_by_bone']
        if len(palettes)!=self.model.bone_count or any(type(v)is not int or (v&63)not in (0,1) or not 224<=v>>6<255 for v in palettes):raise ValueError('Ungültige Palette.')
        if doc['uv_mode'] not in ('fit224','atlas256'):raise ValueError('Unbekannte UV-Abbildung.')
        import copy
        candidate=copy.copy(self);candidate.blink_records=doc['blink_records'];candidate._blink_bytes()
        texture=doc.get('texture_png')
        if texture:
            from PIL import Image
            with Image.open(texture) as image:
                if image.size!=(128,256):raise ValueError('Zugeordnete Textur hat nicht 128×256 Pixel.')
        self.assignment=assignment;self.settings=settings;self.scale=doc['scale'];self.rotation=doc['rotation'];self.offset=doc['offset'];self.palette_by_bone=palettes
        self.reference_name=name;self.reference_clip=clip;self.reference_frame=frame;self.uv_mode=doc['uv_mode'];self.blink_records=doc['blink_records'];self.texture_png=doc.get('texture_png')

    def export_gltf(self,path):
        """Export rigid bone hierarchy and ALL native clips, embedded buffers/PNG."""
        import base64,io
        from .native_texture import NativeTexture
        native,report=self.build_native();model=NativeModel(native)
        animations={name:NativeAnimation(data,model.bone_count) for name,data in self.adjusted_animation_bytes().items()}
        doc={'asset':{'version':'2.0','generator':'DW2 Rig Import v8 (jype format adaptation)'},'scene':0,
             'scenes':[{'nodes':[],'extras':{'blinking_data':list(native[model.blink_offset:model.blink_offset+24])}}],
             'nodes':[],'meshes':[],'animations':[],'buffers':[],'bufferViews':[],'accessors':[],
             'materials':[{'name':'Native DW2 atlas','pbrMetallicRoughness':{'baseColorTexture':{'index':0},'metallicFactor':0.,'roughnessFactor':1.},'alphaMode':'MASK','alphaCutoff':.1,'doubleSided':True}],
             'textures':[{'sampler':0,'source':0}],'samplers':[{'magFilter':9728,'minFilter':9728,'wrapS':33071,'wrapT':33071}]}
        binary=bytearray()
        def accessor(values,kind):
            arr=np.asarray(values,dtype='<f4');start=(len(binary)+3)//4*4;binary.extend(bytes(start-len(binary)));binary.extend(arr.tobytes())
            view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':start,'byteLength':arr.nbytes})
            row={'bufferView':view,'componentType':5126,'count':len(arr),'type':kind}
            if len(arr):
                flat=arr.reshape(len(arr),-1);row.update(min=flat.min(0).tolist(),max=flat.max(0).tolist())
            index=len(doc['accessors']);doc['accessors'].append(row);return index
        def trs(matrix):
            scale=np.linalg.norm(matrix[:3,:3],axis=0)
            if np.min(scale)<1e-8:raise ValueError('Singuläre Animationstransformation.')
            r=matrix[:3,:3]/scale
            # SVD removes tiny fixed-point rounding errors before quaternion extraction.
            u,_,vt=np.linalg.svd(r);r=u@vt
            trace=np.trace(r)
            if trace>0:
                s=np.sqrt(trace+1)*2;q=np.array([(r[2,1]-r[1,2])/s,(r[0,2]-r[2,0])/s,(r[1,0]-r[0,1])/s,.25*s])
            else:
                i=int(np.argmax(np.diag(r)));j=(i+1)%3;k=(i+2)%3;s=np.sqrt(max(0.,1+r[i,i]-r[j,j]-r[k,k]))*2
                if s<1e-10:raise ValueError('Ungültige Animationsrotation.')
                q=np.zeros(4);q[i]=.25*s;q[j]=(r[j,i]+r[i,j])/s;q[k]=(r[k,i]+r[i,k])/s;q[3]=(r[k,j]-r[j,k])/s
            return matrix[:3,3].tolist(),(q/np.linalg.norm(q)).tolist(),scale.tolist()
        first=next(iter(animations.values())).local_pose()
        for i in range(model.bone_count):
            t,q,scale=trs(first[i]);doc['nodes'].append({'name':self.settings[i].label or f'bone_{i}','translation':t,'rotation':q,'scale':scale,'children':[]})
        for i,parent in enumerate(self.parents):
            (doc['scenes'][0]['nodes'] if parent<0 else doc['nodes'][parent]['children']).append(i)
        for bone,part in enumerate(model.parts):
            vertices=np.array([struct.unpack_from('<hhh',native,part.vertices+6+i*6) for i in range(part.vertex_count)],dtype=float)@D
            normals=np.array([struct.unpack_from('<hhh',native,part.normals+6+i*6) for i in range(part.normal_count)],dtype=float)@D/4096
            points=[];ns=[];uvs=[]
            for vs,normal_ids,uv,clut,stp in part.primitives:
                for order in ((2,1,0),(1,2,3)) if len(vs)==4 else ((2,1,0),):
                    for j in order:points.append(vertices[vs[j]]);ns.append(normals[normal_ids[j]]);uvs.append((uv[j][0]/128,uv[j][1]/256))
            mesh=len(doc['meshes']);doc['meshes'].append({'name':f'mesh_{bone}','primitives':[{'attributes':{'POSITION':accessor(points,'VEC3'),'NORMAL':accessor(ns,'VEC3'),'TEXCOORD_0':accessor(uvs,'VEC2')},'material':0,'mode':4}]})
            node=len(doc['nodes']);doc['nodes'].append({'name':f'geometry_{bone}','mesh':mesh});doc['nodes'][bone]['children'].append(node)
        for name,animation in animations.items():
            for ci,clip in enumerate(animation.clips):
                a={'name':f'{Path(name).stem}:{ci}','samplers':[],'channels':[],'extras':{'termination_mask':clip.termination,'loop_mask':clip.loop}}
                times=accessor(np.arange(len(clip.indices),dtype=float)/30,'SCALAR')
                for bone in range(model.bone_count):
                    values=[trs(animation.transforms[bone][row[bone]]) for row in clip.indices]
                    quaternions=[v[1] for v in values]
                    for j in range(1,len(quaternions)):
                        if np.dot(quaternions[j-1],quaternions[j])<0:quaternions[j]=(-np.array(quaternions[j])).tolist()
                    for channel,kind,data in (('translation','VEC3',[v[0] for v in values]),('rotation','VEC4',quaternions),('scale','VEC3',[v[2] for v in values])):
                        index=len(a['samplers']);a['samplers'].append({'input':times,'output':accessor(data,kind),'interpolation':'LINEAR'});a['channels'].append({'sampler':index,'target':{'node':bone,'path':channel}})
                doc['animations'].append(a)
        png=io.BytesIO();NativeTexture(native).to_image().save(png,format='PNG')
        doc['images']=[{'uri':'data:image/png;base64,'+base64.b64encode(png.getvalue()).decode()}]
        doc['buffers']=[{'byteLength':len(binary),'uri':'data:application/octet-stream;base64,'+base64.b64encode(binary).decode()}]
        Path(path).write_text(json.dumps(doc,separators=(',',':')),encoding='utf-8')
        return Path(path),report
