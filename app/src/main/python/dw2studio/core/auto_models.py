"""Automatic, cached DW2 model discovery and external converter pipeline.
No game data or third-party executable is distributed with this project.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import re

MODEL_FILE = re.compile(r"^[A-KM]\d{3}[A-Z0-9]{4}\.BIN$", re.I)

def model_entries(entries):
    """DW2 model (M) and associated animation (A-K) BINs across recovered disc locations."""
    return [e for e in entries if not e.directory and MODEL_FILE.fullmatch(e.path.replace('\\','/').split('/')[-1])]

def cache_key(disc_path):
    p=Path(disc_path)
    st=p.stat()
    fingerprint=f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:20]

def candidate_models(root, digimon):
    root=Path(root)
    if not root.exists():return []
    identifier=f"M{digimon.id:03d}{digimon.code}".upper()
    code=digimon.code.upper()
    supported={'.glb','.gltf','.obj','.stl'}
    paths=[p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in supported]
    # Favor exact model filename, then abbreviation; no arbitrary replacement model.
    return sorted([p for p in paths if identifier in p.stem.upper() or code in p.stem.upper()], key=lambda p:(identifier not in p.stem.upper(),p.suffix.lower()!='.glb',str(p)))

def selected_model_entries(entries, digimon):
    """Only the selected M model and its A-K animation companions."""
    stem=f"{digimon.id:03d}{digimon.code}".upper()
    return [e for e in model_entries(entries)
            if e.path.replace('\\','/').split('/')[-1].upper()[1:] == stem+'.BIN']

def converted_tim(root, digimon):
    """Upstream names its extracted texture 003AGUM.TIM, without the M prefix."""
    p=Path(root)/f"{digimon.id:03d}{digimon.code}.TIM"
    return p if p.is_file() else None

def model_animation_names(path):
    """Read animation names from glTF without loading large binary buffers."""
    p=Path(path)
    if p.suffix.lower() not in ('.gltf','.glb'): return []
    from .gltf_document import read_document
    data=read_document(p)
    return [str(a.get('name') or f"Animation {i+1}") for i,a in enumerate(data.get('animations',[]))]

def extract_model_entries(disc, entries, destination):
    destination=Path(destination); destination.mkdir(parents=True,exist_ok=True)
    used=set(); count=0
    for entry in sorted(model_entries(entries), key=lambda e: e.path.upper()):
        name=entry.path.replace('\\','/').split('/')[-1]
        if name.upper() in used: continue
        used.add(name.upper())
        disc.extract(entry,destination/name)
        count+=1
    return count

def convert_models(executable, source, output, timeout=1200, cancel=None):
    executable=Path(executable);source=Path(source);output=Path(output)
    if not executable.is_file():raise FileNotFoundError(f'Konverter fehlt: {executable}')
    if not source.is_dir() or not any(source.iterdir()):raise ValueError('Keine extrahierten Modell-Dateien gefunden')
    output.mkdir(parents=True,exist_ok=True)
    if cancel is None:
        completed=subprocess.run([str(executable),str(source),str(output)],capture_output=True,text=True,errors='replace',timeout=timeout,check=False,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    else:
        import time
        process=subprocess.Popen([str(executable),str(source),str(output)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        started=time.monotonic()
        try:
            while True:
                if cancel():raise RuntimeError('Konvertierung abgebrochen.')
                if time.monotonic()-started>timeout:raise TimeoutError('Konverter-Zeitlimit überschritten.')
                try:
                    stdout,stderr=process.communicate(timeout=.2)
                    completed=subprocess.CompletedProcess(process.args,process.returncode,stdout,stderr);break
                except subprocess.TimeoutExpired:pass
        finally:
            if process.poll() is None:
                process.kill();process.communicate()
    if completed.returncode:raise RuntimeError(f'Konverter fehlgeschlagen ({completed.returncode}):\n{(completed.stdout+completed.stderr)[-4000:]}')
    return completed.stdout+completed.stderr
