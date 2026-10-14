// Simulador: o personagem do projeto anda pelo chão, comandado pelo teclado ou por cliques, e as
// animações trocam sozinhas (parado, andando, correndo), como num jogo. Mostra o que a tela de
// uma animação só não mostra: a troca de uma para a outra e o pé deslizando quando a velocidade
// do personagem não combina com o passo da animação.
//
// Cada animação do projeto é um GLB com o personagem inteiro. Aqui o personagem é carregado uma
// vez e das outras só se aproveita o movimento, que serve porque o esqueleto é o mesmo.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const $ = (sel) => document.querySelector(sel);
const HIPS = /hips|pelvis/i;
const num = (value, digits = 2) => Number(value).toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const clamp = (value, low, high) => Math.min(Math.max(value, low), high);

const projectId = decodeURIComponent(location.hash.replace(/^#/, ''));
const SAVE_KEY = `ponte.simulador.${projectId}`;
// O que cada momento do jogo pede, e como achar a animação certa pelo nome.
const TURN = /turn|vira|meia.?volta|180/i;
const RUN = /run|corr/i;
const STATES = {
  // `prefer` é o nome exato que o jogo usa: com ele, ganha de qualquer outro parecido.
  idle: { label: 'Parado', match: /idle|parad|stand|breath|ocios|espera/i, exclude: /turn|vira|meia.?volta|180|_to_|start|partida|come[cç]/i, prefer: /^idle$/i },
  walk: { label: 'Andando', match: /walk|andar|andando|caminh/i, exclude: /turn|vira|meia.?volta|180|_to_|start|partida|come[cç]/i, prefer: /^walk(_forward)?$/i },
  // A partida: do parado para o andar com passos de verdade (termina igual ao primeiro quadro do andar).
  start: { label: 'Começar a andar', match: /idle_to_walk|_to_walk|start|partida|come[cç]/i, exclude: TURN, prefer: /^idle_to_walk$/i },
  // A parada: do andar para o parado com o passo que falta (termina igual ao primeiro quadro do parado).
  stop: { label: 'Parar de andar', match: /walk_to_idle|_to_idle|stop|parar|parada/i, exclude: /turn|vira|meia.?volta|180|run|corr/i, prefer: /^walk_to_idle$/i },
  stopRun: { label: 'Parar de correr', match: /run_to_idle|run_stop|parar.*corr|parada.*corr/i, exclude: TURN, prefer: /^run_to_idle$/i },
  run: { label: 'Correndo', match: /run|corr|jog|sprint|dispar/i, exclude: TURN, prefer: /^run(_forward)?$/i },
  // A meia-volta: quando o jogador manda para o lado contrário, toca este clipe em vez de girar no
  // lugar. O clipe vira o corpo por conta própria (180°) e termina na pose do andar, que segue dele.
  turnWalk: { label: 'Meia-volta andando', match: TURN, exclude: /idle|parad|left|right|esquerd|direit|run|corr/i, prefer: /^turn_around(_walk)?$/i },
  turnIdle: { label: 'Meia-volta parado', match: TURN, require: /idle|parad/i, exclude: /left|right|esquerd|direit|run|corr/i, prefer: /^turn_around_idle$/i },
  // Virar 90°: o mesmo, para quando a direção pedida fica para o lado (entre 60° e 135°).
  turnLeft: { label: 'Virar à esquerda andando', match: TURN, require: /left|esquerd/i, exclude: /idle|parad|around|meia|run|corr|_(45|135)/i, prefer: /^turn_left$/i },
  turnRight: { label: 'Virar à direita andando', match: TURN, require: /right|direit/i, exclude: /idle|parad|around|meia|run|corr|_(45|135)/i, prefer: /^turn_right$/i },
  // As de 45° e 135° (12/10/2026) só entram pelo nome exato (strict): sem elas, o ângulo mais próximo que existe serve.
  turnLeft45: { label: 'Virar 45° à esquerda andando', match: TURN, prefer: /^turn_left_45$/i, strict: true },
  turnRight45: { label: 'Virar 45° à direita andando', match: TURN, prefer: /^turn_right_45$/i, strict: true },
  turnLeft135: { label: 'Virar 135° à esquerda andando', match: TURN, prefer: /^turn_left_135$/i, strict: true },
  turnRight135: { label: 'Virar 135° à direita andando', match: TURN, prefer: /^turn_right_135$/i, strict: true },
  turnLeft45Idle: { label: 'Virar 45° à esquerda parado', match: TURN, prefer: /^turn_left_45_idle$/i, strict: true },
  turnRight45Idle: { label: 'Virar 45° à direita parado', match: TURN, prefer: /^turn_right_45_idle$/i, strict: true },
  turnLeft135Idle: { label: 'Virar 135° à esquerda parado', match: TURN, prefer: /^turn_left_135_idle$/i, strict: true },
  turnRight135Idle: { label: 'Virar 135° à direita parado', match: TURN, prefer: /^turn_right_135_idle$/i, strict: true },
  // Correndo, as viradas sao outras (em trote): comecam e terminam no run_forward.
  turnAroundRun: { label: 'Meia-volta correndo', match: TURN, require: RUN, exclude: /left|right|esquerd|direit|idle|parad/i, prefer: /^run_turn_around$/i },
  turnLeftRun: { label: 'Virar à esquerda correndo', match: TURN, require: RUN, exclude: /around|meia|idle|parad/i, prefer: /^run_turn_left$/i },
  turnRightRun: { label: 'Virar à direita correndo', match: TURN, require: RUN, exclude: /around|meia|idle|parad/i, prefer: /^run_turn_right$/i },
  turnLeftIdle: { label: 'Virar à esquerda parado', match: TURN, require: /(left|esquerd)[\s\S]*(idle|parad)|(idle|parad)[\s\S]*(left|esquerd)/i, exclude: /around|meia|_(45|135)/i, prefer: /^turn_left_idle$/i },
  turnRightIdle: { label: 'Virar à direita parado', match: TURN, require: /(right|direit)[\s\S]*(idle|parad)|(idle|parad)[\s\S]*(right|direit)/i, exclude: /around|meia|_(45|135)/i, prefer: /^turn_right_idle$/i },
};
// Num nome com direção ou postura, a animação não é a de andar para frente em pé.
const VARIANT = /back|left|right|tr[aá]s|esquerd|direit|lado|side|strafe|crouch|agach|aim|mira/i;
// Agachado é outro corpo: não serve de virada a quem está em pé (13/10/2026: o "crouching turn 90 left" de um
// pacote do Mixamo entrava em toda virada do andar).
const CROUCH = /crouch|agach/i;
const LOOPS = ['idle', 'walk', 'run'];
// O nome como o jogo o escreve: um pacote do Mixamo vem com espaço ("walk forward"), o jogo usa sublinhado
// ("walk_forward"). É por esta forma que os momentos são achados; na tela o nome aparece como é.
const keyOf = (name) => String(name).trim().replace(/[\s-]+/g, '_');
const byName = (x, y) => x.name.localeCompare(y.name, 'pt-BR', { numeric: true, sensitivity: 'base' });

function fail(message) {
  $('#loading').hidden = false;
  $('#loading').textContent = message;
}

function toast(message) {
  const el = Object.assign(document.createElement('div'), { className: 'toast ok', textContent: message });
  $('#toasts').append(el);
  setTimeout(() => el.remove(), 7000);
}

// --- Cena ---------------------------------------------------------------------------------------

const stage = $('#stage');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.domElement.tabIndex = 0;
stage.prepend(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0e1013);
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.45;
scene.fog = new THREE.Fog(0x0e1013, 10, 40);
const sun = new THREE.DirectionalLight(0xffffff, 1.2);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.bias = -0.0004;
scene.add(sun, sun.target);

const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 500);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.enablePan = false; // a câmera fica presa ao personagem; arrastar só gira
controls.maxPolarAngle = Math.PI / 2 - 0.03;

function resize() {
  const { clientWidth: w, clientHeight: h } = stage;
  if (!w || !h) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(stage);
resize();

// Um quadrado com borda; repetido, vira a grade do piso (é ela que mostra o pé deslizando).
function gridTexture() {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#22262e';
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = '#6f7b90';
  ctx.fillRect(0, 0, size, 3);
  ctx.fillRect(0, 0, 3, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return texture;
}

// --- Leitura dos arquivos -----------------------------------------------------------------------

const loader = new GLTFLoader();

function dispose(root) {
  root.traverse((obj) => {
    obj.geometry?.dispose();
    for (const mat of [].concat(obj.material || [])) {
      for (const value of Object.values(mat)) if (value?.isTexture) value.dispose();
      mat.dispose();
    }
  });
}

// O mesmo GLB sem malha, textura nem material: fica só o esqueleto e o movimento. Uma animação do
// projeto leva o personagem inteiro (dezenas de MB de textura), e daqui só interessa o movimento.
function withoutMeshes(buffer) {
  const view = new DataView(buffer);
  if (view.getUint32(0, true) !== 0x46546c67 || view.getUint32(16, true) !== 0x4e4f534a) throw new Error('não é um GLB');
  const jsonLength = view.getUint32(12, true);
  const json = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 20, jsonLength)));
  for (const key of ['images', 'textures', 'samplers', 'materials', 'meshes', 'skins', 'cameras', 'extensionsUsed', 'extensionsRequired']) delete json[key];
  for (const node of json.nodes || []) {
    delete node.mesh;
    delete node.skin;
    delete node.camera;
  }
  const text = new TextEncoder().encode(JSON.stringify(json));
  const padded = Math.ceil(text.length / 4) * 4;
  const rest = buffer.byteLength - (20 + jsonLength); // o pedaço binário, com o cabeçalho dele
  const out = new Uint8Array(20 + padded + rest);
  const head = new DataView(out.buffer);
  head.setUint32(0, 0x46546c67, true);
  head.setUint32(4, 2, true);
  head.setUint32(8, out.length, true);
  head.setUint32(12, padded, true);
  head.setUint32(16, 0x4e4f534a, true);
  out.fill(0x20, 20, 20 + padded);
  out.set(text, 20);
  out.set(new Uint8Array(buffer, 20 + jsonLength, rest), 20 + padded);
  return out.buffer;
}

// --- O personagem -------------------------------------------------------------------------------

