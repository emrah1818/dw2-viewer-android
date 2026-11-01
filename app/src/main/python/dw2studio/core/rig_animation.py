"""DW2 A–K animation reader/fixed-size editing, adapted from jype (MIT, 2024).

Direct format port: third_party/dw2_model_converter/src/dw2_anim.cpp/.hpp,
gltf_exporter.cpp; original license retained there. Existing timing/clip tables
and keyframe counts stay intact. No invented names for animation IDs.
"""
from dataclasses import dataclass, field
import math
import struct
import numpy as np

D = np.diag([1., -1., -1.])


def parents_from_depths(depths):
    parents=[];stack=[]
    for i,depth in enumerate(depths):
        if type(depth) is not int or depth<0 or depth>len(stack):
            raise ValueError('Ungültige native Knochenhierarchie.')
        parents.append(stack[depth-1] if depth else -1)
        stack=stack[:depth]+[i]
    return parents


def rotation_xyz(degrees):
    x,y,z=np.radians(degrees)
    rx=np.array([[1,0,0],[0,np.cos(x),-np.sin(x)],[0,np.sin(x),np.cos(x)]])
    ry=np.array([[np.cos(y),0,np.sin(y)],[0,1,0],[-np.sin(y),0,np.cos(y)]])
    rz=np.array([[np.cos(z),-np.sin(z),0],[np.sin(z),np.cos(z),0],[0,0,1]])
    return rz@ry@rx


def _rotation_power(matrix, amount):
    u,_,vt=np.linalg.svd(matrix);r=u@vt
    if np.linalg.det(r)<0:u[:,-1]*=-1;r=u@vt
    angle=math.acos(float(np.clip((np.trace(r)-1)/2,-1,1)))
    if angle<1e-8:return np.eye(3)
    if abs(math.sin(angle))<1e-6:
        vals,vecs=np.linalg.eig(r);axis=np.real(vecs[:,np.argmin(abs(vals-1))]);axis/=np.linalg.norm(axis)
    else:axis=np.array([r[2,1]-r[1,2],r[0,2]-r[2,0],r[1,0]-r[0,1]])/(2*math.sin(angle))
    k=np.array([[0,-axis[2],axis[1]],[axis[2],0,-axis[0]],[-axis[1],axis[0],0]])
    theta=angle*amount
    return np.eye(3)+math.sin(theta)*k+(1-math.cos(theta))*(k@k)


@dataclass
class BoneAdjustment:
    label: str = ''
    rotation: list = field(default_factory=lambda:[0.,0.,0.])
    motion_scale: float = 1.
    translation_scale: float = 1.
    offset: list = field(default_factory=lambda:[0.,0.,0.])

    def validate(self):
        if not isinstance(self.label,str) or len(self.label)>200:raise ValueError('Körperteilname muss ein kurzer Text sein.')
        values=[*self.rotation,*self.offset,self.motion_scale,self.translation_scale]
        if len(self.rotation)!=3 or len(self.offset)!=3 or not np.isfinite(values).all():raise ValueError('Ungültige Knochenkorrektur.')
        if not 0<=self.motion_scale<=3 or not 0<=self.translation_scale<=3:raise ValueError('Bewegungsfaktor muss 0–3 sein.')


@dataclass(frozen=True)
class Clip:
    indices: tuple
    termination: int
    loop: int


