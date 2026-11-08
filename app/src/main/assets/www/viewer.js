import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { AnimFile, BonePlayer, TexAnimator, decodeRect, fromBase64, glMatrix, MAX_DELTA } from './native_anim.js';

/** PS1-Mischmodi (tpage ABR) für halbtransparente Texel. */
const ABR_LABEL = ['50 % (B/2+F/2)', 'additiv (B+F)', 'subtraktiv (B−F)', 'B+F/4'];

/** three.js-Viewer für die vom DW2-Konverter erzeugten glTF-Modelle (Touch: drehen, zoomen, verschieben). */
export class Viewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x16243a);
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.01, 5000);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.screenSpacePanning = true;
    this.ambient = new THREE.AmbientLight(0xffffff, 0.9);
    this.key = new THREE.DirectionalLight(0xffffff, 1.2); this.key.position.set(3, 6, 5);
    this.fill = new THREE.DirectionalLight(0xaac4ff, 0.5); this.fill.position.set(-4, 2, -3);
    this.scene.add(this.ambient, this.key, this.fill);
    this.grid = new THREE.GridHelper(10, 20, 0x3a5578, 0x24374f);
    this.scene.add(this.grid);
    this.clock = new THREE.Clock();
    this.loader = new GLTFLoader();
    this.mixer = null; this.actions = []; this.model = null;
    this.playing = true; this.speed = 1; this.nearest = true; this.wire = false; this.token = 0;
    // Originalgetreue Kanäle (Diagnosemodus kann einzelne abschalten)
    this.channels = { bones: true, blink: true, cycles: true, extended: true, blend: true };
    this.smooth = false;        // Glättung zwischen 30-Hz-Zeilen (nicht original)
    this.repeatOnce = false;    // Einmal-Animationen nach kurzer Pause neu starten (nicht original)
    this.native = null;
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
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  tick() {
    const dt = Math.min(this.clock.getDelta(), 0.25);
    if (this.native) this.stepNative(dt);
    else if (this.mixer && this.playing) this.mixer.update(dt * this.speed);
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
    this.model = null; this.mixer = null; this.actions = []; this.native = null;
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

  refreshTextures(rects) {
    const n = this.native;
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
      semi: Object.entries(abr).map(([k, v]) => `${ABR_LABEL[k] || k} ×${v}`).join(', ') || '–',
      warnings: [...(t.warnings || []), ...Object.entries(p.file_warnings || {}).flatMap(([k, w]) => w.map(x => `${k}: ${x}`)),
        ...Object.entries(p.skipped || {}).map(([k, w]) => `${k}: übersprungen (${w})`),
        ...(n.tex?.outside ? [`${n.tex.outside} Texturkopien außerhalb der Modelltextur (abgeschnitten)`] : [])],
    };
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
      (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => {
        m.side = THREE.DoubleSide;
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

  setLight(v) { this.key.intensity = v; this.ambient.intensity = 0.4 + v * 0.4; }
  setBackground(hex) { this.scene.background = new THREE.Color(hex); }
}