const sim = {
  ready: false,
  model: null,
  character: new THREE.Group(), // quem anda pelo chão; o modelo fica dentro, sem sair do lugar
  height: 1.8,
  hips: null,
  feet: { l: null, r: null },
  anims: [], // {id, name, clip, natural: {speed, angle}, travel, duration}
  clipFor: { idle: null, walk: null, run: null, start: null, stop: null, stopRun: null, turnAroundRun: null, turnLeftRun: null, turnRightRun: null, turnWalk: null, turnIdle: null, turnLeft: null, turnRight: null, turnLeftIdle: null, turnRightIdle: null },
  mixer: null,
  current: null, // {anim, action}
  oneShot: null,
  position: new THREE.Vector3(),
  facing: 0,
  moveDir: new THREE.Vector3(0, 0, 1),
  speed: 0,
  target: null,
  mode: 'idle',
  rate: 1,
  slide: null,
};
scene.add(sim.character);

const settings = { set: 'patrulha', fade: 0.25, turn: 540, fit: false, speedWalk: null, speedRun: null, idle: undefined, walk: undefined, run: undefined, start: undefined, stop: undefined, stopRun: undefined, turnAroundRun: undefined, turnLeftRun: undefined, turnRightRun: undefined, turnWalk: undefined, turnIdle: undefined, turnLeft: undefined, turnRight: undefined, turnLeftIdle: undefined, turnRightIdle: undefined, ...JSON.parse(localStorage.getItem(SAVE_KEY) || '{}') };
const save = () => localStorage.setItem(SAVE_KEY, JSON.stringify(settings));

const sideOf = (name) => (/left|(^|[^a-z])l([^a-z]|$)/i.test(name) ? 'l' : /right|(^|[^a-z])r([^a-z]|$)/i.test(name) ? 'r' : null);
const nodeOf = (track) => sim.model.getObjectByName(THREE.PropertyBinding.parseTrackName(track.name).nodeName);

/** Que parte das pistas da animação acha o osso dela neste personagem (0 a 1). */
function bound(clip) {
  if (!clip?.tracks.length) return 0;
  return clip.tracks.filter((track) => nodeOf(track)).length / clip.tracks.length;
}

/** O movimento de um GLB do projeto. Tenta a leitura leve; se os ossos não baterem, lê o arquivo inteiro. */
async function fetchClip(url) {
  const buffer = await (await fetch(url)).arrayBuffer();
  try {
    const light = await loader.parseAsync(withoutMeshes(buffer), '');
    if (bound(light.animations[0]) >= 0.8) return light.animations[0];
  } catch { /* cai na leitura inteira */ }
  const full = await loader.parseAsync(buffer, '');
  dispose(full.scene);
  return full.animations[0] || null;
}

function carriesHips(node) {
  for (let obj = sim.hips; obj; obj = obj.parent) if (obj === node) return true;
  return false;
}

/**
 * A mesma animação sem sair do lugar: sai o deslocamento no chão do começo ao fim (em linha
 * reta) e fica o balanço do corpo. Num jogo quem leva o personagem é o código, não a animação.
 */
/** Onde o quadril está no chão, no espaço do modelo, `time` segundos depois do começo do clipe (do caminho medido). */
function rootAt(root, time) {
  const k = clamp(time / root.dt, 0, root.xz.length - 1);
  const i = Math.floor(k);
  const f = k - i;
  const a = root.xz[i];
  const b = root.xz[Math.min(i + 1, root.xz.length - 1)];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
}

function inPlace(clip, root = null) {
  const out = clip.clone();
  for (const track of out.tracks) {
    if (!track.name.endsWith('.position')) continue;
    const node = nodeOf(track);
    if (!node?.parent || !carriesHips(node)) continue;
    const v = track.values;
    const t = track.times;
    const n = t.length;
    if (n < 2) continue;
    // Só a parte horizontal sai. Qual é ela, nos eixos do osso, depende de como o pai dele está virado.
    const toWorld = new THREE.Matrix3().setFromMatrix4(node.parent.matrixWorld);
    if (root && node === sim.hips) {
      // Num clipe que vai a algum lugar (uma virada, um bote) sai o caminho inteiro do quadril, quadro a quadro, e
      // ele volta como movimento do personagem no instante certo (`rootAt`): é o root motion de um jogo. Tirar só a
      // média deixava no clipe o que sobra do caminho, e a mistura com o andar (que é no lugar) somava posições
      // que se afastam: a velocidade do corpo fazia um V na entrada de cada virada e dava um tranco no fim dela.
      const toLocal = toWorld.clone().invert();
      for (let i = 0; i < n; i++) {
        const [x, z] = rootAt(root, t[i] - t[0]);
        const d = new THREE.Vector3(x, 0, z).applyMatrix3(toLocal);
        v[i * 3] -= d.x;
        v[i * 3 + 1] -= d.y;
        v[i * 3 + 2] -= d.z;
      }
      continue;
    }
    const drift = new THREE.Vector3(v[(n - 1) * 3] - v[0], v[(n - 1) * 3 + 1] - v[1], v[(n - 1) * 3 + 2] - v[2]).applyMatrix3(toWorld);
    drift.y = 0;
    drift.applyMatrix3(toWorld.clone().invert());
    const span = t[n - 1] - t[0] || 1;
    for (let i = 0; i < n; i++) {
      const k = (t[i] - t[0]) / span;
      v[i * 3] -= drift.x * k;
      v[i * 3 + 1] -= drift.y * k;
      v[i * 3 + 2] -= drift.z * k;
    }
  }
  return out;
}

/** A direção, no chão, em que um ponto mais se espalha (a linha em que o pé vai e volta). */
function principalAxis(points) {
  const n = points.length;
  const mx = points.reduce((sum, p) => sum + p.x, 0) / n;
  const mz = points.reduce((sum, p) => sum + p.z, 0) / n;
  let sxx = 0;
  let szz = 0;
  let sxz = 0;
  for (const p of points) {
    sxx += (p.x - mx) ** 2;
    szz += (p.z - mz) ** 2;
    sxz += (p.x - mx) * (p.z - mz);
  }
  const theta = 0.5 * Math.atan2(2 * sxz, sxx - szz);
  return new THREE.Vector3(Math.cos(theta), 0, Math.sin(theta));
}

/**
 * O passo da animação: a que velocidade e para que lado o corpo iria, no chão.
 * Se ela anda de verdade, é o deslocamento do quadril. Se foi feita parada no lugar, é o
 * contrário do que o pé apoiado faz: ele escorrega para trás na velocidade em que o corpo iria.
 */
function measure(clip) {
  const mixer = new THREE.AnimationMixer(sim.model);
  const action = mixer.clipAction(clip);
  action.play();
  const duration = clip.duration;
  const steps = clamp(Math.round(duration * 30), 8, 300);
  const hips = [];
  const feet = { l: [], r: [] };
  const legs = { l: [], r: [] };
  for (let i = 0; i <= steps; i++) {
    mixer.setTime(Math.min((duration * i) / steps, Math.max(duration - 1e-4, 0)));
    sim.model.updateMatrixWorld(true);
    if (sim.hips) hips.push(sim.hips.getWorldPosition(new THREE.Vector3()));
    for (const side of ['l', 'r']) {
      if (sim.feet[side]) feet[side].push(sim.feet[side].getWorldPosition(new THREE.Vector3()));
      if (sim.legs?.[side]) legs[side].push(sim.legs[side].getWorldPosition(new THREE.Vector3()));
    }
  }
  action.stop();
  mixer.uncacheRoot(sim.model);
  sim.model.updateMatrixWorld(true);

  const travel = hips.length > 1 ? hips[hips.length - 1].clone().sub(hips[0]).setY(0) : new THREE.Vector3();
  // A velocidade do quadril no chão no primeiro e no último quadro: é com ela que o clipe entra e sai, e é
  // dela que o corpo tem de continuar na troca (um clipe de virada que termina a 80 cm/s não pode cair a 62 num quadro).
  const n = hips.length;
  const edge = n > 2 ? { start: hips[1].clone().sub(hips[0]).setY(0).length() / (duration / steps), end: hips[n - 1].clone().sub(hips[n - 2]).setY(0).length() / (duration / steps) } : { start: 0, end: 0 };
  // O caminho do quadril no chão (root motion), para os clipes que saem do lugar de verdade; o balanço de um laço
  // feito no lugar (uns centímetros) fica como está.
  const xz = hips.map((h) => [h.x - hips[0].x, h.z - hips[0].z]);
  const roams = xz.some(([x, z]) => Math.hypot(x, z) > 0.15 * sim.height);
  const root = roams && n > 2 ? { dt: duration / steps, xz } : null;
  // A fase dos pés, quadro a quadro (Bollo, Gears of War 4): pé esquerdo menos direito, projetado na frente do corpo
  // (a linha entre as coxas). Positivo = esquerdo na frente; com o sentido (subindo ou caindo) diz o ponto do passo.
  let phase = null;
  const m = feet.l.length;
  if (m > 2 && feet.r.length === m && legs.l.length === m && legs.r.length === m) {
    const q = feet.l.map((l, i) => {
      const lateral = legs.l[i].clone().sub(legs.r[i]).setY(0).normalize();
      const fwd = new THREE.Vector3().crossVectors(lateral, THREE.Object3D.DEFAULT_UP);
      return l.clone().sub(feet.r[i]).setY(0).dot(fwd);
    });
    phase = { dt: duration / steps, q };
  }
  // Onde estão os pés em relação ao quadril no primeiro e no último quadro, vistos do próprio corpo (não muda com
  // o giro): é o que diz se um clipe termina na pose do parado ou na do andar (`endsStanding`).
  let pose = null;
  if (phase && hips.length === m) {
    const stance = (i) => {
      const lateral = legs.l[i].clone().sub(legs.r[i]).setY(0).normalize();
      const fwd = new THREE.Vector3().crossVectors(lateral, THREE.Object3D.DEFAULT_UP);
      return ['l', 'r'].flatMap((side) => {
        const d = feet[side][i].clone().sub(hips[i]);
        return [d.dot(lateral), d.y, d.dot(fwd)];
      });
    };
    pose = { first: stance(0), last: stance(m - 1) };
  }
  const moves = 0.08 * sim.height; // por segundo; abaixo disso é balanço, não é andar
  let velocity = duration > 0 ? travel.clone().divideScalar(duration) : new THREE.Vector3();
  let how = 'deslocamento';
  if (velocity.length() < moves && duration > 0) {
    // Parada no lugar: o que a ponta do pé faz enquanto está no chão, com o sinal trocado.
    const dt = duration / steps;
    const sum = new THREE.Vector3();
    let sides = 0;
    for (const side of ['l', 'r']) {
      const p = feet[side];
      if (p.length < 3) continue;
      const axis = principalAxis(p); // a linha em que o pé vai e volta
      const along = p.map((q) => q.x * axis.x + q.z * axis.z);
      if (Math.max(...along) - Math.min(...along) < 0.08 * sim.height) continue; // não dá passo: é balanço
      const ys = p.map((q) => q.y);
      const low = Math.min(...ys);
      const near = low + Math.max(0.2 * (Math.max(...ys) - low), 0.01 * sim.height);
      // Perto do chão o pé ou está apoiado, indo para trás devagar, ou acabou de passar rente,
      // indo para a frente depressa. O apoio dura mais: é o grupo maior.
      const back = [];
      const front = [];
      for (let i = 0; i < p.length - 1; i++) {
        if (ys[i] > near || ys[i + 1] > near) continue;
        const u = (along[i + 1] - along[i]) / dt;
        (u < 0 ? back : front).push(u);
      }
      const group = (back.length >= front.length ? back : front).sort((a, b) => a - b);
      if (group.length < 2) continue;
      sum.addScaledVector(axis, -group[Math.floor(group.length / 2)]);
      sides += 1;
    }
    velocity = sides ? sum.divideScalar(sides) : new THREE.Vector3();
    how = sides ? 'pés' : 'nada';
  }
  const speed = velocity.length();
  const walking = speed >= moves;
  let angle = walking ? Math.atan2(velocity.x, velocity.z) : 0;
  if (Math.abs(angle) < THREE.MathUtils.degToRad(12)) angle = 0; // quase para frente é para frente
  return { natural: { speed: walking ? speed : 0, angle, how: walking ? how : 'nada' }, travel, edge, root, phase, pose };
}

