// Interface da PonteAnimada: os projetos, que são jogos, e dentro de cada um as abas dele, com os
// personagens (o visor 3D e as animações), os assets e a gestão (tarefas e documentos), e o
// terminal. O Blender roda por trás, comandado pela IA chamada no terminal; aqui só se vê o resultado.
// A tela anterior (laudo, rig, roteiros, revisão) continua em /antiga/.

import { Viewer } from './viewer.js';
import { renderMarkdown } from './markdown.js';
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
  data: { games: [], items: [], tasks: [], assets: [], motions: [], results: [], jobs: [], meshy: {}, engines: null },
  legacy: false, // o servidor no ar é de antes dos jogos: a tela nova espera o reinício
  game: null, // id do jogo aberto; nulo na tela de projetos
  tab: null, // id da aba escolhida na tela do jogo; nulo (ou uma que não existe mais) mostra a primeira
  project: null, // id do personagem (ou do modelo 3D) aberto
  item: null, // id da textura, do som ou do documento aberto
  anim: null, // id da animação escolhida; nulo mostra o modelo parado
  known: null, // animações já vistas: as que chegarem depois são abertas sozinhas
  keys: {},
  pickEngine: false, // a escolha do gerador foi reaberta pela barra de cima
  media: {}, // o que só se sabe abrindo o arquivo: o tamanho da textura, a duração do som
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

// Um projeto é um personagem ou um modelo 3D (um asset do jogo); os dois dizem em `game` de que jogo são.
// As texturas, os sons e os documentos são os "items". Na tela, modelos, texturas e sons juntos são
// os Assets; os documentos ficam numa aba de gestão, com as tarefas ("tasks").
const asset = (id) => state.data.assets.find((a) => a.id === id);
const game = (id) => state.data.games.find((g) => g.id === id);
const item = (id) => state.data.items.find((i) => i.id === id);
const currentGame = () => game(state.game);
const currentProject = () => asset(state.project);
const currentItem = () => item(state.item);
const roleOf = (a) => a?.role || 'personagem';
const isDoc = (i) => i?.kind === 'documento';
const gameOf = (a) => (a?.game && game(a.game) ? a.game : null);
const charactersOf = (id) => state.data.assets.filter((a) => a.game === id && roleOf(a) === 'personagem');
const modelsOf = (id) => state.data.assets.filter((a) => a.game === id && roleOf(a) === 'modelo');
const itemsOf = (id) => state.data.items.filter((i) => i.game === id);
const filesOf = (id) => itemsOf(id).filter((i) => !isDoc(i)); // as texturas e os sons
const docsOf = (id) => itemsOf(id).filter(isDoc);
const tasksOf = (id) => state.data.tasks.filter((t) => t.game === id);

// As abas da tela do jogo. Duas vêm com ele; as outras o dono cria (pedido dele em 13/10/2026:
// "adicione uma opção onde eu possa criar minhas abas seja ela de personagens, assets e gestão").
// O servidor de antes das abas não as manda: a tela mostra as duas de sempre e criar espera o reinício.
const BUILTIN_TABS = [
  { id: 'characters', name: 'Characters', kind: 'personagens' },
  { id: 'assets', name: 'Assets', kind: 'assets' },
];
const TAB_KINDS = {
  personagens: { label: 'Personagens', about: 'Os personagens do jogo: cada um com o modelo, as animações e o terminal dele.', hint: 'Os personagens do jogo. Abra um para ver o modelo e as animações dele.' },
  assets: { label: 'Assets', about: 'O que não é personagem: modelos 3D (arma, objeto, cenário), texturas e sons.', hint: 'O que não é personagem: modelos 3D (arma, objeto, cenário), texturas e sons.' },
  gestao: { label: 'Gestão', about: 'Um quadro de tarefas (a fazer, fazendo, feito) e os documentos do jogo: ideias, regras, roteiro.', hint: 'As tarefas e os documentos do jogo. A IA chamada no terminal ao lado também lê e atualiza os dois.' },
};
const hasTabs = (g) => Array.isArray(g?.tabs);
const tabsOf = (g) => (hasTabs(g) ? g.tabs : BUILTIN_TABS);
const isBuiltin = (tab) => BUILTIN_TABS.some((t) => t.id === tab.id);
// Em que aba uma coisa aparece: a que ela diz, se existe e é do tipo dela; senão, a primeira desse tipo.
function tabIn(g, thing, kind) {
  const same = tabsOf(g).filter((t) => t.kind === kind);
  return same.find((t) => t.id === thing.tab) || same[0] || null;
}
const projectTab = (a) => tabIn(game(a.game), a, roleOf(a) === 'modelo' ? 'assets' : 'personagens');
const itemTab = (i) => tabIn(game(i.game), i, isDoc(i) ? 'gestao' : 'assets');
const taskTab = (t) => tabIn(game(t.game), t, 'gestao');
function currentTab() {
  const tabs = tabsOf(currentGame());
  return tabs.find((t) => t.id === state.tab) || tabs[0];
}
const animsOf = (id) => state.data.results.filter((r) => r.asset_id === id);
const motionOf = (result) => state.data.motions.find((m) => m.id === result.motion_id);
const animName = (result) => motionOf(result)?.name || result.prompt || result.id;
const jobsOf = (id) => state.data.jobs.filter((j) => ACTIVE.includes(j.status) && j.params?.asset_id === id);
const fileUrl = (i) => `${i.files_base}/${encodeURIComponent(i.file)}`;

// --- Utilidades ---------------------------------------------------------------------------

const num = (value, digits = 0) =>
  value == null ? '—' : Number(value).toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const bytes = (n) => (n == null ? '—' : n < 1024 ? `${n} B` : n < 1024 ** 2 ? `${num(n / 1024)} KB` : `${num(n / 1024 ** 2, 1)} MB`);
const byName = (x, y) => x.name.localeCompare(y.name, 'pt-BR', { numeric: true, sensitivity: 'base' });
const plural = (count, one, many) => (count === 1 ? `1 ${one}` : `${count} ${many}`);
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

// A leitura do estado às vezes leva uns segundos (o servidor confere os geradores no meio dela). Nas
// abas e no quadro de tarefas, o que acabou de ser mudado já entra no que a tela mostra (`applied`),
// sem esperar; uma leitura pedida antes da mudança chegaria com o estado de antes, e é refeita.
let dataEpoch = 0;
function applied() {
  dataEpoch += 1;
  render();
  refresh();
}

async function refresh() {
  const epoch = dataEpoch;
  let data;
  try {
    data = await api('/api/state');
  } catch {
    state.online = false;
    renderStatus();
    return;
  }
  if (epoch !== dataEpoch) return refresh();
  const back = !state.online; // o servidor voltou (foi reiniciado): o terminal aberto caiu junto
  state.online = true;
  state.legacy = !Array.isArray(data.games);
  state.data = { ...data, games: data.games || [], items: data.items || [], tasks: data.tasks || [] };
  watchJobs();
  watchNewAnimations();
  settle();
  if (back) term.items = true; // o servidor que voltou pode ser o novo: pergunta de novo
  if (back && !term.ws) openTerminal(termTarget());
  else if (term.where && term.where !== termTarget()) openTerminal(termTarget()); // o que estava aberto foi apagado ou mudou de jogo
  render();
}

