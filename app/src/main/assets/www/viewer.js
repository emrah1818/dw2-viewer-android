import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { AnimFile, BonePlayer, TexAnimator, decodeRect, fromBase64, glMatrix, faceOrientation, MAX_DELTA } from './native_anim.js';

/** PS1-Mischmodi (tpage ABR) für halbtransparente Texel. */
const ABR_LABEL = ['50 % (B/2+F/2)', 'additiv (B+F)', 'subtraktiv (B−F)', 'B+F/4'];

/** three.js-Viewer für die vom DW2-Konverter erzeugten glTF-Modelle (Touch: drehen, zoomen, verschieben). */
export class Viewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene = new THREE.Scene();
    this.bgColor = new THREE.Color(0x16243a);
    this.scene.background = null;   // Original-DW2-Hintergrund liegt als CSS-Ebenen hinter der Leinwand
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.01, 5000);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.screenSpacePanning = true;
    this.ambient = new THREE.AmbientLight(0xffffff, 0.9);
    this.key = new THREE.DirectionalLight(0xffffff, 1.2); this.key.position.set(3, 6, 5);
    this.fill = new THREE.DirectionalLight(0xaac4ff, 0.5); this.fill.position.set(-4, 2, -3);
    this.scene.add(this.ambient, this.key, this.fill);
    this.grid = new THREE.GridHelper(10, 20, 0x3a5578, 0x24374f);
    this.grid.visible = false;   // Boden-Raster: im Original-Hintergrund nicht vorhanden (Ansicht → Boden-Raster)
    this.scene.add(this.grid);
    this.clock = new THREE.Clock();
    this.loader = new GLTFLoader();
    this.mixer = null; this.actions = []; this.model = null;
    this.playing = true; this.speed = 1; this.nearest = true; this.wire = false; this.token = 0;
    // Originalgetreue Kanäle (Diagnosemodus kann einzelne abschalten)
    this.channels = { bones: true, blink: true, cycles: true, extended: true, blend: true, cull: true };
    this.smooth = false;        // Glättung zwischen 30-Hz-Zeilen (nicht original)
    this.repeatOnce = false;    // Einmal-Animationen nach kurzer Pause neu starten (nicht original)
    this.native = null;
    this.shadow = null; this.shadowOn = true; this.shadowCache = new Map();
    this.home = { pos: new THREE.Vector3(0, 0.5, 3), target: new THREE.Vector3(0, 0.4, 0) };
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
    this.renderer.setAnimationLoop(() => this.tick());
  }

  get blink() { return this.channels.blink; }
  set blink(v) { this.setChannel('blink', v); }

  resize() {
    const p = this.canvas.parentElement;
    const w = Math.max(1, p.clientWidth), h = Math.max(1, p.clientHeight);
    this.renderer.setSize(w, h, false);
    if (this.battleAspect) {   // 4:3-Bild des Spiels, mittig; außen bleibt der Hintergrund
      const vw = Math.min(w, h * this.battleAspect), vh = vw / this.battleAspect;
      const x = (w - vw) / 2, y = (h - vh) / 2;
      this.renderer.setViewport(x, y, vw, vh); this.renderer.setScissor(x, y, vw, vh); this.renderer.setScissorTest(true);
      this.camera.aspect = this.battleCamAspect || this.battleAspect;
    } else {
      this.renderer.setViewport(0, 0, w, h); this.renderer.setScissorTest(false);
      this.camera.aspect = w / h;
    }
    this.camera.updateProjectionMatrix();
  }

  tick() {
    const dt = Math.min(this.clock.getDelta(), 0.25);
    if (this.native) this.stepNative(dt);
    else if (this.mixer && this.playing) this.mixer.update(dt * this.speed);
    this.followShadow();
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  clear() {
    this.token++;
    if (this.model) {
      this.scene.remove(this.model);
      const seen = new Set();
      this.model.traverse(o => {
        if (o.geometry && !seen.has(o.geometry)) { seen.add(o.geometry); o.geometry.dispose(); }
        const mats = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : [];
        mats.forEach(m => { if (!seen.has(m)) { seen.add(m); m.map?.dispose(); m.dispose(); } });
      });
    }
    this.native?.textures.forEach(t => t.tex.dispose());
    this.model = null; this.mixer = null; this.actions = []; this.native = null; this.shadow = null;
  }

  filter(tex) {
    tex.magFilter = this.nearest ? THREE.NearestFilter : THREE.LinearFilter;
    tex.minFilter = this.nearest ? THREE.NearestFilter : THREE.LinearMipmapLinearFilter;
    tex.generateMipmaps = !this.nearest;
    tex.needsUpdate = true;
  }

  async load(url) {
    this.clear();
    const mine = this.token;
    const gltf = /\.obj$/i.test(url)
      ? { scene: await new OBJLoader().loadAsync(url), animations: [] }
      : await this.loader.loadAsync(url);
    if (mine !== this.token) throw new Error('abgebrochen');
    this.model = gltf.scene;
    this.scene.add(this.model);
    const payload = this.model.userData?.dw2_native;
    let names = gltf.animations.map((c, i) => c.name || `Animation ${i + 1}`);
    if (payload?.format === 1) {
      try { this.setupNative(payload); names = payload.anims.map(a => a.name); }
      catch (e) { console.error(e); this.native = null; }
    }
    this.applyMaterial();
    this.model.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(this.model);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const r = Math.max(size.x, size.y, size.z) || 1;
    this.model.position.sub(new THREE.Vector3(center.x, box.min.y, center.z));
    this.grid.scale.setScalar(Math.max(r / 5, 0.1));
    this.camera.near = r / 100; this.camera.far = r * 100; this.camera.updateProjectionMatrix();
    if (this.savedCam) this.endBattleCamera();
    this.home.pos.set(0, size.y * 0.6, r * 2.1);
    this.home.target.set(0, size.y * 0.45, 0);
    this.resetCamera();
    if (!this.native) {
      this.mixer = gltf.animations.length ? new THREE.AnimationMixer(this.model) : null;
      this.actions = gltf.animations.map(clip => this.mixer.clipAction(clip));
    }
    return { animations: names, native: !!this.native };
  }

  // ------------------------------------------------------------ Originalgetreue Wiedergabe
  setupNative(p) {
    const bones = [];
    for (let i = 0; i < p.bones; i++) {
      const b = this.model.getObjectByName(`bone_${i}`);
      if (!b) throw new Error(`bone_${i} fehlt`);
      b.matrixAutoUpdate = false;
      bones.push(b);
    }
    const files = {};
    for (const [k, v] of Object.entries(p.files || {})) files[k] = new AnimFile(fromBase64(v), p.bones);
    const vram = fromBase64(p.vram);
    const tex = vram.length >= 0x4000 ? new TexAnimator(fromBase64(p.texanim?.region || ''), vram) : null;
    const n = {
      payload: p, bones, files, player: new BonePlayer(p.bones), tex, anim: null, animId: -1,
      acc: 0, hold: 0, restarts: 0, cache: new Map(), textures: [], semi: [], tmp: new THREE.Matrix4(), ticks: 0,
    };
    this.native = n;
    // Texturen je Material aus dem VRAM-Abbild (gleiche Dekodierung wie der Konverter)
    const byMat = new Map();
    const meshes = [];
    this.model.traverse(o => { if (o.isMesh && !o.userData.dw2Twin) meshes.push(o); });
    n.orientation = faceOrientation(meshes);
    // PS1 zeichnet nur Vorderseiten (Gfx_AddQuadsGT4/Gfx_AddTrisGT3: NCLIP, opz <= 0 → verworfen).
    // Welche Seite vorn ist, folgt aus der Lage der Lichtnormalen der Modelldatei.
    n.cullSide = n.orientation.agree >= n.orientation.disagree ? THREE.FrontSide : THREE.BackSide;
    meshes.forEach(o => {
      const m = o.material;
      if (!m || m.userData?.clut === undefined) return;
      if (!byMat.has(m)) {
        let entry = null;
        if (tex) {
          const rgba = new Uint8Array(128 * 256 * 4);
          if (decodeRect(tex.vram, m.userData.clut, !!m.userData.semi_transparent, rgba)) {
            const dt = new THREE.DataTexture(rgba, 128, 256, THREE.RGBAFormat);
            dt.colorSpace = THREE.SRGBColorSpace; dt.flipY = false; this.filter(dt);
            m.map?.dispose(); m.map = dt; m.needsUpdate = true;
            entry = { mat: m, tex: dt, rgba, clut: m.userData.clut, stp: !!m.userData.semi_transparent, dirty: null };
            n.textures.push(entry);
          }
        }
        let semi = null;
        if (m.userData.semi_transparent) {
          semi = this.makeSemi(m, m.userData.abr | 0);
          m.userData.dw2Pass = 'opaque';
          n.semi.push(semi);
        }
        byMat.set(m, { entry, semi });
      }
      const { semi } = byMat.get(m);
      if (semi && !o.userData.dw2SemiAdded) {
        const twin = new THREE.Mesh(o.geometry, semi);
        twin.name = `${o.name}_semi`; twin.renderOrder = 2; twin.userData.dw2Twin = true;
        o.userData.dw2SemiAdded = true;
        o.add(twin);
      }
    });
    if (p.anims.length) this.play(0); else this.applyPose(true);
  }

  /** Halbtransparente Texel (STP-Bit) als eigener Durchgang mit dem PS1-Mischmodus. */
  makeSemi(base, abr) {
    const m = base.clone();
    m.userData = { ...base.userData, dw2Pass: 'semi', abr };
    m.transparent = true; m.depthWrite = false; m.alphaTest = 0;
    const u = { value: 0.5 };
    m.userData.alphaUniform = u;
    m.onBeforeCompile = shader => {
      shader.uniforms.dw2Alpha = u;
      shader.fragmentShader = 'uniform float dw2Alpha;\n' + shader.fragmentShader.replace('#include <map_fragment>',
        '#include <map_fragment>\n if (diffuseColor.a < 0.25 || diffuseColor.a > 0.75) discard;\n diffuseColor.a = dw2Alpha;');
    };
    m.customProgramCacheKey = () => 'dw2semi';
    this.setBlend(m, abr);
    return m;
  }

  setBlend(m, abr) {
    const u = m.userData.alphaUniform;
    m.blendEquation = THREE.AddEquation; m.blendSrc = THREE.SrcAlphaFactor; m.blendDst = THREE.OneMinusSrcAlphaFactor;
    if (!this.channels.blend || abr === 0) { m.blending = THREE.NormalBlending; u.value = 0.5; }
    else {
      m.blending = THREE.CustomBlending;
      if (abr === 1) { m.blendSrc = THREE.OneFactor; m.blendDst = THREE.OneFactor; u.value = 1; }
      else if (abr === 2) { m.blendEquation = THREE.ReverseSubtractEquation; m.blendSrc = THREE.OneFactor; m.blendDst = THREE.OneFactor; u.value = 1; }
      else { m.blendSrc = THREE.SrcAlphaFactor; m.blendDst = THREE.OneFactor; u.value = 0.25; }
    }
    m.needsUpdate = true;
  }

  keyMatrix(fileKey, file, bone, k) {
    const id = `${fileKey}:${bone}:${k}`;
    let v = this.native.cache.get(id);
    if (!v) { v = glMatrix(file.key(bone, k)); this.native.cache.set(id, v); }
    return v;
  }

  applyPose(force = false, frac = 0) {
    const n = this.native;
    if (!n || !n.anim) return;
    const file = n.files[n.anim.file];
    const keys = n.player.keys;
    const next = this.smooth && frac > 0 ? n.player.peekNext() : null;
    const out = new Array(16);
    for (let i = 0; i < n.bones.length; i++) {
      const a = this.keyMatrix(n.anim.file, file, i, keys[i]);
      let e = a;
      if (next && next[i] !== keys[i]) {
        const b = this.keyMatrix(n.anim.file, file, i, next[i]);
        for (let j = 0; j < 16; j++) out[j] = a[j] + (b[j] - a[j]) * frac;
        e = out;
      }
      const bone = n.bones[i];
      bone.matrix.set(e[0], e[1], e[2], e[3], e[4], e[5], e[6], e[7], e[8], e[9], e[10], e[11], 0, 0, 0, 1);
      bone.matrixWorldNeedsUpdate = true;
    }
  }

  stepNative(dt) {
    const n = this.native;
    if (!this.playing) return;
    n.acc += dt * 60 * this.speed;
    let ticks = Math.floor(n.acc);
    n.acc -= ticks;
    if (ticks > MAX_DELTA) ticks = MAX_DELTA;
    if (ticks > 0) {
      n.ticks += ticks;
      if (this.channels.bones && n.anim) {
        n.player.tick(ticks);
        if (n.player.finished && this.repeatOnce) {
          n.hold += ticks;
          if (n.hold >= 45) { n.hold = 0; n.restarts++; n.player.restart(); }
        }
      }
      if (n.tex) {
        const rects = n.tex.frame(ticks, n.animId);
        if (rects.length) this.refreshTextures(rects);
      }
    }
    if (this.channels.bones && (ticks > 0 || this.smooth)) this.applyPose(false, this.smooth ? Math.min(1, (n.player.timer + n.acc) / 2) : 0);
  }

  /** HD-Vorschau: ein PNG (128×256 mal 1–16, bis 2048×4096) ersetzt die Seite aller Materialien. */
  async setHdPreview(url) {
    const n = this.native;
    if (!n || !n.textures.length) throw new Error('Kein natives Modell geladen.');
    const img = await new THREE.ImageLoader().loadAsync(url);
    const max = this.renderer.capabilities.maxTextureSize;
    if (img.width > max || img.height > max) throw new Error(`Grafikkarte erlaubt höchstens ${max} Pixel Kantenlänge.`);
    // eine Leinwand statt eines festen Bildes: Blinzeln und Texturzyklen kopieren dieselben Rechtecke
    // wie im Spiel (DR_MOVE) auch im HD-Bild, wie der PC-Port (TexRep_OnMove)
    const canvas = document.createElement('canvas');
    canvas.width = img.width; canvas.height = img.height;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const tex = new THREE.CanvasTexture(canvas);
    n.hdCanvas = { ctx, base: ctx.getImageData(0, 0, img.width, img.height), k: img.width / 128 };
    tex.colorSpace = THREE.SRGBColorSpace; tex.flipY = false;
    this.filter(tex);   // Pixel-Look gilt auch für HD: Auflösung und Filter sind getrennt
    tex.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    this.clearHdPreview();
    n.hd = tex;
    for (const t of n.textures) { t.mat.map = tex; t.mat.needsUpdate = true; }
    if (n.tex) { n.tex.reset(); this.refreshTextures([[0, 0, 128, 256]]); }
    return { width: img.width, height: img.height, max };
  }

  clearHdPreview() {
    const n = this.native;
    if (!n?.hd) return;
    for (const t of n.textures) { t.mat.map = t.tex; t.mat.needsUpdate = true; }
    n.hd.dispose(); n.hd = null; n.hdCanvas = null;
  }

  refreshTextures(rects) {
    const n = this.native;
    if (n.hd) {   // HD-Vorschau: dieselben Kopien im HD-Bild, immer aus dem unveränderten HD-Original
      const h = n.hdCanvas, k = h?.k;
      if (!h) return;
      if (rects.length === 1 && rects[0][2] - rects[0][0] >= 128 && rects[0][3] - rects[0][1] >= 256) {
        h.ctx.putImageData(h.base, 0, 0);   // zurückgesetzt
      } else {
        for (const [sx, sy, w, hh, dx, dy] of n.tex.lastMoves || []) {
          h.ctx.putImageData(h.base, (dx - sx) * 4 * k, (dy - sy) * k, sx * 4 * k, sy * k, w * 4 * k, hh * k);
        }
      }
      n.hd.needsUpdate = true;
      return;
    }
    const palette = rects.some(r => r[3] > 224);
    for (const t of n.textures) {
      if (palette) decodeRect(n.tex.vram, t.clut, t.stp, t.rgba);
      else for (const [x0, y0, x1, y1] of rects) decodeRect(n.tex.vram, t.clut, t.stp, t.rgba, x0, y0, x1, y1);
      t.tex.needsUpdate = true;
    }
  }

  setChannel(name, on) {
    this.channels[name] = !!on;
    const n = this.native;
    if (!n) return;
    if (n.tex && (name === 'blink' || name === 'cycles' || name === 'extended')) {
      n.tex.enabled[name] = !!on;
      if (!on) { n.tex.reset(); this.refreshTextures([[0, 0, 128, 256]]); }
    }
    if (name === 'blend') n.semi.forEach(m => this.setBlend(m, m.userData.abr));
    if (name === 'bones' && on) this.applyPose(true);
    if (name === 'cull') this.applyMaterial();
  }

  /** Zustand für die Anzeige unter der Animationsauswahl. */
  status() {
    const n = this.native;
    if (!n || !n.anim) return null;
    const a = n.anim, p = n.player;
    return {
      name: a.name, id: a.id, rows: a.rows, frame: p.frame + 1, finished: p.finished, loops: p.loops,
      loopRow: a.terminator === 0xFE ? Math.floor(a.loop / n.payload.bones) + 1 : null,
      blink: a.id >= 0 && [0x64, 0x0A, 0x14, 0x15, 0x16].includes(a.id) ? 'zu (Animation erlaubt kein Blinzeln)' : 'Spielrhythmus',
    };
  }

  /** Übersicht der Kanäle des geladenen Modells (Diagnose). */
  channelsInfo() {
    const n = this.native;
    if (!n) return null;
    const p = n.payload, t = p.texanim || {};
    const abr = {};
    n.semi.forEach(m => { abr[m.userData.abr] = (abr[m.userData.abr] || 0) + 1; });
    return {
      bones: p.bones, files: Object.keys(p.files || {}).join(' ') || '–', clips: p.anims.length,
      loops: p.anims.filter(a => a.terminator === 0xFE).length, holds: p.anims.filter(a => a.terminator === 0xFF).length,
      legacy: p.anims.filter(a => a.legacy).length,
      eyes: t.eyes || 0, cycles: t.cycles || 0, extended: t.extended || 0, palette: !!t.palette,
      culling: `${this.channels.cull ? 'PS1 (nur Vorderseiten)' : 'aus (beidseitig)'} · ${n.orientation.agree}/${n.orientation.agree + n.orientation.disagree} Flächen passend${n.cullSide === THREE.BackSide ? ' · Umlauf gespiegelt' : ''}`,
      semi: Object.entries(abr).map(([k, v]) => `${ABR_LABEL[k] || k} ×${v}`).join(', ') || '–',
      warnings: [...(t.warnings || []), ...Object.entries(p.file_warnings || {}).flatMap(([k, w]) => w.map(x => `${k}: ${x}`)),
        ...Object.entries(p.skipped || {}).map(([k, w]) => `${k}: übersprungen (${w})`),
        ...(n.tex?.outside ? [`${n.tex.outside} Texturkopien außerhalb der Modelltextur (abgeschnitten)`] : [])],
    };
  }

  /** Kampf-Nahaufnahme wie im Spiel (Stg30_CameraUpdate 2–7): Werte in DW2-Einheiten, y nach oben.
   *  Senkrechter Bildwinkel aus der Projektion 0x5DC auf 240 Zeilen; das Modell steht im Ursprung. */
  battleCamera(c) {
    if (!this.model) return;
    if (!this.savedCam) this.savedCam = { fov: this.camera.fov, near: this.camera.near, far: this.camera.far,
      pos: this.camera.position.clone(), target: this.controls.target.clone() };
    // Kampfbild 320 × 480 GTE-Einheiten, angezeigt 4:3: senkrechter Winkel aus 240 Zeilen, waagerecht 160
    this.camera.fov = 2 * Math.atan((c.screen[1] / 2) / c.projection) * 180 / Math.PI;
    this.battleCamAspect = c.screen[0] / c.screen[1];
    this.camera.near = 50; this.camera.far = 200000;
    // Das Spiel stellt den Modellursprung auf den Boden; die Ansicht hat das Modell auf seine Unterkante
    // verschoben. Die Kamera wandert mit, damit der Bildausschnitt dem Spiel entspricht.
    const o = this.model.position;
    if (c.eye) {   // Kampfeinstellung aus battle_shots.preview: Punkte in Modellachsen um den Ursprung
      this.camera.position.set(o.x + c.eye[0], o.y + c.eye[1], o.z + c.eye[2]);
      this.controls.target.set(o.x + c.target[0], o.y + c.target[1], o.z + c.target[2]);
    } else {
      this.camera.position.set(o.x, o.y + c.eye_height, o.z + c.distance);
      this.controls.target.set(o.x, o.y + c.look_height, o.z);
    }
    this.camera.updateProjectionMatrix(); this.controls.update();
    this.controls.enabled = false;
    this.battleAspect = 4 / 3;
    this.resize();
  }
  endBattleCamera() {
    const s = this.savedCam;
    if (!s) return;
    this.savedCam = null; this.battleAspect = null; this.controls.enabled = true;
    this.camera.fov = s.fov; this.camera.near = s.near; this.camera.far = s.far;
    this.camera.position.copy(s.pos); this.controls.target.copy(s.target);
    this.camera.updateProjectionMatrix(); this.controls.update(); this.resize();
  }

  /** Kamera auf die aktuelle Pose einstellen (Skelettverformung eingerechnet), z. B. für den
   *  Vergleich DW3-Original / Import mit gleichem Bildausschnitt. */
  framePose() {
    if (!this.model) return;
    this.model.updateMatrixWorld(true);
    const box = new THREE.Box3(), tmp = new THREE.Box3(), p = new THREE.Vector3();
    this.model.traverse(o => {
      if (!o.isMesh || !o.geometry?.attributes?.position) return;
      const pos = o.geometry.attributes.position;
      for (let i = 0; i < pos.count; i++) {
        if (o.isSkinnedMesh) o.getVertexPosition(i, p); else p.fromBufferAttribute(pos, i);
        p.applyMatrix4(o.matrixWorld); tmp.expandByPoint(p);
      }
    });
    if (tmp.isEmpty()) return;
    box.copy(tmp);
    const size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
    const r = Math.max(size.x, size.y, size.z) || 1;
    this.home.pos.set(c.x, box.min.y + size.y * 0.6, c.z + r * 2.1);
    this.home.target.set(c.x, box.min.y + size.y * 0.45, c.z);
    this.resetCamera();
  }

  resetCamera() {
    this.camera.position.copy(this.home.pos);
    this.controls.target.copy(this.home.target);
    this.controls.update();
  }

  play(index) {
    const n = this.native;
    if (n) {
      const a = n.payload.anims[index];
      const file = a && n.files[a.file];
      if (!file) return;
      n.anim = a; n.animId = a.id; n.acc = 0; n.hold = 0;
      n.player.set(file, a.offset);
      this.applyPose(true);
      return;
    }
    this.actions.forEach(x => x.stop());
    this.actions[index]?.reset().play();
  }

  /** Animationseditor: Zeilen eines nativen Clips (wie Anim_StepModelAnim) und die Loop-Zeile. */
  nativeClipInfo(index) {
    const n = this.native, a = n?.payload.anims[index], f = a && n.files[a.file];
    if (!f) return null;
    const nb = n.player.bones;
    let pos = 0, rows = 0, loop = null;
    for (;;) {
      if (a.offset + pos + nb > f.bytes.length || rows > 5000) break;
      pos += nb; rows++;
      const q = f.bytes[a.offset + pos];
      if (q === 0xFF) break;
      if (q === 0xFE) { loop = Math.floor((f.bytes[a.offset + pos + 1] | (f.bytes[a.offset + pos + 2] << 8)) / nb); break; }
    }
    return { rows, loop, id: a.id, name: a.name };
  }

  /** Animationseditor: Clip INDEX anhalten und Zeile ROW zeigen (Schleifen wie im Spiel). */
  nativeSeek(index, row) {
    const n = this.native, a = n?.payload.anims[index], f = a && n.files[a.file];
    if (!f) return 0;
    this.playing = false;
    n.anim = a; n.animId = a.id; n.acc = 0; n.hold = 0;
    n.player.set(f, a.offset);
    if (row > 0) n.player.tick(2 * row);
    this.applyPose(true);
    return n.player.frame;
  }

  /** Aktuelle Zeile des laufenden nativen Clips. */
  nativeRow() { return this.native ? this.native.player.frame : 0; }

  /** Kleines Vorschaubild der aktuellen Ansicht (PNG-Data-URL), z. B. für die DW3-Liste. */
  snapshot(size = 160) {
    this.renderer.render(this.scene, this.camera);
    const src = this.renderer.domElement, s = Math.min(src.width, src.height);
    if (!s) return null;
    const c = document.createElement('canvas'); c.width = c.height = size;
    c.getContext('2d').drawImage(src, (src.width - s) / 2, (src.height - s) / 2, s, s, 0, 0, size, size);
    return c.toDataURL('image/png');
  }

  /** glTF-Animation (DW3-Original) an Bild FRAME (30 Bilder/s) anhalten. */
  gltfSeek(index, frame) {
    if (!this.mixer || !this.actions[index]) return;
    this.actions.forEach(x => x.stop());
    const act = this.actions[index];
    act.reset().play(); act.paused = true;
    this.mixer.setTime(frame / 30);
  }

  /** Abgelaufene Einmal-Animation neu starten (Play-Taste). */
  restartIfFinished() {
    const n = this.native;
    if (n?.player.finished) { n.player.restart(); this.applyPose(true); return true; }
    return false;
  }

  applyMaterial() {
    if (!this.model) return;
    this.model.traverse(o => {
      if (!o.isMesh) return;
      if (o.userData.dw2Shadow) { o.material.wireframe = this.wire; if (o.material.map) this.filter(o.material.map); return; }
      (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => {
        const native = this.native && m.userData?.clut !== undefined;
        m.side = native && this.channels.cull ? this.native.cullSide : THREE.DoubleSide;
        const pass = m.userData?.dw2Pass;
        if (pass === 'opaque') {
          // Undurchsichtige Texel halbtransparenter Flächen; die STP-Texel zeichnet der Zwilling.
          m.transparent = false; m.depthWrite = true; m.alphaTest = 0.75;
        } else if (pass !== 'semi' && m.transparent) {
          // Ohne native Daten (Importe): bisheriges Verhalten.
          m.depthWrite = true; m.alphaTest = Math.max(m.alphaTest || 0, 0.02);
        }
        m.wireframe = this.wire;
        if (m.map) this.filter(m.map);
        m.needsUpdate = true;
      });
    });
  }

  /** Schatten wie im Spiel (main/shadow.c): Modell 0x5B auf dem Boden (y 0) unter Knochen 0,
   *  undurchsichtig gezeichnet (Gfx_DrawTexModel Modus 1), immer unter dem Digimon. */
  async setShadow(url) {
    const mine = this.token;
    if (!url || !this.model) return;
    let src = this.shadowCache.get(url);
    if (!src) { src = (await this.loader.loadAsync(url)).scene; this.shadowCache.set(url, src); }
    if (mine !== this.token || !this.model) return;
    const sh = src.clone(true);
    sh.name = 'dw2_shadow';
    sh.traverse(o => {
      if (!o.isMesh) return;
      const src = o.material, ud = src.userData || {};
      // Gfx_AddQuadsGT4/GT3: STP-Texel der halbtransparenten Flächen werden mit dem ABR-Modus
      // gemischt; der Schatten nutzt eine helle Verlaufstextur mit Modus 2 (Hintergrund − Textur).
      // Die Leinwand ist durchsichtig über dem CSS-Hintergrund, daher wird „minus Textur“ als
      // schwarze Abdunklung mit der Texturhelligkeit als Deckkraft gezeichnet.
      const m = new THREE.MeshBasicMaterial({ map: src.map, transparent: true, depthWrite: false, side: THREE.DoubleSide });
      const abr = { value: ud.semi_transparent ? (ud.abr | 0) : -1 };
      m.onBeforeCompile = shader => {
        shader.uniforms.dw2Abr = abr;
        shader.fragmentShader = 'uniform int dw2Abr;\n' + shader.fragmentShader
          .replace('#include <map_fragment>', '#include <map_fragment>\n  vec4 dw2t = diffuseColor;\n  if (dw2t.a < 0.25) discard;')
          .replace('#include <dithering_fragment>', `#include <dithering_fragment>
  if (dw2Abr >= 0 && dw2t.a <= 0.75) {
    vec3 c = pow(clamp(dw2t.rgb, 0.0, 1.0), vec3(0.4545));
    float l = max(max(c.r, c.g), c.b);
    if (dw2Abr == 2) gl_FragColor = vec4(0.0, 0.0, 0.0, l);
    else if (dw2Abr == 0) gl_FragColor = vec4(gl_FragColor.rgb, 0.5);
    else gl_FragColor = vec4(gl_FragColor.rgb, l);
  } else gl_FragColor.a = 1.0;`);
      };
      m.customProgramCacheKey = () => 'dw2shadow';
      m.polygonOffset = true; m.polygonOffsetFactor = 1; m.polygonOffsetUnits = 4;
      if (m.map) this.filter(m.map);
      o.material = m; o.renderOrder = -1; o.userData.dw2Shadow = true;
    });
    sh.visible = this.shadowOn;
    this.model.add(sh);
    this.shadow = sh;
    this.followShadow();
  }

  followShadow() {
    const sh = this.shadow, root = this.native?.bones[0] || this.model?.getObjectByName('bone_0');
    if (!sh || !root) return;
    if (root.matrixAutoUpdate) { sh.position.set(root.position.x, 0, root.position.z); }
    else { const e = root.matrix.elements; sh.position.set(e[12], 0, e[14]); }
  }

  setShadowVisible(on) { this.shadowOn = on; if (this.shadow) this.shadow.visible = on; }

  setLight(v) { this.key.intensity = v; this.ambient.intensity = 0.4 + v * 0.4; }
  setBackground(hex) { this.bgColor = new THREE.Color(hex); if (this.scene.background) this.scene.background = this.bgColor; }
  /** true: transparente Leinwand über dem DW2-Hintergrund; false: einfarbig. */
  setOriginalBackground(on) { this.scene.background = on ? null : this.bgColor; }
}

