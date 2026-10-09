// Confere que um acessório aparece no mesmo lugar no visualizador (three.js) e nos arquivos
// gravados pelo Blender. No GLB do resultado, o nó PROP_<id> que o Blender prendeu ao osso
// tem que coincidir com osso × matriz, que é como o visualizador o desenha.
//
//   node tests/check_props.mjs <resultado.glb> <props.json>
//
// props.json: [{ "id", "bone" (nome no Blender), "matrix": [16 números por colunas] }]

import { readFileSync } from 'node:fs';
import * as THREE from '../web/node_modules/three/build/three.module.js';
import { GLTFLoader } from '../web/node_modules/three/examples/jsm/loaders/GLTFLoader.js';

const [pathGlb, pathProps] = process.argv.slice(2);
const props = JSON.parse(readFileSync(pathProps, 'utf8'));
const data = readFileSync(pathGlb);
const gltf = await new Promise((resolve, reject) =>
  new GLTFLoader().parse(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength), '', resolve, reject),
);
const sanitize = (name) => THREE.PropertyBinding.sanitizeNodeName(name);
const height = new THREE.Box3().setFromObject(gltf.scene).getSize(new THREE.Vector3()).y;
const mixer = new THREE.AnimationMixer(gltf.scene);
mixer.clipAction(gltf.animations[0]).play();

let worstPos = 0;
let worstAxis = 0;
for (const time of [0, 0.7, 2.1, 4.0]) {
  mixer.setTime(time);
  gltf.scene.updateMatrixWorld(true);
  for (const prop of props) {
    const baked = gltf.scene.getObjectByName(sanitize(`PROP_${prop.id}`));
    const bone = gltf.scene.getObjectByName(sanitize(prop.bone));
    if (!baked || !bone) {
      console.log(`FALHA nó ${baked ? prop.bone : `PROP_${prop.id}`} não encontrado no GLB`);
      process.exit(1);
    }
    const expected = bone.matrixWorld.clone().multiply(new THREE.Matrix4().fromArray(prop.matrix));
    const a = baked.matrixWorld.elements;
    const b = expected.elements;
    worstPos = Math.max(worstPos, Math.hypot(a[12] - b[12], a[13] - b[13], a[14] - b[14]));
    // Eixos (com a escala): diferença relativa ao tamanho do eixo esperado.
    for (const col of [0, 4, 8]) {
      const diff = Math.hypot(a[col] - b[col], a[col + 1] - b[col + 1], a[col + 2] - b[col + 2]);
      worstAxis = Math.max(worstAxis, diff / Math.hypot(b[col], b[col + 1], b[col + 2]));
    }
  }
}
console.log(`posição: ${((100 * worstPos) / height).toFixed(4)} % da altura | orientação e escala: ${(100 * worstAxis).toFixed(4)} %`);
const ok = worstPos < 0.002 * height && worstAxis < 0.002;
console.log(ok ? 'ok    acessório no mesmo lugar no visualizador e no Blender' : 'FALHA acessório em lugares diferentes');
process.exit(ok ? 0 : 1);