/**
 * O clipe termina na pose do parado, e não na do andar? Os clipes do jogo que emendam no andar terminam no primeiro
 * quadro dele; uma virada de pacote do Mixamo ("turn 90 left") termina igual ao parado, e é o parado que entra depois.
 */
function endsStanding(anim) {
  const idle = sim.clipFor.idle?.pose;
  if (!anim?.pose || !idle) return false;
  const apart = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));
  const toIdle = apart(anim.pose.last, idle.first);
  const walk = sim.clipFor.walk?.pose;
  return toIdle < 0.03 * sim.height && (!walk || toIdle < 0.5 * apart(anim.pose.last, walk.first));
}

const nameOf = (data, result) => data.motions.find((m) => m.id === result.motion_id)?.name || result.prompt || result.id;

async function start() {
  if (!projectId) return fail('Abra o simulador pela tela de um projeto.');
  const data = await (await fetch('/api/state')).json();
  const asset = data.assets.find((a) => a.id === projectId);
  if (!asset) return fail('Não achei este projeto. Volte à tela de projetos e abra o simulador de novo.');
  $('#back').href = `/#p/${projectId}`;
  $('#project-name').textContent = asset.name;
  document.title = `Simulador · ${asset.name}`;
  const list = data.results
    .filter((r) => r.asset_id === projectId && r.files?.glb)
    .map((r) => ({ id: r.id, name: nameOf(data, r), stamp: r.created_at, url: `${r.files_base}/${r.files.glb}?v=${encodeURIComponent(r.created_at)}` }))
    .map((a) => ({ ...a, key: keyOf(a.name) }))
    .sort((a, b) => a.stamp.localeCompare(b.stamp));
  sim.signature = JSON.stringify(list.map((a) => [a.id, a.stamp]));
  if (!list.length) return fail(`${asset.name} ainda não tem animação. O simulador precisa de pelo menos uma: peça à IA no terminal do projeto ou traga uma do Mixamo.`);

  // O personagem vem do arquivo da animação de "parado" (ou da primeira), com textura e tudo.
  const fits = (state, a) => STATES[state].match.test(a.key) && !STATES[state].exclude?.test(a.key) && (!STATES[state].require || STATES[state].require.test(a.key));
  // Na falta do nome do jogo: a que não é variante; depois, uma variante em pé; agachada só entra num laço (parado, andar, correr), nunca numa virada.
  const pick = (state) => list.find((a) => a.id === settings[state]) || (settings[state] === null ? null : list.find((a) => STATES[state].prefer?.test(a.key)) || (STATES[state].strict ? null : list.find((a) => fits(state, a) && !VARIANT.test(a.key)) || list.find((a) => fits(state, a) && !CROUCH.test(a.key)) || (LOOPS.includes(state) ? list.find((a) => fits(state, a)) : null)) || null);
  const base = pick('idle') || list[0];
  $('#loading').textContent = `Carregando ${asset.name}…`;
  const gltf = await loader.loadAsync(base.url);
  const model = (sim.model = gltf.scene);
  sim.character.add(model);
  model.updateMatrixWorld(true);

  const box = new THREE.Box3().setFromObject(model);
  const h = (sim.height = Math.max(box.getSize(new THREE.Vector3()).y, 0.01));
  sim.floor = box.min.y;
  model.traverse((obj) => {
    if (!obj.isMesh) return;
    for (const mat of [].concat(obj.material || [])) {
      mat.fog = false; // a névoa é só para o piso sumir ao longe
      if (!mat.transparent) continue;
      mat.transparent = false;
      mat.alphaHash = true;
      mat.depthWrite = true;
    }
    obj.castShadow = true;
    obj.frustumCulled = false; // a caixa de uma malha com skin fica na pose de descanso
  });
  const bones = [];
  model.traverse((obj) => obj.isBone && bones.push(obj));
  sim.hips = bones.find((b) => HIPS.test(b.name)) || bones[0] || null;
  // As coxas dão a frente do corpo (a linha entre elas), para a fase dos pés não depender de para onde ele está virado.
  sim.legs = { l: bones.find((b) => /LeftUpLeg$|Left.*Thigh|L_Thigh|thigh\.L/i.test(b.name)) || null, r: bones.find((b) => /RightUpLeg$|Right.*Thigh|R_Thigh|thigh\.R/i.test(b.name)) || null };
  // O que encosta no chão: a ponta do pé (ela fica parada do pé inteiro no chão até sair);
  // sem osso de ponta, o tornozelo.
  const contact = { l: {}, r: {} };
  for (const bone of bones) {
    const side = sideOf(bone.name);
    if (!side || /end|ik|roll|heel/i.test(bone.name)) continue;
    if (/toe/i.test(bone.name)) contact[side].toe ??= bone;
    else if (/foot/i.test(bone.name)) contact[side].foot ??= bone;
  }
  for (const side of ['l', 'r']) sim.feet[side] = contact[side].toe || contact[side].foot || null;
  sim.helper = new THREE.SkeletonHelper(model);
  sim.helper.visible = false;
  scene.add(sim.helper);

  // As animações: a do arquivo aberto já veio; das outras, só o movimento.
  for (const [index, anim] of list.entries()) {
    $('#loading').textContent = `Lendo as animações de ${asset.name}: ${index + 1} de ${list.length}…`;
    const clip = anim === base ? gltf.animations[0] : await fetchClip(anim.url);
    if (!clip || bound(clip) < 0.5) {
      toast(`"${anim.name}" não combina com o esqueleto deste personagem e ficou de fora.`);
      continue;
    }
    const { natural, travel, edge, root, phase, pose } = measure(clip);
    sim.anims.push({ id: anim.id, name: anim.name, key: anim.key, clip: inPlace(clip, root), natural, travel, edge, root, phase, pose, duration: clip.duration });
  }
  if (!sim.anims.length) return fail('Nenhuma animação deste projeto pôde ser lida.');
  const byId = (id) => sim.anims.find((a) => a.id === id) || null;
  for (const state of Object.keys(STATES)) sim.clipFor[state] = byId(pick(state)?.id);
  // Virada que não sai do lugar e não tem o nome exato do jogo (as "turn 90 left/right" de um pacote do Mixamo, que
  // começam e terminam na pose do parado) não entra sozinha em momento nenhum: no meio do andar ela para o corpo, e
  // em fila (90° e mais 90°) ele achou lenta ("ao invés de virar de uma vez ele vai girando devagarzinho, animação
  // por animação", 13/10/2026). Sem clipe ele vira de uma vez (`sim.steer`). Ela fica nos seletores, para quem quiser.
  for (const state of ['turnLeft', 'turnRight', 'turnWalk']) {
    const anim = sim.clipFor[state];
    if (anim && !anim.root && !anim.natural.speed && settings[state] === undefined && !STATES[state].prefer.test(anim.key)) sim.clipFor[state] = null;
  }
  if (settings.set === 'alerta') chooseSet('alerta');
  if (!sim.clipFor.idle && settings.idle === undefined && sim.anims.length === 1 && !sim.clipFor.walk) sim.clipFor.idle = sim.anims[0];

  sim.mixer = new THREE.AnimationMixer(model);
  sim.mixer.addEventListener('finished', (e) => {
    if (sim.oneShot?.action === e.action) sim.oneShot.done = true;
    if (sim.cover?.action === e.action) sim.cover.done = true;
  });

  buildArena(h);
  setCamera('near');
  buildPanel(asset);
  sim.ready = true;
  $('#loading').hidden = true;
  $('#hud').hidden = $('#keys').hidden = $('#side').hidden = false;
  resize();
  renderer.domElement.focus();
  document.body.dataset.visor = `sim:${projectId}`; // "pronto": é o que tests/ui_click.mjs espera
  setInterval(watchProject, 3000);
}

// --- O cenário ----------------------------------------------------------------------------------

