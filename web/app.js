// Interface da PonteAnimada: os projetos e, dentro de cada um, o visor 3D, as animações e o terminal.
// O Blender roda por trás, comandado pela IA chamada no terminal; aqui só se vê o resultado.
// A tela anterior (laudo, rig, roteiros, revisão) continua em /antiga/.

import { Viewer } from './viewer.js';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';

const $ = (sel) => document.querySelector(sel);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key === 'class') el.className = value;
    else if (key in el && key !== 'list') el[key] = value;
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

const state = {
  data: { assets: [], motions: [], results: [], jobs: [], meshy: {}, engines: null },
  project: null, // id do projeto aberto (o do personagem); nulo na tela de projetos
  anim: null, // id da animação escolhida; nulo mostra o modelo parado
  known: null, // animações já vistas: as que chegarem depois são abertas sozinhas
  keys: {},
  myJobs: new Set(),
  jobStatus: new Map(),
  loaded: null,
  scrubbing: false,
  online: true,
};

const viewer = new Viewer($('#viewport'));
const ACTIVE = ['fila', 'rodando'];

// --- API --------------------------------------------------------------------------------

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch { /* corpo não era JSON */ }
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join('; ');
    throw new Error(detail);
  }
  return (res.headers.get('content-type') || '').includes('json') ? res.json() : res.text();
}

const send = (method, path, body) =>
  api(path, { method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body ?? {}) });

const asset = (id) => state.data.assets.find((a) => a.id === id);
const currentProject = () => asset(state.project);
const animsOf = (id) => state.data.results.filter((r) => r.asset_id === id);
const motionOf = (result) => state.data.motions.find((m) => m.id === result.motion_id);
const animName = (result) => motionOf(result)?.name || result.prompt || result.id;
const jobsOf = (id) => state.data.jobs.filter((j) => ACTIVE.includes(j.status) && j.params?.asset_id === id);

// --- Utilidades ---------------------------------------------------------------------------

const num = (value, digits = 0) =>
  value == null ? '—' : Number(value).toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const chip = (tone, text) => h('span', { class: `chip ${tone}` }, text);
// Troca o conteúdo de um elemento. O que for nulo ou falso fica de fora (replaceChildren escreveria "null").
const fill = (el, ...children) => el.replaceChildren(...children.flat().filter((child) => child != null && child !== false));

function toast(message, tone = 'info', onClick) {
  const el = h('div', { class: `toast ${tone}`, role: 'status' }, message);
  if (onClick) {
    el.style.cursor = 'pointer';
    el.addEventListener('click', () => { onClick(); el.remove(); });
  }
  $('#toasts').append(el);
  setTimeout(() => el.remove(), tone === 'erro' ? 12000 : 6000);
}

async function guard(action) {
  try {
    return await action();
  } catch (err) {
    toast(err.message, 'erro');
    return null;
  }
}

// Redesenha só quando o que a parte mostra mudou: a tela é refeita a cada 2 s.
function changed(name, value) {
  const key = JSON.stringify(value);
  if (state.keys[name] === key) return false;
  state.keys[name] = key;
  return true;
}

// --- Atualização periódica ------------------------------------------------------------------

async function refresh() {
  let data;
  try {
    data = await api('/api/state');
  } catch {
    state.online = false;
    renderStatus();
    return;
  }
  const back = !state.online; // o servidor voltou (foi reiniciado): o terminal aberto caiu junto
  state.online = true;
  state.data = data;
  if (back && state.project && currentProject() && !term.ws) openTerminal(state.project);
  watchJobs();
  watchNewAnimations();
  if (state.project && !currentProject()) goHome(); // o projeto aberto foi apagado
  showScreen();
  renderStatus();
  if (state.project) {
    renderCrumb();
    renderAnimations();
  } else {
    renderHome();
    renderMeshy();
    renderActivity();
  }
  syncViewer();
}

function watchJobs() {
  for (const job of state.data.jobs) {
    const before = state.jobStatus.get(job.id);
    state.jobStatus.set(job.id, job.status);
    if (!state.myJobs.has(job.id) || before === job.status) continue;
    if (job.status === 'ok') {
      state.myJobs.delete(job.id);
      const resultId = job.output?.result_ids?.[0];
      if (resultId && state.project === job.params?.asset_id) selectAnimation(resultId);
    } else if (job.status === 'erro' || job.status === 'interrompido') {
      state.myJobs.delete(job.id);
      toast(`${job.title}: ${job.error || job.progress}`, 'erro');
    }
  }
}

