"""Two-language UI glossary for the standalone 3D viewer.

German is the original/fallback language. Unknown strings (e.g. Digimon names,
third-party converter diagnostics, filenames) are deliberately not translated.
No machine/network translator is used; core file formats are unaffected.
"""

LANGUAGES = ("de", "en")

EN = {
    "Eigenschaften": "Properties",
    "Digimon-Werte": "Digimon Stats",
    "Spielstand/Memorycard exportieren": "Export Save / Memory Card",
    "Typ ändern": "Change Digimon Type",
    "Typ konnte nicht geändert werden": "Could Not Change Digimon Type",
    "Typ: Spiel-Image und Digimon wählen": "Type: choose a game image and Digimon",
    "Spiel-Image und Digimon wählen": "Choose a game image and Digimon",
    "Attacken bearbeiten": "Edit Battle Techniques",
    "Attacken konnten nicht geändert werden": "Could Not Edit Battle Techniques",
    "Native DW2-Textur – Vorschau vor dem Schreiben": "Native DW2 Texture – Preview Before Writing",
    "Vergleich: Original / bearbeitete PNG / tatsächliches PS1-Ergebnis. Die PlayStation unterstützt nur 16 Farben pro Teilpalette.": "Comparison: original / edited PNG / actual PS1 result. PlayStation supports only 16 colors per subpalette.",
    "Original im Spiel": "Original in Game",
    "Deine bearbeitete PNG": "Your Edited PNG",
    "Erwartetes Ergebnis im Spiel": "Expected Result in Game",
    "Mittlerer Farbfehler: {error}/255 | Starke Farbabweichungen: {bad:.1%} | Geänderte Paletten: {palettes} | Neue Palettenfarben: {colors}": "Mean color error: {error}/255 | Large color differences: {bad:.1%} | Changed palettes: {palettes} | New palette colors: {colors}",
    "Nur fortfahren, wenn die rechte Vorschau deinen gewünschten Farben entspricht. Die Original-BIN bleibt unverändert.": "Continue only if the preview on the right matches your intended colors. The original BIN stays unchanged.",
    "Farben stimmen – BIN erstellen": "Colors Look Right – Create BIN",
    # Main window and controls
    "DW2 · 3D Viewer Studio v2.8": "DW2 · 3D Viewer Studio v2.8",
    "DIGIMON / MODELLE": "DIGIMON / MODELS",
    "BIN / ISO öffnen": "Open BIN / ISO",
    "3D-Datei importieren": "Import 3D File",
    "Digimon suchen …": "Search Digimon …",
    "BIN/ISO öffnen oder 3D-Datei importieren": "Open a BIN/ISO or import a 3D file",
    "Ausgewähltes Digimon öffnen": "Open Selected Digimon",
    "3D-Datei oder Digimon wählen": "Choose a 3D file or Digimon",
    "MODELL & TEXTUREN": "MODEL & TEXTURES",
    "Aktive Datei": "Active File",
    "Noch kein Modell": "No Model Loaded",
    "3D-Datei exportieren": "Export 3D File",
    "3D-Modelle (*.gltf *.glb *.obj *.stl)": "3D Models (*.gltf *.glb *.obj *.stl)",
    "Modelle (*.gltf *.glb *.obj *.stl)": "Models (*.gltf *.glb *.obj *.stl)",
    "3D-Objekt ersetzen": "Replace 3D Object",
    "Originalmodell wiederherstellen": "Restore Original Model",
    "Textur auswählen": "Select Texture",
    "Textur als PNG exportieren": "Export Texture as PNG",
    "PNG-Textur importieren": "Import PNG Texture",
    "Textur ersetzen (PNG)": "Replace Texture (PNG)",
    "Modell im Viewer und im Digimon-Projekt ersetzen – Original bleibt erhalten": "Replace model in viewer and Digimon project – original remains unchanged",
    "Aktiven Textur-Slot ersetzen und sofort im Viewer anzeigen": "Replace active texture slot and update the viewer immediately",
    "3D-Objekt und Texturen werden in Projektkopien ersetzt. glTF-/GLB-Texturwechsel erhält die vorhandenen Animationen. Ein anderes OBJ übernimmt nur seine eigene Geometrie (ohne Animationsübertragung). Kein nativer DW2-ROM-Modellimport.": "3D models and textures are replaced in project copies. glTF/GLB texture replacement preserves existing animations. A different OBJ brings only its own geometry (no animation transfer). No native DW2 ROM model import.",
    "SPIEL-IMAGE · NATIVE TIM-TEXTUR": "GAME IMAGE · NATIVE TIM TEXTURE",
    "Originale Digimon-TIM exportieren, bearbeiten und in eine NEUE Spiel-BIN schreiben. Nur Textur – kein OBJ-/GLB-Geometrieimport!": "Export and edit the original Digimon TIM texture, then write it to a NEW game BIN. Texture only – no OBJ/GLB geometry import!",
    "Original-TIM exportieren (PNG)": "Export Original TIM (PNG)",
    "Vollständigen nativen Augenatlas exportieren": "Export Complete Native Eye Atlas",
    "Augen offen (Original)": "Eyes Open (Original)",
    "Augenstellung {number}": "Eye Pose {number}",
    "Vollständigen Augenatlas exportieren": "Export Complete Eye Atlas",
    "Augenatlas ins Spiel-Image schreiben": "Write Eye Atlas to Game Image",
    "Augen blinzeln (experimentelle Vorschau)": "Eye Blinking (Experimental Preview)",
    "Automatisch": "Automatic",
    "Augen offen": "Eyes Open",
    "Halb geschlossen": "Half Closed",
    "Geschlossen": "Closed",
    "Andere offene Pose": "Alternative Open Pose",
    "Original-Augenatlas mit fünf Posen exportieren": "Export Original Eye Atlas with Five Poses",
    "Augenatlas exportiert": "Eye Atlas Exported",
    "Augenatlas-Export fehlgeschlagen": "Eye Atlas Export Failed",

    "Textur ins Spiel-Image schreiben": "Write Texture to Game Image",
    "PROTOKOLL": "ACTIVITY LOG",
    "Bereit · DW2 3D Viewer Studio": "Ready · DW2 3D Viewer Studio",
    "Sprache:": "Language:",
    "Deutsch": "German",
    "Englisch": "English",
    "Einstellungen": "Settings",
    "Datei": "File",
    # VTK animation controls, camera, appearance
    "OBJ / glTF / GLB laden – texturierte Vorschau, kein DW2-BIN-Import": "Load OBJ / glTF / GLB – textured preview, not DW2 BIN import",
    "3D-Abhängigkeiten fehlen: pip install pyqtgraph PyOpenGL trimesh numpy Pillow": "3D dependencies missing: pip install pyqtgraph PyOpenGL trimesh numpy Pillow",
    "glTF laden · Animation auswählen · Play/Pause": "Load glTF · choose animation · Play/Pause",
    "Kamera · Microsoft-ähnliche Steuerung": "Camera · familiar mouse controls",
    "Perspektivisch": "Perspective",
    "Orthografisch": "Orthographic",
    "Projektion": "Projection",
    "Sichtfeld": "Field of View",
    "Empfindlichkeit": "Sensitivity",
    "Zoom": "Zoom",
    "Kamera zurücksetzen": "Reset Camera",
    "Ansicht wählen": "Select View",
    "Vorne": "Front",
    "Hinten": "Back",
    "Links": "Left",
    "Rechts": "Right",
    "Oben": "Top",
    "3D schräg": "3D Isometric",
    "Perspektive": "Viewpoint",
    "Rotation": "Rotation",
    "Automatische Rotation": "Auto Rotation",
    "Stufe 1 · 7,5°/s": "Level 1 · 7.5°/s",
    "Stufe 2 · 15°/s": "Level 2 · 15°/s",
    "Stufe 3 · 30°/s": "Level 3 · 30°/s",
    "Geschwindigkeit": "Speed",
    "Darstellung": "Appearance",
    "DW2 – blau/grünes Raster": "DW2 – Blue/Green Grid",
    "Studio – hellgrau": "Studio – Light Gray",
    "Neutral – dunkelblau": "Neutral – Dark Blue",
    "Hintergrund": "Background",
    "Texturen anzeigen (aus = grünes Polygon-Drahtgitter)": "Show Textures (off = green wireframe)",
    "Ohne Textur: nur grüne Polygonkanten.": "Without texture: green polygon edges only.",
    "Links ziehen: drehen\nRechts ziehen: verschieben\nMausrad: zoomen": "Left drag: rotate\nRight drag: pan\nMouse wheel: zoom",
    "▶ Abspielen": "▶ Play",
    "⏸ Pause": "⏸ Pause",
    "Wiederholen": "Loop",
    "Geschwindigkeit der Original-DW2-Animation": "Original DW2 animation speed",
    # Dialogs and messages
    "DW2-Spiel-Image öffnen": "Open DW2 Game Image",
    "Image konnte nicht gelesen werden": "Could Not Read Image",
    "Konverter fehlt": "Converter Missing",
    "dw2_model_converter.exe nicht gefunden.": "dw2_model_converter.exe not found.",
    "Modell fehlt": "Model Missing",
    "Konvertierung fehlgeschlagen": "Conversion Failed",
    "3D-Modell konnte nicht geladen werden": "Could Not Load 3D Model",
    "Kein Modell": "No Model",
    "Bitte zuerst ein Digimon oder eine 3D-Datei laden.": "Load a Digimon or 3D file first.",
    "Neues 3D-Objekt als Ersatz wählen": "Choose Replacement 3D Object",
    "3D-Ersetzung fehlgeschlagen": "3D Replacement Failed",
    "Kein Spielmodell": "No Game Model",
    "Wiederherstellung ist für aus einer BIN geladene Digimon verfügbar.": "Restoring the original is available for Digimon loaded from a BIN.",
    "3D-Modell importieren": "Import 3D Model",
    "Import fehlgeschlagen": "Import Failed",
    "Modell exportieren": "Export Model",
    "Bitte zuerst ein Modell öffnen.": "Open a model first.",
    "Original-/Projektdatei bitte nicht überschreiben.": "Do not overwrite the original/project file.",
    "Export fehlgeschlagen": "Export Failed",
    "Textur exportieren": "Export Texture",
    "Textur-Export fehlgeschlagen": "Texture Export Failed",
    "Bitte zunächst eine DW2-BIN laden und ein Digimon im Viewer öffnen.": "Load a DW2 BIN and open a Digimon in the viewer first.",
    "Originale Spieltextur (TIM) exportieren": "Export Original Game Texture (TIM)",
    "Native TIM exportiert": "Native TIM Exported",
    "Die exportierte PNG ist die ORIGINAL-Pixelanordnung aus dem Spiel. Bitte genau diese Vorlage bearbeiten; der 3D-Viewer kann eine anders angeordnete glTF-Textur nutzen.": "This PNG uses the ORIGINAL pixel layout from the game. Edit this exact template; the 3D viewer may use a differently arranged glTF texture.",
    "TIM-Export fehlgeschlagen": "TIM Export Failed",
    "Texturquelle auswählen": "Choose Texture Source",
    "Soll die aktuell angezeigte Projekttextur direkt als native TIM geschrieben werden?\n\nWICHTIG: Die Abmessungen passen zwar, aber glTF- und PS1-TIM-Atlanten können verschieden angeordnet sein.\n\nJa = aktuelle Textur verwenden.\nNein = bearbeitete Original-TIM-PNG auswählen.": "Write the currently displayed project texture as native TIM?\n\nIMPORTANT: Although dimensions match, glTF and PS1 TIM atlases can be arranged differently.\n\nYes = use current texture.\nNo = select edited original TIM PNG.",
    "Neue Spiel-BIN erstellen (Original unverändert)": "Create New Game BIN (Original Unchanged)",
    "Ziel muss eine neue .bin-Datei sein.": "Destination must be a new .bin file.",
    "Das Original und bestehende Dateien dürfen nicht überschrieben werden.": "The original and existing files must not be overwritten.",
    "Native TIM ins Spiel schreiben": "Write Native TIM to Game",
    "Erstelle modifizierte Spiel-BIN … Die Originaldatei bleibt unverändert.": "Creating modified game BIN … Original file stays unchanged.",
    "ROM-Texturpatch fehlgeschlagen": "ROM Texture Patch Failed",
    "Spiel-Image geschrieben": "Game Image Written",
    "ROM-Texturpatch fehlgeschlagen; Original unverändert.": "ROM texture patch failed; original unchanged.",
    "Keine Textur": "No Texture",
    "Das Modell hat keinen vorhandenen Textur-Slot.": "This model has no texture slot.",
    "Neue PNG-Textur als Ersatz wählen": "Choose Replacement PNG Texture",
    "Textur-Import fehlgeschlagen": "Texture Import Failed",
    "Textur aus Material exportieren (falls vorhanden)": "Export Material Texture (if available)",
    "Ja": "Yes", "Nein": "No", "Abbrechen": "Cancel", "OK": "OK",
    'Analysiere Image und suche versteckte Modell-Dateien …': 'Analyzing image and searching for hidden model files …',
    'Ersatzmodell aktiv – Originaldatei unverändert': 'Replacement model active – original unchanged',
    'Animation {number}': 'Animation {number}',
    '{name} · {count} Teilmodell(e) · Texturfarben (UV-Sampling)': '{name} · {count} mesh part(s) · texture colors (UV sampling)',
    '{name} · {count} Original-DW2-Animation(en) · glTF-Materialien': '{name} · {count} original DW2 animation(s) · glTF materials',
    ' · Blinkdaten erkannt; Augenframes bei unterstützten Modellen aktivierbar': ' · blink metadata detected; eye poses available on supported models',
    'Sprache / Language': 'Language / Sprache',
    ('Eine neue Spiel-BIN wird erstellt.\n\nDigimon: {digimon}\n'
     'Native TIM: {width}×{height}, {bpp}-Bit\n'
     'Quelle: {png}\nZiel: {dest}\n\n'
     'Die Farben werden auf die PlayStation-Palette reduziert. '
     '3D-Geometrie, UV-Koordinaten und Animationen werden NICHT aus der Projektdatei übernommen.\n\n'
     'Die Original-BIN bleibt unverändert. Fortfahren?'):
       ('A new game BIN will be created.\n\nDigimon: {digimon}\n'
        'Native TIM: {width}×{height}, {bpp}-bit\n'
        'Source: {png}\nDestination: {dest}\n\n'
        'Colors will be quantized to the PlayStation palette. '
        '3D geometry, UV coordinates and animations will NOT be transferred from the project file.\n\n'
        'The original BIN remains unchanged. Continue?'),
    # Dynamic status/log strings: format placeholders are intentional.
    "{image}\n{count} Digimon · {files} Dateien": "{image}\n{count} Digimon · {files} files",
    "{count} Digimon · {files} Dateien": "{count} Digimon · {files} files",
    "{count} Modell-IDs gefunden": "{count} model IDs found",
    "Ausgewählt: {name} – zum Laden klicken": "Selected: {name} – click to load",
    "Gespeichertes Ersatzmodell geladen: {path}": "Saved replacement model loaded: {path}",
    "Modell geöffnet: {path}": "Model opened: {path}",
    "Geladen: {name}": "Loaded: {name}",
    "Für {name} wurden keine Modelldaten gefunden.": "No model data found for {name}.",
    "Konvertiere {name} (Modell + Animationen) …": "Converting {name} (model + animations) …",
    "3D-Objekt ersetzt (Projekt): {path}": "3D object replaced (project): {path}",
    "Ersatzmodell aktiv – Originaldatei unverändert": "Replacement model active – original file unchanged",
    "Originalmodell für dieses Digimon wiederhergestellt": "Original model restored for this Digimon",
    "3D exportiert: {path}": "3D exported: {path}",
    "PNG gespeichert: {path}": "PNG saved: {path}",
    "Native TIM-Vorlage exportiert: {path} ({width}×{height}, {bpp}-bit)": "Native TIM template exported: {path} ({width}×{height}, {bpp}-bit)",
    "Native TIM-Ersatztextur wählen ({width}×{height})": "Choose Native TIM Replacement Texture ({width}×{height})",
    "Ersatztextur muss PNG mit {width}×{height} Pixeln sein.": "Replacement texture must be a {width}×{height} PNG.",
    "Ziel-CUE existiert bereits: {path}": "Destination CUE already exists: {path}",
    "Image-Kopie mit TIM-Ersatz wird erstellt: {path}": "Creating game image copy with TIM replacement: {path}",
    "Neue Spiel-BIN erstellt: {name}": "New game BIN created: {name}",
    "Textur in Projektkopie ersetzt: {path}": "Texture replaced in project copy: {path}",
    "Native TIM in neue Spiel-BIN geschrieben.\n\n{path}\n{sectors} Sektor(en) mit gültiger EDC/ECC neu geschrieben.": "Native TIM written to new game BIN.\n\n{path}\n{sectors} sector(s) rewritten with valid EDC/ECC.",
    "\nCUE-Datei: {path}": "\nCUE file: {path}",
    "\n\nOriginal-Image nicht verändert. Bitte die NEUE BIN/CUE im Emulator laden.": "\n\nOriginal image unchanged. Load the NEW BIN/CUE in your emulator.",
    "Viewer: VTK mit glTF-Animationen aktiviert": "Viewer: VTK with glTF animations enabled",
    "Viewer: VTK nicht verfügbar; animiertes glTF benötigt vtk>=9.3": "Viewer: VTK unavailable; animated glTF requires vtk>=9.3",
}