// O que estava aberto ainda existe? Um personagem apagado devolve ao jogo dele; um jogo apagado, à entrada.
function settle() {
  const before = [state.game, state.project, state.item].join();
  if (state.item && !currentItem()) {
    state.item = null;
    doc.editing = false; // o documento aberto foi apagado: não há mais o que salvar
  }
  if (state.project && !currentProject()) state.project = state.anim = null;
  const inside = currentItem() ? currentItem().game : currentProject() ? gameOf(currentProject()) : state.game;
  state.game = inside && game(inside) ? inside : null;
  if ([state.game, state.project, state.item].join() === before) return;
  state.keys = {};
  writeHash();
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
// Projetos (os jogos) > o jogo (as abas dele) > um personagem, um asset ou um documento aberto.
// O endereço guarda onde se está: #g/<jogo>/<aba>, #p/<personagem ou modelo>/<animação>,
// #i/<textura, som ou documento>.

function screen() {
  if (state.item) return 'asset';
  if (state.project) return roleOf(currentProject()) === 'modelo' ? 'asset' : 'personagem';
  return state.game ? 'jogo' : 'entrada';
}

function showScreen() {
  const where = screen();
  $('#home').hidden = where !== 'entrada';
  $('#game').hidden = where !== 'jogo';
  $('#project').hidden = where === 'entrada' || where === 'jogo';
  $('#crumb').hidden = where === 'entrada';
  $('#anims-panel').hidden = where !== 'personagem';
  $('#details-panel').hidden = where !== 'asset';
  document.body.dataset.tela = where;
}

function render() {
  const where = screen();
  showScreen();
  renderStatus();
  renderEngine();
  renderCrumb();
  renderTermWhere();
  if (where === 'entrada') {
    renderHome();
    renderLoose();
    renderMeshy();
  } else if (where === 'jogo') renderGame();
  else if (where === 'personagem') renderAnimations();
  else {
    renderDetails();
    syncDocument();
  }
  renderActivity();
  syncViewer();
}

function writeHash(push = false) {
  // A primeira aba é a do endereço sem aba: #g/<jogo>.
  const tab = state.game && !state.project && !state.item && currentTab().id !== tabsOf(currentGame())[0].id ? `/${currentTab().id}` : '';
  const hash = state.item ? `#i/${state.item}` : state.project ? `#p/${state.project}${state.anim ? `/${state.anim}` : ''}` : state.game ? `#g/${state.game}${tab}` : '';
  if (location.hash === hash) return;
  history[push ? 'pushState' : 'replaceState'](null, '', hash || location.pathname);
}

function go(next) {
  if (!leaveDocument()) return writeHash(); // ficou no documento: o endereço volta a ser o dele
  Object.assign(state, { game: null, project: null, item: null, anim: null }, next, { keys: {} });
  writeHash(true);
  render();
  openTerminal(termTarget());
}

const goHome = () => go({});

// Sem aba dita, o jogo abre na aba em que se estava (voltando de um personagem, é a dele).
function openGame(id, tab) {
  if (game(id)) go(tab === undefined ? { game: id } : { game: id, tab });
}

function selectTab(id) {
  if (currentTab().id === id) return;
  state.tab = id;
  state.keys.game = null;
  writeHash(true);
  render();
}

function openProject(id, anim = null) {
  const a = asset(id);
  if (a) go({ game: gameOf(a), project: id, anim, tab: gameOf(a) ? projectTab(a).id : state.tab });
}

function openItem(id) {
  const i = item(id);
  if (i) go({ game: game(i.game) ? i.game : null, item: id, tab: game(i.game) ? itemTab(i)?.id ?? state.tab : state.tab });
}

// De um personagem ou de um asset, volta ao jogo dele; do jogo, à tela de projetos.
function goBack() {
  if (state.game && (state.project || state.item)) openGame(state.game);
  else goHome();
}

function applyHash() {
  const [, kind, id, anim] = location.hash.match(/^#([gpi])\/([a-z0-9-]+)(?:\/([a-z0-9-]+))?/) || [];
  if (kind === 'p' && asset(id)) {
    if (state.project !== id || state.item) openProject(id, anim || null);
    else if ((anim || null) !== state.anim) selectAnimation(anim || null);
  } else if (kind === 'i' && item(id)) {
    if (state.item !== id) openItem(id);
  } else if (kind === 'g' && game(id)) {
    // O terceiro pedaço do endereço do jogo é a aba; sem ele (ou com uma que não existe mais), a primeira.
    const tab = tabsOf(game(id)).find((t) => t.id === anim)?.id || tabsOf(game(id))[0].id;
    if (state.game !== id || state.project || state.item) openGame(id, tab);
    else selectTab(tab);
  } else if (state.game || state.project || state.item) goHome();
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
    current && h('button', { type: 'button', class: 'engine', id: 'change-engine', title: `${current.problem ? `${current.name}: ${current.problem}` : current.about}\nClique para trocar o gerador.`, onclick: () => { state.pickEngine = true; renderEngine(); } }, h('span', { class: `dot ${current.problem ? '' : 'on'}` }), `Gerador: ${current.name}`),
  );
}

// --- Gerador ------------------------------------------------------------------------------------
// O Kimodo original (Docker), o kimodo.cpp (Windows) ou o ARDY (Ubuntu): os três aparecem sempre, e
// o que não está instalado fica apagado, com o motivo. A ponte pergunta ao abrir a janela; a
// resposta vale para o que for gerado dali em diante, pela tela e pela linha de comando.

function renderEngine() {
  const engines = state.data.engines;
  const box = $('#engine-pick');
  // Perguntado uma vez por janela aberta: recarregar a página não pergunta de novo.
  const asked = sessionStorage.getItem('ponte-gerador');
  if (!engines || (asked && !state.pickEngine)) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  if (!changed('engine-pick', [engines, state.pickEngine])) return;
  const none = !engines.options.some((o) => !o.problem);
  // Reaberta pela barra de cima, ou sem nada instalado para escolher, dá para fechar sem trocar.
  const close = state.pickEngine || none ? () => { sessionStorage.setItem('ponte-gerador', engines.current); state.pickEngine = false; renderEngine(); } : null;
  fill(
    box,
    h(
      'div',
      { class: 'engine-box', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Escolha do gerador' },
      h('h2', {}, 'Qual gerador você vai usar?'),
      h('p', { class: 'hint' }, 'O Kimodo original e o kimodo.cpp rodam o mesmo modelo, no mesmo esqueleto; o ARDY é outro modelo, com esqueleto próprio. A escolha vale para o que for gerado a partir de agora, pela tela e pelo terminal; dá para trocar depois, clicando em “Gerador”, na barra de cima.'),
      h('p', { class: 'hint' }, 'Escolher não liga nada: o gerador só é ligado quando uma geração é pedida.'),
      h(
        'div',
        { class: 'engine-options' },
        engines.options.map((o) =>
          h(
            'button',
            { type: 'button', class: `engine-option${o.id === engines.current ? ' current' : ''}`, 'data-engine': o.id, disabled: !!o.problem, onclick: () => pickEngine(o.id) },
            h('strong', {}, o.name),
            h('span', {}, o.about),
            o.problem ? h('span', { class: 'engine-problem' }, o.problem) : o.id === engines.current ? h('span', { class: 'engine-current' }, 'É o que está em uso.') : null,
          ),
        ),
      ),
      close && h('div', { class: 'engine-foot' }, h('button', { type: 'button', class: 'btn small', id: 'engine-close', onclick: close }, none ? 'Fechar' : 'Deixar como está')),
    ),
  );
}

async function pickEngine(id) {
  const engines = await guard(() => send('PUT', '/api/engine', { engine: id }));
  if (!engines) return;
  sessionStorage.setItem('ponte-gerador', id);
  state.pickEngine = false;
  state.data.engines = engines;
  renderEngine();
  renderStatus();
  toast(`Gerador em uso: ${engines.options.find((o) => o.id === engines.current)?.name}.`, 'ok');
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
// O que avisar de um projeto: num modelo 3D, não ter esqueleto é o esperado.
const trouble = (a) => (roleOf(a) === 'modelo' ? (a.verdict === 'erro' ? NOT_READY.erro : null) : NOT_READY[a.verdict] || null);
const KIND = { textura: 'textura', som: 'som', documento: 'documento' };
// Como chamar uma textura, um som ou um documento numa frase: "o asset casa", "o documento Regras".
const itemWord = (i) => (isDoc(i) ? 'documento' : 'asset');

function renderCrumb() {
  const where = screen();
  if (where === 'entrada') return;
  const g = currentGame();
  const a = currentProject();
  const i = currentItem();
  const open = i || a || g;
  if (!open || !changed('crumb', [where, g?.id, g?.name, g?.code_path, open.id, open.name, a?.verdict, a?.status, a?.summary, a?.role, i?.size_bytes])) return;
  const up = where !== 'jogo' && g; // dentro do jogo, volta-se a ele
  $('#back').textContent = up ? `← ${g.name}` : '← Projetos';
  $('#back').title = up ? `Voltar ao jogo ${g.name}` : 'Voltar à tela de projetos';
  $('#crumb-name').textContent = open.name;
  if (i) fill($('#crumb-facts'), `${KIND[i.kind]} · ${bytes(i.size_bytes)}`);
  else if (a) fill($('#crumb-facts'), projectFacts(a), trouble(a) ? chip('bad', trouble(a)) : null, !a.verdict && a.status !== 'erro' ? chip('info', 'lendo o arquivo…') : null);
  else {
    fill($('#crumb-facts'), h(
        'button',
        { class: 'btn link small', title: 'A pasta onde está o código do jogo (o projeto na Godot, por exemplo). É o que a IA chamada no terminal lê para saber onde fazer a jogabilidade. Clique para mudar.', onclick: setCodePath },
        g.code_path ? `código do jogo: ${g.code_path}` : 'dizer onde está o código do jogo',
      ),
    );
  }
}

async function renameCurrent() {
  const i = currentItem();
  const a = currentProject();
  const g = currentGame();
  const [what, open, path] = i ? [`do ${itemWord(i)}`, i, `/api/items/${i.id}`] : a ? [roleOf(a) === 'modelo' ? 'do asset' : 'do personagem', a, `/api/assets/${a.id}`] : g ? ['do jogo', g, `/api/games/${g.id}`] : [];
  if (!open) return;
  const name = prompt(`Nome ${what}:`, open.name);
  if (!name || name.trim() === open.name) return;
  if (await guard(() => send('PATCH', path, { name: name.trim() }))) refresh();
}

async function setCodePath() {
  const g = currentGame();
  if (!g) return;
  const path = prompt(`Em que pasta está o código de ${g.name}? (a pasta do projeto na Godot, por exemplo)\nA IA chamada no terminal lê isto para saber onde fazer a jogabilidade. Vazio tira a pasta.`, g.code_path || '');
  if (path === null || path.trim() === (g.code_path || '')) return;
  if (await guard(() => send('PATCH', `/api/games/${g.id}`, { code_path: path.trim() }))) refresh();
}

// --- Tela de projetos: os jogos --------------------------------------------------------------------

const newCard = (label, title, onclick) =>
  h('button', { class: 'picker-card new', title, onclick }, h('div', { class: 'avatar plus', 'aria-hidden': 'true' }, '+'), h('div', { class: 'picker-name' }, label));

function renderHome() {
  const rows = state.data.games.map((g) => ({ g, characters: charactersOf(g.id).length, assets: modelsOf(g.id).length + filesOf(g.id).length }));
  if (!changed('home', [state.legacy, rows.map((r) => [r.g.id, r.g.name, r.characters, r.assets])])) return;
  fill($('#home-games'), ...rows.map(({ g, characters, assets }) =>
      h(
        'div',
        { class: 'picker-slot' },
        h(
          'button',
          { class: 'picker-card', title: `Abrir o jogo ${g.name}`, onclick: () => openGame(g.id) },
          h('div', { class: 'avatar letter', 'aria-hidden': 'true' }, (g.name[0] || '?').toUpperCase()),
          h('div', { class: 'picker-name' }, g.name),
          h('div', { class: 'item-chips' }, chip(characters ? 'ok' : '', plural(characters, 'personagem', 'personagens')), chip(assets ? 'ok' : '', plural(assets, 'asset', 'assets'))),
        ),
        h('button', { class: 'picker-delete', title: `Excluir o jogo ${g.name}`, 'aria-label': `Excluir o jogo ${g.name}`, onclick: () => deleteGame(g) }, '×'),
      ),
    ),
    state.legacy
      ? h('p', { class: 'notice' }, 'A ponte mudou: agora cada projeto é um jogo, com os personagens e os assets dentro. A tela nova liga quando a ponte for reiniciada (feche e abra a ponte). Até lá os personagens estão aqui embaixo, e o terminal ao lado continua funcionando.')
      : newCard('Novo jogo', 'Cria um jogo: dentro dele ficam os personagens, os assets e o terminal na pasta dele.', createGame),
  );
}

async function createGame() {
  const name = prompt('Nome do jogo:');
  if (!name?.trim()) return;
  const created = await guard(() => send('POST', '/api/games', { name: name.trim() }));
  if (!created) return;
  await refresh();
  openGame(created.id);
}

async function deleteGame(g) {
  const projects = charactersOf(g.id).length + modelsOf(g.id).length;
  const files = filesOf(g.id).length;
  const papers = docsOf(g.id).length + tasksOf(g.id).length;
  const lines = [
    projects ? `${plural(projects, 'personagem ou modelo 3D dele não é apagado: fica', 'personagens e modelos 3D dele não são apagados: ficam')} sem jogo, nesta tela.` : null,
    files ? `${plural(files, 'textura ou som dele sai', 'texturas e sons dele saem')} do disco.` : null,
    papers ? 'As tarefas e os documentos da gestão dele também saem do disco.' : null,
    'O terminal do jogo é fechado, com o que estiver rodando nele. Não tem volta.',
  ].filter(Boolean);
  if (!confirm(`Excluir o jogo ${g.name}?\n${lines.join('\n')}`)) return;
  if (await guard(() => api(`/api/games/${g.id}`, { method: 'DELETE' }))) {
    toast(`Jogo ${g.name} excluído.`, 'ok');
    refresh();
  }
}

// Um personagem ou um modelo 3D, como cartão: na tela do jogo e, sem jogo, na de projetos.
function projectCard(a) {
  const model = roleOf(a) === 'modelo';
  const count = animsOf(a.id).length;
  const what = model ? 'o asset' : 'o personagem';
  return [
    h(
      'button',
      { class: 'picker-card', title: `Abrir ${what} ${a.name}`, onclick: () => openProject(a.id) },
      h('div', { class: `avatar ${model ? 'shape' : 'letter'}`, 'aria-hidden': 'true' }, model ? '◆' : (a.name[0] || '?').toUpperCase()),
      h('div', { class: 'picker-name' }, a.name),
      h(
        'div',
        { class: 'item-chips' },
        model ? chip('', 'modelo 3D') : null,
        trouble(a) ? chip('bad', trouble(a)) : null,
        !a.verdict && a.status !== 'erro' ? chip('info', 'lendo o arquivo…') : null,
        model ? a.summary?.triangles && chip('', `${num(a.summary.triangles)} triângulos`) : chip(count ? 'ok' : '', plural(count, 'animação', 'animações')),
        jobsOf(a.id).length ? chip('info', 'trabalhando…') : null,
      ),
    ),
    // Um projeto cabe nas abas de personagens e nas de assets: a aba para onde ele vai diz o que ele é.
    gameOf(a) && moveTool(a.name, projectTab(a), tabsOf(game(a.game)).filter((t) => t.kind !== 'gestao'), (tab) => moveProjectTo(a, tab)),
    h('button', { class: 'picker-delete', title: `Excluir ${what} ${a.name}`, 'aria-label': `Excluir ${what} ${a.name}`, onclick: () => deleteProject(a) }, '×'),
  ];
}
const projectKey = (a) => [a.id, a.name, a.verdict, a.status, a.role, a.game, a.tab, a.summary?.triangles, animsOf(a.id).length, jobsOf(a.id).length];

// O botão ⇄ de um cartão: passa a coisa para outra aba em que ela cabe. Com um destino só (as duas
// abas que vêm com o jogo), um clique passa; com mais, abre a lista das abas.
function moveTool(name, here, fits, move) {
  const others = fits.filter((t) => t.id !== here?.id);
  if (!others.length) return null;
  const only = others.length === 1 ? others[0] : null;
  const label = only ? `Passar ${name} para ${only.name}` : `Passar ${name} para outra aba`;
  return h(
    'button',
    { class: 'picker-tool', title: label, 'aria-label': label, 'aria-haspopup': only ? null : 'menu', onclick: (e) => (only ? move(only) : openMenu(e.currentTarget, others.map((t) => ({ label: t.name, hint: TAB_KINDS[t.kind].label, onclick: () => move(t) })))) },
    '⇄',
  );
}

// Uma lista de escolhas, aberta embaixo do botão que a chamou. Fecha na escolha, no clique fora e no Esc.
let closeMenu = () => {};
function openMenu(anchor, entries) {
  closeMenu();
  const box = h('div', { class: 'menu', role: 'menu' }, entries.map((entry) => h('button', { type: 'button', class: 'menu-item', role: 'menuitem', onclick: () => { closeMenu(); entry.onclick(); } }, entry.label, entry.hint && h('span', { class: 'count' }, entry.hint))));
  const away = (e) => {
    if (e.type === 'keydown' ? e.key === 'Escape' : !box.contains(e.target)) closeMenu();
  };
  closeMenu = () => {
    box.remove();
    document.removeEventListener('pointerdown', away, true);
    document.removeEventListener('keydown', away, true);
    closeMenu = () => {};
  };
  document.body.append(box);
  const at = anchor.getBoundingClientRect();
  box.style.left = `${Math.max(8, Math.min(at.left, window.innerWidth - box.offsetWidth - 8))}px`;
  box.style.top = `${Math.min(at.bottom + 4, window.innerHeight - box.offsetHeight - 8)}px`;
  document.addEventListener('pointerdown', away, true);
  document.addEventListener('keydown', away, true);
  box.querySelector('button')?.focus();
}

// Uma caixa por cima da tela, para o que pede mais de uma resposta (aba nova, tarefa). `build`
// recebe a função que fecha e devolve o que vai dentro. O Esc e o clique fora também fecham.
function openDialog(label, build, size = '') {
  const back = $('#dialog');
  const onKey = (e) => {
    if (e.key === 'Escape') close();
  };
  function close() {
    back.hidden = true;
    back.replaceChildren();
    document.removeEventListener('keydown', onKey, true);
  }
  fill(back, h('div', { class: `engine-box dialog-box ${size}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': label }, ...build(close)));
  back.onpointerdown = (e) => {
    if (e.target === back) close();
  };
  back.hidden = false;
  document.addEventListener('keydown', onKey, true);
  back.querySelector('input, textarea')?.focus();
  return close;
}

// Quem ainda não está em nenhum jogo: o que veio de antes dos jogos, ou o que o Meshy acabou de criar.
function renderLoose() {
  const rows = state.data.assets.filter((a) => !gameOf(a)).sort(byName);
  const games = state.data.games;
  if (!changed('loose', [state.legacy, rows.map(projectKey), games.map((g) => [g.id, g.name])])) return;
  $('#loose-head').hidden = !rows.length;
  $('#loose-title').textContent = state.legacy ? 'Personagens' : 'Sem jogo';
  $('#loose-hint').textContent = state.legacy ? '' : games.length ? 'Personagens e modelos que ainda não estão em nenhum jogo. Escolha o jogo de cada um.' : 'Personagens e modelos que ainda não estão em nenhum jogo. Crie um jogo, acima, e escolha aqui o de cada um.';
  fill($('#home-loose'), ...rows.map((a) =>
      h(
        'div',
        { class: 'picker-slot stacked' },
        ...projectCard(a),
        games.length
          ? h(
              'select',
              { class: 'pick-game', 'aria-label': `Pôr ${a.name} num jogo`, onchange: (e) => assignGame(a, e.target.value) },
              h('option', { value: '', selected: true, disabled: true }, 'pôr no jogo…'),
              ...games.map((g) => h('option', { value: g.id }, g.name)),
            )
          : null,
      ),
    ),
  );
}

async function assignGame(a, gameId) {
  if (!gameId) return;
  if (await guard(() => send('PATCH', `/api/assets/${a.id}`, { game: gameId }))) {
    toast(`${a.name} entrou em ${game(gameId)?.name}.`, 'ok');
    refresh();
  }
}

// --- Tela do jogo: as abas -----------------------------------------------------------------------------
// Uma barra de abas no alto e, embaixo, o que há na aba escolhida: os personagens, os assets ou, numa
// aba de gestão, o quadro de tarefas e os documentos. Characters e Assets vêm com o jogo; "+ Nova aba"
// cria as outras.

const SHOWN_RE = /\.(png|jpe?g|webp|bmp|gif)$/i; // as texturas que o navegador sabe mostrar
const extension = (file) => (file.split('.').pop() || '').toUpperCase();

function itemCard(i) {
  const texture = i.kind === 'textura';
  const fits = tabsOf(game(i.game)).filter((t) => t.kind === (isDoc(i) ? 'gestao' : 'assets'));
  return h(
    'div',
    { class: 'picker-slot' },
    h(
      'button',
      { class: 'picker-card', title: `Abrir ${i.name}`, onclick: () => openItem(i.id) },
      texture && SHOWN_RE.test(i.file) ? h('img', { class: 'avatar thumb', alt: '', loading: 'lazy', src: fileUrl(i) }) : h('div', { class: 'avatar shape', 'aria-hidden': 'true' }, i.kind === 'som' ? '♪' : extension(i.file)),
      h('div', { class: 'picker-name' }, i.name),
      h('div', { class: 'item-chips' }, chip('', KIND[i.kind]), chip('', bytes(i.size_bytes))),
    ),
    moveTool(i.name, itemTab(i), fits, (tab) => moveItemTo(i, tab)),
    h('button', { class: 'picker-delete', title: `Excluir o ${itemWord(i)} ${i.name}`, 'aria-label': `Excluir o ${itemWord(i)} ${i.name}`, onclick: () => deleteItem(i) }, '×'),
  );
}

function renderGame() {
  const g = currentGame();
  if (!g) return;
  const tabs = tabsOf(g);
  const tab = currentTab();
  const characters = charactersOf(g.id).sort(byName);
  const models = modelsOf(g.id).sort(byName);
  const files = filesOf(g.id).sort((x, y) => (x.kind === y.kind ? byName(x, y) : x.kind === 'textura' ? -1 : 1));
  const docs = docsOf(g.id).sort(byName);
  const tasks = tasksOf(g.id);
  const inside = (things, tabOf, t = tab) => things.filter((thing) => tabOf(thing)?.id === t.id);
  // O número ao lado do nome da aba: quantos personagens, quantos assets, quantas tarefas por fazer.
  const count = (t) => (t.kind === 'personagens' ? inside(characters, projectTab, t).length : t.kind === 'assets' ? inside(models, projectTab, t).length + inside(files, itemTab, t).length : inside(tasks, taskTab, t).filter((task) => task.status !== 'feito').length);
  const key = [g.id, hasTabs(g), tab.id, tabs.map((t) => [t.id, t.name, t.kind, count(t)]), characters.map(projectKey), models.map(projectKey), [...files, ...docs].map((i) => [i.id, i.name, i.file, i.size_bytes, i.tab]), tasks.map((t) => [t.id, t.title, t.status, t.notes, t.tab])];
  if (!changed('game', key)) return;
  fill($('#game-tabs'), ...tabs.map((t) =>
      h(
        'button',
        { type: 'button', class: 'tab', role: 'tab', 'aria-selected': t.id === tab.id ? 'true' : 'false', 'data-tab': t.id, title: `Aba de ${TAB_KINDS[t.kind].label.toLowerCase()}. Dois cliques mudam o nome.`, onclick: () => selectTab(t.id), ondblclick: () => renameTab(t) },
        t.name,
        h('span', { class: 'count' }, count(t) || ''),
      ),
    ),
    h('button', { type: 'button', class: 'tab new', id: 'tab-new', title: 'Cria uma aba no jogo: de personagens, de assets ou de gestão (tarefas e documentos).', onclick: newTab }, '+ Nova aba'),
  );
  $('#tab-hint').textContent = TAB_KINDS[tab.kind].hint;
  fill($('#tab-tools'), h('button', { type: 'button', class: 'btn link small', id: 'tab-rename', title: 'Muda o nome desta aba.', onclick: () => renameTab(tab) }, 'mudar o nome'),
    !isBuiltin(tab) && h('button', { type: 'button', class: 'btn link small', id: 'tab-delete', title: 'Apaga esta aba.', onclick: () => deleteTab(tab) }, 'apagar a aba'),
  );
  const board = tab.kind === 'gestao';
  $('#tab-cards').hidden = board;
  $('#tab-gestao').hidden = !board;
  if (board) {
    renderBoard(inside(tasks, taskTab));
    const mine = inside(docs, itemTab);
    $('#doc-count').textContent = mine.length || '';
    fill($('#tab-docs'), ...mine.map(itemCard), newCard('Novo documento', 'Cria um documento em branco nesta aba: ideias, regras, roteiro de missão. Você escreve na tela, ou a IA chamada no terminal dele escreve. Também vale arrastar um arquivo .md ou .txt para a janela.', createDocument));
  } else if (tab.kind === 'personagens') {
    fill($('#tab-cards'), ...inside(characters, projectTab).map((a) => h('div', { class: 'picker-slot' }, ...projectCard(a))),
      newCard('Novo personagem', 'Envie um personagem: FBX, GLB, BLEND, OBJ, ou um ZIP com o modelo e as texturas. Também vale arrastar os arquivos para a janela.', () => $('#file-input').click()),
    );
  } else {
    fill($('#tab-cards'), ...inside(models, projectTab).map((a) => h('div', { class: 'picker-slot' }, ...projectCard(a))),
      ...inside(files, itemTab).map(itemCard),
      newCard('Novo asset', 'Envie um modelo 3D (FBX, GLB, BLEND, OBJ ou ZIP, com as texturas dele), uma textura ou um som. Também vale arrastar os arquivos para a janela.', () => $('#asset-input').click()),
    );
  }
}

// Criar, mudar o nome e apagar aba. O servidor de antes das abas não sabe fazer isso: espera o reinício.
const TABS_WAIT = 'As abas novas ligam quando a ponte for reiniciada: feche e abra a ponte.';

function newTab() {
  const g = currentGame();
  if (!g) return;
  if (!hasTabs(g)) return toast(TABS_WAIT, 'erro');
  openDialog('Nova aba', (close) => {
    const name = h('input', { type: 'text', class: 'field', id: 'tab-name', maxLength: 40, placeholder: 'Nome da aba (em branco, fica o nome do tipo)', 'aria-label': 'Nome da aba' });
    const create = async (kind) => {
      const created = await guard(() => send('POST', `/api/games/${g.id}/tabs`, { name: name.value.trim() || TAB_KINDS[kind].label, kind }));
      if (!created) return;
      close();
      g.tabs.push(created);
      state.tab = created.id;
      writeHash(true);
      applied();
    };
    return [
      h('h2', {}, 'Nova aba'),
      h('p', { class: 'hint' }, 'Dê um nome e escolha o que a aba guarda. O nome dá para mudar depois; o tipo, não.'),
      name,
      h('div', { class: 'engine-options' }, Object.entries(TAB_KINDS).map(([kind, about]) => h('button', { type: 'button', class: 'engine-option', 'data-kind': kind, onclick: () => create(kind) }, h('strong', {}, about.label), h('span', {}, about.about)))),
      h('div', { class: 'engine-foot' }, h('button', { type: 'button', class: 'btn small', onclick: close }, 'Cancelar')),
    ];
  });
}

async function renameTab(tab) {
  const g = currentGame();
  if (!hasTabs(g)) return toast(TABS_WAIT, 'erro');
  const name = prompt('Nome da aba:', tab.name);
  if (!name?.trim() || name.trim() === tab.name) return;
  const renamed = await guard(() => send('PATCH', `/api/games/${g.id}/tabs/${tab.id}`, { name: name.trim() }));
  if (!renamed) return;
  g.tabs = g.tabs.map((t) => (t.id === renamed.id ? renamed : t));
  applied();
}

async function deleteTab(tab) {
  const g = currentGame();
  const home = tabsOf(g).find((t) => t.kind === tab.kind && isBuiltin(t));
  const projects = [...charactersOf(g.id), ...modelsOf(g.id)].filter((a) => projectTab(a).id === tab.id).length + filesOf(g.id).filter((i) => itemTab(i)?.id === tab.id).length;
  const tasks = tasksOf(g.id).filter((t) => taskTab(t)?.id === tab.id).length;
  const docs = docsOf(g.id).filter((i) => itemTab(i)?.id === tab.id).length;
  const what = tab.kind === 'gestao'
    ? tasks + docs ? `${[tasks ? plural(tasks, 'tarefa', 'tarefas') : null, docs ? plural(docs, 'documento', 'documentos') : null].filter(Boolean).join(' e ')} dela ${tasks + docs === 1 ? 'sai' : 'saem'} do disco. Não tem volta.` : 'Ela está vazia.'
    : projects ? `O que está nela não é apagado: volta para a aba ${home.name}.` : 'Ela está vazia.';
  if (!confirm(`Apagar a aba ${tab.name}?\n${what}`)) return;
  if (!(await guard(() => api(`/api/games/${g.id}/tabs/${tab.id}`, { method: 'DELETE' })))) return;
  // De uma aba de gestão, as tarefas e os documentos saem junto; o resto volta sozinho para a aba que vem com o jogo.
  state.data.tasks = state.data.tasks.filter((t) => t.game !== g.id || taskTab(t)?.id !== tab.id);
  state.data.items = state.data.items.filter((i) => i.game !== g.id || !isDoc(i) || itemTab(i)?.id !== tab.id);
  g.tabs = g.tabs.filter((t) => t.id !== tab.id);
  toast(`Aba ${tab.name} apagada.`, 'ok');
  writeHash();
  applied();
}

// --- A aba de gestão: o quadro de tarefas e os documentos ------------------------------------------------
// As tarefas ficam em três colunas. Um cartão muda de coluna pelas setas dele ou arrastado; um clique
// abre a tarefa, para mudar o título e o detalhe. A IA chamada no terminal do jogo lê e atualiza o
// mesmo quadro (`ponte game task ...`): o que ela muda aparece aqui em 2 segundos.

const TASK_STATES = [['a_fazer', 'A fazer', 'Nada por fazer.'], ['fazendo', 'Fazendo', 'Nada em andamento.'], ['feito', 'Feito', 'Nada feito ainda.']];
const columnOf = (task) => Math.max(0, TASK_STATES.findIndex(([status]) => status === task.status));

function renderBoard(tasks) {
  fill($('#board'), ...TASK_STATES.map(([status, label, empty], column) => {
      const mine = tasks.filter((t) => columnOf(t) === column);
      return h(
        'section',
        {
          class: 'board-column',
          'data-status': status,
          'aria-label': label,
          ondragover: (e) => {
            if (!e.dataTransfer.types.includes('application/x-ponte-tarefa')) return;
            e.preventDefault();
            e.currentTarget.classList.add('over');
          },
          ondragleave: (e) => e.currentTarget.classList.remove('over'),
          ondrop: (e) => {
            e.preventDefault();
            e.currentTarget.classList.remove('over');
            const dropped = tasks.find((t) => t.id === e.dataTransfer.getData('application/x-ponte-tarefa'));
            if (dropped && columnOf(dropped) !== column) moveTask(dropped, status);
          },
        },
        h('h3', {}, label, h('span', { class: 'count' }, mine.length || '')),
        ...mine.map((t) => taskCard(t, column)),
        !mine.length && h('p', { class: 'empty' }, empty),
      );
    }),
  );
}

function taskCard(task, column) {
  const to = (step) => TASK_STATES[column + step];
  const arrow = (step, sign) => to(step) && h('button', { type: 'button', class: 'task-tool', title: `Passar para ${to(step)[1]}`, 'aria-label': `Passar ${task.title} para ${to(step)[1]}`, onclick: () => moveTask(task, to(step)[0]) }, sign);
  return h(
    'article',
    { class: 'task', draggable: true, 'data-task': task.id, ondragstart: (e) => { e.dataTransfer.setData('application/x-ponte-tarefa', task.id); e.dataTransfer.effectAllowed = 'move'; } },
    // Não é um <button>: em alguns navegadores não dá para arrastar o cartão segurando por um botão.
    h('div', { class: 'task-body', role: 'button', tabIndex: 0, title: 'Clique para abrir a tarefa: o título, o detalhe e a coluna. Arraste para mudar de coluna.', onclick: () => editTask(task), onkeydown: (e) => e.key === 'Enter' && editTask(task) }, h('span', { class: 'task-title' }, task.title), task.notes && h('span', { class: 'task-notes' }, task.notes)),
    h('div', { class: 'task-tools' }, arrow(-1, '‹'), arrow(1, '›'), h('button', { type: 'button', class: 'task-tool delete', title: 'Apagar a tarefa', 'aria-label': `Apagar a tarefa ${task.title}`, onclick: () => deleteTask(task) }, '×')),
  );
}

async function createTask(e) {
  e.preventDefault();
  const g = currentGame();
  const tab = currentTab();
  const title = $('#task-title').value.trim();
  if (!g || tab.kind !== 'gestao' || !title) return;
  $('#task-title').value = '';
  const created = await guard(() => send('POST', `/api/games/${g.id}/tasks`, { title, tab: tab.id }));
  if (created) putTask(created);
  else if (!$('#task-title').value) $('#task-title').value = title; // não entrou: o que foi escrito volta ao campo
}
$('#task-new').addEventListener('submit', createTask);

// A tarefa como o servidor a devolveu entra no quadro na hora. Quem mudou de coluna vai para o fim dela.
function putTask(task, moved = false) {
  const at = state.data.tasks.findIndex((t) => t.id === task.id);
  if (at < 0 || moved) state.data.tasks = [...state.data.tasks.filter((t) => t.id !== task.id), task];
  else state.data.tasks[at] = task;
  applied();
}

async function moveTask(task, status) {
  const moved = await guard(() => send('PATCH', `/api/tasks/${task.id}`, { status }));
  if (moved) putTask(moved, true);
}

async function deleteTask(task) {
  if (!confirm(`Apagar a tarefa "${task.title}"?`)) return false;
  if (!(await guard(() => api(`/api/tasks/${task.id}`, { method: 'DELETE' })))) return false;
  state.data.tasks = state.data.tasks.filter((t) => t.id !== task.id);
  applied();
  return true;
}

function editTask(task) {
  const boards = tabsOf(game(task.game)).filter((t) => t.kind === 'gestao');
  const here = taskTab(task)?.id;
  openDialog('Tarefa', (close) => {
    const title = h('input', { type: 'text', class: 'field', id: 'task-edit-title', maxLength: 200, value: task.title });
    const notes = h('textarea', { class: 'field', id: 'task-edit-notes', rows: 6, maxLength: 4000, placeholder: 'O que é, o que falta, onde está (opcional).', value: task.notes || '' });
    const status = h('select', { class: 'field', id: 'task-edit-status' }, TASK_STATES.map(([value, label], column) => h('option', { value, selected: column === columnOf(task) }, label)));
    const where = boards.length > 1 ? h('select', { class: 'field', id: 'task-edit-tab' }, boards.map((t) => h('option', { value: t.id, selected: t.id === here }, t.name))) : null;
    const save = async (e) => {
      e.preventDefault();
      if (!title.value.trim()) return title.focus();
      const body = { title: title.value.trim(), notes: notes.value, status: status.value };
      if (where && where.value !== here) body.tab = where.value;
      const saved = await guard(() => send('PATCH', `/api/tasks/${task.id}`, body));
      if (!saved) return;
      close();
      putTask(saved, saved.status !== task.status);
    };
    return [
      h('h2', {}, 'Tarefa'),
      h(
        'form',
        { class: 'dialog-form', onsubmit: save },
        h('label', {}, 'Título', title),
        h('label', {}, 'Detalhe', notes),
        h('div', { class: 'dialog-row' }, h('label', {}, 'Coluna', status), where && h('label', {}, 'Aba', where)),
        h(
          'div',
          { class: 'engine-foot' },
          h('button', { type: 'button', class: 'btn small danger', onclick: async () => (await deleteTask(task)) && close() }, 'Apagar'),
          h('button', { type: 'button', class: 'btn small', onclick: close }, 'Cancelar'),
          h('button', { type: 'submit', class: 'btn small ok' }, 'Salvar'),
        ),
      ),
    ];
  }, 'narrow');
}

async function createDocument() {
  const g = currentGame();
  const tab = currentTab();
  if (!g || tab.kind !== 'gestao') return;
  const name = prompt('Nome do documento:');
  if (!name?.trim()) return;
  const created = await guard(() => send('POST', `/api/games/${g.id}/documents`, { name: name.trim(), tab: tab.id }));
  if (!created) return;
  state.data.items.unshift(created);
  dataEpoch += 1;
  openItem(created.id);
  refresh();
}

async function deleteProject(a) {
  const model = roleOf(a) === 'modelo';
  const count = animsOf(a.id).length;
  const what = model ? 'O modelo é apagado' : count ? `O personagem e ${count === 1 ? 'a animação dele' : `as ${count} animações dele`} são apagados` : 'O personagem é apagado';
  if (!confirm(`Excluir ${model ? 'o asset' : 'o personagem'} ${a.name}?\n${what} do disco. Não tem volta.`)) return;
  if (await guard(() => api(`/api/asset/${a.id}`, { method: 'DELETE' }))) {
    toast(`${a.name} excluído.`, 'ok');
    refresh();
  }
}

async function deleteItem(i) {
  if (!confirm(`Excluir o ${itemWord(i)} ${i.name}?\nO arquivo (${i.file}) sai do disco. Não tem volta.`)) return;
  if (state.item === i.id) doc.editing = false; // apagar o documento aberto não pergunta do texto por salvar
  if (await guard(() => api(`/api/items/${i.id}`, { method: 'DELETE' }))) {
    toast(`${i.name} excluído.`, 'ok');
    refresh();
  }
}

// De uma aba para outra: o arquivo e as animações ficam como estão. A aba diz o que o projeto é
// (numa de personagens, personagem; numa de assets, modelo). O servidor de antes das abas só
// entende o papel, e é o que basta entre as duas abas que vêm com o jogo.
async function moveProjectTo(a, tab) {
  const role = tab.kind === 'assets' ? 'modelo' : 'personagem';
  if (!(await guard(() => send('PATCH', `/api/assets/${a.id}`, { role, tab: tab.id })))) return;
  Object.assign(a, { role, tab: tab.id });
  toast(`${a.name} passou para ${tab.name}.`, 'ok');
  applied();
}

// O modelo aberto é um personagem: passa para a aba de personagens que vem com o jogo.
const moveProject = (a) => moveProjectTo(a, tabsOf(game(a.game)).find((t) => t.kind === 'personagens'));

async function moveItemTo(i, tab) {
  if (!(await guard(() => send('PATCH', `/api/items/${i.id}`, { tab: tab.id })))) return;
  i.tab = tab.id;
  toast(`${i.name} passou para ${tab.name}.`, 'ok');
  applied();
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
  if (!resume && !confirm(`Aprovar a imagem de ${request.name} e gerar o modelo 3D?\nGasta créditos do Meshy e leva alguns minutos. Pronto, o personagem aparece aqui, sem jogo, para você dizer de qual é.`)) return;
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

// O que está sendo feito agora, na tela de projetos e na do jogo (ler um arquivo enviado, o Meshy gerando).
function renderActivity() {
  const where = screen();
  if (where !== 'entrada' && where !== 'jogo') return;
  // Na tela do jogo, só o que é dele e o que não é de projeto nenhum: nada de outro jogo aparece ali.
  const here = (j) => where === 'entrada' || !asset(j.params?.asset_id) || asset(j.params.asset_id).game === state.game;
  const busy = state.data.jobs.filter((j) => ACTIVE.includes(j.status) && here(j));
  if (!changed('activity', [where, busy.map((j) => [j.id, j.status, j.progress])])) return;
  fill($(where === 'jogo' ? '#game-activity' : '#home-activity'), ...busy.map(jobRow));
}

const jobRow = (job) =>
  h('div', { class: 'job' }, h('div', { class: 'job-title' }, h('span', { class: 'spinner' }), job.title), h('div', { class: 'job-progress' }, job.progress || ''));

// --- Animações do personagem ------------------------------------------------------------------------

const ORIGIN = { mixamo: 'Mixamo', blender: 'Blender', captura: 'captura', importado: 'importada' };

function renderAnimations() {
  const a = currentProject();
  if (!a) return;
  // Em ordem pelo nome, as soltas e as de cada pasta (pedido dele em 13/10/2026: "organize as animações de acordo com os nomes").
  const anims = animsOf(a.id).sort((x, y) => animName(x).localeCompare(animName(y), 'pt-BR', { numeric: true, sensitivity: 'base' }));
  const busy = jobsOf(a.id);
  if (state.anim && !anims.some((r) => r.id === state.anim)) state.anim = null; // a que estava aberta foi apagada
  // As pastas: cada animação aprovada está numa, com o nome do modo do jogo; o resto fica solto.
  const folders = new Map();
  const loose = [];
  for (const r of anims) {
    const name = folderOf(r);
    if (name) folders.set(name, [...(folders.get(name) || []), r]);
    else loose.push(r);
  }
  const names = [...folders.keys()].sort((x, y) => x.localeCompare(y, 'pt-BR'));
  if (!changed('anims', [a.id, a.verdict, state.anim, anims.map((r) => [r.id, animName(r), r.stats?.duration_s, motionOf(r)?.source, r.review?.status, r.review?.notes]), names.map((n) => openFolders.has(folderKey(n))), busy.map((j) => [j.id, j.status, j.progress])])) return;
  $('#anim-count').textContent = anims.length ? anims.length : '';
  $('#mixamo-button').disabled = a.verdict !== 'pronto';
  $('#sim-link').hidden = !anims.length; // o simulador precisa de pelo menos uma animação
  $('#sim-link').href = `simulador.html#${a.id}`;
  fill($('#anim-list'), h(
      'button',
      { class: 'anim', 'aria-current': state.anim === null ? 'true' : null, onclick: () => selectAnimation(null) },
      h('span', { class: 'anim-icon' }, '◼'),
      h('span', { class: 'anim-name' }, 'Modelo parado'),
      h('span', { class: 'anim-meta' }, 'sem animação'),
    ),
    ...names.flatMap((name) => {
      const members = folders.get(name);
      const open = openFolders.has(folderKey(name));
      return [
        h(
          'button',
          { class: 'anim folder', 'aria-expanded': open ? 'true' : 'false', onclick: () => toggleFolder(name), ondblclick: () => renameFolder(name, members), title: 'Pasta das aprovadas deste modo do jogo. Clique para abrir ou fechar; dois cliques mudam o nome.' },
          h('span', { class: 'anim-icon' }, open ? '▾' : '▸'),
          h('span', { class: 'anim-name' }, name),
          h('span', { class: 'anim-meta' }, `${members.length} ${members.length === 1 ? 'animação' : 'animações'}`),
        ),
        ...(open ? members.map((r) => animRow(r, { inFolder: true })) : []),
      ];
    }),
    ...loose.map((r) => animRow(r)),
    ...busy.map(jobRow),
    !anims.length && !busy.length
      ? h('p', { class: 'empty' }, a.verdict === 'pronto' ? 'Nenhuma animação ainda. Peça uma à IA, no terminal abaixo, ou traga uma do Mixamo.' : 'Este personagem ainda não pode receber animação.')
      : null,
  );
}

// Uma linha da lista: a animação, com o botão de aprovar (fora de pasta) ou de tirar da pasta (dentro), e o de apagar.
function animRow(r, { inFolder = false } = {}) {
  const origin = ORIGIN[motionOf(r)?.source] || 'gerada';
  return h(
    'div',
    { class: `anim-slot${inFolder ? ' in-folder' : ''}` },
    h(
      'button',
      { class: 'anim', 'aria-current': state.anim === r.id ? 'true' : null, onclick: () => selectAnimation(r.id), ondblclick: () => renameAnimation(r), title: 'Clique para ver; dois cliques mudam o nome.' },
      h('span', { class: 'anim-icon' }, '▶'),
      h('span', { class: 'anim-name' }, animName(r)),
      h('span', { class: 'anim-meta' }, `${num(r.stats?.duration_s, 1)} s · ${origin}`),
    ),
    inFolder
      ? h('button', { class: 'anim-tool anim-unapprove', title: `Tirar ${animName(r)} da pasta: volta para as que não foram aprovadas`, 'aria-label': `Tirar ${animName(r)} da pasta`, onclick: () => unapproveAnimation(r) }, '↩')
      : h('button', { class: 'anim-tool anim-approve', title: `Aprovar ${animName(r)}: entra numa pasta`, 'aria-label': `Aprovar ${animName(r)}`, onclick: () => approveAnimation(r) }, '✓'),
    h('button', { class: 'anim-delete', title: `Apagar a animação ${animName(r)}`, 'aria-label': `Apagar a animação ${animName(r)}`, onclick: () => deleteAnimation(r) }, '×'),
  );
}

// Pastas (pedido dele em 11/10/2026): a animação aprovada entra numa pasta com o nome do modo do jogo
// ("soldier patrol", "soldier patrol alert"); estar numa pasta é a aprovação. O que ele ainda não
// aprovou fica solto, fora das pastas. Por dentro é a revisão da prévia: "aprovado", com o nome da
// pasta na nota, que é o que `ponte status` e a tela anterior mostram. Nada novo no servidor.
const folderOf = (r) => (r.review?.status === 'aprovado' ? (r.review.notes || '').trim() || 'Aprovadas' : null);
const FOLDERS_KEY = 'ponte.pastas-abertas';
const openFolders = new Set(JSON.parse(localStorage.getItem(FOLDERS_KEY) || '[]'));
const folderKey = (name) => `${state.project}/${name}`;
const saveFolders = () => localStorage.setItem(FOLDERS_KEY, JSON.stringify([...openFolders]));

function toggleFolder(name) {
  const key = folderKey(name);
  if (openFolders.has(key)) openFolders.delete(key);
  else openFolders.add(key);
  saveFolders();
  renderAnimations();
}

async function approveAnimation(result) {
  const names = [...new Set(animsOf(state.project).map(folderOf).filter(Boolean))];
  const last = localStorage.getItem('ponte.ultima-pasta');
  const name = prompt(`Aprovar ${animName(result)}. Em que pasta ela entra?${names.length ? `\nPastas que já existem: ${names.join(', ')}` : ''}`, last || names[0] || '');
  if (!name?.trim()) return;
  localStorage.setItem('ponte.ultima-pasta', name.trim());
  if (await guard(() => send('POST', `/api/review/result/${result.id}`, { status: 'aprovado', notes: name.trim() }))) {
    openFolders.add(folderKey(name.trim()));
    saveFolders();
    refresh();
  }
}

async function unapproveAnimation(result) {
  if (await guard(() => send('POST', `/api/review/result/${result.id}`, { status: 'pendente', notes: '' }))) refresh();
}

async function renameFolder(name, members) {
  const next = prompt('Nome da pasta:', name);
  if (!next?.trim() || next.trim() === name) return;
  const ok = await guard(async () => {
    for (const r of members) await send('POST', `/api/review/result/${r.id}`, { status: 'aprovado', notes: next.trim() });
    return true;
  });
  if (!ok) return;
  if (openFolders.delete(folderKey(name))) openFolders.add(folderKey(next.trim()));
  saveFolders();
  refresh();
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

// --- O asset aberto: o que ele é ------------------------------------------------------------------

function renderDetails() {
  const i = currentItem();
  const a = currentProject();
  const open = i || a;
  if (!open) return;
  const s = a?.summary || {};
  const rows = i
    ? [
        ['Arquivo', h('a', { href: fileUrl(i), download: i.file, title: 'Baixar o arquivo' }, i.file)],
        ['Tamanho', bytes(i.size_bytes)],
        isDoc(i) ? ['Gravado', i.modified ? new Date(i.modified).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '—'] : [i.kind === 'som' ? 'Duração' : 'Dimensões', state.media[i.id] || '—'],
      ]
    : [
        ['Arquivo', a.filename || '—'],
        ['Triângulos', num(s.triangles)],
        ['Altura', s.height_m ? `${num(s.height_m, 2)} m` : '—'],
        ['Texturas', num(s.textures)],
        ['Esqueleto', s.rig ? `${s.rig} (${s.bones} ossos)` : 'não tem'],
      ];
  if (!changed('details', [open.id, rows.map(([label, value]) => [label, value?.textContent ?? value])])) return;
  $('#details-title').textContent = isDoc(i) ? 'Documento' : 'Asset';
  $('#details-kind').textContent = isDoc(i) ? '' : i ? KIND[i.kind] : 'modelo 3D';
  $('#details-move').hidden = !a || !!i || !gameOf(a);
  fill($('#details'), rows.flatMap(([label, value]) => [h('dt', {}, label), h('dd', {}, value)]));
}

function deleteOpenAsset() {
  if (currentItem()) deleteItem(currentItem());
  else if (currentProject()) deleteProject(currentProject());
}

$('#details-delete').addEventListener('click', deleteOpenAsset);
$('#details-move').addEventListener('click', () => currentProject() && moveProject(currentProject()));

// --- Visor --------------------------------------------------------------------------------------

function viewerSource() {
  const i = currentItem();
  if (i) return { key: `i:${i.id}:${i.created_at}`, flat: i.kind, url: `${fileUrl(i)}?v=${encodeURIComponent(i.created_at)}`, file: i.file, title: i.name };
  const a = currentProject();
  if (!a) return null;
  const result = state.anim && animsOf(a.id).find((r) => r.id === state.anim);
  if (result?.files?.glb) {
    return { key: `r:${result.id}:${result.created_at}`, url: `${result.files_base}/${result.files.glb}?v=${encodeURIComponent(result.created_at)}`, title: animName(result), project: a.id };
  }
  if (a.preview) {
    return { key: `a:${a.id}:${a.inspected_at}`, url: `${a.files_base}/${a.preview}?v=${encodeURIComponent(a.inspected_at || '')}`, title: 'Modelo parado', project: a.id };
  }
  return { key: `vazio:${a.id}:${a.status}`, url: null, title: '', project: a.id, empty: a.status === 'erro' ? `Não consegui abrir o arquivo deste ${roleOf(a) === 'modelo' ? 'modelo' : 'personagem'}: ${a.error || 'erro'}` : 'Lendo o arquivo…' };
}

// Textura, som e documento não vão para o visor 3D: a imagem, o tocador e a página aparecem por cima dele.
function showFlat(source) {
  const kind = source?.flat || null;
  const image = $('#stage-image');
  const audio = $('#stage-audio');
  const shown = kind === 'textura' && SHOWN_RE.test(source.file);
  $('#project').classList.toggle('flat', !!kind);
  $('#project').classList.toggle('doc', kind === 'documento');
  $('#stage-doc').hidden = kind !== 'documento';
  image.hidden = !shown;
  if (shown) image.src = source.url;
  else image.removeAttribute('src');
  audio.hidden = kind !== 'som';
  if (kind === 'som') audio.src = source.url;
  else if (audio.hasAttribute('src')) {
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
  }
  if (kind === 'textura' && !shown) $('#viewport-empty').textContent = `O navegador não mostra arquivo ${extension(source.file)}. Ele está guardado no jogo: o link em "Arquivo", ao lado, baixa uma cópia.`;
}

// O tamanho da textura e a duração do som só se sabem com o arquivo aberto.
function learned(text) {
  if (!state.item) return;
  state.media[state.item] = text;
  renderDetails();
}
$('#stage-image').addEventListener('load', (e) => learned(`${e.target.naturalWidth} × ${e.target.naturalHeight} px`));
$('#stage-audio').addEventListener('loadedmetadata', (e) => Number.isFinite(e.target.duration) && learned(`${num(e.target.duration, 1)} s`));

// --- O documento aberto ----------------------------------------------------------------------------
// Um documento é um arquivo de texto (Markdown) do jogo. A página o mostra formatado e o relê
// sempre que ele muda no disco: é assim que o que a IA do terminal escreve aparece sozinho. "Editar"
// troca a página pelo texto, para o dono escrever; uma caixa de marcar do texto se marca com um clique.

const doc = { id: null, modified: null, text: '', editing: false, outside: false };
const docDirty = () => doc.editing && $('#doc-text').value !== doc.text;

// Sair de um documento com texto por salvar pergunta antes. Devolve se dá para sair.
function leaveDocument() {
  if (!docDirty()) return true;
  if (!confirm('O que você escreveu no documento ainda não foi salvo.\nSair assim mesmo?')) return false;
  doc.editing = false;
  return true;
}

function renderDocument() {
  const editing = doc.editing;
  $('#doc-page').hidden = editing;
  $('#doc-text').hidden = !editing;
  $('#doc-edit').hidden = editing;
  $('#doc-save').hidden = $('#doc-cancel').hidden = !editing;
  $('#doc-state').textContent = editing && doc.outside ? 'O arquivo mudou no disco enquanto você escrevia (a IA gravou?). Salvar passa por cima.' : editing ? 'Ctrl+S salva.' : '';
  if (editing) return;
  if (doc.text.trim()) fill($('#doc-page'), renderMarkdown(doc.text, { onToggle: toggleBox }));
  else fill($('#doc-page'), h('p', { class: 'empty' }, 'Documento em branco. Clique em "Editar" para escrever, ou chame a IA no terminal ao lado e peça a ela.'));
}

async function syncDocument() {
  const i = currentItem();
  if (!isDoc(i)) {
    if (doc.id) Object.assign(doc, { id: null, modified: null, text: '', editing: false, outside: false });
    return;
  }
  if (doc.id === i.id && doc.modified === i.modified) return;
  if (doc.id !== i.id) {
    Object.assign(doc, { text: '', editing: false, outside: false });
    fill($('#doc-page'));
  }
  Object.assign(doc, { id: i.id, modified: i.modified });
  const text = await guard(() => api(`${fileUrl(i)}?v=${i.modified ?? ''}`, { cache: 'no-store' }));
  if (text == null || doc.id !== i.id) return; // não leu, ou outro documento foi aberto enquanto lia
  if (doc.editing) {
    // O que ele está escrevendo não é trocado pelo que chegou do disco: fica o aviso.
    doc.outside = String(text) !== doc.text;
    return renderDocument();
  }
  doc.text = String(text);
  renderDocument();
}

async function saveDocument(text) {
  const i = currentItem();
  if (!isDoc(i)) return false;
  const saved = await guard(() => send('PUT', `/api/items/${i.id}/text`, { text }));
  if (!saved) return false;
  Object.assign(i, { modified: saved.modified, size_bytes: saved.size_bytes }); // já é o texto gravado: não precisa reler
  Object.assign(doc, { text, modified: saved.modified, editing: false, outside: false });
  renderCrumb();
  renderDetails();
  renderDocument();
  return true;
}

// Uma caixa de marcar do documento: o clique troca "[ ]" por "[x]" na linha dela e grava.
async function toggleBox(line, checked) {
  const rows = doc.text.replace(/\r\n?/g, '\n').split('\n');
  if (rows[line] === undefined) return;
  rows[line] = rows[line].replace(/\[( |x|X)\]/, checked ? '[x]' : '[ ]');
  if (!(await saveDocument(rows.join('\n')))) renderDocument(); // não gravou: a caixa volta ao que está no arquivo
}

$('#doc-edit').addEventListener('click', () => {
  Object.assign(doc, { editing: true, outside: false });
  $('#doc-text').value = doc.text;
  renderDocument();
  $('#doc-text').focus();
});
$('#doc-cancel').addEventListener('click', () => {
  if (docDirty() && !confirm('Descartar o que você escreveu?')) return;
  doc.editing = false;
  doc.modified = null; // relê o arquivo: ele pode ter mudado enquanto se escrevia
  syncDocument();
  renderDocument();
});
$('#doc-save').addEventListener('click', () => saveDocument($('#doc-text').value));
$('#doc-text').addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== 's') return;
  e.preventDefault();
  saveDocument($('#doc-text').value);
});
// Fechar ou recarregar a janela com texto por salvar: o navegador pergunta.
window.addEventListener('beforeunload', (e) => {
  if (docDirty()) e.preventDefault();
});

async function syncViewer() {
  const source = viewerSource();
  if (!source) {
    if (state.loaded) {
      viewer.clear();
      showFlat(null);
    }
    state.loaded = null;
    state.loadedProject = null;
    return;
  }
  if (source.key === state.loaded) return;
  state.loaded = source.key;
  delete document.body.dataset.visor; // "o visor já mostra": é o que tests/ui_click.mjs espera
  $('#viewport-title').textContent = source.title;
  $('#viewport-empty').textContent = source.empty || '';
  showFlat(source);
  if (source.flat) {
    viewer.clear();
    setTransport(false);
    state.loadedProject = null;
    document.body.dataset.visor = source.key;
    return;
  }
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
  if (e.code !== 'Space' || !state.project || e.target.closest('input, textarea, select, button, audio, .terminal')) return;
  e.preventDefault();
  togglePlay();
});

// --- Terminal: um por espaço (o jogo, cada personagem, cada asset) ---------------------------------
// Um terminal de verdade, parado no prompt: quem chama a IA (o claude ou outra) é o dono. Cada
// espaço tem o dele, aberto na pasta dele: o jogo, cada personagem e cada asset (pedido do dono em
// 13/10/2026: "clico dentro do assets casa vc já saiba onde está e que assets vai editar a mesma
// coisa para os personagens"). O painel é um só e mostra o de onde se está; a IA chamada ali lê o
// guia da pasta e sabe no que vai mexer. Depois que alguém escreve num terminal, ele continua vivo
// no servidor: sair dali ou recarregar só solta a tela, e ao voltar o que estava escrito
// reaparece. Sem nada escrito, o servidor o fecha pouco depois de a tela sair.
//
// A tela de projetos tem o dela, na pasta da ponte (HOME).

const HOME = '@home'; // o terminal da tela de entrada; o nome que o servidor dá a ele vem em /api/terminal
// `items`: o servidor abre terminal de textura e de som? O de antes não abria: nelas fica o do jogo.
const term = { xterm: null, fit: null, ws: null, where: null, homeId: null, muted: false, items: true };
const termTarget = () => state.project || (term.items && state.item) || state.game || HOME;

function renderTermWhere() {
  const where = termTarget();
  const a = where === HOME ? null : asset(where);
  const i = where === HOME ? null : item(where);
  $('#term-where').textContent = where === HOME ? 'na pasta da ponte'
    : a ? `na pasta do ${roleOf(a) === 'modelo' ? 'asset' : 'personagem'} ${a.name}`
    : i ? `na pasta do ${itemWord(i)} ${i.name}`
    : `na pasta do jogo ${game(where)?.name || ''}`;
}

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
  term.xterm.onData((data) => {
    if (!term.muted) sendToTerminal({ type: 'input', data });
  });
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
  term.where = null;
  term.muted = false;
  ws?.close();
}

async function openTerminal(where) {
  if (term.where === where && term.ws) return; // o mesmo terminal, já ligado: trocar de animação não o desliga
  closeTerminal();
  if (!term.xterm) createTerminal();
  term.where = where;
  term.xterm.reset();
  renderTermWhere();
  termState('abrindo…');
  const info = await guard(() => api('/api/terminal'));
  if (term.where !== where) return; // trocou de tela enquanto abria
  if (!info) return termState('sem resposta', 'bad');
  if (info.problem) {
    term.xterm.writeln(info.problem);
    return termState('indisponível', 'bad');
  }
  term.homeId = info.home || null;
  if (where !== HOME && item(where) && !info.items) {
    // O servidor no ar é de antes de textura e som terem terminal: nelas fica o do jogo.
    term.items = false;
    term.where = null;
    return openTerminal(termTarget());
  }
  if (where === HOME && !term.homeId) {
    // O servidor no ar é de antes deste terminal existir.
    term.xterm.writeln('Este terminal liga quando a ponte for reiniciada: feche e abra a ponte.');
    return termState('espera o reinício', 'warn');
  }
  const id = where === HOME ? term.homeId : where;
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/terminal/${id}?token=${encodeURIComponent(info.token)}`);
  term.ws = ws;
  ws.addEventListener('open', () => {
    termState('ligado', 'ok');
    fitTerminal();
    term.xterm.focus();
  });
  ws.addEventListener('message', (event) => {
    if (term.ws !== ws) return;
    const message = JSON.parse(event.data);
    if (message.type === 'output' && message.replay && message.answered) {
      // O que já estava escrito traz as perguntas que o programa fez ao terminal lá atrás (que tipo ele é,
      // onde está o cursor). Outra tela já as respondeu: responder de novo chegaria como texto digitado.
      term.muted = true;
      term.xterm.write(message.data, () => {
        if (term.ws === ws) term.muted = false;
      });
    } else if (message.type === 'output') term.xterm.write(message.data);
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
  const where = termTarget();
  const id = where === HOME ? term.homeId : where;
  if (!id || !confirm('Fechar este terminal e abrir um novo?\nO que estiver rodando nele (a conversa com a IA, por exemplo) é encerrado.')) return;
  closeTerminal();
  if (await guard(() => send('POST', `/api/terminal/${id}/restart`))) openTerminal(where);
}

$('#term-restart').addEventListener('click', restartTerminal);
// Terminal desligado (o servidor foi reiniciado): um clique nele liga de novo.
$('#terminal').addEventListener('pointerdown', () => {
  if (!term.ws) openTerminal(termTarget());
});

// --- Largura das duas metades ----------------------------------------------------------------------

const SIDE_KEY = 'ponte.lado';
function setSide(pixels) {
  const max = window.innerWidth - 360;
  const width = Math.round(Math.min(Math.max(pixels, 380), Math.max(max, 380)));
  $('#layout').style.setProperty('--side', `${width}px`);
  return width;
}
const saved = Number(localStorage.getItem(SIDE_KEY));
if (saved) setSide(saved);
$('#splitter').addEventListener('pointerdown', (e) => {
  const splitter = e.currentTarget;
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

// --- Envio de arquivos --------------------------------------------------------------------------------
// Dentro de um jogo, quem diz o que o arquivo é (personagem ou asset) é o botão usado, ou o lado
// da janela em que ele foi solto. Dentro de um personagem, FBX solto é animação do Mixamo e
// textura solta é textura dele.

const MODEL_RE = /\.(fbx|glb|gltf|blend|obj|zip)$/i; // o .zip traz o modelo e as texturas juntos
const SIDECAR_RE = /\.(png|jpe?g|tga|bmp|tiff?|webp|exr|dds|mtl|bin)$/i; // o que acompanha um modelo
const TEXTURE_RE = /\.(png|jpe?g|webp|bmp|gif|tga|tiff?|exr|hdr|dds|psd)$/i;
const SOUND_RE = /\.(wav|ogg|mp3|flac)$/i;
const DOC_RE = /\.(md|txt)$/i;
const asEntries = (files) => [...files].map((file) => ({ file, path: file.name }));
// A aba em que entra o que é enviado da tela do jogo: a que está aberta, se for do tipo do arquivo;
// senão (ou de dentro de um asset aberto), fica sem aba dita e vai para a que vem com o jogo.
const uploadTab = (kind) => (screen() === 'jogo' && hasTabs(currentGame()) && currentTab().kind === kind ? currentTab().id : null);
const named = (re) => (entry) => re.test(entry.file.name);

// Arquivos soltos na janela, entrando nas pastas e guardando o caminho de cada um.
// As entradas precisam ser lidas ainda dentro do evento de soltar; o resto pode esperar.
function droppedEntries(dataTransfer) {
  const roots = [...dataTransfer.items].map((entry) => entry.webkitGetAsEntry?.()).filter(Boolean);
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

// Cada modelo vira um projeto do jogo aberto, como personagem ou como asset. Devolve o id do último.
async function sendModels(models, sidecars, role) {
  let last = null;
  const tab = uploadTab(role === 'modelo' ? 'assets' : 'personagens');
  for (const model of models) {
    // Com texturas na mesma leva, a leitura do arquivo espera elas chegarem.
    const loose = sidecars.length > 0 && !/\.zip$/i.test(model.file.name);
    const query = new URLSearchParams({ filename: model.file.name });
    if (loose) query.set('defer', 'true');
    if (state.game) query.set('game', state.game);
    if (role === 'modelo') query.set('role', role);
    if (tab) query.set('tab', tab);
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
  return last;
}

function ignored(count) {
  if (count) toast(`${count} arquivo(s) ignorado(s): formato não reconhecido.`);
}

async function sendCharacters(entries) {
  const models = entries.filter(named(MODEL_RE));
  const sidecars = entries.filter(named(SIDECAR_RE));
  ignored(entries.length - models.length - sidecars.length);
  if (!models.length) return toast('Um personagem é um modelo 3D: FBX, GLB, BLEND, OBJ, ou um ZIP com o modelo e as texturas. As texturas vão junto com ele.', 'erro');
  const last = await sendModels(models, sidecars, 'personagem');
  await refresh();
  if (last) openProject(last);
}

async function sendAssets(entries) {
  if (!state.game) return toast('Este modelo ainda não está em nenhum jogo: os assets são de um jogo.', 'erro');
  const models = entries.filter(named(MODEL_RE));
  const sounds = entries.filter(named(SOUND_RE));
  // Imagem que chega junto com um modelo é textura dele; sozinha, é um asset.
  const sidecars = models.length ? entries.filter(named(SIDECAR_RE)) : [];
  const textures = entries.filter((e) => TEXTURE_RE.test(e.file.name) && !sidecars.includes(e));
  ignored(entries.length - models.length - sounds.length - sidecars.length - textures.length);
  let sent = 0;
  const tab = uploadTab('assets');
  for (const { file } of [...textures, ...sounds]) {
    const query = new URLSearchParams({ filename: file.name, ...(tab ? { tab } : {}) });
    if (await guard(() => api(`/api/games/${state.game}/items?${query}`, { method: 'POST', body: file }))) sent += 1;
  }
  if (await sendModels(models, sidecars, 'modelo')) sent += models.length;
  if (sent) toast(`${plural(sent, 'asset enviado', 'assets enviados')} para ${currentGame()?.name}.`, 'ok');
  refresh();
}

// Numa aba de gestão, o que chega é documento: um arquivo de texto (.md ou .txt).
async function sendDocuments(entries) {
  const docs = entries.filter(named(DOC_RE));
  ignored(entries.length - docs.length);
  if (!docs.length) return toast('Numa aba de gestão entram documentos de texto (.md ou .txt). Personagem e asset entram pela aba deles.', 'erro');
  let sent = 0;
  for (const { file } of docs) {
    const query = new URLSearchParams({ filename: file.name, tab: currentTab().id });
    if (await guard(() => api(`/api/games/${state.game}/items?${query}`, { method: 'POST', body: file }))) sent += 1;
  }
  if (sent) toast(`${plural(sent, 'documento enviado', 'documentos enviados')} para ${currentTab().name}.`, 'ok');
  refresh();
}

// Dentro de um personagem: o que chega é para ele.
async function sendToCharacter(entries) {
  const a = currentProject();
  const models = entries.filter(named(MODEL_RE));
  const sidecars = entries.filter(named(SIDECAR_RE));
  if (models.length && !sidecars.length && models.every((m) => /\.fbx$/i.test(m.file.name))) {
    const what = models.length === 1 ? `"${models[0].file.name}"` : `${models.length} arquivos`;
    const asMixamo = confirm(`Aplicar ${what} em ${a.name} como animação do Mixamo?\n\nOK: animação deste personagem.\nCancelar: personagem novo com o arquivo.`);
    if (asMixamo) return importMixamo(models.map((m) => m.file));
  }
  if (!models.length && sidecars.length) {
    const sent = await sendSidecars(a.id, sidecars, '');
    if (!sent) return;
    const job = await guard(() => send('POST', `/api/assets/${a.id}/inspect`));
    if (job) state.myJobs.add(job.id);
    return toast(`${sent} arquivo(s) de textura adicionado(s) a ${a.name}.`, 'ok');
  }
  return sendCharacters(entries);
}

function upload(entries, as = null) {
  const where = screen();
  if (state.legacy) return toast('A tela nova espera a ponte ser reiniciada: até lá ela não recebe arquivos.', 'erro');
  if (where === 'entrada') return toast('Abra um jogo antes: o arquivo entra como personagem ou como asset dele.', 'erro');
  if (where === 'personagem') return sendToCharacter(entries);
  if (inBoard()) return sendDocuments(entries);
  if (!as) return toast('Solte o arquivo num dos dois lados da janela: personagem ou asset.', 'erro');
  return as === 'personagem' ? sendCharacters(entries) : sendAssets(entries);
}
// Na tela do jogo, com uma aba de gestão aberta: o que se solta ali é documento, e a janela não se divide.
const inBoard = () => screen() === 'jogo' && currentTab().kind === 'gestao';

$('#mixamo-button').addEventListener('click', () => $('#mixamo-input').click());
$('#mixamo-input').addEventListener('change', (e) => {
  importMixamo([...e.target.files]);
  e.target.value = '';
});
$('#file-input').addEventListener('change', (e) => {
  upload(asEntries(e.target.files), 'personagem');
  e.target.value = '';
});
$('#asset-input').addEventListener('change', (e) => {
  upload(asEntries(e.target.files), 'asset');
  e.target.value = '';
});

let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
const dropHalf = (e) => e.target.closest?.('.drop-half') || null;
function showDropzone(show) {
  // Dentro de um jogo a janela se divide em dois lados: personagem e asset. Numa aba de gestão, não: ali entra documento.
  $('#dropzone').classList.toggle('split', !state.legacy && !!state.game && ['jogo', 'asset'].includes(screen()) && !inBoard());
  $('#drop-single').textContent = inBoard() ? 'Solte para enviar o documento (.md ou .txt)' : 'Solte para enviar';
  $('#dropzone').hidden = !show;
  if (!show) for (const half of document.querySelectorAll('.drop-half')) half.classList.remove('over');
}
window.addEventListener('dragenter', (e) => {
  if (!hasFiles(e)) return;
  dragDepth += 1;
  showDropzone(true);
});
window.addEventListener('dragleave', () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) showDropzone(false);
});
window.addEventListener('dragover', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  for (const half of document.querySelectorAll('.drop-half')) half.classList.toggle('over', half === dropHalf(e));
});
window.addEventListener('drop', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  const as = dropHalf(e)?.dataset.as || null;
  dragDepth = 0;
  showDropzone(false);
  droppedEntries(e.dataTransfer).then((entries) => upload(entries, as), (err) => toast(`Não consegui ler os arquivos soltos: ${err.message}`, 'erro'));
});

$('#back').addEventListener('click', goBack);
$('#crumb-name').addEventListener('click', renameCurrent);
window.addEventListener('hashchange', applyHash);
window.addEventListener('popstate', applyHash);

await refresh();
applyHash();
if (!term.where) openTerminal(termTarget()); // na tela de projetos, o terminal da ponte
setInterval(refresh, 2000);