// Animação que chega com a tela aberta (a IA do terminal acabou de pôr, ou o Mixamo terminou) abre sozinha.
function watchNewAnimations() {
  const first = state.known === null;
  state.known ??= new Set();
  let newest = null;
  for (const result of state.data.results) {
    if (state.known.has(result.id)) continue;
    state.known.add(result.id);
    if (!first && result.asset_id === state.project) newest ??= result;
  }
  if (newest) {
    selectAnimation(newest.id);
    toast(`Animação nova: ${animName(newest)}`, 'ok');
  }
}

// --- Telas ----------------------------------------------------------------------------------

function showScreen() {
  const home = !state.project;
  $('#home').hidden = !home;
  $('#project').hidden = home;
  $('#crumb').hidden = home;
}

function writeHash() {
  const hash = state.project ? `#p/${state.project}${state.anim ? `/${state.anim}` : ''}` : '';
  if (location.hash !== hash) history.replaceState(null, '', hash || location.pathname);
}

function openProject(id, anim = null) {
  if (!asset(id)) return;
  state.project = id;
  state.anim = anim;
  state.keys = {};
  if (!location.hash.startsWith(`#p/${id}`)) history.pushState(null, '', `#p/${id}`);
  writeHash();
  showScreen();
  renderCrumb();
  renderAnimations();
  syncViewer();
  openTerminal(id);
}

function goHome() {
  state.project = null;
  state.anim = null;
  state.keys = {};
  if (location.hash) history.pushState(null, '', location.pathname);
  closeTerminal();
  showScreen();
  renderHome();
  renderMeshy();
  renderActivity();
  syncViewer();
}