def translate(source: str, language: str = "de", **values) -> str:
    """Translate an exact German source string and optionally interpolate fields."""
    if language not in LANGUAGES:
        language = "de"
    result = EN.get(source, source) if language == "en" else source
    return result.format(**values) if values else result


# Updated native texture workflow: this uses DW2's face-selected palettes,
# not the dummy palette in its ordinary TIM header.
EN.update({
    'Original-TIM exportieren (PNG, inkl. Augen)': 'Export Original TIM (PNG, Including Eyes)',
    'Originale Digimon-TIM inklusive erkannter Augenstellungen exportieren und in eine NEUE Spiel-BIN schreiben. Die unteren 32 Zeilen sind reserviert und werden automatisch ignoriert. Nur Textur – kein OBJ-/GLB-Geometrieimport!': 'Export the original native Digimon TIM, including detected eye poses, and write it into a NEW game BIN. The bottom 32 reserved rows are ignored automatically. Texture only – no OBJ/GLB geometry import.',
    ('Diese PNG zeigt die echten DW2-Farben pro Modellfläche. '
     'Bitte diese neue Vorlage bearbeiten – NICHT die alte, falsch dekodierte TIM-PNG aus v2.1/v2.2. '
     'Beim Schreiben bleiben die im Modell eingebetteten Farbpaletten erhalten.'):
    ('This PNG shows the real DW2 colors for each model face. '
     'Edit this NEW template, NOT an incorrectly decoded native PNG from v2.1/v2.2. '
     'The real embedded game palettes are preserved when patching.'),
    ('Eine neue Spiel-BIN wird erstellt.\n\nDigimon: {digimon}\n'
     'Native TIM: {width}×{height}, {bpp}-Bit\n'
     'Quelle: {png}\nZiel: {dest}\n\n'
     'Die Farben wurden in der Vorschau geprüft und pro Modellfläche in die 16-Farben-Palette umgewandelt. '
     'Für neue Farben werden auch die nativen Paletten aktualisiert. '
     'Nutze ausschließlich eine NEU exportierte native Vorlage aus v2.4. '
     '3D-Geometrie, UV-Koordinaten und Animationen werden NICHT aus der Projektdatei übernommen.\n\n'
     'Die Original-BIN bleibt unverändert. Fortfahren?'):
    ('A new game BIN will be created.\n\nDigimon: {digimon}\n'
     'Native TIM: {width}×{height}, {bpp}-bit\n'
     'Source: {png}\nDestination: {dest}\n\n'
     'The colors were verified in the PS1 preview and encoded using the 16-color palettes per model face. '
     'The native game palettes are updated when new colors are required. '
     'Use only a NEW native texture exported with v2.4. '
     'The project’s 3D geometry, UV coordinates and animations are NOT transferred.\n\n'
     'The original game BIN remains unchanged. Continue?'),
})