class NativeAnimation:
    def __init__(self,data,bones):
        self.data=bytes(data);self.bones=bones
        if not 1<=bones<=256 or len(data)<4+bones*4+8 or data[:4]!=bytes(4):raise ValueError('Ungültiger DW2-Animationskopf.')
        self.offsets=struct.unpack_from(f'<{bones}I',data,4)
        pos=4+bones*4;frame_offsets=[]
        # The upstream skips zero padding before the first clip pointer.
        while pos+4<=len(data) and struct.unpack_from('<I',data,pos)[0]==0:pos+=4
        while pos+4<=len(data):
            value=struct.unpack_from('<I',data,pos)[0];pos+=4
            if value in (0,1):break
            if value<pos or value>=len(data):raise ValueError('Animationsclip-Zeiger außerhalb der Datei.')
            frame_offsets.append(value)
            if len(frame_offsets)>1024:raise ValueError('Zu viele Animationsclips.')
        else:raise ValueError('Fehlender Animationstabellenabschluss.')
        if not frame_offsets:raise ValueError('Keine Animationsclips.')
        self.clips=[];maximum=np.zeros(bones,dtype=int);spans=[]
        for begin in frame_offsets:
            cursor=begin;rows=[]
            while cursor<len(data) and data[cursor] not in (254,255):
                if cursor+bones>len(data):raise ValueError('Unvollständige Framezeile.')
                row=tuple(data[cursor:cursor+bones]);rows.append(row);maximum=np.maximum(maximum,row);cursor+=bones
                if len(rows)>100000:raise ValueError('Animationsclip zu lang.')
            if not rows or cursor+3>len(data):raise ValueError('Unvollständiger Animationsclip.')
            terminator=data[cursor];loop=struct.unpack_from('<H',data,cursor+1)[0]
            self.clips.append(Clip(tuple(rows),terminator,loop));spans.append((begin,cursor+3))
        self.transforms=[]
        for bone,offset in enumerate(self.offsets):
            end=offset+(int(maximum[bone])+1)*24
            if offset<pos or end>len(data):raise ValueError('Animationsmatrix außerhalb der Datei.')
            spans.append((offset,end));frames=[]
            for key in range(int(maximum[bone])+1):
                values=np.array(struct.unpack_from('<12h',data,offset+key*24),dtype=float)
                m=np.eye(4);m[:3,:3]=D@(values[:9].reshape(3,3).T/4096.)@D;m[:3,3]=D@values[9:12];frames.append(m)
            self.transforms.append(tuple(frames))
        # Shared identical blocks can occur; partial overlaps cannot be edited safely.
        spans=sorted(set(spans))
        if any(a[1]>b[0] for a,b in zip(spans,spans[1:])):raise ValueError('Überlappende Animationsblöcke.')

    def local_pose(self,clip=0,frame=0):
        rows=self.clips[clip].indices;row=rows[frame%len(rows)]
        return np.array([self.transforms[i][key] for i,key in enumerate(row)])

    def world_pose(self,depths,clip=0,frame=0):
        local=self.local_pose(clip,frame);parents=parents_from_depths(depths);world=[]
        for i,parent in enumerate(parents):world.append(local[i] if parent<0 else world[parent]@local[i])
        return np.asarray(world)

    def adjusted(self,settings):
        if len(settings)!=self.bones:raise ValueError('Knochenkorrekturen passen nicht zum Ziel.')
        output=bytearray(self.data);writes={}
        for bone,setting in enumerate(settings):
            setting.validate()
            if setting.rotation==[0.,0.,0.] and setting.offset==[0.,0.,0.] and setting.motion_scale==setting.translation_scale==1:continue
            reference=self.transforms[bone][self.clips[0].indices[0][bone]]
            base=reference[:3,:3]
            for key,pose in enumerate(self.transforms[bone]):
                adjusted=pose[:3,:3] if setting.motion_scale==1 and setting.rotation==[0.,0.,0.] else rotation_xyz(setting.rotation)@base@_rotation_power(np.linalg.solve(base,pose[:3,:3]),setting.motion_scale)
                translation=reference[:3,3]+(pose[:3,3]-reference[:3,3])*setting.translation_scale+setting.offset
                values=np.rint(np.r_[(D@adjusted@D).T.flatten()*4096,D@translation]).astype(np.int64)
                if np.any(values<-32768) or np.any(values>32767):raise ValueError('Animationskorrektur überschreitet 16-Bit-Bereich.')
                offset=self.offsets[bone]+key*24;block=struct.pack('<12h',*values)
                if offset in writes and writes[offset]!=block:raise ValueError('Gemeinsam genutzte Matrix hat widersprüchliche Knochenkorrekturen.')
                writes[offset]=block;output[offset:offset+24]=block
        NativeAnimation(output,self.bones)
        return bytes(output)