function buildArena(h) {
  const cell = Math.max(1, Math.round(h / 1.8)); // quadrados de 1 m num personagem de tamanho humano
  const cells = 400;
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshStandardMaterial({ map: gridTexture(), roughness: 1, metalness: 0 }));
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = sim.floor;
  ground.scale.setScalar(cells * cell);
  ground.material.map.repeat.set(cells, cells);
  ground.receiveShadow = true;
  scene.add(ground);
  scene.fog.near = h * 14;
  scene.fog.far = h * 45;
  camera.near = h / 200;
  camera.far = h * 400;
  camera.updateProjectionMatrix();
  controls.minDistance = h * 1.2;
  controls.maxDistance = h * 30;

  // Colunas em volta: sem nada parado por perto não dá para sentir a velocidade.
  const post = new THREE.MeshStandardMaterial({ color: 0x3a4252, roughness: 0.9, fog: false });
  for (let i = 0; i < 10; i++) {
    const angle = (i / 10) * Math.PI * 2 + 0.3;
    const radius = h * (i % 2 ? 4.5 : 7.5);
    const size = h * (i % 2 ? 0.28 : 0.4);
    const tall = h * (i % 2 ? 1.0 : 1.6);
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(size, tall, size), post);
    mesh.position.set(Math.sin(angle) * radius, sim.floor + tall / 2, Math.cos(angle) * radius);
    mesh.castShadow = mesh.receiveShadow = true;
    scene.add(mesh);
  }
  // O muro baixo da cobertura (12/10/2026) saiu a pedido dele no mesmo dia, junto com os clipes de cobertura: o código
  // (`sim.wall`, `coverStep`, teclas E e F) fica dormente enquanto `sim.wall` for nulo.
  sim.wall = null;
  // O alvo do clique: um anel no chão.
  sim.marker = new THREE.Mesh(new THREE.RingGeometry(h * 0.1, h * 0.14, 32), new THREE.MeshBasicMaterial({ color: 0xf0a43a, fog: false, side: THREE.DoubleSide }));
  sim.marker.rotation.x = -Math.PI / 2;
  sim.marker.position.y = sim.floor + h * 0.004;
  sim.marker.visible = false;
  scene.add(sim.marker);

  const shadow = sun.shadow.camera;
  shadow.left = shadow.bottom = -h * 5;
  shadow.right = shadow.top = h * 5;
  shadow.near = h * 0.1;
  shadow.far = h * 14;
  shadow.updateProjectionMatrix();
  sun.shadow.normalBias = h * 0.02;
}

function placeSun() {
  const h = sim.height;
  sun.target.position.set(sim.position.x, sim.floor + h * 0.5, sim.position.z);
  sun.position.set(sim.position.x + h * 2.2, sim.floor + h * 5, sim.position.z + h * 2.6);
}

// De perto: atrás do personagem. De cima: o ângulo de um jogo de estratégia.
function setCamera(kind) {
  const h = sim.height;
  sim.cameraKind = kind;
  controls.target.set(sim.position.x, sim.floor + h * 0.55, sim.position.z);
  const offset = kind === 'top' ? new THREE.Vector3(0, 1, -0.55).normalize().multiplyScalar(h * 9) : new THREE.Vector3(-0.25, 0.42, -1).normalize().multiplyScalar(h * 4.2);
  camera.position.copy(controls.target).add(offset);
  controls.update();
}

// --- Animações ----------------------------------------------------------------------------------

const actionOf = (anim) => sim.mixer.clipAction(anim.clip);

/** Passa a tocar esta animação, trocando aos poucos a partir da que estava. */
function play(anim, { once = false, sync = false } = {}) {
  const before = sim.current;
  if (before?.anim === anim && !once) return;
  const fade = settings.fade;
  const next = anim ? actionOf(anim) : null;
  if (next && next === before?.action && !once) {
    sim.current = { anim, action: next };
    return;
  }
  if (next) {
    const phase = sync && before?.action ? before.action.time / before.action.getClip().duration : 0;
    next.reset();
    next.setLoop(once ? THREE.LoopOnce : THREE.LoopRepeat, Infinity);
    next.clampWhenFinished = once;
    next.timeScale = 1;
    if (phase) next.time = phase * next.getClip().duration; // o pé que estava na frente continua na frente
    if (fade > 0 && before?.action) next.fadeIn(fade);
    next.play();
  }
  if (before?.action && before.action !== next) {
    if (fade > 0 && next) before.action.fadeOut(fade);
    else before.action.stop();
  }
  sim.current = anim ? { anim, action: next } : null;
}

function playOnce(anim) {
  if (!sim.ready || !anim) return;
  sim.target = null;
  sim.marker.visible = false;
  play(anim, { once: true });
  sim.oneShot = { anim, action: sim.current.action, done: false };
}

// --- Comandos -----------------------------------------------------------------------------------

const keys = { up: false, down: false, left: false, right: false, shift: false };
const KEYMAP = { KeyW: 'up', ArrowUp: 'up', KeyS: 'down', ArrowDown: 'down', KeyA: 'left', ArrowLeft: 'left', KeyD: 'right', ArrowRight: 'right', ShiftLeft: 'shift', ShiftRight: 'shift' };
const typing = (e) => !!e.target.closest?.('input, select, textarea');

window.addEventListener('keydown', (e) => {
  if (typing(e) || e.ctrlKey || e.altKey || e.metaKey) return;
  if (KEYMAP[e.code]) {
    keys[KEYMAP[e.code]] = true;
    e.preventDefault();
    return;
  }
  if (e.repeat || !sim.ready) return;
  if (e.code === 'KeyC') setCamera(sim.cameraKind === 'top' ? 'near' : 'top');
  else if (e.code === 'KeyQ') {
    // Alterna patrulha <-> alerta no meio do jogo: o clipe do momento troca pelo do outro conjunto, em mistura.
    chooseSet(settings.set === 'alerta' ? 'patrulha' : 'alerta');
    $('#set').value = settings.set;
    toast(settings.set === 'alerta' ? 'Alerta: fuzil no ombro.' : 'Patrulha: fuzil baixo.');
  }
  else if (e.code === 'KeyR') reset();
  else if (e.code === 'KeyE') coverToggle();
  else if (e.code === 'KeyF') coverFire();
  else if (/^Digit[1-9]$/.test(e.code)) playOnce(sim.extras?.[Number(e.code.slice(5)) - 1]);
});
window.addEventListener('keyup', (e) => {
  if (KEYMAP[e.code]) keys[KEYMAP[e.code]] = false;
});
window.addEventListener('blur', () => {
  for (const key of Object.keys(keys)) keys[key] = false;
});

// Arrastar gira a câmera; só um clique parado manda o personagem até o ponto.
{
  const canvas = renderer.domElement;
  let down = null;
  canvas.addEventListener('pointerdown', (e) => {
    down = [e.clientX, e.clientY];
    canvas.focus();
  });
  canvas.addEventListener('pointerup', (e) => {
    const still = down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 5;
    down = null;
    if (!still || e.button !== 0 || !sim.ready || sim.oneShot) return;
    const rect = canvas.getBoundingClientRect();
    const pointer = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(pointer, camera);
    const hit = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -sim.floor), new THREE.Vector3());
    if (!hit) return;
    // Dois cliques seguidos no chao: ele corre ate la (um clique: anda).
    const now = performance.now();
    sim.runToTarget = !!(sim.lastClick && now - sim.lastClick.at < 600 && sim.lastClick.point.distanceTo(hit) < 0.3 * sim.height);
    sim.lastClick = { at: now, point: hit.clone() };
    sim.target = hit.setY(0);
    sim.marker.position.set(hit.x, sim.marker.position.y, hit.z);
    sim.marker.visible = true;
  });
}

function reset() {
  const dx = -sim.position.x;
  const dz = -sim.position.z;
  if (sim.cover) {
    sim.cover = null;
    sim.current = null;
    play(sim.clipFor.idle);
  }
  sim.position.set(0, 0, 0);
  sim.facing = 0;
  sim.speed = 0;
  sim.target = null;
  sim.marker.visible = false;
  camera.position.x += dx;
  camera.position.z += dz;
  controls.target.x += dx;
  controls.target.z += dz;
}

// --- Um quadro do jogo --------------------------------------------------------------------------

const forward = new THREE.Vector3();
const screenUp = new THREE.Vector3();
const wish = new THREE.Vector3();

const WALKING_TURN = 240; // graus por segundo: ninguem gira mais rapido que isso andando

// Cada virada (e a parada) que entra do andar tem duas versoes: a normal comeca com o pe esquerdo na
// frente (o quadro 1 do andar) e a "_r" com o pe direito (a metade do passo). Quando a virada e pedida, o
// andar esta num ponto qualquer do passo: entra a versao que casa, e se nenhuma esta perto o personagem
// anda mais um pouco (no maximo PHASE_WINDOW do passo) ate uma delas casar. Sem isso a mistura trocava as
// pernas no ar: o "gap" entre andar e virar.
const PHASE_WINDOW = 0.12;
const variantOf = (anim) => (anim ? sim.anims.find((a) => a.key === anim.key.replace(/(_aiming)?$/i, '_r$1')) || null : null);

function walkPhase() {
  const action = sim.current?.action;
  if (!action || !(sim.mode === 'walk' || sim.mode === 'run')) return 0;
  const duration = action.getClip().duration || 1;
  return ((action.time % duration) + duration) % duration / duration;
}

/** A versao da animacao que casa com o passo de agora, e a que distancia (fracao do passo) ela esta. */
function byPhase(anim) {
  const other = variantOf(anim);
  const p = walkPhase();
  const gap = (start) => Math.min(Math.abs(p - start), 1 - Math.abs(p - start));
  if (!other) return { anim, gap: gap(0) };
  return gap(0) <= gap(0.5) ? { anim, gap: gap(0) } : { anim: other, gap: gap(0.5) };
}

/**
 * Em que segundo do laço `anim` os pés estão como no último quadro de `from`: mesmo quociente de fase e mesmo
 * sentido (indo ou vindo). 0 quando não dá para saber, quando o laço não dá passo (parado) ou quando o casamento
 * cai no começo ou no fim do laço (que é onde os clipes bem montados terminam).
 */
