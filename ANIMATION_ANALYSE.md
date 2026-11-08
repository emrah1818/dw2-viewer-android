# 3D Viewer – Full Animation Support (v4.2, Test-Build)

Stand: 8. November 2026. Grundlage ist der Spielcode selbst: die passende (matching)
Decompilation von Digimon World 2 im Projekt [Wyrelade/DW2-PC](https://github.com/Wyrelade/DW2-PC)
(CC0). Zitierte Funktionen stehen dort in `src/main/anim.c`, `src/main/model.c`,
`src/main/digidata.c`, `src/main/texslot.c` und `include/main/156C.h`.

**Wichtig:** In dieser Entwicklungsumgebung lag kein Spiel-Image vor. Alle Aussagen zum
*Format* sind durch den Spielcode belegt; welche der 395 Modelle welche Kanäle *tatsächlich*
nutzen, ermittelt die neue **Animationsprüfung** in der App (Mehr → „Animationsprüfung aller
Digimon“) mit deinem Image. Bestätigtes und Vermutetes ist unten getrennt.

## 1. Im Originalspiel gefundene Animationsarten (bestätigt durch den Spielcode)

| Kanal | Spielcode | Daten | Zeitverhalten |
|---|---|---|---|
| Skelettanimation | `Anim_StepModelAnim`, `Gfx_CalcModelBoneMatrices` | A–K-Dateien: je Knochen eine Tabelle mit 3×3-Matrix (s16, /4096, zeilenweise) + Translation; Clips = Zeilen mit Schlüsselindex je Knochen | 1 Zeile je 2 VBlanks (30 Bilder/s), **keine Interpolation**. `0xFF` = letztes Bild halten, `0xFE` = Sprung auf Byte-Offset im Clip (Schleife ab Zwischenbild) |
| Augen (Blinzeln) | `Gfx_AnimateModelTex`, `Gfx_AnimAllowsBlink` | `texAnimParts` Einträge 0–1 (10 Byte: Ziel, Größe, 3 Quellen) | Zufallsintervall 60–187 VBlanks; Ablauf halb (4) → zu (4) → halb (4) → offen. Bei Animations-ID 10, 20, 21, 22, 100 bleiben die Augen geschlossen |
| Texturanimation „Zyklus“ | `Gfx_AnimateModelTex` | `texAnimParts` Einträge 2–9, Ende `0xFF`/`0xFE` | 3 Bilder, je 8 VBlanks (Zyklus 24 VBlanks), läuft immer |
| Texturanimation „erweitert“ | `Gfx_AnimateModelTex`, `GfxModelTexAnim` (42 Byte) | nach `0xFE`: bis 10 Einträge mit 2 Rechtecken je Bild, Periode und Startphase | 1 Bild je 2 VBlanks, bis 8 Bilder, eigene Phase |
| Halbtransparenz / Mischmodus | `Gfx_AddQuadsGT4`, `Gfx_AddTrisGT3` | erster Quad- und Dreiecksblock je Knochen; ABR in Bit 5–6 des tpage-Worts jeder Fläche | – |
| Animationszuordnung | `Digi_GetAnimFile`, `DigiData` | MODELDT0/1/2: `animFiles[11]` = Datei-IDs für Slot A–K (auch Dateien anderer Digimon) | Animations-ID = Slot × 10 + Clipindex |

Technischer Mechanismus der Texturanimation: Es werden **VRAM-Rechtecke kopiert**
(`DR_MOVE`) – innerhalb der 128×256-Textur des Modells. Die Kopien bleiben stehen; das
nächste Bild überschreibt sie. Liegt ein Ziel in den Zeilen 224–255, ändert sich damit auch
eine Palette (Palettenwechsel über denselben Mechanismus).

### Nicht gefunden (bestätigt)
- **Vertex-/Mesh-Animation:** Vertices und Normalen sind je Knochen statisch
  (`Gfx_ProjectModelVerts`). Verformungen entstehen nur über die Knochenmatrizen
  (die Skalierung und Scherung enthalten dürfen).
- **UV-Animation / UV-Scrolling:** UVs werden unverändert aus der Fläche übernommen.
- **Palettenanimation als Modelldaten:** `clutRow`/`tpageFlags` werden zur Laufzeit von
  Kampf-/Statuscode gesetzt (z. B. Treffer- oder Sonderdarstellung), nicht aus der Modelldatei.
  Das ist kein Animationskanal des Modells und wird bewusst nicht nachgebildet.

## 2. Was dem Viewer bis v4.1 fehlte

1. **Texturanimation (Zyklus und erweitert) fehlte vollständig.** Der Block hinter den
   Augendaten wurde als „4 Byte sonstige Metadaten“ behandelt.
2. **Augen:** Der zweite Augeneintrag (Bytes 10–19) wurde fälschlich als weitere
   *Quellposen* des ersten Auges gelesen; Rhythmus geschätzt (3,8 s), Spielregel
   „Augen zu bei bestimmten Animationen“ fehlte.
3. **Mischmodus:** Alle halbtransparenten Flächen wurden als 50 %-Mischung gezeigt; das
   tpage-Wort (ABR) wurde nicht gelesen. Additive/subtraktive Teile wirkten dadurch matt.
4. **Clip-Tabelle:** Der Konverter brach beim ersten leeren Tabelleneintrag (0) ab – Clips
   hinter einer Lücke gingen verloren, und Clipnummern verschoben sich gegenüber dem Spiel.
5. **Schleifen:** Jede Animation lief als Endlosschleife ab Bild 1; Schleifenpunkt
   (`0xFE`-Offset) und Einmal-Animationen (`0xFF`) wurden ignoriert.
6. **Tempo/Interpolation:** Lineare Interpolation statt 30-Hz-Schritten des Spiels.
7. **Transformation:** Matrizen wurden für glTF in Translation/Rotation/Skalierung zerlegt;
   Scherung ging dabei verloren.
8. **Zuordnung:** Animationen wurden nur über gleichen Dateinamen gefunden. Laut
   US-Dateitabelle gibt es **395 M-Dateien, aber nur 202 A-Dateien** (bestätigt aus
   `native_file_ids_us.json`). Modelle ohne eigene A–K-Dateien zeigten keine Animation, auch
   wenn das Spiel ihnen über MODELDT Animationen zuweist.

## 3. Technische Ursachen
Der Viewer folgte dem Format des Fremdkonverters (jype, dw2_model_converter), der nur
Geometrie, Textur und Knochenanimation als glTF ausgibt. glTF kann weder VRAM-Kopien noch
PS1-Mischmodi, Schleifenpunkte oder Scherung ausdrücken; diese Daten wurden deshalb nie
übertragen.

## 4. Implementierte Änderungen
- `dw2studio/core/native_anim.py` (neu): Lesen von Clip-Tabelle, texAnimParts, ABR,
  MODELDT-Zuordnung, Matrixprüfung – Feld für Feld nach dem Spielcode.
- `native_gltf.py`: Clips mit Spielindex (Lücken bleiben erhalten, Rückfall auf die alte
  tolerante Lesart), Material je (Halbtransparenz, CLUT, ABR), Loop-Angaben in den
  glTF-extras und eine Nutzlast `dw2_native` (Animationsdateien, Texturwörter, texAnimParts).
- `android_api.py`: Animationsdateien wie `Digi_GetAnimFile` (MODELDT); jede Datei wird gegen
  die Knochenzahl geprüft, sonst Dateiname als Rückfall. Neue Funktionen
  `animation_audit` (Prüfung aller Modelle, JSON + CSV) und `native_files_export` (ZIP).
- `www/native_anim.js` (neu): Player wie `Anim_StepModelAnim` (VBlank-genau, Loop/Halten),
  VRAM-Nachbildung wie `Gfx_AnimateModelTex` (inkl. Blinzelregel und Ausführungsreihenfolge
  der Ordnungstabelle), Dekodierung identisch zum Konverter.
- `www/viewer.js`: Knochen mit den Originalmatrizen (keine Zerlegung), Texturen als
  dynamische Texturen (nur geänderte Rechtecke werden neu dekodiert), STP-Texel als zweiter
  Durchgang mit dem PS1-Mischmodus (50 %, additiv, subtraktiv, +25 %).
- Oberfläche: Statuszeile (Spiel-ID, Bild, Schleife/einmalig), ▶ startet beendete
  Einmal-Animationen neu, optional „Bewegung glätten“ und „Einmal-Animationen wiederholen“
  (beide als *nicht original* gekennzeichnet, standardmäßig aus), Diagnosemodus mit einzeln
  abschaltbaren Kanälen, Rohdaten-Export (ZIP).
- Importierte fremde Modelle und alte Caches ohne Nutzlast laufen wie bisher über glTF.

## 5. Welche Digimon profitieren
- **Bestätigt (Format):** alle Modelle mit Halbtransparenz, mit Texturanimation, mit
  Augen, mit Einmal-Animationen oder Schleifenpunkten sowie alle Modelle, deren
  Animationen über MODELDT aus anderen Dateien kommen.
- **Vermutung (noch mit deinem Image zu bestätigen):** Die statisch wirkenden Flammen von
  **Meramon** (Datei `M009MERA`) und **Birdramon** (`M021BIRD`) sind Texturanimationen
  (Zyklus und/oder erweitert) und teils additive Halbtransparenz. Das passt zu den Videos
  (Flammenmuster ändert sich, Flügelflammen leuchten heller als im alten Viewer), ist hier
  aber nicht mit den Originaldaten geprüft. Die Animationsprüfung zeigt es eindeutig
  (Spalten `tex_cycles`, `tex_extended`, `abr`).
- Die genaue Liste liefert der Prüfbericht (`animationspruefung_*.csv`, Spalte
  `viewer_v41_missing`).

## 6. Offene Punkte
- **Mit echten Daten prüfen:** Animationsprüfung auf dem Handy ausführen und den Bericht
  (oder die Rohdaten-ZIPs von Meramon/Birdramon) zurückgeben; danach Feinabgleich.
- Zeichenreihenfolge: Die PS1 sortiert per Ordnungstabelle ohne Tiefenpuffer; der Viewer
  nutzt einen Tiefenpuffer. Bei überlappenden halbtransparenten Teilen kann die Reihenfolge
  abweichen.
- Beleuchtung entspricht nicht exakt den drei PS1-Flachlichtern (kein Animationsthema).
- GLB/glTF-Export: weiterhin Translation/Rotation/Skalierung mit linearer Interpolation;
  Scherung, Schleifenpunkte und Texturanimation sind dort nur in den extras enthalten.
- `rig_animation.py` (Knochenkorrektur beim Rig-Import) liest die Matrix transponiert
  gegenüber dem Spielcode. Die Anzeige ist davon nicht betroffen; vor weiterer Nutzung der
  Knochenkorrektur prüfen.

## 7. Tests (alle erfolgreich)
- `tests/test_native_anim.py` – 26 Prüfungen (Spielformat: Lücke, Loop, Halten, Scherung,
  texAnimParts, ABR, MODELDT-Zuordnung inkl. geteilter Animation, Nutzlast, Prüfung, ZIP).
- `tests/test_native_anim.mjs` – 21 Prüfungen der JS-Wiedergabe (30 Hz, Loop ab Zeile 1,
  Halten/Neustart, D·M·D-Matrizen mit Scherung, Dekodierung identisch zu Python,
  Zyklus 8/16/24 VBlanks, Blinzelablauf 47/51, Augen-zu-Regel, erweiterte Phase).
- `tests/e2e_anim.py` – 22 Schritte im echten Browser (Auswahl, Loop, Pause/Fortsetzen,
  Geschwindigkeit 0,5×/2×, Wechsel, Halten, Diagnose, Kanalschalter, Digimon-Wechsel,
  geteilte Animation, Prüfdialog, Export, keine JS-Fehler).
- Regression: `test_android_api.py`, `test_android_edit.py` (35), `e2e_ui.py` (20/20).
