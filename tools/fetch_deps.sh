#!/usr/bin/env bash
# Holt three.js (MIT) für die 3D-Ansicht. Läuft automatisch in der GitHub-Action.
set -euo pipefail
cd "$(dirname "$0")/.."
THREE=0.160.0
WWW=app/src/main/assets/www/lib
mkdir -p "$WWW/examples/jsm/loaders" "$WWW/examples/jsm/controls" "$WWW/examples/jsm/utils"
CDN=https://cdn.jsdelivr.net/npm/three@$THREE
curl -fsSL "$CDN/build/three.module.js" -o "$WWW/three.module.js"
curl -fsSL "$CDN/examples/jsm/loaders/GLTFLoader.js" -o "$WWW/examples/jsm/loaders/GLTFLoader.js"
curl -fsSL "$CDN/examples/jsm/controls/OrbitControls.js" -o "$WWW/examples/jsm/controls/OrbitControls.js"
curl -fsSL "$CDN/examples/jsm/utils/BufferGeometryUtils.js" -o "$WWW/examples/jsm/utils/BufferGeometryUtils.js"
echo "three.js bereit."