function phaseStart(anim, from) {
  const a = from?.phase?.q;
  const b = anim?.phase?.q;
  if (!a || !b || a.length < 3 || b.length < 3) return 0;
  const qEnd = a[a.length - 1];
  const up = a[a.length - 1] - a[a.length - 2] > 0;
  const spread = Math.max(...b) - Math.min(...b);
  if (spread < 0.05 * sim.height) return 0;
  let best = 0;
  let bestD = Infinity;
  for (let i = 0; i < b.length - 1; i++) {
    const sameWay = (b[i + 1] - b[i] > 0) === up;
    const d = Math.abs(b[i] - qEnd) + (sameWay ? 0 : spread);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  const t = best * anim.phase.dt;
  return t < 2 * anim.phase.dt || t > anim.duration - 2 * anim.phase.dt ? 0 : t;
}

// --- Cobertura atrás do muro baixo (12/10/2026, Company of Heroes / Gears of War) ---------------------
// E junto ao muro: entra (cover_low_enter) e fica agachado (cover_low_idle). F: levanta (cover_low_aim_up), mira
// (cover_low_aim), dá três tiros (cover_low_fire) e abaixa (cover_low_aim_down). E de novo, ou uma tecla de andar:
// sai (cover_low_exit) e volta ao parado. Os clipes são achados pelo nome exato.
const COVER = { idle: 'cover_low_idle', aim: 'cover_low_aim', enter: 'cover_low_enter', exit: 'cover_low_exit', up: 'cover_low_aim_up', down: 'cover_low_aim_down', fire: 'cover_low_fire' };
const coverClip = (key) => sim.anims.find((a) => a.name === COVER[key]) || null;

function nearWall() {
  const w = sim.wall;
  if (!w) return false;
  const p = sim.position;
  const h = sim.height;
  return p.x > w.x0 && p.x < w.x1 && p.z > w.z0 - 0.9 * h && p.z < w.z0;
}

/** Toca um clipe da cobertura: em laço (idle, aim) ou uma vez, com o que vem depois na fila. */
function coverPlay(key, queue = []) {
  const anim = coverClip(key);
  if (!anim) return false;
  const loop = key === 'idle' || key === 'aim';
  play(anim, { once: !loop });
  sim.cover = { key, action: sim.current.action, done: false, queue, loop };
  return true;
}

function coverToggle() {
  if (!sim.ready) return;
  if (sim.cover) {
    if (sim.cover.key === 'exit') return;
    if (sim.cover.key === 'idle' || sim.cover.key === 'aim') coverPlay('exit', [null]);
    else sim.cover.queue = ['exit', null]; // acaba o que está fazendo e sai
    return;
  }
  if (!nearWall() || !coverClip('idle')) {
    toast(nearWall() ? 'Este projeto não tem cover_low_idle.' : 'Chegue ao muro (até um corpo de distância) e aperte E.');
    return;
  }
  const h = sim.height;
  sim.target = null;
  sim.marker.visible = false;
  sim.speed = 0;
  sim.oneShot = null;
  sim.glide = null;
  sim.mode = 'idle';
  // Durante a entrada o corpo escorrega até o lugar certo (os pés a um palmo do muro) e vira para o muro (+z),
  // em vez de pular para lá num quadro.
  const slide = { x0: sim.position.x, z0: sim.position.z, x1: sim.position.x, z1: sim.wall.z0 - 0.26 * h, f0: sim.facing, f1: -(sim.clipFor.walk?.natural.angle || 0) };
  if (coverPlay('enter', ['idle'])) sim.cover.slide = slide;
  else {
    sim.position.z = slide.z1;
    sim.facing = slide.f1;
    coverPlay('idle');
  }
}

function coverFire() {
  if (!sim.cover || sim.cover.key !== 'idle') return;
  if (!coverClip('up') || !coverClip('aim') || !coverClip('fire')) return toast('Faltam clipes da cobertura (aim_up, aim, fire).');
  coverPlay('up', ['aim:0.4', 'fire', 'fire', 'fire', 'aim:0.3', 'down', 'idle']);
}

/** Um quadro de cobertura: segue a fila quando um clipe acaba (ou quando um laço cumpriu o tempo pedido). */
function coverStep(dt) {
  const c = sim.cover;
  if (!c) return;
  const moving = keys.up || keys.down || keys.left || keys.right;
  if (moving && (c.key === 'idle' || c.key === 'aim') && coverClip('exit')) {
    coverPlay('exit', [null]);
    return;
  }
  if (c.slide && c.action) {
    // Entrando: o corpo vai até o lugar da cobertura e vira para o muro no tempo do clipe (suave, sem pulo).
    const k = clamp(c.action.time / Math.max(c.action.getClip().duration, 1e-3), 0, 1);
    const w = k * k * (3 - 2 * k);
    const s = c.slide;
    sim.position.x = s.x0 + (s.x1 - s.x0) * w;
    sim.position.z = s.z0 + (s.z1 - s.z0) * w;
    const d = Math.atan2(Math.sin(s.f1 - s.f0), Math.cos(s.f1 - s.f0));
    sim.facing = s.f0 + d * w;
  }
  if (c.loop) {
    c.held = (c.held || 0) + dt;
    if (c.wait !== undefined && c.held >= c.wait) c.done = true;
  }
  if (!c.done) return;
  const next = c.queue.shift();
  if (next === null || next === undefined) {
    sim.cover = null;
    sim.current = null;
    play(sim.clipFor.idle);
    return;
  }
  const [key, wait] = String(next).split(':');
  const rest = c.queue;
  if (!coverPlay(key, rest)) {
    sim.cover = null;
    play(sim.clipFor.idle);
    return;
  }
  if (wait !== undefined) sim.cover.wait = Number(wait);
}

function turnToward(angle, want, most) {
  const diff = Math.atan2(Math.sin(want - angle), Math.cos(want - angle));
  return Math.abs(diff) <= most ? want : angle + Math.sign(diff) * most;
}

function step(dt) {
  if (sim.oneShot?.next && !sim.oneShot.done) {
    const { action: a, anim } = sim.oneShot;
    const rest = (anim.duration - a.time) / Math.max(a.timeScale, 1e-6);
    if (rest <= 1e-6) sim.oneShot.done = true;
    else if (rest < dt) {
      // O clipe acaba no meio deste quadro: anda só até o fim dele, e o que sobra do quadro já é do laço seguinte.
      // Sem isso o último quadro do clipe saía curto (ou parado, por arredondamento) e cada troca dava um tranco.
      step(rest);
      if (sim.oneShot && !sim.oneShot.done) sim.oneShot.done = true;
      dt -= rest;
    }
  }
  const h = sim.height;
  const before = sim.position.clone();

  // Em cobertura o corpo não anda nem vira: só a fila de clipes da cobertura corre.
  if (sim.cover) {
    coverStep(dt);
    sim.speed = 0;
    sim.rate = 1;
    sim.slide = null;
    sim.character.position.copy(sim.position);
    sim.character.rotation.y = sim.facing;
    sim.mixer.update(dt);
    placeSun();
    hud();
    return;
  }

  // A meia-volta acabou: o corpo já virou dentro do clipe, então a frente do personagem pula 180°
  // no mesmo instante em que o andar entra do começo, e a pose não muda (o clipe termina igual ao
  // primeiro quadro do andar). Sem mistura aqui: misturar o fim do clipe, já virado, com o andar
  // faria o quadril dar meia volta de novo.
  if (sim.oneShot?.done && sim.oneShot.next) {
    const next = sim.oneShot.next;
    // Onde o quadril esta no ultimo quadro do clipe: e onde ele tem de continuar depois da troca.
    const hipsBefore = sim.hips ? sim.hips.getWorldPosition(new THREE.Vector3()) : null;
    if (sim.oneShot.turnTo !== undefined) sim.facing = sim.oneShot.turnTo;
    const goalSpeed = next === 'walk' ? settings.speedWalk : next === 'run' ? settings.speedRun : 0;
    // O corpo continua na velocidade com que o clipe terminou (medida no quadril dele) e desliza para a do
    // laço no tempo da mistura. Um clipe de virada montado antes de 12/10/2026 terminava a 80 ou 116 cm/s e
    // o andar segue a 62: a queda num quadro só era um tranco em toda troca.
    const ending = sim.oneShot.turnTo !== undefined ? sim.oneShot.anim.edge?.end ?? goalSpeed : goalSpeed;
    sim.speed = goalSpeed > 0 && ending > 0.3 * goalSpeed ? ending : goalSpeed; // para o parado, zero: o resto de velocidade do clipe não empurra o corpo
    sim.glide = goalSpeed > 0 && Math.abs(sim.speed - goalSpeed) > 0.005 ? { from: sim.speed, to: goalSpeed, left: settings.fade, total: settings.fade } : null;
    const ended = sim.oneShot.anim;
    sim.oneShot.action.stop();
    sim.oneShot = null;
    sim.current = null;
    sim.mode = next;
    const nextAnim = next === 'run' ? sim.clipFor.run || sim.clipFor.walk : next === 'walk' ? sim.clipFor.walk || sim.clipFor.idle : sim.clipFor.idle;
    play(nextAnim);
    // O laço entra no quadro em que os pés estão como no fim do clipe (casamento de fase, Gears of War 4). Os clipes
    // feitos no Blender para emendar terminam no quadro 1 do andar (dá 0); um clipe do Mixamo ou uma geração crua, não.
    const at = phaseStart(nextAnim, ended);
    sim.lastPhaseStart = at; // para os testes (estado().ultimaFaseDeEntrada)
    if (at > 0 && sim.current?.action) sim.current.action.time = at;
    if (hipsBefore) {
      // A frente do personagem pulou 90 ou 180 graus em torno do pivo dele (o chao entre os pes), e o quadril
      // fica uns centimetros a frente do pivo: girar o pivo tiraria o quadril do lugar. O corpo e deslocado
      // para o quadril ficar exatamente onde estava, e a troca nao da pulo.
      sim.character.rotation.y = sim.facing;
      sim.mixer.update(0);
      sim.character.updateMatrixWorld(true);
      const hipsAfter = sim.hips.getWorldPosition(new THREE.Vector3());
      sim.position.x += hipsBefore.x - hipsAfter.x;
      sim.position.z += hipsBefore.z - hipsAfter.z;
      // A câmera não acompanha este deslocamento: ele existe só para o quadril ficar onde estava (o personagem não sai
      // do lugar), e levá-la junto fazia o chão inteiro pular 5 a 7 cm num quadro, o "teleporte" que ele via na
      // troca de qualquer virada para o andar (medido em 12/10/2026: base 7,2 cm, quadril 1,2 cm).
      before.x += hipsBefore.x - hipsAfter.x;
      before.z += hipsBefore.z - hipsAfter.z;
    }
  }

  // O que o jogador quer: para que lado, andando ou correndo.
  let dir = null;
  let holdFacing = false; // esperando o passo casar com a virada: segue reto
  if (!sim.oneShot || sim.oneShot.start) { // na partida as teclas continuam valendo: a direcao pode mudar durante o clipe
    const ix = (keys.right ? 1 : 0) - (keys.left ? 1 : 0);
    const iz = (keys.up ? 1 : 0) - (keys.down ? 1 : 0);
    if (ix || iz) {
      sim.target = null;
      sim.marker.visible = false;
      // "Para frente" é para onde a câmera olha; vista de cima, é o alto da tela.
      camera.getWorldDirection(forward).setY(0);
      if (forward.lengthSq() < 0.01) forward.copy(screenUp.set(0, 1, 0).applyQuaternion(camera.quaternion)).setY(0);
      forward.normalize();
      dir = wish.set(forward.x * iz - forward.z * ix, 0, forward.z * iz + forward.x * ix).normalize();
    } else if (sim.target) {
      wish.copy(sim.target).sub(sim.position).setY(0);
      const left = wish.length();
      if (left <= Math.max(0.02 * h, sim.speed * dt)) {
        sim.position.x = sim.target.x;
        sim.position.z = sim.target.z;
        sim.target = null;
        sim.runToTarget = false;
        sim.marker.visible = false;
      } else dir = wish.divideScalar(left);
    }
  }
  // Mandou para o lado contrário? Com um clipe de meia-volta, ele vira com passos de verdade em vez
  // de girar no lugar: o do andar, se estava andando; o do parado, se estava parado. Até o clipe
  // acabar, quem leva o personagem é o deslocamento que ele tem (como as ações de tocar uma vez).
  if (dir && !sim.oneShot) {
    const walkAngle = (sim.mode === 'run' ? sim.clipFor.run : sim.clipFor.walk)?.natural.angle || 0;
    const want = Math.atan2(dir.x, dir.z) - walkAngle;
    const diff = Math.atan2(Math.sin(want - sim.facing), Math.cos(want - sim.facing));
    const moving = sim.mode === 'walk' || sim.mode === 'run';
    // Mais de 135° é meia-volta; entre 60° e 135°, a virada de 90° do lado certo (diff > 0 é a esquerda dele).
    // Menos que isso ele gira no lugar, como sempre. O que sobrar depois do clipe o giro normal completa.
    // A virada do ângulo mais próximo entre as que existem (45, 90, 135 e 180; correndo só 90 e 180). Abaixo de
    // 22,5° (ou de 60°, quando não há clipe de 45°) ele gira sem clipe. O que sobrar depois do clipe o giro normal completa.
    const runningNow = sim.mode === 'run';
    const left = diff > 0;
    const c = sim.clipFor;
    const bank = runningNow
      ? [[90, left ? c.turnLeftRun || c.turnLeft : c.turnRightRun || c.turnRight], [180, c.turnAroundRun || c.turnWalk]]
      : moving
        ? [[45, left ? c.turnLeft45 : c.turnRight45], [90, left ? c.turnLeft : c.turnRight], [135, left ? c.turnLeft135 : c.turnRight135], [180, c.turnWalk]]
        : [[45, left ? c.turnLeft45Idle : c.turnRight45Idle], [90, left ? c.turnLeftIdle : c.turnRightIdle], [135, left ? c.turnLeft135Idle : c.turnRight135Idle], [180, c.turnIdle]];
    const have = bank.filter(([, anim]) => anim);
    const degrees = Math.abs(THREE.MathUtils.radToDeg(diff));
    const floor = have.some(([angle]) => angle === 45) ? 22.4 : 59.9;
    let turn = null;
    let by = 0;
    if (have.length && degrees >= floor) {
      const [angle, anim] = have.reduce((best, cur) => (Math.abs(cur[0] - degrees) < Math.abs(best[0] - degrees) ? cur : best));
      // Só serve o clipe de ângulo parecido (até 45° de diferença): com só o de 90°, uma meia-volta virava dois clipes em fila.
      if (Math.abs(angle - degrees) <= 45.01) {
        turn = anim;
        by = Math.sign(diff) * THREE.MathUtils.degToRad(angle);
      }
    }
    // Virada grande sem clipe que sirva (um pacote só de laços, como o do Mixamo): ele vira de uma vez, no giro cheio,
    // e anda para onde o corpo aponta. Levar o corpo já na direção nova, com o giro limitado do andar, fazia-o andar
    // de costas enquanto virava (13/10/2026: "ele tá andando o contrário"; 22 quadros de costas numa meia-volta).
    if (!turn && degrees >= floor) sim.steer = true;
    // Uma virada de corrida termina no run_forward; as outras, no walk_forward.
    const after = turn && runningNow && RUN.test(turn.key) ? 'run' : 'walk';
    if (turn && moving) {
      const pick = byPhase(turn);
      if (pick.gap > PHASE_WINDOW) {
        holdFacing = true; // ainda nao: segue reto mais um pouco, sem girar, ate o passo casar
        turn = null;
      } else turn = pick.anim;
    }
    if (turn) {
      // Pedida andando, a virada entra em mistura de `fade` segundos: nesse tempo o andar que está saindo continua
      // a empurrar o corpo na parte dele (a animação de andar é no lugar; quem a move é esta velocidade), para o
      // lado em que ele vinha, e o clipe empurra na parte dele. Zerar a velocidade de uma vez parava o corpo com
      // as pernas ainda andando; empurrar para o lado novo (o contrário) fazia a velocidade cruzar o zero.
      const ease = moving && sim.speed > 0 && settings.fade > 0 ? { from: sim.speed, left: settings.fade, w: 0, dir: sim.moveDir.clone() } : null;
      sim.moveDir.copy(dir);
      if (!ease) sim.speed = 0;
      play(turn, { once: true });
      // A virada que termina na pose do parado devolve ao parado; com a tecla ainda apertada, o andar entra dele com a mistura de sempre.
      sim.oneShot = { anim: turn, action: sim.current.action, done: false, next: endsStanding(turn) ? 'idle' : after, turnTo: Math.atan2(Math.sin(sim.facing + by), Math.cos(sim.facing + by)), ease };
      dir = null;
    } else if (sim.mode === 'idle' && sim.clipFor.start && !(keys.shift && sim.clipFor.run)) {
      // Parado e mandou andar para a frente: a partida, com o corpo ganhando velocidade enquanto ela toca.
      sim.moveDir.copy(dir);
      play(sim.clipFor.start, { once: true });
      sim.oneShot = { anim: sim.clipFor.start, action: sim.current.action, done: false, next: 'walk', start: true };
      dir = null;
    }
  }
  // Andava e soltou a tecla: a parada, com o corpo freando enquanto ela toca; o parado entra do fim dela.
  // Tambem em duas versoes, pelo pe que esta na frente; se nenhuma casa, anda mais um pouco.
  let stopWait = false;
  // Correndo, a parada e outra (run_to_idle: passos de frenagem); sem ela, vale a do andar.
  const stopClip = sim.mode === 'run' ? sim.clipFor.stopRun || sim.clipFor.stop : sim.clipFor.stop;
  if (!dir && !sim.oneShot && (sim.mode === 'walk' || sim.mode === 'run') && stopClip) {
    const pick = byPhase(stopClip);
    if (pick.gap <= PHASE_WINDOW) {
      // Parada feita no lugar (walk_to_idle): a velocidade do corpo cai da que ele tinha a zero ao longo do clipe.
      // Parada com deslocamento proprio (run_to_idle, passos de frenagem): entra como uma virada, o laco que sai
      // empurra na parte dele durante a mistura e dali em diante quem leva o corpo e o caminho do quadril do clipe.
      const ease = pick.anim.root && sim.speed > 0 && settings.fade > 0 ? { from: sim.speed, left: settings.fade, w: 0, dir: sim.moveDir.clone() } : null;
      play(pick.anim, { once: true });
      sim.oneShot = { anim: pick.anim, action: sim.current.action, done: false, next: 'idle', stop: true, from: sim.speed, ease };
      if (pick.anim.root && !ease) sim.speed = 0;
    } else stopWait = true;
  }
  const running = !!dir && (keys.shift || (!!sim.target && sim.runToTarget)) && !!sim.clipFor.run;
  // Esperando o passo casar para parar, ele segue no que estava (correndo continua correndo): cair para o andar
  // nesse instante trocava a parada da corrida pela do andar.
  const mode = sim.oneShot ? 'action' : dir || stopWait ? (running || (stopWait && sim.mode === 'run') ? 'run' : 'walk') : 'idle';
  const goal = mode === 'run' ? settings.speedRun : mode === 'walk' || sim.oneShot?.start ? settings.speedWalk : 0;

  // A velocidade chega ao que foi pedido no mesmo tempo em que a animação troca.
  const most = (Math.max(settings.speedWalk, settings.speedRun, 0.2 * h) / Math.max(settings.fade, 0.05)) * dt;
  sim.speed += clamp(goal - sim.speed, -most, most);
  if (sim.oneShot) sim.glide = null; // a rampa de uma troca anterior nao sobrevive a um clipe novo: disparava no fim da mistura de entrada (tranco de 80 cm/s)
  if ((sim.oneShot?.start || sim.oneShot?.stop) && !sim.oneShot.anim.root) { // so para partida/parada feitas no lugar; com caminho proprio, vale o root motion
    // Na partida e na parada a velocidade segue o clipe: ele foi feito como mistura suave (smoothstep) entre
    // o parado e o andar, e e nessa curva que o pe apoiado desliza; o corpo acompanha para o pe ficar firme.
    const k = clamp(sim.oneShot.action.time / Math.max(sim.oneShot.anim.duration, 1e-3), 0, 1);
    const w = k * k * (3 - 2 * k);
    // Na partida sobe ate o andar; na parada desce da velocidade que ele tinha (andar ou corrida) ate zero.
    sim.speed = sim.oneShot.start ? settings.speedWalk * w : (sim.oneShot.from ?? settings.speedWalk) * (1 - w);
  } else if (sim.oneShot?.ease) {
    // Virada pedida andando: a velocidade do andar que sai cai com o peso dele na mistura (linear, como o fadeOut).
    const e = sim.oneShot.ease;
    e.left -= dt;
    e.w = clamp(1 - e.left / Math.max(settings.fade, 1e-3), 0, 1);
    sim.speed = e.from * (1 - e.w);
    if (e.left <= 0) sim.oneShot.ease = null;
  } else if (sim.glide) {
    // Saída de uma virada: da velocidade em que o clipe terminou para a do laço, suave, no tempo da mistura.
    const g = sim.glide;
    g.left -= dt;
    g.to = goal;
    const k = clamp(1 - g.left / Math.max(g.total, 1e-3), 0, 1);
    sim.speed = g.from + (g.to - g.from) * (k * k * (3 - 2 * k));
    if (g.left <= 0 || mode === 'idle' || sim.oneShot) sim.glide = null;
  }
  if (!dir || sim.oneShot) sim.steer = false;
  let advance = 1;
  if (sim.steer) {
    // Virando de uma vez: o corpo anda para onde aponta, e só o quanto já aponta para o lado pedido (de costas para
    // ele, gira no lugar). Quando alinha, volta a valer a direção pedida, que então é a mesma.
    const angle = (mode === 'run' ? sim.clipFor.run : sim.clipFor.walk)?.natural.angle || 0;
    advance = Math.max(0, Math.cos(Math.atan2(dir.x, dir.z) - angle - sim.facing));
    sim.moveDir.set(Math.sin(sim.facing + angle), 0, Math.cos(sim.facing + angle));
  } else if (dir && !holdFacing) sim.moveDir.copy(dir); // esperando o passo casar com a virada ele segue reto, para onde ia: levar o corpo já para o lado novo era andar de costas até o clipe entrar
  sim.position.addScaledVector(sim.oneShot?.ease?.dir || sim.moveDir, sim.speed * advance * dt);

  // A animação do momento.
  if (sim.oneShot) {
    // O deslocamento que a ação tem (um bote para frente, por exemplo) leva o personagem junto.
    const { anim, action, done } = sim.oneShot;
    if (!done && anim.duration > 0) {
      // Pelo caminho do quadril, no trecho de tempo que este quadro avança (root motion); sem caminho medido, pela média.
      let push;
      if (anim.root) {
        const [ax, az] = rootAt(anim.root, action.time);
        const [bx, bz] = rootAt(anim.root, Math.min(action.time + dt * action.timeScale, anim.duration));
        push = new THREE.Vector3(bx - ax, 0, bz - az).applyAxisAngle(THREE.Object3D.DEFAULT_UP, sim.facing);
      } else push = anim.travel.clone().applyAxisAngle(THREE.Object3D.DEFAULT_UP, sim.facing).multiplyScalar((dt * action.timeScale) / anim.duration);
      if (sim.oneShot.ease) push.multiplyScalar(sim.oneShot.ease.w); // na mistura de entrada, so a parte do clipe
      sim.position.add(push);
    }
    if (sim.oneShot.start) {
      // Na partida o corpo ja vai virando para onde foi mandado (uma diagonal, por exemplo): sem isso ele
      // saia andando de lado durante o clipe e so virava depois.
      const walkAngle = sim.clipFor.walk?.natural.angle || 0;
      sim.facing = turnToward(sim.facing, Math.atan2(sim.moveDir.x, sim.moveDir.z) - walkAngle, THREE.MathUtils.degToRad(Math.min(settings.turn, WALKING_TURN)) * dt);
    }
    if (done) {
      sim.oneShot = null;
      play(sim.clipFor.idle);
    }
    sim.rate = 1;
    sim.slide = null;
  } else {
    const anim = mode === 'run' ? sim.clipFor.run : mode === 'walk' ? sim.clipFor.walk || sim.clipFor.idle : sim.clipFor.idle;
    const wasMoving = sim.mode === 'walk' || sim.mode === 'run';
    play(anim, { sync: wasMoving && mode !== 'idle' });
    const natural = mode === 'idle' ? 0 : anim?.natural.speed || 0;
    sim.rate = mode !== 'idle' && settings.fit && natural > 0 ? clamp(goal / natural, 0.25, 4) : 1;
    if (sim.current?.action) sim.current.action.timeScale = sim.rate;
    sim.slide = mode === 'idle' ? null : natural > 0 ? Math.abs(goal - natural * sim.rate) : NaN;
    if (dir) {
      const angle = (mode === 'run' ? sim.clipFor.run : sim.clipFor.walk)?.natural.angle || 0;
      // Andando, o giro sem clipe (menos de 60°, as diagonais) e uma curva, nao um estalo: no maximo WALKING_TURN.
      const rate = mode === 'idle' || sim.steer ? settings.turn : Math.min(settings.turn, WALKING_TURN);
      const goalFacing = Math.atan2(dir.x, dir.z) - angle;
      if (!holdFacing) sim.facing = turnToward(sim.facing, goalFacing, THREE.MathUtils.degToRad(rate) * dt);
      if (sim.steer && Math.abs(Math.atan2(Math.sin(goalFacing - sim.facing), Math.cos(goalFacing - sim.facing))) < 1e-3) sim.steer = false;
    }
  }
  sim.mode = mode;

  // O muro baixo não se atravessa: o personagem (raio de 0,15 corpo) é empurrado para fora do lado por onde entrou.
  if (sim.wall) {
    const w = sim.wall;
    const r = 0.15 * h;
    const p = sim.position;
    if (p.x > w.x0 - r && p.x < w.x1 + r && p.z > w.z0 - r && p.z < w.z1 + r) {
      const pushes = [p.x - (w.x0 - r), (w.x1 + r) - p.x, p.z - (w.z0 - r), (w.z1 + r) - p.z];
      const k = pushes.indexOf(Math.min(...pushes));
      if (k === 0) p.x = w.x0 - r; else if (k === 1) p.x = w.x1 + r; else if (k === 2) p.z = w.z0 - r; else p.z = w.z1 + r;
    }
  }

  sim.character.position.copy(sim.position);
  sim.character.rotation.y = sim.facing;
  sim.mixer.update(dt);

  // A câmera e a luz acompanham.
  const dx = sim.position.x - before.x;
  const dz = sim.position.z - before.z;
  camera.position.x += dx;
  camera.position.z += dz;
  controls.target.x += dx;
  controls.target.z += dz;
  placeSun();
  hud();
}

function hud() {
  const label = sim.cover ? `Cobertura: ${sim.current?.anim.name || ''} (E sai, F atira)` : sim.oneShot ? (sim.oneShot.turnTo !== undefined ? `Virando: ${sim.oneShot.anim.name}` : sim.oneShot.start ? `Partindo: ${sim.oneShot.anim.name}` : sim.oneShot.stop ? `Parando: ${sim.oneShot.anim.name}` : `Tocando: ${sim.oneShot.anim.name}`) : STATES[sim.mode]?.label || '';
  $('#hud-state').textContent = `${label} · ${settings.set === 'alerta' ? 'alerta' : 'patrulha'}`;
  $('#hud-speed').textContent = `${num(sim.speed)} m/s${sim.rate !== 1 ? ` · animação a ${num(sim.rate)}×` : ''}`;
  const slide = $('#hud-slide');
  if (sim.slide === null) {
    slide.textContent = '';
  } else if (Number.isNaN(sim.slide)) {
    slide.textContent = 'sem passo medido nesta animação';
    slide.className = 'muted';
  } else {
    const firm = sim.slide < Math.max(0.03 * sim.height, 0.05 * sim.speed);
    slide.textContent = firm ? 'pé firme no chão' : `pé desliza uns ${num(sim.slide * 100, 0)} cm por segundo`;
    slide.className = firm ? 'ok' : 'warn';
  }
}

const clock = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const dt = Math.min(clock.getDelta(), 0.1);
  if (sim.ready) step(dt);
  controls.update();
  renderer.render(scene, camera);
});