function applyHash() {
  const [, id, anim] = location.hash.match(/^#p\/([a-z0-9-]+)(?:\/([a-z0-9-]+))?/) || [];
  if (id && asset(id)) {
    if (state.project !== id) openProject(id, anim || null);
    else if ((anim || null) !== state.anim) selectAnimation(anim || null);
  } else if (state.project) goHome();
}

function selectAnimation(id) {
  state.anim = id;
  writeHash();
  state.keys.anims = null;
  renderAnimations();
  syncViewer();
}

// --- Barra de cima ------------------------------------------------------------------------------

function renderStatus() {
  const engines = state.data.engines;
  const current = engines?.options.find((o) => o.id === engines.current);
  const busy = state.data.jobs.filter((j) => ACTIVE.includes(j.status));
  if (!changed('status', [state.online, current?.name, current?.problem, busy.map((j) => [j.id, j.title])])) return;
  if (!state.online) {
    fill($('#status'), h('span', { class: 'dot' }), 'Servidor local sem resposta');
    return;
  }
  fill($('#status'), busy.length ? h('span', { class: 'busy', title: busy.map((j) => j.title).join('\n') }, h('span', { class: 'spinner' }), busy.length === 1 ? busy[0].title : `${busy.length} trabalhos em andamento`) : null,
    current && h('span', { class: 'engine', title: current.problem ? `${current.name}: ${current.problem}` : current.about }, h('span', { class: `dot ${current.problem ? '' : 'on'}` }), `Gerador: ${current.name}`),
  );
}

function projectFacts(a) {
  const s = a.summary || {};
  return [
    s.rig ? `rig ${s.rig}` : null,
    s.bones ? `${s.bones} ossos` : null,
    s.triangles ? `${num(s.triangles)} triângulos` : null,
    s.height_m ? `${num(s.height_m, 2)} m` : null,
  ].filter(Boolean).join(' · ');
}

const NOT_READY = {
  precisa_rig: 'sem esqueleto',
  precisa_mapeamento: 'esqueleto não reconhecido',
  nao_suportado: 'rig não suportado',
  so_animacao: 'é uma animação, não um personagem',
  erro: 'erro ao abrir o arquivo',
};

function renderCrumb() {
  const a = currentProject();
  if (!a || !changed('crumb', [a.id, a.name, a.verdict, a.status, a.summary])) return;
  $('#project-name').textContent = a.name;
  fill($('#project-facts'), projectFacts(a), a.verdict && NOT_READY[a.verdict] ? chip('bad', NOT_READY[a.verdict]) : null, !a.verdict && a.status !== 'erro' ? chip('info', 'lendo o arquivo…') : null);
}

async function renameProject() {
  const a = currentProject();
  if (!a) return;
  const name = prompt('Nome do projeto:', a.name);
  if (!name || name.trim() === a.name) return;
  if (await guard(() => send('PATCH', `/api/assets/${a.id}`, { name: name.trim() }))) refresh();
}

// --- Tela de projetos -------------------------------------------------------------------------------

function renderHome() {
  const rows = state.data.assets.map((a) => ({ a, count: animsOf(a.id).length, working: jobsOf(a.id).length }));
  if (!changed('home', rows.map((r) => [r.a.id, r.a.name, r.a.verdict, r.a.status, r.count, r.working]))) return;
  fill($('#home-projects'), ...rows.map(({ a, count, working }) =>
      h(
        'div',
        { class: 'picker-slot' },
        h(
          'button',
          { class: 'picker-card', title: `Abrir o projeto ${a.name}`, onclick: () => openProject(a.id) },
          h('div', { class: 'avatar letter', 'aria-hidden': 'true' }, (a.name[0] || '?').toUpperCase()),
          h('div', { class: 'picker-name' }, a.name),
          h(
            'div',
            { class: 'item-chips' },
            a.verdict && NOT_READY[a.verdict] ? chip('bad', NOT_READY[a.verdict]) : null,
            !a.verdict && a.status !== 'erro' ? chip('info', 'lendo o arquivo…') : null,
            chip(count ? 'ok' : '', count === 1 ? '1 animação' : `${count} animações`),
            working ? chip('info', 'trabalhando…') : null,
          ),
        ),
        h('button', { class: 'picker-delete', title: `Excluir o projeto ${a.name}`, 'aria-label': `Excluir o projeto ${a.name}`, onclick: () => deleteProject(a) }, '×'),
      ),
    ),
    h(
      'button',
      {
        class: 'picker-card new',
        title: 'Envie um personagem: FBX, GLB, BLEND, OBJ, ou um ZIP com o modelo e as texturas. Também vale arrastar os arquivos para a janela.',
        onclick: () => $('#file-input').click(),
      },
      h('div', { class: 'avatar plus', 'aria-hidden': 'true' }, '+'),
      h('div', { class: 'picker-name' }, 'Novo personagem'),
    ),
  );
}

async function deleteProject(a) {
  const count = animsOf(a.id).length;
  const what = count ? `O personagem e ${count === 1 ? 'a animação dele' : `as ${count} animações dele`} são apagados` : 'O personagem é apagado';
  if (!confirm(`Excluir o projeto ${a.name}?\n${what} do disco. Não tem volta.`)) return;
  if (await guard(() => api(`/api/asset/${a.id}`, { method: 'DELETE' }))) {
    toast(`Projeto ${a.name} excluído.`, 'ok');
    refresh();
  }
}

// Os personagens pedidos ao Meshy: primeiro chega a imagem, para aprovar; aprovada, ela vira o
// modelo 3D e um projeto novo. Reprovada, a nota volta a quem fez o pedido.
const MESHY_STATUS = {
  gerando_imagem: ['info', 'gerando a imagem…'],
  aguardando_aprovacao: ['warn', 'aprovar a imagem?'],
  reprovado: ['bad', 'imagem reprovada'],
  gerando_modelo: ['info', 'gerando o modelo 3D…'],
  pronto: ['ok', 'virou projeto'],
  erro: ['bad', 'erro'],
};

function renderMeshy() {
  const requests = state.data.meshy?.requests || [];
  const meshyJobs = state.data.jobs.filter((j) => j.kind === 'meshy');
  if (!changed('meshy', [requests.map((r) => [r.id, r.status, r.note, r.error, r.asset_id, r.image_at]), meshyJobs.map((j) => [j.id, j.status])])) return;
  $('#meshy-head').hidden = !requests.length;
  fill($('#home-meshy'), ...requests.map((r) => {
      const [tone, label] = MESHY_STATUS[r.status] || ['info', r.status];
      const waiting = r.status === 'aguardando_aprovacao';
      // Gerando sem trabalho no ar: o programa foi fechado no meio. O modelo que o Meshy já fazia é retomado.
      const stalled = r.status === 'gerando_modelo' && !meshyJobs.some((j) => ACTIVE.includes(j.status));
      const exists = r.asset_id && asset(r.asset_id);
      return h(
        'div',
        { class: 'meshy-card' },
        r.image
          ? h('a', { class: 'meshy-link', href: `${r.files_base}/${r.image}`, target: '_blank', rel: 'noopener', title: 'Abrir a imagem inteira' }, h('img', { class: 'meshy-image', alt: `Imagem de ${r.name} gerada pelo Meshy`, src: `${r.files_base}/${r.image}?v=${encodeURIComponent(r.image_at || '')}` }))
          : h('div', { class: 'meshy-image', 'aria-hidden': 'true' }, '…'),
        h(
          'div',
          { class: 'meshy-body' },
          h('div', { class: 'picker-name' }, r.name),
          h('div', { class: 'sub' }, r.prompt),
          h('div', { class: 'item-chips' }, chip(tone, label)),
          r.note && h('div', { class: 'sub' }, `O que mudar: ${r.note}`),
          r.error && h('div', { class: 'sub' }, `Não deu certo: ${r.error}`),
          h(
            'div',
            { class: 'meshy-actions' },
            waiting && h('button', { class: 'btn small ok', onclick: () => approveMeshy(r) }, 'Aprovar e gerar o 3D'),
            waiting && h('button', { class: 'btn small', onclick: () => rejectMeshy(r) }, 'Reprovar'),
            stalled && h('button', { class: 'btn small', onclick: () => approveMeshy(r, true) }, 'Retomar'),
            exists && h('button', { class: 'btn small', onclick: () => openProject(r.asset_id) }, 'Abrir o projeto'),
            !['gerando_imagem', 'gerando_modelo'].includes(r.status) && h('button', { class: 'btn link small', onclick: () => removeMeshy(r) }, 'tirar da lista'),
          ),
        ),
      );
    }),
  );
}

async function approveMeshy(request, resume = false) {
  if (!resume && !confirm(`Aprovar a imagem de ${request.name} e gerar o modelo 3D?\nGasta créditos do Meshy e leva alguns minutos. Pronto, o personagem aparece aqui como projeto novo.`)) return;
  const job = await guard(() => send('POST', `/api/meshy/requests/${request.id}/approve`));
  if (!job) return;
  state.myJobs.add(job.id);
  toast(`Gerando o modelo 3D de ${request.name} no Meshy.`);
  refresh();
}

async function rejectMeshy(request) {
  const note = prompt(`O que mudar na imagem de ${request.name}? (a nota chega a quem faz o pedido)`, request.note || '');
  if (note === null) return;
  if (await guard(() => send('POST', `/api/meshy/requests/${request.id}/reject`, { note }))) {
    toast('Imagem reprovada. A nota foi guardada.', 'ok');
    refresh();
  }
}

async function removeMeshy(request) {
  if (!confirm(`Tirar o pedido de ${request.name} da lista?${request.asset_id ? ' O projeto criado a partir dele fica.' : ''}`)) return;
  if (await guard(() => api(`/api/meshy/requests/${request.id}`, { method: 'DELETE' }))) refresh();
}

// O que está sendo feito agora, na tela de projetos (ler um arquivo enviado, o Meshy gerando).
function renderActivity() {
  const busy = state.data.jobs.filter((j) => ACTIVE.includes(j.status));
  if (!changed('activity', busy.map((j) => [j.id, j.status, j.progress]))) return;
  fill($('#home-activity'), ...busy.map(jobRow));
}

const jobRow = (job) =>
  h('div', { class: 'job' }, h('div', { class: 'job-title' }, h('span', { class: 'spinner' }), job.title), h('div', { class: 'job-progress' }, job.progress || ''));

// --- Animações do projeto -------------------------------------------------------------------------

const ORIGIN = { mixamo: 'Mixamo', blender: 'Blender', captura: 'captura', importado: 'importada' };

function renderAnimations() {
  const a = currentProject();
  if (!a) return;
  const anims = animsOf(a.id);
  const busy = jobsOf(a.id);
  if (state.anim && !anims.some((r) => r.id === state.anim)) state.anim = null; // a que estava aberta foi apagada
  if (!changed('anims', [a.id, a.verdict, state.anim, anims.map((r) => [r.id, animName(r), r.stats?.duration_s, motionOf(r)?.source]), busy.map((j) => [j.id, j.status, j.progress])])) return;
  $('#anim-count').textContent = anims.length ? anims.length : '';
  $('#mixamo-button').disabled = a.verdict !== 'pronto';
  fill($('#anim-list'), h(
      'button',
      { class: 'anim', 'aria-current': state.anim === null ? 'true' : null, onclick: () => selectAnimation(null) },
      h('span', { class: 'anim-icon' }, '◼'),
      h('span', { class: 'anim-name' }, 'Modelo parado'),
      h('span', { class: 'anim-meta' }, 'sem animação'),
    ),
    ...anims.map((r) => {
      const origin = ORIGIN[motionOf(r)?.source] || 'gerada';
      return h(
        'div',
        { class: 'anim-slot' },
        h(
          'button',
          { class: 'anim', 'aria-current': state.anim === r.id ? 'true' : null, onclick: () => selectAnimation(r.id), ondblclick: () => renameAnimation(r), title: 'Clique para ver; dois cliques mudam o nome.' },
          h('span', { class: 'anim-icon' }, '▶'),
          h('span', { class: 'anim-name' }, animName(r)),
          h('span', { class: 'anim-meta' }, `${num(r.stats?.duration_s, 1)} s · ${origin}`),
        ),
        h('button', { class: 'anim-delete', title: `Apagar a animação ${animName(r)}`, 'aria-label': `Apagar a animação ${animName(r)}`, onclick: () => deleteAnimation(r) }, '×'),
      );
    }),
    ...busy.map(jobRow),
    !anims.length && !busy.length
      ? h('p', { class: 'empty' }, a.verdict === 'pronto' ? 'Nenhuma animação ainda. Peça uma à IA, no terminal abaixo, ou traga uma do Mixamo.' : 'Este personagem ainda não pode receber animação.')
      : null,
  );
}

async function renameAnimation(result) {
  const motion = motionOf(result);
  if (!motion) return;
  const name = prompt('Nome da animação:', animName(result));
  if (!name || name.trim() === animName(result)) return;
  if (await guard(() => send('PATCH', `/api/motions/${motion.id}`, { name: name.trim() }))) refresh();
}

async function deleteAnimation(result) {
  if (!confirm(`Apagar a animação ${animName(result)}?\nO arquivo dela sai do disco. Não tem volta.`)) return;
  const path = motionOf(result) ? `/api/motion/${result.motion_id}` : `/api/result/${result.id}`;
  if (await guard(() => api(path, { method: 'DELETE' }))) {
    if (state.anim === result.id) state.anim = null;
    refresh();
  }
}

// Animações prontas do Mixamo: o FBX baixado de lá é aplicado neste personagem pelo Blender, por trás.
async function importMixamo(files) {
  const a = currentProject();
  if (a?.verdict !== 'pronto') return toast('Este personagem ainda não pode receber animação.', 'erro');
  for (const file of files) {
    if (!/\.fbx$/i.test(file.name)) {
      toast(`${file.name}: a animação do Mixamo precisa estar em FBX.`, 'erro');
      continue;
    }
    const job = await guard(() => api(`/api/motions/import-fbx?filename=${encodeURIComponent(file.name)}&asset_id=${a.id}`, { method: 'POST', body: file }));
    if (job) {
      state.myJobs.add(job.id);
      toast(`Aplicando ${file.name} em ${a.name}. Leva uns 20 segundos.`);
    }
  }
  refresh();
}

// --- Visor --------------------------------------------------------------------------------------

function viewerSource() {
  const a = currentProject();
  if (!a) return null;
  const result = state.anim && animsOf(a.id).find((r) => r.id === state.anim);
  if (result?.files?.glb) {
    return { key: `r:${result.id}:${result.created_at}`, url: `${result.files_base}/${result.files.glb}?v=${encodeURIComponent(result.created_at)}`, title: animName(result), project: a.id };
  }
  if (a.preview) {
    return { key: `a:${a.id}:${a.inspected_at}`, url: `${a.files_base}/${a.preview}?v=${encodeURIComponent(a.inspected_at || '')}`, title: 'Modelo parado', project: a.id };
  }
  return { key: `vazio:${a.id}:${a.status}`, url: null, title: '', project: a.id, empty: a.status === 'erro' ? `Não consegui abrir o arquivo deste personagem: ${a.error || 'erro'}` : 'Lendo o arquivo do personagem…' };
}

async function syncViewer() {
  const source = viewerSource();
  if (!source) {
    if (state.loaded) viewer.clear();
    state.loaded = null;
    state.loadedProject = null;
    return;
  }
  if (source.key === state.loaded) return;
  state.loaded = source.key;
  delete document.body.dataset.visor; // "o visor já mostra": é o que tests/ui_click.mjs espera
  $('#viewport-title').textContent = source.title;
  $('#viewport-empty').textContent = source.empty || '';
  if (!source.url) {
    viewer.clear();
    setTransport(false);
    return;
  }
  // Trocar de animação no mesmo personagem não mexe na câmera: dá para comparar do mesmo ângulo.
  const keep = state.loadedProject === source.project && viewer.root ? { position: viewer.camera.position.clone(), target: viewer.controls.target.clone() } : null;
  let clips;
  try {
    clips = await viewer.load(source.url);
  } catch (err) {
    if (state.loaded === source.key) $('#viewport-empty').textContent = `Não consegui mostrar este arquivo: ${err.message}`;
    return;
  }
  if (clips === null) return; // outra escolha chegou antes
  state.loadedProject = source.project;
  document.body.dataset.visor = source.key;
  if (keep) {
    viewer.camera.position.copy(keep.position);
    viewer.controls.target.copy(keep.target);
  }
  for (const [option, id] of [['follow', '#follow'], ['inPlace', '#in-place-view'], ['bones', '#bones'], ['wire', '#wire']]) viewer.setOption(option, $(id).checked);
  viewer.setSpeed(Number($('#speed').value));
  setTransport(clips.length > 0);
}

function setTransport(enabled) {
  for (const id of ['#play', '#scrub', '#speed', '#follow', '#in-place-view']) $(id).disabled = !enabled;
  $('#play').textContent = enabled ? '⏸' : '▶';
  if (!enabled) {
    $('#scrub').value = 0;
    $('#time').textContent = '—';
  }
}

const seconds = (value) => `${num(value, 2)} s`;
viewer.onTime = (time, duration) => {
  if (state.scrubbing) return;
  $('#scrub').value = duration ? time / duration : 0;
  $('#time').textContent = `${seconds(time)} / ${seconds(duration)}`;
};

function togglePlay() {
  if (!viewer.duration) return;
  viewer.setPlaying(!viewer.playing);
  $('#play').textContent = viewer.playing ? '⏸' : '▶';
}

// De onde olhar: o personagem olha para +Z no arquivo.
const VIEWS = { front: [0, 0.12, 1], side: [1, 0.12, 0], back: [0, 0.12, -1], top: [0, 1, 0.001] };
function setView(name) {
  if (!viewer.root) return;
  const target = viewer.controls.target;
  const [x, y, z] = VIEWS[name];
  const length = Math.hypot(x, y, z);
  const distance = (viewer.reach || 1) * 2.4;
  viewer.camera.position.set(target.x + (x / length) * distance, target.y + (y / length) * distance, target.z + (z / length) * distance);
  viewer.controls.update();
}

$('#play').addEventListener('click', togglePlay);
$('#scrub').addEventListener('pointerdown', () => { state.scrubbing = true; });
$('#scrub').addEventListener('input', (e) => {
  viewer.setPlaying(false);
  $('#play').textContent = '▶';
  viewer.seek(Number(e.target.value) * viewer.duration);
  $('#time').textContent = `${seconds(Number(e.target.value) * viewer.duration)} / ${seconds(viewer.duration)}`;
});
$('#scrub').addEventListener('change', () => { state.scrubbing = false; });
$('#speed').addEventListener('change', (e) => viewer.setSpeed(Number(e.target.value)));
for (const [option, id] of [['follow', '#follow'], ['inPlace', '#in-place-view'], ['bones', '#bones'], ['wire', '#wire']]) {
  $(id).addEventListener('change', (e) => viewer.setOption(option, e.target.checked));
}
for (const button of document.querySelectorAll('#views button')) button.addEventListener('click', () => setView(button.dataset.view));
window.addEventListener('keydown', (e) => {
  // Espaço toca e pausa, menos quando se está escrevendo (no terminal, num campo).
  if (e.code !== 'Space' || !state.project || e.target.closest('input, textarea, select, button, .terminal')) return;
  e.preventDefault();
  togglePlay();
});

// --- Terminal do projeto -----------------------------------------------------------------------
// Um terminal de verdade na pasta do projeto, parado no prompt: quem chama a IA (o claude ou
// outra) é o dono. Depois que alguém escreve nele, continua vivo no servidor: trocar de projeto
// ou recarregar só solta a tela, e ao voltar o que estava escrito reaparece. Sem nada escrito,
// o servidor fecha o terminal pouco depois de a tela sair.

const term = { xterm: null, fit: null, ws: null, project: null };

function termState(text, tone = '') {
  $('#term-state').textContent = text;
  $('#term-state').className = `term-state ${tone}`;
}

function sendToTerminal(message) {
  if (term.ws?.readyState === WebSocket.OPEN) term.ws.send(JSON.stringify(message));
}

function fitTerminal() {
  if (!term.xterm || !$('#terminal').clientWidth) return;
  term.fit.fit();
  sendToTerminal({ type: 'resize', cols: term.xterm.cols, rows: term.xterm.rows });
}

function createTerminal() {
  term.xterm = new Terminal({
    fontFamily: '"Cascadia Mono", "Cascadia Code", Consolas, "Courier New", monospace',
    fontSize: 13,
    lineHeight: 1.15,
    cursorBlink: true,
    scrollback: 8000,
    theme: { background: '#0e1013', foreground: '#e6e8ec', cursor: '#f0a43a', selectionBackground: '#3a4252' },
  });
  term.fit = new FitAddon();
  term.xterm.loadAddon(term.fit);
  term.xterm.open($('#terminal'));
  term.xterm.onData((data) => sendToTerminal({ type: 'input', data }));
  // Ctrl+V cola e Ctrl+C copia o que estiver marcado (sem nada marcado, Ctrl+C interrompe, como em todo terminal).
  term.xterm.attachCustomKeyEventHandler((e) => {
    if (e.type !== 'keydown' || !e.ctrlKey || e.altKey) return true;
    const key = e.key.toLowerCase();
    if (key === 'v') return false; // o navegador cola, e o terminal recebe o texto
    if (key === 'c' && term.xterm.hasSelection()) {
      navigator.clipboard?.writeText(term.xterm.getSelection());
      term.xterm.clearSelection();
      return false;
    }
    return true;
  });
  new ResizeObserver(() => fitTerminal()).observe($('#terminal'));
}

function closeTerminal() {
  const ws = term.ws;
  term.ws = null;
  term.project = null;
  ws?.close();
}

async function openTerminal(assetId) {
  closeTerminal();
  if (!term.xterm) createTerminal();
  term.project = assetId;
  term.xterm.reset();
  $('#term-where').textContent = `na pasta de ${asset(assetId)?.name || 'projeto'}`;
  termState('abrindo…');
  const info = await guard(() => api('/api/terminal'));
  if (term.project !== assetId) return; // trocou de projeto enquanto abria
  if (!info) return termState('sem resposta', 'bad');
  if (info.problem) {
    term.xterm.writeln(info.problem);
    return termState('indisponível', 'bad');
  }
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/terminal/${assetId}?token=${encodeURIComponent(info.token)}`);
  term.ws = ws;
  ws.addEventListener('open', () => {
    termState('ligado', 'ok');
    fitTerminal();
    term.xterm.focus();
  });
  ws.addEventListener('message', (event) => {
    if (term.ws !== ws) return;
    const message = JSON.parse(event.data);
    if (message.type === 'output') term.xterm.write(message.data);
    else if (message.type === 'error') {
      term.xterm.writeln(message.message);
      termState('não abriu', 'bad');
    } else if (message.type === 'exit') {
      term.xterm.writeln('\r\n[o terminal foi fechado; clique em "reiniciar" para abrir outro]');
      termState('fechado', 'warn');
    }
  });
  ws.addEventListener('close', () => {
    if (term.ws !== ws) return;
    term.ws = null;
    if ($('#term-state').textContent.startsWith('ligado')) termState('desligado', 'warn');
  });
}

async function restartTerminal() {
  const id = state.project;
  if (!id || !confirm('Fechar este terminal e abrir um novo?\nO que estiver rodando nele (a conversa com a IA, por exemplo) é encerrado.')) return;
  closeTerminal();
  if (await guard(() => send('POST', `/api/terminal/${id}/restart`))) openTerminal(id);
}

$('#term-restart').addEventListener('click', restartTerminal);
// Terminal desligado (o servidor foi reiniciado): um clique nele liga de novo.
$('#terminal').addEventListener('pointerdown', () => {
  if (state.project && !term.ws) openTerminal(state.project);
});

// --- Largura das duas metades ----------------------------------------------------------------------

const SIDE_KEY = 'ponte.lado';
function setSide(pixels) {
  const max = window.innerWidth - 360;
  const width = Math.round(Math.min(Math.max(pixels, 380), Math.max(max, 380)));
  $('#project').style.setProperty('--side', `${width}px`);
  return width;
}
{
  const saved = Number(localStorage.getItem(SIDE_KEY));
  if (saved) setSide(saved);
  const splitter = $('#splitter');
  splitter.addEventListener('pointerdown', (e) => {
    splitter.setPointerCapture(e.pointerId);
    document.body.classList.add('resizing');
    const move = (ev) => localStorage.setItem(SIDE_KEY, setSide(window.innerWidth - ev.clientX));
    const stop = () => {
      splitter.removeEventListener('pointermove', move);
      splitter.removeEventListener('pointerup', stop);
      document.body.classList.remove('resizing');
    };
    splitter.addEventListener('pointermove', move);
    splitter.addEventListener('pointerup', stop);
  });
}

// --- Envio de arquivos --------------------------------------------------------------------------------

const MODEL_RE = /\.(fbx|glb|gltf|blend|obj|zip)$/i; // o .zip traz o modelo e as texturas juntos
const SIDECAR_RE = /\.(png|jpe?g|tga|bmp|tiff?|webp|exr|dds|mtl|bin)$/i;
const asEntries = (files) => [...files].map((file) => ({ file, path: file.name }));

// Arquivos soltos na janela, entrando nas pastas e guardando o caminho de cada um.
// As entradas precisam ser lidas ainda dentro do evento de soltar; o resto pode esperar.
function droppedEntries(dataTransfer) {
  const roots = [...dataTransfer.items].map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
  if (!roots.length) return Promise.resolve(asEntries(dataTransfer.files));
  const out = [];
  const walk = async (entry) => {
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      out.push({ file, path: entry.fullPath.replace(/^\//, '') });
      return;
    }
    const reader = entry.createReader();
    for (;;) {
      const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
      if (!batch.length) break;
      for (const child of batch) await walk(child);
    }
  };
  return Promise.all(roots.map(walk)).then(() => out);
}

// A textura fica no mesmo lugar relativo ao modelo que tinha na pasta de origem.
function relativeToModel(modelPath, filePath) {
  const dir = modelPath.slice(0, modelPath.lastIndexOf('/') + 1);
  return dir && filePath.startsWith(dir) ? filePath.slice(dir.length) : filePath.split('/').pop();
}

async function sendSidecars(assetId, sidecars, modelPath) {
  let sent = 0;
  for (const { file, path } of sidecars) {
    const target = encodeURIComponent(relativeToModel(modelPath, path));
    if (await guard(() => api(`/api/assets/${assetId}/files?path=${target}`, { method: 'POST', body: file }))) sent += 1;
  }
  return sent;
}

async function upload(entries) {
  const models = entries.filter((e) => MODEL_RE.test(e.file.name));
  const sidecars = entries.filter((e) => SIDECAR_RE.test(e.file.name));
  const ignored = entries.length - models.length - sidecars.length;
  if (ignored) toast(`${ignored} arquivo(s) ignorado(s): formato não reconhecido.`);

  // Dentro de um projeto, FBX solto é animação do Mixamo para o personagem dele.
  if (state.project && models.length && !sidecars.length && models.every((m) => /\.fbx$/i.test(m.file.name))) {
    const what = models.length === 1 ? `"${models[0].file.name}"` : `${models.length} arquivos`;
    const asMixamo = confirm(`Aplicar ${what} em ${currentProject()?.name} como animação do Mixamo?\n\nOK: animação deste personagem.\nCancelar: criar um projeto novo com o arquivo.`);
    if (asMixamo) return importMixamo(models.map((m) => m.file));
  }
  if (!models.length && sidecars.length) {
    const a = currentProject();
    if (!a) return toast('Texturas precisam de um projeto: arraste-as junto com o modelo, ou abra o projeto antes de soltar.', 'erro');
    const sent = await sendSidecars(a.id, sidecars, '');
    if (!sent) return;
    const job = await guard(() => send('POST', `/api/assets/${a.id}/inspect`));
    if (job) state.myJobs.add(job.id);
    return toast(`${sent} arquivo(s) de textura adicionado(s) a ${a.name}.`, 'ok');
  }
  let last = null;
  for (const model of models) {
    // Com texturas na mesma leva, a leitura do arquivo espera elas chegarem.
    const loose = sidecars.length > 0 && !/\.zip$/i.test(model.file.name);
    const query = `filename=${encodeURIComponent(model.file.name)}${loose ? '&defer=true' : ''}`;
    const out = await guard(() => api(`/api/assets?${query}`, { method: 'POST', body: model.file }));
    if (!out) continue;
    let job = out.job;
    if (loose) {
      const sent = await sendSidecars(out.asset.id, sidecars, model.path);
      toast(`${out.asset.name}: ${sent} arquivo(s) de textura enviado(s) com o modelo.`);
      job = await guard(() => send('POST', `/api/assets/${out.asset.id}/inspect`));
    }
    if (job) state.myJobs.add(job.id);
    last = out.asset.id;
  }
  await refresh();
  if (last) openProject(last);
}

$('#mixamo-button').addEventListener('click', () => $('#mixamo-input').click());
$('#mixamo-input').addEventListener('change', (e) => {
  importMixamo([...e.target.files]);
  e.target.value = '';
});
$('#file-input').addEventListener('change', (e) => {
  upload(asEntries(e.target.files));
  e.target.value = '';
});

let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
window.addEventListener('dragenter', (e) => {
  if (!hasFiles(e)) return;
  dragDepth += 1;
  $('#dropzone').hidden = false;
});
window.addEventListener('dragleave', () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $('#dropzone').hidden = true;
});
window.addEventListener('dragover', (e) => hasFiles(e) && e.preventDefault());
window.addEventListener('drop', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $('#dropzone').hidden = true;
  droppedEntries(e.dataTransfer).then(upload, (err) => toast(`Não consegui ler os arquivos soltos: ${err.message}`, 'erro'));
});

$('#back-home').addEventListener('click', goHome);
$('#project-name').addEventListener('click', renameProject);
window.addEventListener('hashchange', applyHash);
window.addEventListener('popstate', applyHash);

await refresh();
applyHash();
setInterval(refresh, 2000);
