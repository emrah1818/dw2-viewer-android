"""Non-destructive glTF 2.0/GLB texture replacement.

Preserves buffers, skins, animations, mesh attributes, and extensions. Changing
an image only redirects an existing glTF image slot to a PNG in a workcopy;
GLB changes append a bufferView and never rewrite the original geometry data.
"""
from __future__ import annotations

import base64
import io
import json
import re
import struct
from pathlib import Path
from urllib.parse import unquote

from PIL import Image
from .png_source import verified_png,SIGNATURE

_MAGIC = b'glTF'
_JSON_CHUNK = b'JSON'
_BIN_CHUNK = b'BIN\0'
_DATA_URI = re.compile(r'^data:([^;,]+)?(?:;[^,]*)?,(.*)$', re.S | re.I)


def read_glb(path):
    raw = Path(path).read_bytes()
    if len(raw) < 20 or raw[:4] != _MAGIC or struct.unpack_from('<I', raw, 4)[0] != 2:
        raise ValueError('Keine gültige glTF-2.0-GLB-Datei')
    if struct.unpack_from('<I', raw, 8)[0] != len(raw):
        raise ValueError('GLB-Längenangabe stimmt nicht mit Datei überein')
    chunks = []
    offset = 12
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise ValueError('Unvollständiger GLB-Chunk-Header')
        length, typ = struct.unpack_from('<I4s', raw, offset)
        offset += 8
        if length % 4 or offset + length > len(raw):
            raise ValueError('Ungültige GLB-Chunk-Größe')
        chunks.append((typ, raw[offset:offset + length]))
        offset += length
    if not chunks or chunks[0][0] != _JSON_CHUNK:
        raise ValueError('GLB hat keinen JSON-Chunk')
    doc = json.loads(chunks[0][1].decode('utf-8').rstrip(' \t\r\n\0'))
    binary = next((chunk for typ, chunk in chunks if typ == _BIN_CHUNK), b'')
    return doc, binary, chunks


def _chunk(kind, content, pad):
    content += pad * ((-len(content)) % 4)
    return struct.pack('<I4s', len(content), kind) + content


def write_glb(path, doc, binary, chunks):
    text = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    rebuilt = [_chunk(_JSON_CHUNK, text, b' ')]
    wrote_binary = False
    for kind, data in chunks[1:]:
        if kind == _BIN_CHUNK:
            rebuilt.append(_chunk(_BIN_CHUNK, binary, b'\0'))
            wrote_binary = True
        else:
            rebuilt.append(_chunk(kind, data, b'\0'))
    if not wrote_binary and binary:
        rebuilt.insert(1, _chunk(_BIN_CHUNK, binary, b'\0'))
    payload = b''.join(rebuilt)
    out = _MAGIC + struct.pack('<II', 2, 12 + len(payload)) + payload
    target = Path(path)
    pending = target.with_name(target.name + '.pending')
    try:
        pending.write_bytes(out)
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return target


def document(path):
    path = Path(path)
    return read_glb(path)[0] if path.suffix.lower() == '.glb' else json.loads(path.read_text(encoding='utf-8'))


def _safe_uri(model, uri):
    uri = unquote(uri)
    if not uri or uri.startswith(('/', '\\')) or '://' in uri or '\\' in uri:
        raise ValueError('Ungültiger oder externer Bildpfad in glTF')
    out = (model.parent / uri).resolve()
    if not out.is_relative_to(model.parent.resolve()):
        raise ValueError('Texturpfad verlässt den Projektordner')
    return out


def _uri_bytes(model, uri):
    match = _DATA_URI.match(uri)
    if match:
        if ';base64,' not in uri.lower().split(',', 1)[0] + ',':
            # glTF image data URIs normally use base64, but percent encoding is valid.
            from urllib.parse import unquote_to_bytes
            return unquote_to_bytes(match.group(2))
        return base64.b64decode(match.group(2), validate=True)
    return _safe_uri(model, uri).read_bytes()