// --- O painel -----------------------------------------------------------------------------------

function describe(anim) {
  if (!anim) return '';
  const { speed, angle, how } = anim.natural;
  if (!speed) return how === 'nada' ? 'sem passo: esta animação não sai do lugar' : '';
  const degrees = Math.round(THREE.MathUtils.radToDeg(angle));
  const side = !degrees ? '' : Math.abs(degrees) > 135 ? ', de costas' : `, de lado (${Math.abs(degrees)}° para a ${degrees > 0 ? 'esquerda' : 'direita'} dele)`;
  return `passo da animação: ${num(speed)} m/s${side}${how === 'pés' ? ' (medido pelos pés)' : ''}`;
}

function fallbackSpeed(state) {
  return sim.clipFor[state]?.natural.speed || sim.height * (state === 'run' ? 1.65 : 0.78);
}

function buildPanel(asset) {
  const s = asset.summary || {};
  $('#project-facts').textContent = [s.rig ? `rig ${s.rig}` : null, `${sim.anims.length} ${sim.anims.length === 1 ? 'animação' : 'animações'}`].filter(Boolean).join(' · ');
  $('#height').textContent = `${num(sim.height)} m`;

  for (const state of Object.keys(STATES)) {
    const select = $(`#clip-${state}`);
    if (!select) continue; // momento sem seletor no painel: segue valendo pelo nome
    select.replaceChildren(new Option('(nenhuma)', ''), ...[...sim.anims].sort(byName).map((a) => new Option(a.name, a.id))); // em ordem pelo nome (13/10/2026)
    select.value = sim.clipFor[state]?.id || '';
    select.addEventListener('change', () => {
      sim.clipFor[state] = sim.anims.find((a) => a.id === select.value) || null;
      settings[state] = sim.clipFor[state]?.id || null;
      if ((state === 'walk' || state === 'run') && sim.clipFor[state]?.natural.speed) setSpeed(state, sim.clipFor[state].natural.speed);
      save();
      refreshPanel();
      select.blur();
    });
  }
  if (!(settings.speedWalk > 0)) settings.speedWalk = fallbackSpeed('walk');
  if (!(settings.speedRun > 0)) settings.speedRun = fallbackSpeed('run');

  const bind = (id, key, low, high) => {
    const input = $(id);
    input.value = Number(settings[key].toFixed(2));
    input.addEventListener('change', () => {
      const value = Number(String(input.value).replace(',', '.'));
      if (Number.isFinite(value)) settings[key] = clamp(value, low, high);
      input.value = Number(settings[key].toFixed(2));
      save();
      input.blur();
    });
  };
  bind('#speed-walk', 'speedWalk', 0, 100);
  bind('#speed-run', 'speedRun', 0, 100);
  bind('#fade', 'fade', 0, 2);
  bind('#turn', 'turn', 30, 3600);
  $('#set').value = settings.set;
  $('#set').addEventListener('change', (e) => {
    chooseSet(e.target.value);
    e.target.blur();
  });
  $('#fit').checked = settings.fit;
  $('#fit').addEventListener('change', (e) => {
    settings.fit = e.target.checked;
    save();
    e.target.blur();
  });
  $('#natural').addEventListener('click', () => {
    setSpeed('walk', fallbackSpeed('walk'));
    setSpeed('run', fallbackSpeed('run'));
    save();
  });
  $('#cam-near').addEventListener('click', () => setCamera('near'));
  $('#cam-top').addEventListener('click', () => setCamera('top'));
  $('#reset').addEventListener('click', reset);
  $('#reload').addEventListener('click', () => location.reload());
  $('#bones').addEventListener('change', (e) => {
    sim.helper.visible = e.target.checked;
    e.target.blur();
  });
  for (const button of document.querySelectorAll('.sim-side button')) button.addEventListener('click', () => renderer.domElement.focus());
  refreshPanel();
}

