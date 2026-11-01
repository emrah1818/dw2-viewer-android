#!/usr/bin/env bash
# Holt alles, was nicht im Repository liegt: Upstream-Konverter (mit Submodulen),
# Fallback-Header (glm, nlohmann/json, stb, tinygltf) und three.js.
# Läuft automatisch in der GitHub-Action. Lokal: Git Bash, WSL, Linux oder macOS.
set -euo pipefail
cd "$(dirname "$0")/.."
DEPS=native/deps
mkdir -p "$DEPS"
clone() { # url dir [ref]
  [ -d "$DEPS/$2" ] && return 0
  if [ -n "${3:-}" ]; then git clone --depth 1 --recurse-submodules --shallow-submodules --branch "$3" "$1" "$DEPS/$2"
  else git clone --depth 1 --recurse-submodules --shallow-submodules "$1" "$DEPS/$2"; fi
}
clone https://github.com/jype/dw2_model_converter.git dw2_model_converter
mkdir -p "$DEPS/fallback"
[ -d "$DEPS/fallback/glm" ]      || git clone --depth 1 --branch 1.0.1 https://github.com/g-truc/glm.git "$DEPS/fallback/glm"
[ -d "$DEPS/fallback/json" ]     || git clone --depth 1 --branch v3.11.3 https://github.com/nlohmann/json.git "$DEPS/fallback/json"
[ -d "$DEPS/fallback/stb" ]      || git clone --depth 1 https://github.com/nothings/stb.git "$DEPS/fallback/stb"
[ -d "$DEPS/fallback/tinygltf" ] || git clone --depth 1 --branch v2.9.3 https://github.com/syoyo/tinygltf.git "$DEPS/fallback/tinygltf"
# Beispiel-/Testquellen der Fallbacks werden nicht kompiliert (nur Header werden genutzt).

THREE=0.160.0
WWW=app/src/main/assets/www/lib
mkdir -p "$WWW/examples/jsm/loaders" "$WWW/examples/jsm/controls" "$WWW/examples/jsm/utils"
CDN=https://cdn.jsdelivr.net/npm/three@$THREE
curl -fsSL "$CDN/build/three.module.js" -o "$WWW/three.module.js"
curl -fsSL "$CDN/examples/jsm/loaders/GLTFLoader.js" -o "$WWW/examples/jsm/loaders/GLTFLoader.js"
curl -fsSL "$CDN/examples/jsm/controls/OrbitControls.js" -o "$WWW/examples/jsm/controls/OrbitControls.js"
curl -fsSL "$CDN/examples/jsm/utils/BufferGeometryUtils.js" -o "$WWW/examples/jsm/utils/BufferGeometryUtils.js"
echo "Abhängigkeiten bereit."
