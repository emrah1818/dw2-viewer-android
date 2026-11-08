# Original-Hintergrund von Digimon World 2 (v5.0, ergänzt in v5.1)

Der 3D-Bereich zeigt den animierten Menühintergrund des Originalspiels. Aufbau von hinten nach vorn:

1. **Grund** (`www/bg/bg_base.png`, 320×240): tiefes Dunkelblau, im Zeichenband (y 42–170) wolkiges Blau, dunkle Schattenlinien 4 px neben den kräftigen Rasterlinien.
2. **DigiCode-Zeichen** (`bg_glyphs_l.png`, `bg_glyphs_r.png`, je 579×240): „デジモンワールド“ (Digimon World), Pixel für Pixel nach dem Referenz-Screenshot gezeichnet. Zeilen 1 und 3 laufen nach links, Zeile 2 nach rechts.
3. **Raster** (`bg_grid.png`, 32×32): türkis, senkrecht alle 16 px (abwechselnd kräftig/schwach), waagerecht im Muster 8/8/16 px.
4. **Grünes Statusfenster** (v5.1) wie im Statusbildschirm: RGB 0/93/0 mit 63 % Deckkraft (aus dem Referenzbild berechnet: Grund 1/21/89 → 0/66/34, kräftige Rasterlinie → 2/121/55), mit grauer Pixelkante; Raster und Zeichen scheinen grünlich durch.
5. **Schatten** (v5.1) wie im Spiel: `main/shadow.c` lädt das Modell **0x5B** und zeichnet es auf dem Boden (y = 0) unter der Welt-X/Z-Position von Knochen 0, undurchsichtig (`Gfx_DrawTexModel` Modus 1). Der Viewer liest genau diese Datei über die Dateitabelle in SLUS_011.93 und lässt den Schatten jedem Bild der Animation folgen. Abschaltbar unter Ansicht.
6. **3D-Modell** auf transparenter Leinwand.
7. **Rahmen und Bedienleisten** im Stil der DW2-Menüfenster (`frame9.png`, `frame_tab.png`).

## Messwerte (aus den Referenzen des Nutzers)

| Merkmal | Wert | Herkunft |
|---|---|---|
| Grundfarbe Band / oben-unten | RGB 1/21/89 · 0/1/56 | Screenshot 1536×1152 (= 320×240 × 4,8) |
| Raster kräftig / schwach | RGB 32/168/144 · 24/104/128 | Screenshot |
| Zeichenfarbe | RGB 32/168/224, ~78 % deckend | Screenshot (Mittel der Zeichenpixel) |
| Zeilenabstand | 57 px | Screenshot |
| Streifen | 579 px, zwei Worte mit 29 bzw. 173 px Abstand | Screenshot (beide Zeilen damit erklärbar) |
| Tempo | 1 Spielpixel je 1/60 s (≈ 60 px/s bei 320 px Breite) | Video (30-fps-Aufnahme, eine Zeile) |
| Richtung | Zeile 1 und 3 links, Zeile 2 rechts | Video + Angabe des Nutzers |

**Unsicher und deshalb einstellbar:** das Tempo (Ansicht → „Hintergrund-Tempo“). Die Lage der dritten Zeile ist geschätzt (im Screenshot vom Dialog verdeckt). Die Originaltextur aus den Spieldateien lag nicht vor; die Ebenen sind aus den Referenzen rekonstruiert.

## Technik
- Reine CSS-Ebenen hinter dem WebGL-Canvas (`www/dw2bg.css`), die Zeichen bewegen sich per GPU-Transform in Stufen von genau einem Spielpixel (`steps(579)`), ohne Video und ohne JavaScript pro Bild.
- `--px` (CSS-Pixel je Spielpixel) wird so gewählt, dass ein Spielpixel ganze Gerätepixel belegt (ca. 260 Spielpixel über die Breite) – scharf auf jedem Display.
- Abschaltbar unter Ansicht → „Original-Hintergrund (Digimon World 2)“; dann gilt wieder die einfarbige Hintergrundfarbe. Das Boden-Raster der 3D-Szene ist standardmäßig aus.
- Erzeugung: `python tools/dw2_background/build.py <Ausgabeordner>`.
- Test: `tests/e2e_anim.py` prüft gegenläufige Zeilen, ganze Gerätepixel, transparente Leinwand und Abschalten.