// O conjunto: "patrulha" sao os nomes do jogo (idle, walk_forward...); "alerta" sao os mesmos com _aiming
// (fuzil no ombro). Escolher um troca todos os momentos de uma vez; o que nao tiver versao fica como esta.
const AIMING = /_aiming$/i;
function chooseSet(name) {
  settings.set = name;
  for (const state of Object.keys(STATES)) {
    const prefer = STATES[state].prefer;
    if (!prefer) continue;
    const found = name === 'alerta'
      ? sim.anims.find((a) => AIMING.test(a.key) && prefer.test(a.key.replace(AIMING, '')))
      : sim.anims.find((a) => !AIMING.test(a.key) && prefer.test(a.key));
    if (found) {
      sim.clipFor[state] = found;
      settings[state] = found.id;
      const select = $(`#clip-${state}`);
      if (select) select.value = found.id;
    }
  }
  // A velocidade do corpo acompanha o passo do andar do conjunto (o do alerta e mais rapido).
  if (sim.clipFor.walk?.natural.speed) setSpeed('walk', sim.clipFor.walk.natural.speed);
  if (sim.clipFor.run?.natural.speed) setSpeed('run', sim.clipFor.run.natural.speed);
  save();
  if (sim.ready) refreshPanel();
}

function setSpeed(state, value) {
  const key = state === 'run' ? 'speedRun' : 'speedWalk';
  settings[key] = value;
  $(state === 'run' ? '#speed-run' : '#speed-walk').value = Number(value.toFixed(2));
}