# Backward-compatible translation for earlier v2.3 dialog messages.
EN.update({
    'Original-TIM exportieren (PNG, inkl. Augen)': 'Export Original TIM (PNG, Including Eyes)',
    'Originale Digimon-TIM inklusive erkannter Augenstellungen exportieren und in eine NEUE Spiel-BIN schreiben. Die unteren 32 Zeilen sind reserviert und werden automatisch ignoriert. Nur Textur – kein OBJ-/GLB-Geometrieimport!': 'Export the original native Digimon TIM, including detected eye poses, and write it into a NEW game BIN. The bottom 32 reserved rows are ignored automatically. Texture only – no OBJ/GLB geometry import.',
    ('Eine neue Spiel-BIN wird erstellt.\n\nDigimon: {digimon}\n'
     'Native TIM: {width}×{height}, {bpp}-Bit\n'
     'Quelle: {png}\nZiel: {dest}\n\n'
     'Die Farben werden pro Modellfläche auf deren originale PlayStation-Palette abgebildet. '
     'Die versteckten Farbpaletten bleiben unverändert. '
     'Nutze ausschließlich eine NEU exportierte native Vorlage aus v2.3. '
     '3D-Geometrie, UV-Koordinaten und Animationen werden NICHT aus der Projektdatei übernommen.\n\n'
     'Die Original-BIN bleibt unverändert. Fortfahren?'):
    ('A new game BIN will be created.\n\nDigimon: {digimon}\n'
     'Native TIM: {width}×{height}, {bpp}-bit\n'
     'Source: {png}\nDestination: {dest}\n\n'
     'The colors are mapped to the ORIGINAL face palettes. '
     'The game palettes are left untouched. '
     'Use only a newly exported native texture. '
     'The project’s 3D geometry, UV and animation data are NOT transferred.\n\n'
     'The original game BIN remains unchanged. Continue?'),
})

