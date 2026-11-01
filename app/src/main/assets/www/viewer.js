import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

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
    this.home = { pos: new THREE.Vector3(0, 0.5, 3), target: new THREE.Vector3(0, 0.4, 0) };
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
    this.renderer.setAnimationLoop(() => this.tick());
  }

  resize() {
    const p = this.canvas.parentElement;
    const w = Math.max(1, p.clientWidth), h = Math.max(1, p.clientHeight);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  tick() {
    const dt = this.clock.getDelta();
    if (this.mixer && this.playing) this.mixer.update(dt * this.speed);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  clear() {
    this.token++;
    if (this.model) {
      this.scene.remove(this.model);
      this.model.traverse(o => {
        o.geometry?.dispose();
        const mats = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : [];
        mats.forEach(m => { m.map?.dispose(); m.dispose(); });
      });
    }
    this.model = null; this.mixer = null; this.actions = [];
  }

  async load(url) {
    this.clear();
    const mine = this.token;
    const gltf = await this.loader.loadAsync(url);
    if (mine !== this.token) throw new Error('abgebrochen');
    this.model = gltf.scene;
    this.scene.add(this.model);
    this.applyMaterial();
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
    this.mixer = gltf.animations.length ? new THREE.AnimationMixer(this.model) : null;
    this.actions = gltf.animations.map(clip => this.mixer.clipAction(clip));
    return { animations: gltf.animations.map((c, i) => c.name || `Animation ${i + 1}`) };
  }

  resetCamera() {
    this.camera.position.copy(this.home.pos);
    this.controls.target.copy(this.home.target);
    this.controls.update();
  }

  play(index) {
    this.actions.forEach(a => a.stop());
    this.actions[index]?.reset().play();
  }

  applyMaterial() {
    if (!this.model) return;
    this.model.traverse(o => {
      if (!o.isMesh) return;
      (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => {
        m.side = THREE.DoubleSide;
        m.wireframe = this.wire;
        if (m.map) {
          m.map.magFilter = this.nearest ? THREE.NearestFilter : THREE.LinearFilter;
          m.map.minFilter = this.nearest ? THREE.NearestFilter : THREE.LinearMipmapLinearFilter;
          m.map.needsUpdate = true;
        }
        m.needsUpdate = true;
      });
    });
  }

  setLight(v) { this.key.intensity = v; this.ambient.intensity = 0.4 + v * 0.4; }
  setBackground(hex) { this.scene.background = new THREE.Color(hex); }
}