function refreshPanel() {
  $('#note-walk').textContent = describe(sim.clipFor.walk);
  $('#note-run').textContent = sim.clipFor.run ? describe(sim.clipFor.run) : 'sem animação de correr, o Shift não faz nada';
  // O que não está em nenhum momento fica para tocar uma vez, pelas teclas de número.
  const used = new Set(Object.values(sim.clipFor).filter(Boolean));
  sim.extras = sim.anims.filter((a) => !used.has(a) && !/_r(_aiming)?$/i.test(a.key)).sort(byName); // as versoes "_r" entram pelo passo, nao pela tecla
  $('#actions-box').hidden = !sim.extras.length;
  $('#actions').replaceChildren(
    ...sim.extras.map((anim, index) => {
      const button = Object.assign(document.createElement('button'), { className: 'btn small', type: 'button' });
      const key = document.createElement('kbd');
      key.textContent = index < 9 ? String(index + 1) : '·';
      button.append(key, `${anim.name} (${num(anim.duration, 1)} s)`);
      button.addEventListener('click', () => {
        playOnce(anim);
        renderer.domElement.focus();
      });
      return button;
    }),
  );
}

// Animação que chega ou muda no projeto com o simulador aberto: avisa, e recarregar a traz.
async function watchProject() {
  try {
    const data = await (await fetch('/api/state')).json();
    const now = JSON.stringify(
      data.results
        .filter((r) => r.asset_id === projectId && r.files?.glb)
        .map((r) => [r.id, r.created_at])
        .sort((a, b) => a[1].localeCompare(b[1])),
    );
    if (now === sim.signature || sim.told === now) return;
    sim.told = now;
    $('#news').hidden = false;
    $('#news').textContent = 'As animações do projeto mudaram: clique em "Recarregar as animações" para trazer o que há de novo.';
    toast('As animações do projeto mudaram. Recarregue para ver.');
  } catch { /* servidor fora do ar: tenta de novo depois */ }
}

// Para os testes e para quem quiser conferir por número (console do navegador).
window.simulador = {
  /** Anda o jogo este tempo, em quadros de 1/60 s, sem depender do relógio (o navegador sem janela desenha devagar). */
  avancar: (seconds, trace = false) => {
    // Com trace, devolve tambem `rastro`: a velocidade do quadril no chao (cm/s) e o clipe, quadro a quadro.
    const rastro = [];
    // Mede tambem o maior pulo do quadril entre dois quadros (cm): uma troca de animacao sem emenda aparece aqui.
    // E o maior tranco: quanto a velocidade do quadril no chao muda de um quadro para o outro (cm/s). Numa troca
    // bem emendada fica perto do que o proprio andar tem; um clipe que sai a 80 cm/s e cai a 62 aparece aqui.
    // E quanto o pe apoiado (o mais baixo dos dois) escorrega no chao, em cm/s: medio e maior no trecho.
    let worst = 0;
    let jolt = 0;
    let last = sim.hips ? sim.hips.getWorldPosition(new THREE.Vector3()) : null;
    let lastV = null;
    let lastFeet = null;
    let lastBase = null; // a base do personagem (sim.position): e ela que a camera segue; um pulo aqui e o mundo pulando
    let worstBase = 0;
    const slides = [];
    const feetNow = () => (sim.feet.l && sim.feet.r ? { l: sim.feet.l.getWorldPosition(new THREE.Vector3()), r: sim.feet.r.getWorldPosition(new THREE.Vector3()) } : null);
    for (let t = 0; sim.ready && t < seconds; t += 1 / 60) {
      step(1 / 60);
      if (!sim.hips) continue;
      sim.character.updateMatrixWorld(true);
      const now = sim.hips.getWorldPosition(new THREE.Vector3());
      if (last) {
        worst = Math.max(worst, now.distanceTo(last));
        const v = now.clone().sub(last).setY(0).multiplyScalar(60);
        if (lastV) jolt = Math.max(jolt, v.distanceTo(lastV));
        if (trace) rastro.push({ t: Math.round(t * 1000) / 1000, clipe: sim.current?.anim.name || null, v: Math.round(v.length() * 100), tranco: lastV ? Math.round(v.distanceTo(lastV) * 100) : 0, peso: sim.oneShot?.ease?.w ?? null, vel: Math.round(sim.speed * 100), camera: lastBase ? Math.round(Math.hypot(camera.position.x - lastBase.x, camera.position.z - lastBase.z) * 1000) / 10 : 0 });
        lastV = v;
      }
      last = now;
      // Mede a camera, nao a base: na troca de clipe a base e deslocada de proposito (o quadril fica no lugar) e a
      // camera e que nao pode pular.
      if (lastBase) worstBase = Math.max(worstBase, Math.hypot(camera.position.x - lastBase.x, camera.position.z - lastBase.z));
      lastBase = camera.position.clone();
      const feet = feetNow();
      if (feet && lastFeet) {
        const low = feet.l.y <= feet.r.y ? 'l' : 'r';
        const lowBefore = lastFeet.l.y <= lastFeet.r.y ? 'l' : 'r';
        if (low === lowBefore) {
          const s = feet[low].clone().sub(lastFeet[low]).setY(0).length() * 60;
          slides.push(s);
          if (trace && rastro.length) rastro[rastro.length - 1].pe = Math.round(s * 100); // cm/s do pé apoiado neste quadro
        }
      }
      lastFeet = feet;
    }
    const slide = slides.length ? { medio: Math.round((slides.reduce((a, b) => a + b, 0) / slides.length) * 100), maior: Math.round(Math.max(...slides) * 100) } : null;
    return { ...window.simulador.estado(), maiorPuloDoQuadrilCm: Math.round(worst * 1000) / 10, maiorPuloDaCameraCm: Math.round(worstBase * 1000) / 10, maiorTrancoDoQuadrilCmS: Math.round(jolt * 100), deslizeDoPeApoiadoCmS: slide, ...(trace ? { rastro } : {}) };
  },
  estado: () => ({
    pronto: sim.ready,
    modo: sim.mode,
    tocando: sim.current?.anim.name || null,
    meiaVolta: sim.oneShot?.turnTo !== undefined,
    partindo: !!sim.oneShot?.start,
    parando: !!sim.oneShot?.stop,
    velocidade: sim.speed,
    posicao: [sim.position.x, sim.position.z],
    virado: THREE.MathUtils.radToDeg(sim.facing),
    ritmo: sim.rate,
    deslize: sim.slide,
    animacoes: sim.anims.map((a) => ({ nome: a.name, passo: a.natural.speed, angulo: THREE.MathUtils.radToDeg(a.natural.angle), medido: a.natural.how, segundos: a.duration })),
    conjunto: settings.set,
    correndoParaOAlvo: !!(sim.target && sim.runToTarget),
    virandoSemClipe: !!sim.steer,
    cobertura: sim.cover ? { clipe: sim.cover.key, fila: sim.cover.queue.length } : null,
    pertoDoMuro: nearWall(),
    ultimaFaseDeEntrada: sim.lastPhaseStart ?? null,
    momentos: Object.fromEntries(Object.entries(sim.clipFor).map(([k, a]) => [k, a?.name || null])),
  }),
};

start().catch((err) => fail(`O simulador não abriu: ${err.message}`));