# Version 2.8: inform about native-reserved pixels while retaining all paint
# changes on valid body and eye texture areas.
EN.update({
    'Original-TIM exportieren (PNG, inkl. Augen)': 'Export Original TIM (PNG, Including Eyes)',
    'Originale Digimon-TIM inklusive erkannter Augenstellungen exportieren und in eine NEUE Spiel-BIN schreiben. Die unteren 32 Zeilen sind reserviert und werden automatisch ignoriert. Nur Textur – kein OBJ-/GLB-Geometrieimport!': 'Export the original native Digimon TIM, including detected eye poses, and write it into a NEW game BIN. The bottom 32 reserved rows are ignored automatically. Texture only – no OBJ/GLB geometry import.',
    'Hinweis: {locked} geänderte Pixel in den unteren 32 Paletten-Zeilen und {unmapped} Pixel außerhalb gültiger Modell-/Augenflächen werden bewusst ignoriert. Sie sind im nativen DW2-Format nicht als normale Textur beschreibbar. Maßgeblich ist die rechte PS1-Vorschau.':
        'Notice: {locked} modified pixels in the bottom 32 palette rows and {unmapped} pixels outside valid model/eye surfaces are intentionally ignored. They cannot be written as normal textures in the native DW2 format. The right-hand PS1 preview is authoritative.',
    'Die PNG enthält keine wirksamen Änderungen an den Körper- oder Augenflächen. Änderungen außerhalb dieser Flächen bzw. in den unteren 32 Palette-Zeilen werden aus Sicherheitsgründen nicht ins Spiel geschrieben.':
        'This PNG contains no applicable changes to body or eye surfaces. Edits outside those surfaces or in the bottom 32 palette rows are intentionally not written to the game.',
})