def image_bytes(path, index):
    path = Path(path)
    if path.suffix.lower() == '.glb':
        doc, binary, _ = read_glb(path)
    else:
        doc = json.loads(path.read_text(encoding='utf-8'))
        binary = None
    images = doc.get('images', [])
    if index < 0 or index >= len(images):
        raise IndexError('Texturslot nicht vorhanden')
    entry = images[index]
    if 'uri' in entry:
        return _uri_bytes(path, entry['uri'])
    view_id = entry.get('bufferView')
    if view_id is None:
        raise ValueError('Texturslot enthält keine Bilddaten')
    view = doc['bufferViews'][view_id]
    buf_id = view.get('buffer', 0)
    if binary is None or buf_id != 0:
        uri = doc['buffers'][buf_id].get('uri')
        if not uri:
            raise ValueError('glTF-Bildbuffer nicht auflösbar')
        binary = _uri_bytes(path, uri)
    start = view.get('byteOffset', 0)
    end = start + view['byteLength']
    if start < 0 or end > len(binary):
        raise ValueError('Texturdaten liegen außerhalb des GLB-/glTF-Buffers')
    return binary[start:end]


def slots(path):
    doc = document(path)
    return [(f'Textur {i + 1}: {item.get("name") or item.get("uri", "eingebettet").split("/")[-1]}', None)
            for i, item in enumerate(doc.get('images', []))]


def export_png(path, index, target):
    payload = image_bytes(path, index)
    if payload.startswith(SIGNATURE):Path(target).write_bytes(payload)
    else:
        with Image.open(io.BytesIO(payload)) as original:original.convert('RGBA').save(target, format='PNG')
    return Path(target)


def replace_png(path, index, png):
    """Patch image slot only; animation and skin JSON fields remain unchanged."""
    path = Path(path).resolve()
    pixels,_=verified_png(png)
    if path.suffix.lower() == '.glb':
        doc, binary, chunks = read_glb(path)
    elif path.suffix.lower() == '.gltf':
        doc = json.loads(path.read_text(encoding='utf-8'))
    else:
        raise ValueError('Nur glTF oder GLB unterstützt')
    images = doc.get('images', [])
    if not 0 <= index < len(images):
        raise IndexError('Texturindex außerhalb der Datei')
    # A viewer-only PNG change invalidates embedded native exchange data.
    # Do not later export/import the old native texture as if it were current.
    if isinstance(doc.get('extras'),dict):doc['extras'].pop('DW2_native_transfer',None)
    entry = dict(images[index])
    entry.pop('uri', None)
    entry.pop('bufferView', None)
    if path.suffix.lower() == '.glb':
        if len(doc.get('buffers', [])) > 1:
            raise ValueError('Mehrere GLB-Buffer können nicht sicher geändert werden')
        position = len(binary)
        binary += b'\0' * (-position % 4)
        position = len(binary)
        binary += pixels
        view = len(doc.setdefault('bufferViews', []))
        doc['bufferViews'].append({'buffer': 0, 'byteOffset': position, 'byteLength': len(pixels)})
        doc['buffers'] = [{'byteLength': len(binary)}]
        entry['bufferView'] = view
        entry['mimeType'] = 'image/png'
        images[index] = entry
        write_glb(path, doc, binary, chunks)
    else:
        # A new relative PNG also works when the old texture is embedded,
        # a JPEG, or shared by multiple images; no source image is overwritten.
        target = path.parent / f'dw2_replacement_texture_{index + 1}.png'
        pending = target.with_name(target.name + '.pending')
        try:
            pending.write_bytes(pixels)
            pending.replace(target)
        finally:
            pending.unlink(missing_ok=True)
        entry['uri'] = target.name
        entry.pop('mimeType', None)
        images[index] = entry
        pending_doc = path.with_name(path.name + '.pending')
        try:
            pending_doc.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding='utf-8')
            pending_doc.replace(path)
        finally:
            pending_doc.unlink(missing_ok=True)
    return path
