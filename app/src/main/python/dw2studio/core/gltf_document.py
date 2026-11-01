"""Read a glTF/GLB JSON document; pack buffers without dropping rigs or clips."""
from pathlib import Path
import base64,json,mimetypes,struct
from urllib.parse import unquote


def read_document(path):
    path=Path(path)
    if path.suffix.lower()=='.gltf':return json.loads(path.read_text(encoding='utf-8'))
    data=path.read_bytes()
    if len(data)<20 or data[:4]!=b'glTF' or struct.unpack_from('<II',data,4)!=(2,len(data)):
        raise ValueError('Ungültiger GLB-Header.')
    size,kind=struct.unpack_from('<II',data,12)
    if kind!=0x4e4f534a or size%4 or 20+size>len(data):raise ValueError('Ungültiger GLB-JSON-Chunk.')
    return json.loads(data[20:20+size].decode('utf-8'))


def pack_glb(source,target):
    source=Path(source).resolve();target=Path(target)
    document=read_document(source)
    if source.suffix.lower()=='.glb':
        if source!=target.resolve():target.write_bytes(source.read_bytes())
        return target
    def uri_bytes(uri):
        if uri.startswith('data:'):
            head,payload=uri.split(',',1)
            if not head.endswith(';base64'):raise ValueError('Nur Base64-Daten-URIs werden gepackt.')
            return base64.b64decode(payload,validate=True),head[5:-7]
        if '://' in uri or '\\' in uri or uri.startswith(('/','data:')):raise ValueError('Unsichere glTF-Referenz.')
        path=(source.parent/unquote(uri)).resolve()
        if not path.is_relative_to(source.parent):raise ValueError('glTF-Datei verlässt den Modellordner.')
        return path.read_bytes(),mimetypes.guess_type(path.name)[0]
    binary=bytearray();bases=[]
    def append(data):
        offset=(len(binary)+3)//4*4;binary.extend(bytes(offset-len(binary)));binary.extend(data);return offset
    for buffer in document.get('buffers',[]):
        data,_=uri_bytes(buffer['uri'])
        if len(data)<buffer['byteLength']:raise ValueError('glTF-Puffer unvollständig.')
        bases.append(append(data[:buffer['byteLength']]))
    views=document.setdefault('bufferViews',[])
    for view in views:
        if view.get('extensions',{}).get('EXT_meshopt_compression'):raise ValueError('Meshopt-komprimierte Puffer werden nicht gepackt.')
        index=view.get('buffer',0)
        if type(index)is not int or not 0<=index<len(bases):raise ValueError('Ungültige glTF-Pufferreferenz.')
        view['byteOffset']=view.get('byteOffset',0)+bases[index];view['buffer']=0
    for image in document.get('images',[]):
        if 'uri' not in image:continue
        data,mime=uri_bytes(image.pop('uri'))
        image['bufferView']=len(views);image['mimeType']=mime or 'image/png';views.append({'buffer':0,'byteOffset':append(data),'byteLength':len(data)})
    document['buffers']=[{'byteLength':len(binary)}]
    encoded=json.dumps(document,ensure_ascii=False,separators=(',',':')).encode('utf-8');encoded+=b' '*((-len(encoded))%4);binary.extend(bytes((-len(binary))%4))
    length=12+8+len(encoded)+8+len(binary)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(struct.pack('<4sII',b'glTF',2,length)+struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary)
    return target