# Version 2.8
EN.update({
    'Kein Digimon gefunden': 'No Digimon found',
    'Hinweis: Referenzierte Datei nicht gefunden und übersprungen: {name}': 'Notice: referenced file not found and skipped: {name}',
    'Programm beenden': 'Quit Program',
    'Ein Vorgang läuft noch (Image lesen, Konvertieren oder BIN schreiben). Jetzt beenden? Eine halb geschriebene BIN wird nicht übernommen.': 'An operation is still running (reading the image, converting or writing a BIN). Quit now? A half-written BIN will not be kept.',
})

# Standalone viewer 3.0 controls.
EN.update({
 'DW2 · 3D Viewer v3.0':'DW2 · 3D Viewer v3.0',
 'PNG importieren':'Import PNG','PNG exportieren':'Export PNG',
 'Augen vollständig ersetzen':'Replace All Eye Poses','OBJ importieren & riggen':'Import & Rig OBJ',
 'Änderungen':'Changes','Texturen':'Textures','Ansicht':'View','Protokoll':'Log',
 'Neues Image exportieren':'Export New Image','Image überschreiben …':'Overwrite Image …',
 'Ausgewählte Änderung verwerfen':'Discard Selected Change','Mod-Projekt speichern':'Save Mod Project',
 'Mod-Projekt laden':'Load Mod Project','Native PNG inkl. Augen exportieren':'Export Native PNG Including Eyes',
 'Vorschau-Textur ersetzen':'Replace Preview Texture','Externe 3D-Datei ansehen':'View External 3D File',
 'Nachbarmodelle im Hintergrund vorbereiten':'Prepare Neighbor Models in Background',
 '3D-Szenen im RAM':'3D Scenes in RAM','Digimon suchen …':'Search Digimon …',
 'Doppelklick: öffnen\n↑ / ↓: sofort zum nächsten Modell':'Double-click: open\n↑ / ↓: load next model',
 'Spiel-Image öffnen oder externe 3D-Datei laden':'Open Game Image or Load External 3D File',
 'Noch kein Modell':'No Model Yet','0 Dateien vorgemerkt':'0 Files Staged',
 'PNG-, Modell- und Animationsänderungen werden gesammelt. Erst Speichern schreibt das Image.':'PNG, model and animation edits are staged. Saving writes the image.',
 'Native PNG: 128×256, passende Paletten und erkannte Augen. Vorschau-Texturen ändern nur das Projektmodell.':'Native PNG: 128×256, matching palettes and detected eyes. Preview textures only change the project model.',
 'Farben stimmen – vormerken':'Colors Match – Stage Change',
})

