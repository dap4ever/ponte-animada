// Visualizador 3D: carrega um GLB, toca a animação e deixa inspecionar.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const HIPS = /hips|pelvis/i;

export class Viewer {
  constructor(container) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.prepend(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0e1013);
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environmentIntensity = 0.45;
    this.scene.fog = new THREE.Fog(0x0e1013, 10, 40);
    this.sun = new THREE.DirectionalLight(0xffffff, 1.2);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    this.sun.shadow.bias = -0.0004;
    this.scene.add(this.sun, this.sun.target);

    // Piso quadriculado com sombra: a sombra mostra o contato dos pés e, com a câmera
    // seguindo o personagem, é o quadriculado que mostra se o pé desliza.
    // A grade é textura (e não linhas): linhas longas somem perto da câmera em alguns renderizadores.
    this.ground = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1),
      new THREE.MeshStandardMaterial({ map: this.gridTexture(), roughness: 1, metalness: 0 }),
    );
    this.ground.rotation.x = -Math.PI / 2;
    this.ground.receiveShadow = true;
    this.ground.visible = false;
    this.scene.add(this.ground);

    this.camera = new THREE.PerspectiveCamera(38, 1, 0.01, 500);
    this.camera.position.set(1.4, 1.4, 3.6);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.target.set(0, 0.9, 0);

    this.loader = new GLTFLoader();
    this.clock = new THREE.Clock();
    this.clips = [];
    this.options = { follow: true, bones: false, wire: false, inPlace: false };
    this.onTime = () => {};
    this.loadToken = 0;

    // Ajuste de pose: uma rotação extra por osso, aplicada por cima da animação em todo quadro.
    // O manipulador gira o osso escolhido; o que ele mudar vira o ajuste daquele osso.
    this.bones = new Map(); // nome -> osso do modelo carregado
    this.offsets = new Map(); // nome do osso -> Quaternion
    this.animated = new Map(); // valor que a animação deu ao osso neste quadro, antes do ajuste
    this.onOffsets = () => {};
    this.gizmo = new TransformControls(this.camera, this.renderer.domElement);
    this.gizmo.setMode('rotate');
    this.gizmo.setSpace('local');
    this.gizmo.setSize(0.75);
    this.scene.add(this.gizmo.getHelper());
    this.gizmo.addEventListener('dragging-changed', (e) => {
      this.controls.enabled = !e.value;
    });
    this.gizmo.addEventListener('objectChange', () => {
      const target = this.gizmo.object;
      if (target.userData.propId) {
        this.onPropChange(target.userData.propId);
        return;
      }
      const base = this.animated.get(target.name);
      if (!base) return;
      this.offsets.set(target.name, base.clone().invert().multiply(target.quaternion));
      this.onOffsets(this.offsets);
    });

    // Acessórios (arma etc.): cada um é um GLB pendurado num osso, com uma matriz local a ele.
    this.props = new Map(); // id -> Object3D
    this.propCache = new Map(); // url -> Promise<Object3D>
    this.onPropChange = () => {};

    // Caminho desenhado no chão: cada clique vira um ponto por onde o personagem deve passar.
    this.waypoints = [];
    this.pathOrigin = [0, 0]; // de onde o caminho parte: a origem, ou onde o personagem está ao fim do clipe
    this.pathGroup = new THREE.Group();
    this.scene.add(this.pathGroup);
    this.onWaypoints = () => {};
    const canvas = this.renderer.domElement;
    let down = null;
    canvas.addEventListener('pointerdown', (e) => {
      down = [e.clientX, e.clientY];
      if (this.rig && e.button === 0) this.rigDown(e);
    });
    canvas.addEventListener('pointermove', (e) => this.rig && this.rigMove(e));
    canvas.addEventListener('pointerup', (e) => {
      if (this.rig) this.rigUp();
      // Arrastar gira a câmera; só um clique parado marca ponto.
      const still = down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 5;
      down = null;
      if (!this.drawing || !still || e.button !== 0 || !this.root) return;
      const rect = canvas.getBoundingClientRect();
      const pointer = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
      const ray = new THREE.Raycaster();
      ray.setFromCamera(pointer, this.camera);
      const hit = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -this.ground.position.y), new THREE.Vector3());
      if (!hit) return;
      this.waypoints.push([hit.x, hit.z]);
      this.drawWaypoints();
    });

    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
    this.renderer.setAnimationLoop(() => this.tick());
  }

  // --- Marcadores do rig -------------------------------------------------------------------
  // Como no Mixamo: vista de frente, sem perspectiva, com um círculo para cada ponto do corpo.
  // markers: { nome: [x, altura] } em metros; body: medidas do personagem vindas do Blender.

  enterRig(markers, body, labels) {
    this.exitRig();
    const h = body.height_m;
    const front = -body.bbox_min[1] + 0.1 * h; // frente do personagem, no eixo Z do visualizador
    this.rig = { body, symmetric: true, dots: new Map(), tags: new Map(), dragging: null };
    this.onMarkers = this.onMarkers || (() => {});

    this.ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 100 * h);
    this.ortho.position.set(body.center_x_m, body.floor_m + h / 2, front + 20 * h);
    this.ortho.userData.span = h * 1.18; // altura do mundo que cabe na tela
    this.saved = { target: this.controls.target.clone(), rotate: this.controls.enableRotate };
    this.controls.object = this.ortho;
    this.controls.enableRotate = false;
    this.controls.target.set(body.center_x_m, body.floor_m + h / 2, 0);
    this.gizmo.detach();
    this.resize();

    const colors = { chin: 0xf5d547, groin: 0xf0a43a, wrist: 0x4cc38a, elbow: 0x6aa9f2, knee: 0xe879c7 };
    for (const [name, [x, z]] of Object.entries(markers)) {
      const dot = new THREE.Mesh(
        new THREE.SphereGeometry(0.014 * h, 20, 14),
        new THREE.MeshBasicMaterial({ color: colors[name.split('_').pop()], depthTest: false, fog: false }),
      );
      dot.renderOrder = 20;
      dot.position.set(x, z, front);
      this.scene.add(dot);
      this.rig.dots.set(name, dot);
      const tag = document.createElement('div');
      tag.className = 'marker-tag';
      tag.textContent = labels[name] || name;
      this.container.append(tag);
      this.rig.tags.set(name, tag);
    }
  }

  exitRig() {
    if (!this.rig) return;
    for (const dot of this.rig.dots.values()) {
      this.scene.remove(dot);
      dot.geometry.dispose();
      dot.material.dispose();
    }
    for (const tag of this.rig.tags.values()) tag.remove();
    this.controls.object = this.camera;
    this.controls.enableRotate = this.saved.rotate;
    this.controls.target.copy(this.saved.target);
    this.rig = null;
    this.ortho = null;
  }

  /** Os marcadores como estão agora: { nome: [x, altura] }. */
  rigMarkers() {
    return Object.fromEntries([...this.rig.dots].map(([name, dot]) => [name, [dot.position.x, dot.position.y]]));
  }

  setRigMarkers(markers) {
    for (const [name, [x, z]] of Object.entries(markers)) this.rig.dots.get(name)?.position.setX(x).setY(z);
  }

  rigPointer(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector3(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1, 0);
    return { world: ndc.clone().unproject(this.ortho), rect };
  }

  rigDown(event) {
    const { rect } = this.rigPointer(event);
    let best = null;
    for (const [name, dot] of this.rig.dots) {
      const p = dot.position.clone().project(this.ortho);
      const dist = Math.hypot(((p.x + 1) / 2) * rect.width - (event.clientX - rect.left), ((1 - p.y) / 2) * rect.height - (event.clientY - rect.top));
      if (dist < 16 && (!best || dist < best.dist)) best = { name, dist };
    }
    if (!best) return;
    this.rig.dragging = best.name;
    this.controls.enabled = false;
    this.renderer.domElement.setPointerCapture(event.pointerId);
  }

  rigMove(event) {
    const name = this.rig.dragging;
    if (!name) return;
    const { world } = this.rigPointer(event);
    this.rig.dots.get(name).position.setX(world.x).setY(world.y);
    // Com simetria, o par do outro lado espelha em torno do meio do corpo.
    const side = name.match(/^([lr])_(.+)$/);
    if (side && this.rig.symmetric) {
      const twin = this.rig.dots.get(`${side[1] === 'l' ? 'r' : 'l'}_${side[2]}`);
      twin?.position.setX(2 * this.rig.body.center_x_m - world.x).setY(world.y);
    }
  }

  rigUp() {
    if (!this.rig.dragging) return;
    this.rig.dragging = null;
    this.controls.enabled = true;
    this.onMarkers(this.rigMarkers());
  }

  /** Põe o manipulador de rotação num osso (ou tira, com null). */
  selectBone(name) {
    const bone = name && this.bones?.get(name);
    this.gizmo.setMode('rotate');
    if (bone) this.gizmo.attach(bone);
    else this.gizmo.detach();
    return !!bone;
  }

  /**
   * Mostra os acessórios do personagem carregado: [{id, url, bone, matrix}] com o nome do osso
   * como está no modelo. Sem matriz, o acessório é posto na origem do osso, em tamanho plausível.
   * Os que vieram gravados no arquivo (nós PROP_*) ficam ocultos: valem os desta lista.
   */
  async setProps(list) {
    const token = this.loadToken;
    for (const object of this.props.values()) object.removeFromParent();
    this.props.clear();
    if (this.gizmo.object?.userData.propId) this.gizmo.detach();
    if (!this.root) return;
    this.root.traverse((obj) => {
      if (obj.name.startsWith('PROP_')) obj.visible = false;
    });
    for (const prop of list) {
      const bone = this.bones.get(prop.bone);
      if (!bone) continue;
      if (!this.propCache.has(prop.url)) this.propCache.set(prop.url, this.loader.loadAsync(prop.url).then((gltf) => gltf.scene));
      const template = await this.propCache.get(prop.url);
      if (token !== this.loadToken) return; // o modelo mudou enquanto o acessório carregava
      const object = template.clone(true);
      object.userData.propId = prop.id;
      object.traverse((child) => {
        if (!child.isMesh) return;
        child.castShadow = true;
        for (const mat of [].concat(child.material || [])) mat.fog = false;
      });
      if (prop.matrix) {
        bone.add(object);
        new THREE.Matrix4().fromArray(prop.matrix).decompose(object.position, object.quaternion, object.scale);
      } else {
        // Primeira vez: na origem do osso, alinhado ao mundo, com uns 45% da altura do personagem
        // se o arquivo veio numa unidade muito diferente.
        const size = new THREE.Box3().setFromObject(object).getSize(new THREE.Vector3());
        const longest = Math.max(size.x, size.y, size.z) || 1;
        const height = this.reach || 1.8;
        if (longest > height * 1.5 || longest < height * 0.05) object.scale.setScalar((height * 0.45) / longest);
        bone.getWorldPosition(object.position);
        this.scene.add(object);
        bone.attach(object);
      }
      this.props.set(prop.id, object);
    }
  }

  /** Põe o manipulador num acessório, no modo 'translate', 'rotate' ou 'scale'. */
  selectProp(id, mode = 'translate') {
    const object = this.props.get(id);
    if (!object) return false;
    this.gizmo.setMode(mode);
    this.gizmo.attach(object);
    return true;
  }

  /** Matriz do acessório em relação ao osso, como 16 números. */
  propMatrix(id) {
    const object = this.props.get(id);
    if (!object) return null;
    object.updateMatrix();
    return object.matrix.toArray();
  }

  resetOffsets(name) {
    if (name) this.offsets.delete(name);
    else this.offsets.clear();
    this.refreshPose();
    this.onOffsets(this.offsets);
  }

  /** Define o ajuste de um osso por código: [x, y, z, w]. */
  setOffset(name, [x, y, z, w]) {
    this.offsets.set(name, new THREE.Quaternion(x, y, z, w));
    this.refreshPose();
    this.onOffsets(this.offsets);
  }

  // O mixer só reescreve um osso quando o valor animado muda. Então, antes de avançar a
  // animação, os ossos mexidos voltam ao valor animado; depois, guarda-se o valor novo e o
  // ajuste entra por cima. Sem isso, com a animação pausada o ajuste se acumularia a cada quadro.
  beforeMixer() {
    for (const [name, quat] of this.animated) this.bones.get(name)?.quaternion.copy(quat);
  }

  afterMixer() {
    this.animated.clear();
    const touched = new Set(this.offsets.keys());
    if (this.gizmo.object) touched.add(this.gizmo.object.name);
    for (const name of touched) {
      const bone = this.bones.get(name);
      if (!bone) continue;
      this.animated.set(name, bone.quaternion.clone());
      const offset = this.offsets.get(name);
      if (offset) bone.quaternion.multiply(offset);
    }
  }

  refreshPose() {
    if (!this.root) return;
    this.beforeMixer();
    this.mixer?.update(0);
    this.afterMixer();
  }

  setDrawing(on) {
    this.drawing = on;
    this.renderer.domElement.style.cursor = on ? 'crosshair' : '';
  }

  clearWaypoints() {
    this.waypoints = [];
    this.drawWaypoints();
  }

  // Marcadores e trechos como malhas (e não linhas, que somem perto da câmera em alguns renderizadores).
  drawWaypoints() {
    for (const child of [...this.pathGroup.children]) {
      this.pathGroup.remove(child);
      child.geometry.dispose();
    }
    const y = this.ground.position.y;
    const r = (this.reach || 1.8) * 0.018;
    this.pathMaterial ??= new THREE.MeshBasicMaterial({ color: 0xf0a43a, fog: false });
    let last = this.pathOrigin;
    for (const [x, z] of this.waypoints) {
      const dot = new THREE.Mesh(new THREE.SphereGeometry(r * 1.6, 16, 12), this.pathMaterial);
      dot.position.set(x, y + r, z);
      const length = Math.hypot(x - last[0], z - last[1]);
      const bar = new THREE.Mesh(new THREE.BoxGeometry(length, r * 0.5, r * 0.8), this.pathMaterial);
      bar.position.set((x + last[0]) / 2, y + r * 0.3, (z + last[1]) / 2);
      bar.rotation.y = -Math.atan2(z - last[1], x - last[0]);
      this.pathGroup.add(dot, bar);
      last = [x, z];
    }
    this.onWaypoints(this.waypoints);
  }

  /**
   * Onde o quadril está no chão e para onde o corpo olha num instante do clipe, como aparece
   * na tela. É de onde parte o passo seguinte do roteiro. O ângulo segue o Kimodo: 0 = olhando
   * para +Z, crescendo para a esquerda dele (+X). leftLeg e rightLeg são os ossos das coxas.
   */
  poseAt(seconds, leftLeg, rightLeg) {
    const left = this.bones.get(leftLeg);
    const right = this.bones.get(rightLeg);
    if (!this.action || !this.tracked || !left || !right) return null;
    const keep = this.action.time;
    this.action.time = Math.min(Math.max(seconds, 0), this.duration - 1e-4);
    this.mixer.update(0);
    const hips = this.tracked.getWorldPosition(new THREE.Vector3());
    const side = left.getWorldPosition(new THREE.Vector3()).sub(right.getWorldPosition(new THREE.Vector3()));
    this.action.time = keep;
    this.refreshPose();
    return { x: hips.x, z: hips.z, heading: Math.atan2(-side.z, side.x) };
  }

  // Trajetória suavizada do quadril no chão, amostrada a 30 fps. É o que "Parado" desconta:
  // some o deslocamento e fica o balanço natural do quadril (mesma conta do retarget parado).
  computePath() {
    this.path = null;
    if (!this.action || !this.tracked) return;
    this.root.position.set(0, 0, 0);
    const duration = this.duration;
    const count = Math.max(2, Math.round(duration * 30) + 1);
    const keep = this.action.time;
    const p = new THREE.Vector3();
    const raw = [];
    for (let i = 0; i < count; i++) {
      this.action.time = Math.min((duration * i) / (count - 1), duration - 1e-4);
      this.mixer.update(0);
      this.tracked.getWorldPosition(p);
      raw.push([p.x, p.z]);
    }
    this.action.time = keep;
    this.mixer.update(0);

    const sigma = 15;
    const radius = Math.min(3 * sigma, count - 1);
    const kernel = [];
    for (let k = -radius; k <= radius; k++) kernel.push(Math.exp(-0.5 * (k / sigma) ** 2));
    const total = kernel.reduce((a, b) => a + b, 0);
    // Borda espelhada com sinal trocado: preserva tendência linear (caminhada constante some inteira).
    const at = (j, c) => (j < 0 ? 2 * raw[0][c] - raw[-j][c] : j >= count ? 2 * raw[count - 1][c] - raw[2 * (count - 1) - j][c] : raw[j][c]);
    const smooth = raw.map((_, i) => [0, 1].map((c) => kernel.reduce((sum, w, k) => sum + w * at(i + k - radius, c), 0) / total));
    this.path = { smooth, duration };
  }

  applyInPlace() {
    if (!this.root) return;
    if (!this.options.inPlace || !this.path || !this.action) {
      this.root.position.x = this.root.position.z = 0;
      return;
    }
    const { smooth, duration } = this.path;
    const f = Math.min(this.action.time / duration, 1) * (smooth.length - 1);
    const i = Math.min(Math.floor(f), smooth.length - 2);
    const a = f - i;
    this.root.position.x = -(smooth[i][0] * (1 - a) + smooth[i + 1][0] * a - smooth[0][0]);
    this.root.position.z = -(smooth[i][1] * (1 - a) + smooth[i + 1][1] * a - smooth[0][1]);
  }

  resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    if (this.ortho) {
      const half = this.ortho.userData.span / 2;
      Object.assign(this.ortho, { top: half, bottom: -half, left: (-half * w) / h, right: (half * w) / h });
      this.ortho.updateProjectionMatrix();
    }
  }

  clear() {
    this.loadToken += 1;
    this.loopRange = null;
    this.exitRig();
    if (this.helper) {
      this.scene.remove(this.helper);
      this.helper.dispose();
      this.helper = null;
    }
    if (this.root) {
      this.scene.remove(this.root);
      this.root.traverse((obj) => {
        obj.geometry?.dispose();
        for (const mat of [].concat(obj.material || [])) {
          for (const value of Object.values(mat)) if (value?.isTexture) value.dispose();
          mat.dispose();
        }
      });
      this.root = null;
    }
    this.mixer = null;
    this.action = null;
    this.clips = [];
    this.tracked = null;
    this.path = null;
    this.gizmo.detach();
    this.props.clear();
    this.offsets.clear();
    this.animated.clear();
    this.bones = new Map();
    this.ground.visible = false;
  }

  // Um quadrado com borda; repetido, vira a grade do piso.
  gridTexture() {
    const size = 256;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#22262e";
    ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = "#6f7b90";
    ctx.fillRect(0, 0, size, 3);
    ctx.fillRect(0, 0, 3, size);
    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    return texture;
  }

  /** Carrega um GLB. Devolve os nomes das animações que ele traz. */
  async load(url) {
    this.clear();
    const token = this.loadToken;
    const gltf = await this.loader.loadAsync(url);
    if (token !== this.loadToken) return null; // outra seleção chegou antes
    this.root = gltf.scene;
    this.scene.add(this.root);

    const box = new THREE.Box3().setFromObject(this.root);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const height = Math.max(size.y, 0.01);
    this.controls.target.copy(center);
    const reach = Math.max(height, size.x * 0.75, size.z * 0.75);
    this.camera.position.copy(center).add(new THREE.Vector3(0.75, 0.3, 2.0).normalize().multiplyScalar(reach * 2.4));
    this.camera.near = reach / 200;
    this.camera.far = reach * 400;
    // A névoa some com a grade ao longe (sem ela as linhas viram moiré no horizonte).
    this.scene.fog.near = reach * 5;
    this.scene.fog.far = reach * 16;
    this.camera.updateProjectionMatrix();

    this.reach = reach;
    this.midY = center.y;
    // Quadrados de 1 unidade (1 m num personagem de tamanho humano); número par de
    // quadrados para uma linha passar pela origem.
    const cell = Math.max(1, Math.round(reach / 1.8));
    const cells = 2 * Math.round((reach * 100) / cell);
    this.ground.position.set(0, box.min.y, 0);
    this.ground.scale.setScalar(cells * cell);
    this.ground.material.map.repeat.set(cells, cells);
    this.ground.visible = true;
    const shadow = this.sun.shadow.camera;
    shadow.left = shadow.bottom = -reach * 1.6;
    shadow.right = shadow.top = reach * 1.6;
    shadow.near = reach * 0.1;
    shadow.far = reach * 12;
    shadow.updateProjectionMatrix();
    // Sem esta folga a superfície faz sombra nela mesma, em faixas que tremem com o movimento.
    this.sun.shadow.normalBias = reach * 0.02;
    this.root.traverse((obj) => {
      if (!obj.isMesh) return;
      // Transparência comum não grava profundidade: num personagem inteiro, faces de trás
      // aparecem por cima das da frente. O pontilhado (alphaHash) dispensa ordenação.
      for (const mat of [].concat(obj.material || [])) {
        // A névoa é só para o piso sumir no horizonte: no personagem ela apagaria a textura
        // assim que ele se afastasse da câmera.
        mat.fog = false;
        if (!mat.transparent) continue;
        mat.transparent = false;
        mat.alphaHash = true;
        mat.depthWrite = true;
      }
      obj.castShadow = true;
      // A caixa de uma malha com skin fica na pose de descanso: sem isto o personagem
      // some da tela quando a animação o leva para longe da origem.
      obj.frustumCulled = false;
    });
    this.placeSun(center.x, center.z);

    this.helper = new THREE.SkeletonHelper(this.root);
    this.scene.add(this.helper);
    const bones = [];
    this.root.traverse((obj) => obj.isBone && bones.push(obj));
    this.bones = new Map(bones.map((b) => [b.name, b]));
    this.tracked = bones.find((b) => HIPS.test(b.name)) || bones[0] || null;
    this.lastTracked = this.tracked ? this.tracked.getWorldPosition(new THREE.Vector3()) : null;

    this.clips = gltf.animations;
    if (this.clips.length) {
      this.mixer = new THREE.AnimationMixer(this.root);
      this.selectClip(0);
    }
    this.applyOptions();
    return this.clips.map((c) => c.name);
  }

  selectClip(index) {
    if (!this.mixer) return;
    this.mixer.stopAllAction();
    this.action = this.mixer.clipAction(this.clips[index]);
    this.action.play();
    this.computePath();
    this.applyInPlace();
    this.lastTracked = this.tracked ? this.tracked.getWorldPosition(new THREE.Vector3()) : null;
  }

  get duration() {
    return this.action ? this.action.getClip().duration : 0;
  }

  get playing() {
    return !!this.action && !this.action.paused;
  }

  setPlaying(on) {
    if (this.action) this.action.paused = !on;
  }

  /** Toca em repetição só um trecho do clipe, [início, fim] em segundos; null volta ao clipe inteiro. */
  setLoopRange(range) {
    this.loopRange = range;
    if (range) this.seek(range[0]);
  }

  seek(seconds) {
    if (!this.action) return;
    this.action.time = Math.min(Math.max(seconds, 0), this.duration);
    this.refreshPose();
    this.applyInPlace();
    this.followStep();
  }

  setSpeed(speed) {
    if (this.mixer) this.mixer.timeScale = speed;
    this.speed = speed;
  }

  setOption(name, value) {
    this.options[name] = value;
    if (name === 'inPlace' && this.tracked) {
      // O personagem salta de onde estava para a origem (ou de volta): a câmera vai junto.
      const before = this.tracked.getWorldPosition(new THREE.Vector3());
      this.applyInPlace();
      const after = this.tracked.getWorldPosition(new THREE.Vector3());
      for (const v of [this.camera.position, this.controls.target]) {
        v.x += after.x - before.x;
        v.z += after.z - before.z;
      }
      this.lastTracked = after;
    }
    this.applyOptions();
  }

  applyOptions() {
    if (this.helper) this.helper.visible = this.options.bones;
    if (this.mixer && this.speed) this.mixer.timeScale = this.speed;
    this.root?.traverse((obj) => {
      for (const mat of [].concat(obj.material || [])) mat.wireframe = this.options.wire;
    });
  }

  // A luz acompanha o personagem para a sombra não sair do mapa.
  placeSun(x, z) {
    this.sun.target.position.set(x, this.midY, z);
    this.sun.position.set(x + this.reach * 2.2, this.midY + this.reach * 4.5, z + this.reach * 2.6);
  }

  // Mantém o personagem no quadro quando a animação o leva para longe.
  followStep() {
    if (!this.tracked) return;
    const pos = this.tracked.getWorldPosition(new THREE.Vector3());
    this.placeSun(pos.x, pos.z);
    if (this.options.follow && this.lastTracked) {
      const dx = pos.x - this.lastTracked.x;
      const dz = pos.z - this.lastTracked.z;
      this.camera.position.x += dx;
      this.camera.position.z += dz;
      this.controls.target.x += dx;
      this.controls.target.z += dz;
    }
    this.lastTracked = pos;
  }

  tick() {
    const dt = this.clock.getDelta();
    if (this.mixer) {
      this.beforeMixer();
      this.mixer.update(dt);
      if (this.loopRange && this.action) {
        const [start, end] = this.loopRange;
        const t = this.action.time;
        if (t >= end || t < start) {
          // O fim do trecho tem a pose do começo dele: a sobra de tempo segue de lá, sem tranco.
          this.action.time = start + (t >= end ? (t - end) % (end - start) : 0);
          this.mixer.update(0);
        }
      }
      this.afterMixer();
      this.applyInPlace();
      this.followStep();
      this.onTime(this.action.time, this.duration);
    }
    this.controls.update();
    const camera = this.ortho || this.camera;
    if (this.rig) {
      // Os rótulos são HTML por cima do canvas, seguindo cada círculo.
      const { clientWidth: w, clientHeight: h } = this.container;
      for (const [name, dot] of this.rig.dots) {
        const p = dot.position.clone().project(camera);
        this.rig.tags.get(name).style.transform = `translate(${((p.x + 1) / 2) * w + 12}px, ${((1 - p.y) / 2) * h - 9}px)`;
      }
    }
    this.renderer.render(this.scene, camera);
  }
}
