// Confere que um ajuste de pose aplicado no visualizador (three.js) dá a mesma pose que o
// Blender grava nos arquivos. Compara dois GLBs do mesmo retarget: A sem ajuste, com o
// ajuste aplicado aqui em cima; B com o ajuste já gravado pelo Blender.
//
//   node tests/check_adjust.mjs <A.glb> <B.glb> <ajuste.json>
//
// ajuste.json: { "<osso do Blender>": [w, x, y, z], ... }

import { readFileSync } from 'node:fs';
import * as THREE from '../web/node_modules/three/build/three.module.js';
import { GLTFLoader } from '../web/node_modules/three/examples/jsm/loaders/GLTFLoader.js';

const [pathA, pathB, pathAdjust] = process.argv.slice(2);
const adjust = JSON.parse(readFileSync(pathAdjust, 'utf8'));

// O GLTFLoader tira dos nomes os caracteres que não podem aparecer num caminho de animação.
export const sanitize = (name) => THREE.PropertyBinding.sanitizeNodeName(name);

function load(path) {
  const data = readFileSync(path);
  const buffer = data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
  return new Promise((resolve, reject) => new GLTFLoader().parse(buffer, '', resolve, reject));
}

function bonesAt(gltf, time, offsets) {
  const mixer = new THREE.AnimationMixer(gltf.scene);
  mixer.clipAction(gltf.animations[0]).play();
  mixer.setTime(time);
  const bones = new Map();
  gltf.scene.traverse((obj) => obj.isBone && bones.set(obj.name, obj));
  for (const [name, quat] of offsets) bones.get(name).quaternion.multiply(quat);
  gltf.scene.updateMatrixWorld(true);
  return new Map([...bones].map(([name, bone]) => [name, bone.getWorldPosition(new THREE.Vector3())]));
}

const a = await load(pathA);
const b = await load(pathB);
const height = new THREE.Box3().setFromObject(a.scene).getSize(new THREE.Vector3()).y;

// Hipótese: o espaço local de uma junta no glTF é o mesmo do osso no Blender, então o
// quaternion é o mesmo, só muda a ordem dos componentes (Blender w,x,y,z; three x,y,z,w).
const offsets = Object.entries(adjust).map(([bone, [w, x, y, z]]) => [sanitize(bone), new THREE.Quaternion(x, y, z, w)]);

let worst = 0;
let unadjusted = 0;
for (const time of [0.2, 1.0, 2.5]) {
  const plain = bonesAt(await load(pathA), time, []);
  const mine = bonesAt(await load(pathA), time, offsets);
  const baked = bonesAt(b, time, []);
  for (const [name, pos] of baked) {
    worst = Math.max(worst, pos.distanceTo(mine.get(name)));
    unadjusted = Math.max(unadjusted, pos.distanceTo(plain.get(name)));
  }
}
const pct = (v) => `${((100 * v) / height).toFixed(3)} % da altura`;
console.log(`efeito do ajuste (B contra A sem ajuste): ${pct(unadjusted)}`);
console.log(`diferença com o ajuste aplicado no three.js: ${pct(worst)}`);
const ok = worst < 0.002 * height && unadjusted > 0.02 * height;
console.log(ok ? 'ok    visualizador e Blender concordam' : 'FALHA visualizador e Blender NÃO concordam');
process.exit(ok ? 0 : 1);
