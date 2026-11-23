#!/usr/bin/env bash
# Baut den DW3-Konverter (third_party/dw3_converter, MIT) für die App und die Web-Version.
#   tools/build_dw3conv.sh android   -> app/src/main/jniLibs/<ABI>/libdw3conv.so (ausführbares Programm, NDK)
#   tools/build_dw3conv.sh wasm      -> build/dw3conv/dw3conv.js (WebAssembly, Emscripten)
#   tools/build_dw3conv.sh native    -> build/dw3conv/dw3_converter (für die Tests auf dem Rechner)
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=third_party/dw3_converter
FILES="$SRC/cli.cpp $SRC/model.cpp $SRC/game.cpp $SRC/dw2.cpp $SRC/gltf.cpp $SRC/stage_export.cpp"
mkdir -p build/dw3conv
case "${1:-}" in
  android)
    NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_LATEST_HOME:-}}"
    [ -n "$NDK" ] || { echo "ANDROID_NDK_HOME fehlt"; exit 1; }
    BIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"
    for pair in arm64-v8a:aarch64-linux-android24 x86_64:x86_64-linux-android24; do
      ABI=${pair%%:*}; TRIPLE=${pair#*:}
      mkdir -p app/src/main/jniLibs/$ABI
      # Statisch gegen libc++ gelinkt, PIE: Android startet es aus nativeLibraryDir.
      "$BIN/$TRIPLE-clang++" -std=c++17 -O2 -fPIE -pie -static-libstdc++ -I"$SRC" $FILES \
        -o app/src/main/jniLibs/$ABI/libdw3conv.so
      "$BIN/llvm-strip" app/src/main/jniLibs/$ABI/libdw3conv.so
      echo "Android $ABI: $(stat -c %s app/src/main/jniLibs/$ABI/libdw3conv.so) Bytes"
    done ;;
  wasm)
    # Ohne MODULARIZE (das liefert immer ein Promise): synchron, damit Python im Worker es direkt
    # aufrufen kann. Die Ausgabe wird unten in eine Fabrik createDw3Conv(optionen) gehüllt.
    em++ -std=c++17 -O2 -fexceptions -I"$SRC" $FILES -o build/dw3conv/raw.js \
      -sWASM_ASYNC_COMPILATION=0 -sSINGLE_FILE=1 \
      -sALLOW_MEMORY_GROWTH=1 -sINVOKE_RUN=0 -sEXIT_RUNTIME=0 -sENVIRONMENT=worker,node \
      -sEXPORTED_RUNTIME_METHODS=FS,callMain -sFORCE_FILESYSTEM=1 -sSTACK_SIZE=4MB
    {
      echo '// DW3-Konverter (third_party/dw3_converter, MIT) als WebAssembly. Gebaut mit tools/build_dw3conv.sh wasm.'
      echo 'var createDw3Conv = function (Module) { var module; Module = Module || {};'
      cat build/dw3conv/raw.js
      echo ';return Module; };'
      echo 'if (typeof module !== "undefined") module.exports = createDw3Conv;'
    } > build/dw3conv/dw3conv.js
    rm build/dw3conv/raw.js
    echo "WebAssembly: $(stat -c %s build/dw3conv/dw3conv.js) Bytes" ;;
  native)
    ${CXX:-g++} -std=c++17 -O2 -I"$SRC" $FILES -o build/dw3conv/dw3_converter
    echo "Nativ: build/dw3conv/dw3_converter" ;;
  *) echo "Aufruf: $0 android|wasm|native"; exit 2 ;;
esac
