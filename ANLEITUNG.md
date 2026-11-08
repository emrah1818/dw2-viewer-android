# DW2 3D Viewer 4.0 – Android

## Test-APK bekommen (einmalig ca. 10 Minuten, kostenlos)

1. Auf github.com ein Konto anlegen und ein neues Repository erstellen (z. B. `dw2-viewer-android`, privat ist okay).
2. "uploading an existing file" wählen und den **Inhalt** dieses Ordners hochladen (alle Dateien und Ordner, auch `.github`).
   Tipp: Am PC per Drag & Drop; der Ordner `.github` muss mit hochgeladen werden.
3. Reiter **Actions** öffnen → "Android APK - DW2 3D Viewer" → **Run workflow**. Der Build dauert ca. 10–15 Minuten.
4. Danach unter **Releases → v5.1** die Datei `DW2_3D_Viewer_v5.1.apk` direkt auf dem Handy herunterladen.
5. Antippen → Installation aus dieser Quelle erlauben → installieren.

Jede Änderung, die du hochlädst, baut automatisch eine neue Test-APK.

## Bedienung

- **BIN / ISO öffnen**: eigenes Image wählen. Es wird in den App-Speicher kopiert (freier Speicher ≈ Image-Größe × 2 nötig, beim Speichern × 3).
- **Digimon**: Liste mit Suche; Antippen öffnet das 3D-Modell.
- **3D**: ein Finger drehen, zwei Finger zoomen/verschieben, ◀ ▶ nächstes Digimon, Animation wählen, Tempo, Kamera zurücksetzen.
  Unter "Ansicht": Raster, Drahtgitter, Pixel-Look, Licht, Hintergrund, Textur als PNG und Modell als GLB exportieren.
- **Bearbeiten**: Name, Typ & Specialty, Attacken (Standard, Gegner-Techniken, globale MP/Power), Gegnerwerte & EXP,
  Spielstand/Memorycard (HP/MP, Angriff, Verteidigung, Tempo, EXP, Eltern).
- **Änderungen**: Vormerkungen ansehen/verwerfen, neues Image exportieren, Mod-Projekt (.dw2mod) speichern/laden,
  Spielstand exportieren. Das Original bleibt immer unverändert.

## Texturen und 3D-Modelle (ab 4.1)

Im Reiter **3D** unter dem Modell:
- **Texturen:** PNG exportieren (1×–4×), PNG importieren / Textur ersetzen (mit Vorschau Original · deine PNG · Spielergebnis), Augen ersetzen. Palettenmodus „Wie v3.1“ ist Standard.
- **3D-Modelle:** GLB/glTF exportieren (mit Knochen, Animationen und Spieldaten), 3D-Datei importieren (ansehen oder ersetzen), Originalmodell wiederherstellen.
- **Bearbeitet/Original** schaltet zwischen Original und vorgemerkter Fassung um; ↶/↷ machen Schritte rückgängig.
- Änderungen sind erst vorgemerkt. Unter **Änderungen**: „Neues Image exportieren“ oder „Image überschreiben …“ (mit Sicherung).

Details, Testergebnisse und Grenzen: `PRUEFUNG_ANDROID_v4_1.md`.

## Veröffentlichen (Google Play)

1. Google-Play-Developer-Konto (einmalig 25 US-$).
2. Signaturschlüssel erzeugen (einmalig, gut aufbewahren!):
   `keytool -genkeypair -v -keystore release.jks -alias dw2 -keyalg RSA -keysize 4096 -validity 10000`
3. Im GitHub-Repository unter Settings → Secrets → Actions anlegen:
   `ANDROID_KEYSTORE_BASE64` (Inhalt von `base64 -w0 release.jks`), `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` (= dw2), `ANDROID_KEY_PASSWORD`.
4. Workflow erneut starten → Artefakt "DW2-3D-Viewer-release" enthält die `.aab` für die Play Console.
5. Store-Icon: `store/play_icon_512.png`. Die App ist auf Android 16 (API 36) ausgerichtet, wie Google Play es seit 31.08.2026 verlangt.

Hinweis: Die App darf keine Spieldaten enthalten. Im Store-Eintrag klar schreiben, dass Nutzer ihr eigenes Image benötigen,
und keine Original-Logos/Screenshots von Bandai Namco als Werbung verwenden. Name und Logo sind ein Risiko bei der Prüfung
(Markenrecht "Digimon") – ein neutraler App-Name ist sicherer.

## Lokale Prüfung (optional)

`python tests/test_android_api.py` prüft die Python-Brücke mit einem synthetischen ISO und Spielstand.
