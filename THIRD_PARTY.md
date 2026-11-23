# Drittanbieter-Komponenten

- Modell-/Animationsformat nach dw2_model_converter von jype (MIT, 2024); auf Android als Python-Port (dw2studio/core/native_gltf.py). Lizenz: licenses/dw2_model_converter_LICENSE
- three.js (MIT) – 3D-Darstellung
- Chaquopy (MIT), NumPy (BSD), Pillow (HPND) – Python auf Android

Die App enthält keine Spieldaten von Digimon World 2. Nutzer öffnen ihr eigenes Image.

- **DW3-Konverter** (`third_party/dw3_converter`, MIT, siehe `third_party/dw3_converter/LICENSE` und `CREDITS.md`): aus dem DW2 Mod Studio (emrah1818/dw2-dw3-viewer, v0.99); in der App als `libdw3conv.so` (Android NDK), in der Web-Version als WebAssembly.
- **DNA-Tabelle des Digi-Labors** (`dna_image.py`): Tabelleninhalt, Symboladresse und SHA-1 aus dem PC-Port/der Decompilation (emrah1818/dw2-pc-port, `src/stag2000/dna.c`, `configs/USA/sym.stag2000.txt`, `configs/USA/stag2000.yaml`).