# Standalone native name editing 3.1.
EN.update({
 'Namen ändern':'Change Name',
 'DW2 · 3D Viewer v3.1':'DW2 · 3D Viewer v3.1',
 'Namen-, PNG-, Modell- und Animationsänderungen werden gesammelt. Erst Speichern schreibt das Image.':'Name, PNG, model and animation edits are staged. Saving writes the image.',
})

EN.update({'HD-PNG in Vorschau':'HD PNG in Preview','DW2 · 3D Viewer v3.2':'DW2 · 3D Viewer v3.2'})

EN.update({'DW2 · 3D Viewer v3.3':'DW2 · 3D Viewer v3.3','Farbübernahme ins Spiel':'Game Color Import'})

EN.update({'DW2 · 3D Viewer v3.4':'DW2 · 3D Viewer v3.4','PNG ersetzen · Vollfarben':'Replace PNG · Full Color','Vollfarben-Projekt speichern':'Save Full Color Project','Vollfarben-Projekt laden':'Load Full Color Project','PS1-Image exportieren':'Export PS1 Image','Augen ins PS1-Image':'Eyes into PS1 Image'})

EN.update({
 'DW2 · 3D Viewer v3.5':'DW2 · 3D Viewer v3.5',
 'Wie v3.1 · automatische Paletten':'Like v3.1 · automatic palettes',
 'Farbschutz · kleine Änderungen bevorzugen':'Color protection · favor small edits',
 'Exakt RGB555 · nur wenn alle Farben passen':'Exact RGB555 · only if all colors fit',
 'Spieltextur · Paletten':'Game texture · palettes',
 'Vollfarben nur im Viewer ersetzen':'Replace full color in viewer only',
 'PNG ins PS1-Image importieren …':'Import PNG into PS1 image …',
 'Native PNG-Vorlage exportieren':'Export native PNG template',
 'Nativen Augenatlas exportieren':'Export native eye atlas',
})

EN.update({
 'DW2 · 3D Viewer v3.6':'DW2 · 3D Viewer v3.6',
 'Digimon ersetzen · Modell + Animationen':'Replace Digimon · model + animations',
})

EN.update({'DW2 · 3D Viewer v3.6.1':'DW2 · 3D Viewer v3.6.1'})

EN.update({'DW2 · 3D Viewer v3.7':'DW2 · 3D Viewer v3.7'})
