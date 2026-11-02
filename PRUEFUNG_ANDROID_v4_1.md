# DW2 3D Viewer Android 4.1 – Prüfbericht

Stand: 02.11.2026. Grundlage: Windows-Quellcode v4.0 (enthält die v3.1-Palettenlogik als Modus „v31“).

## Legende

- **Getestet (automatisch):** mit synthetischen DW2-Modellen und echtem ISO-Aufbau geprüft, Ergebnis mit den Windows-Kernroutinen verglichen.
- **Getestet (Oberfläche):** echte App-Oberfläche im Chromium-Browser (Handyformat) mit echtem Python-Kern durchgeklickt (`tests/e2e_ui.py`).
- **Nicht getestet:** braucht echte Spieldaten, ein Android-Gerät oder einen Emulator. Das kann nur der Nutzer prüfen.

## 1. Farbpaletten (Priorität 1)

| Prüfung | Ergebnis |
|---|---|
| v3.1-Golden-Test der Windows-Version (4 Fälle: Fläche, viele Farben, Umfärben, 5 Augenposen) auf dem Android-Kern | **bytegleich bestanden** |
| 211 weitere Kern-Tests der Windows-Suite auf dem Android-Kern (Paletten, Augen, TIM, Transfer, Relocation, Werte …) | **bestanden** (GUI-/VTK-Tests nicht lauffähig ohne Qt, nicht relevant) |
| PNG-Import Android == `replace_tim(…, palette_mode='v31')` der Windows-Version | **bytegleich** |

Ergebnis der Prüfung „ist v3.1 die beste Implementierung?“: Die Windows-Version v4.0 nutzt beim PNG-Import standardmäßig genau den aus v3.1 wiederhergestellten Algorithmus (`palette_v31.py`, Golden-Daten aus der echten v3.1). Die Android-App verwendet diesen Code unverändert, Modus „Wie v3.1“ ist Standard. „Farbschutz“ und „Exakt RGB555“ sind wie unter Windows als Alternativen wählbar.

Anzeige: Jede Fläche wird mit genau ihrer PS1-Palette dargestellt. Der Windows-Viewer schätzt die Palette dagegen je 4×4-Block. Wo diese Schätzung stimmt, sind die Farben identisch; wo sie falsch lag (Löcher, falsche Farben an Kanten), ist Android näher am Spiel.

## 2. Funktionen

| Funktion | Status |
|---|---|
| PNG exportieren (nativer Atlas mit allen Augenposen, 1×–4×) | Getestet (automatisch + Oberfläche) – identisch zur Windows-Dekodierung |
| PNG importieren / Textur ersetzen (1×–4×, BOX/NEAREST, Vorschau Original/PNG/PS1-Ergebnis, Qualitätswerte) | Getestet (automatisch + Oberfläche) |
| Augen ersetzen | Implementiert (Windows-Kette identisch), automatisch nur indirekt getestet |
| GLB/glTF exportieren (Geometrie, Paletten-Texturen, Knochen, A–K-Animationen, eingebettete Spieldaten) | Getestet |
| GLB/glTF/OBJ importieren und ansehen | Getestet (Oberfläche) |
| Digimon ersetzen mit DW2-Austausch-GLB (Modell + alle Animationen) | Getestet (automatisch + Oberfläche) |
| Fremdes GLB/glTF/OBJ einbauen mit Knochenzuordnung (Vorschlag per Name/nächstem Knochen, Größe, Textur) | Getestet mit kleinem Testmodell |
| Native Modell-BIN ersetzen | Implementiert, nicht separat getestet |
| Live-Vorschau nach jeder Änderung | Getestet |
| Original / Bearbeitet umschalten | Getestet |
| Rückgängig / Wiederherstellen (alle Spiel- und Spielstand-Änderungen, 50 Schritte) | Getestet |
| Originalmodell wiederherstellen | Implementiert |
| Neues Image exportieren | Getestet (Wiederöffnen, Bytes geprüft) |
| Image überschreiben (Sicherheitsabfrage, Sicherung in der App, „Sicherung exportieren“) | Getestet (Python + Oberfläche); das Schreiben in den Android-Dateispeicher selbst nicht getestet |
| Bisherige Funktionen (Name, Typ, Specialty, Attacken, Gegnerwerte, Spielstand, Mod-Projekt, Sprache) | Regressionstests bestanden |

## 3. Nicht getestet / Einschränkungen

- **Test 9 (Emulator):** nicht möglich ohne Spiel-Image und Emulator. Jedes bearbeitete Image bitte in DuckStation o. ä. prüfen.
- **Echte Spieldaten:** Alle automatischen Tests nutzen künstliche Modelle. Echte Digimon können Sonderfälle enthalten.
- **Fremde 3D-Modelle:** Das PS1-Format erlaubt nur die Geometrie, die in den vorhandenen Modellplatz passt (z. B. wenige hundert Dreiecke), max. 256 Punkte je Knochen, 16 Farben je Palette. Größere Modelle werden mit klarer Meldung abgelehnt. Skinning/Gewichte werden nicht übernommen: Jede Gruppe hängt starr an einem Knochen (wie unter Windows).
- **Knochenzuordnung:** je Gruppe (Mesh/OBJ-Gruppe), nicht je einzelner Fläche wie im Windows-Dialog.
- **Fremdtextur:** wird auf 128×224 und 14 Farben reduziert (Windows-Rig-Import verlangt ≤ 16 Farben je Palette).
- **Austausch-Export:** Digimon, deren Animationen der strenge Schreibleser ablehnt (überlappende Datenblöcke), werden nur zur Ansicht exportiert (ohne eingebettete Spieldaten). Das ist unter Windows genauso.
- **Domains/Sektoren:** In der Windows-3D-Viewer-Oberfläche und der Android-App gibt es keine solchen Bereiche; entfernt wurde nichts.
- **Vollfarben nur im Viewer** (HD-Texturen ohne Spiel-Patch) wurde bewusst nicht übernommen (Mod-Studio-Funktion).

## 4. Tests ausführen

```
python tests/test_android_api.py      # Brücke, Werte, Speichern
python tests/test_android_edit.py     # Tests 1–8 + Undo/Redo + Überschreiben (36 Prüfungen)
python tests/e2e_ui.py                # Oberfläche im Browser (benötigt Playwright + Chromium)
```
