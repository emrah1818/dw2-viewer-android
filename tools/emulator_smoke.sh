#!/usr/bin/env bash
# Läuft im Android-Emulator (CI, x86_64): APK installieren, den DW3-Konverter der App (libdw3conv.so)
# mit dem selbst erstellten Mini-Modell ausführen, App starten und prüfen, dass Python und die
# Oberfläche ohne Absturz hochkommen.   tools/emulator_smoke.sh APP.apk
set -euo pipefail
APK=$1; PKG=app.dw2viewer.studio
adb install -r "$APK"
python3 tests/studio_extra/fixture_dw3.py /tmp/mini.bin
adb push /tmp/mini.bin /data/local/tmp/mini.bin
LIBDIR=$(adb shell pm dump $PKG | sed -n 's/^ *legacyNativeLibraryDir=\(.*\)$/\1/p' | head -1 | tr -d '\r')
[ -n "$LIBDIR" ] || LIBDIR=$(dirname "$(adb shell pm path $PKG | head -1 | sed 's/package://' | tr -d '\r')")/lib
echo "nativeLibraryDir-Basis: $LIBDIR"
CONV=$(adb shell "ls $LIBDIR/*/libdw3conv.so" | head -1 | tr -d '\r')
echo "Konverter: $CONV"
adb shell run-as $PKG sh -c "'cp /data/local/tmp/mini.bin files/mini.bin && rm -rf files/dw3out && $CONV files/mini.bin files/dw3out && ls -l files/dw3out'" | tee /tmp/conv.txt
grep -q model.glb /tmp/conv.txt && grep -q native_source.json /tmp/conv.txt
echo "OK  DW3-Konverter läuft auf Android"
adb logcat -c
adb shell am start -W -n $PKG/app.dw2viewer.MainActivity
sleep 25
adb shell pidof $PKG
adb logcat -d > /tmp/logcat.txt || true
if grep -E "FATAL EXCEPTION|AndroidRuntime: Process: $PKG|PyException|3D Viewer konnte nicht gestartet werden" /tmp/logcat.txt; then
  echo "FEHLER: Absturz oder Startfehler (logcat oben)"; exit 1
fi
adb exec-out screencap -p > shots_emulator_start.png || true
echo "OK  App gestartet, kein Absturz"
