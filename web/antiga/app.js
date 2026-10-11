// Interface do PonteAnimada: listas, visualizador, laudo, revisão e pedidos ao Kimodo.

import { Viewer } from './viewer.js';

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

const KIND_LIST = { asset: 'assets', motion: 'motions', result: 'results' };
const VERDICT = {
  pronto: ['ok', 'Pronto para animar', 'Rig reconhecido e mapeado para o esqueleto do Kimodo.'],
  precisa_rig: ['bad', 'Precisa de rig', 'O arquivo não tem esqueleto.'],
  precisa_mapeamento: ['warn', 'Precisa de mapeamento', 'Há ossos essenciais que não foram reconhecidos.'],
  nao_suportado: ['bad', 'Rig não suportado', 'Este tipo de rig ainda não pode receber animação direto.'],
  so_animacao: ['bad', 'É uma animação, não um personagem', 'O arquivo só tem esqueleto e movimento. Importe-o em Animações Mixamo, dentro do projeto do personagem; este projeto pode ser excluído.'],
  erro: ['bad', 'Erro na inspeção', 'O Blender não conseguiu abrir ou analisar o arquivo.'],
};
const REVIEW = { pendente: ['warn', 'Aguardando validação'], aprovado: ['ok', 'Aprovado'], reprovado: ['bad', 'Reprovado'] };

const state = {
  data: { assets: [], motions: [], results: [], jobs: [], kimodo: {}, ardy: {}, meshy: {}, engines: null },
  pickEngine: false, // a escolha do gerador foi reaberta pelo "trocar gerador"
  project: null, // id do projeto aberto (o do personagem)
  tab: 'result',
  sel: null,
  seen: null,
  fresh: new Set(),
  myJobs: new Set(),
  jobStatus: new Map(),
  dismissed: new Set(),
  reports: new Map(),
  keys: {},
  loadedKey: null,
  fps: 30,
  scrubbing: false,
  propEdits: {},
  propsKey: null,
  adjustBone: null,
  adjustBones: {},
};

const viewer = new Viewer($('#viewport'));

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

// O resultado de um personagem encerrado não é um registro à parte: fica no próprio personagem
// (asset.final) e é selecionado como { kind: 'final', id: <id do personagem> }.
const records = (kind) => (kind === 'final' ? state.data.assets.filter((a) => a.final) : state.data[KIND_LIST[kind]]);
const find = (kind, id) => records(kind).find((r) => r.id === id);

// Cada personagem é um projeto. Animações e prévias (a animação aplicada no personagem, que é
// o que se valida; "result" no código) dizem em asset_id de qual projeto são, e as listas
// mostram só o que é do projeto aberto.
const projectOf = (kind, rec) => (kind === 'asset' || kind === 'final' ? rec.id : rec.asset_id);
const currentProject = () => find('asset', state.project);
const inProject = (kind) => records(kind).filter((r) => projectOf(kind, r) === state.project);

// Duas telas: a de projetos (state.project nulo) e a do projeto aberto, só com o que é dele.
function showScreen() {
  const home = !state.project;
  $('#home').hidden = !home;
  $('.layout').hidden = home;
}

// --- Utilidades ---------------------------------------------------------------------------

const num = (value, digits = 0) =>
  value == null ? '—' : Number(value).toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const when = (iso) => (iso ? new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '');
const chip = (tone, text) => h('span', { class: `chip ${tone}` }, text);
// Como chamar um passo e um roteiro: pelo nome dado a eles ou, sem nome, pelo texto do pedido.
const stepLabel = (step) => step.label || step.text;
const motionTitle = (motion, fallback) => motion?.name || (motion?.steps?.length ? stepLabel(motion.steps.at(-1)) : fallback);
const stepCount = (motion) => (motion?.steps?.length ? `${motion.steps.length} passo(s) · ` : '');

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
    $('#kimodo').replaceChildren(h('span', { class: 'dot' }), 'Servidor local sem resposta');
    return;
  }
  const first = state.seen === null;
  state.seen ??= new Set();
  for (const kind of ['asset', 'result']) {
    for (const rec of data[KIND_LIST[kind]]) {
      if (state.seen.has(rec.id)) continue;
      state.seen.add(rec.id);
      if (first) continue;
      state.fresh.add(rec.id);
      if (kind === 'result') toast(`Nova prévia em ${rec.asset_name}: ${rec.prompt}`, 'ok', () => select('result', rec.id));
    }
  }
  state.data = data;
  watchJobs();
  ensureSelection();
  showScreen();
  renderKimodo();
  renderEngine();
  renderHome();
  renderFinals();
  renderMeshy();
  renderProjectHead();
  renderTabs();
  renderList();
  renderJobs();
  renderComposerProject();
  renderScript();
  renderDetail();
  syncViewer();
}

function watchJobs() {
  for (const job of state.data.jobs) {
    const before = state.jobStatus.get(job.id);
    state.jobStatus.set(job.id, job.status);
    if (!state.myJobs.has(job.id) || before === job.status) continue;
    if (job.status === 'ok') {
      state.myJobs.delete(job.id);
      if (state.sentDraft === job.id) resetDraft(); // o passo chegou: o roteiro libera o próximo
      const out = job.output || {};
      const resultId = out.result_ids?.[0];
      const motionId = out.motion_ids?.[0];
      if (out.final) {
        select('final', out.asset_id);
        toast('Personagem encerrado. Este é o resultado; o atalho dele fica na tela de projetos.', 'ok');
      } else if (resultId) select('result', resultId);
      else if (motionId) select('motion', motionId);
      else if (out.asset_id && state.sel?.id === out.asset_id) state.keys.detail = null;
      // Marcadores estimados chegaram: abre a tela de rig que estava esperando por eles.
      if (out.rig && state.rigWanted === out.asset_id) {
        state.rigWanted = null;
        if (state.sel?.id === out.asset_id) startRig(find('asset', out.asset_id));
      }
    } else if (job.status === 'erro' || job.status === 'interrompido') {
      state.myJobs.delete(job.id);
      if (state.sentDraft === job.id) state.sentDraft = null; // o rascunho fica, para tentar de novo
      toast(`${job.title}: ${job.error || job.progress}`, 'erro');
    }
  }
}

function ensureSelection() {
  // Link direto (#tipo/id) aberto de fora entra no projeto do item; recarregar (Ctrl+R)
  // sempre volta à escolha de personagem, mesmo que o endereço guarde um link antigo.
  if (!state.booted) {
    state.booted = true;
    const reloaded = performance.getEntriesByType('navigation')[0]?.type === 'reload';
    const [hashKind, hashId] = location.hash.slice(1).split('/');
    if (!reloaded && (KIND_LIST[hashKind] || hashKind === 'final') && find(hashKind, hashId)) return select(hashKind, hashId);
    if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  }
  if (!state.project) return;
  if (!currentProject()) return goHome(); // o projeto aberto foi apagado
  const selected = state.sel && find(state.sel.kind, state.sel.id);
  if (selected && projectOf(state.sel.kind, selected) === state.project) return;
  openProject(state.project); // a seleção foi apagada: reabre no que importa
}

// Abre um projeto no que mais interessa validar: uma prévia pendente, ou o personagem.
function openProject(id) {
  if (!id) return goHome();
  state.project = id;
  const results = inProject('result');
  const result = results.find((r) => r.review?.status === 'pendente') || results[0];
  if (result) return select('result', result.id);
  // Projeto sem animação ainda: o personagem no visualizador e, na lista, onde trazer as animações.
  select('asset', id);
  state.tab = 'result';
  state.keys.list = state.keys.tabs = null;
  renderTabs();
  renderList();
}

// Volta à tela de projetos: nada selecionado, nenhum projeto aberto.
function goHome() {
  if (state.rigging) stopRig();
  state.project = null;
  state.sel = null;
  state.keys = {};
  history.replaceState(null, '', location.pathname + location.search);
  showScreen();
  renderHome();
  renderFinals();
  renderMeshy();
  renderJobs();
  renderComposerProject();
  syncViewer(); // sem seleção, o visualizador descarrega o modelo
}

function select(kind, id) {
  if (state.sel?.id !== id) {
    state.adjustBone = null;
    state.rigging = null;
  }
  state.sel = { kind, id };
  // Selecionar algo de outro projeto (por link ou aviso) abre esse projeto.
  const rec = find(kind, id);
  if (rec) state.project = projectOf(kind, rec);
  if (kind !== 'final') state.tab = kind; // o resultado fica fora das abas do projeto
  state.fresh.delete(id);
  state.keys.list = state.keys.detail = state.keys.tabs = state.keys.home = state.keys.finals = state.keys.projectHead = null;
  showScreen();
  renderHome();
  renderFinals();
  renderMeshy();
  renderProjectHead();
  renderTabs();
  renderList();
  renderComposerProject();
  renderScript();
  renderDetail(true);
  syncViewer();
}

// --- Barra do Kimodo ------------------------------------------------------------------------

function renderKimodo() {
  const k = state.data.kimodo;
  const a = state.data.ardy || {};
  const engine = engineNow()?.id;
  const cpp = engine === 'cpp';
  const ardy = engine === 'ardy';
  if (!changed('kimodo', [k, a, engine, noEngine()])) return;
  if (noEngine()) {
    // Desinstalados os dois: não há o que ligar nem o que trocar.
    $('#kimodo').replaceChildren(
      h('span', { class: 'dot' }),
      h('span', { title: 'A ponte segue servindo para importar animações prontas, validar e encerrar. Para voltar a gerar, reinstale o Kimodo: o guia está em docs/kimodo-setup/GUIA-KIMODO.md.' }, 'Nenhum gerador de animação instalado'),
    );
    return;
  }
  const on = ardy ? !!a.encoder : k.docker && k.encoder;
  const busy = k.generating > 0;
  const label = on ? 'ligado' : k.docker ? 'text encoder desligado' : 'desligado';
  // O kimodo.cpp não tem o que ligar: carrega o modelo a cada geração. No ARDY só o codificador
  // de texto fica ligado; ele sobe sozinho quando o texto é novo e é desligado em seguida.
  const button = cpp
    ? null
    : ardy
      ? on
        ? h('button', { class: 'btn small', onclick: stopArdy, disabled: busy, title: 'Desliga o codificador de texto do ARDY e devolve uns 16 GB de RAM.' }, 'Desligar')
        : h('button', { class: 'btn small', onclick: startArdy, title: 'Deixa o codificador de texto do ARDY no ar (uns 16 GB de RAM), para pedir vários textos novos em seguida sem esperar ele subir a cada um. Sem isto ele sobe sozinho quando o texto é novo e é desligado logo depois.' }, 'Ligar')
      : on
        ? h('button', { class: 'btn small', onclick: stopKimodo, disabled: busy }, 'Desligar')
        : h('button', { class: 'btn small', onclick: startKimodo }, 'Ligar');
  const name = cpp ? 'kimodo.cpp' : ardy ? `ARDY · codificador de texto ${on ? 'ligado' : 'desligado'}` : `Kimodo ${label}`;
  $('#kimodo').replaceChildren(
    ...[
      h('span', { class: `dot ${busy ? 'busy' : on || cpp || ardy ? 'on' : ''}` }),
      // Um pedido de cada vez, seja qual for o gerador; o que chega com outro gerando espera na fila.
      h('span', {}, `${name} · esqueleto ${ardy ? 'Core 27' : 'SOMA 77'} · ${busy ? `gerando${k.queued ? ` · ${k.queued} na fila` : ''}` : 'livre'}`),
      h('button', { class: 'btn link small', id: 'change-engine', title: 'Trocar o gerador de animação: Kimodo original, kimodo.cpp ou ARDY', onclick: () => { state.pickEngine = true; renderEngine(); } }, 'trocar gerador'),
      button,
    ].filter(Boolean),
  );
}

// --- Gerador ------------------------------------------------------------------------------------
// O Kimodo original (Docker), o kimodo.cpp (Windows) ou o ARDY (Ubuntu). A ponte pergunta ao
// abrir a janela; a resposta vale para o que for gerado dali em diante, pela tela e pela linha de comando.
const ENGINE_NAMES = { kimodo: 'Kimodo', cpp: 'kimodo.cpp', ardy: 'ARDY' };

function engineNow() {
  const engines = state.data.engines;
  return engines?.options.find((o) => o.id === engines.current);
}
// O que o gerador em uso ainda não sabe fazer: 'travel', 'loop', 'text_weight'.
const engineLacks = (what) => !!engineNow()?.lacks.includes(what);
// Nenhum dos dois instalado: a ponte segue servindo para importar, validar e encerrar, sem gerar.
const noEngine = () => !!state.data.engines && !state.data.engines.options.some((o) => !o.problem);

function renderEngine() {
  const engines = state.data.engines;
  const box = $('#engine-pick');
  // Perguntado uma vez por janela aberta: recarregar a página não pergunta de novo.
  // Sem nenhum gerador instalado não há o que escolher.
  if (!engines || noEngine() || (sessionStorage.getItem('ponte-gerador') && !state.pickEngine)) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  if (!changed('engine-pick', engines)) return;
  box.replaceChildren(
    h(
      'div',
      { class: 'engine-box', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Escolha do gerador' },
      h('h2', {}, 'Qual gerador você vai usar?'),
      h('p', { class: 'hint' }, 'O Kimodo original e o kimodo.cpp rodam o mesmo modelo, no mesmo esqueleto; o ARDY é outro modelo, com esqueleto próprio. A escolha vale para o que for gerado a partir de agora; dá para trocar depois, em “trocar gerador”, na barra de cima.'),
      h(
        'div',
        { class: 'engine-options' },
        engines.options.map((o) =>
          h(
            'button',
            { type: 'button', class: `engine-option${o.id === engines.current ? ' current' : ''}`, 'data-engine': o.id, disabled: !!o.problem, onclick: () => pickEngine(o.id) },
            h('strong', {}, o.name),
            h('span', {}, o.about),
            o.problem ? h('span', { class: 'engine-problem' }, o.problem) : o.id === engines.current ? h('span', {}, 'É o que estava em uso da última vez.') : null,
          ),
        ),
      ),
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
  renderKimodo();
  renderScript(true);
  toast(`Gerador em uso: ${engineNow().name}.`, 'ok');
}

async function startKimodo() {
  const job = await guard(() => send('POST', '/api/kimodo/start'));
  if (job) {
    state.myJobs.add(job.id);
    toast('Ligando o Kimodo. Na primeira vez do dia o text encoder leva uns 5 minutos.');
  }
}

async function startArdy() {
  if (!confirm('O codificador de texto do ARDY ocupa uns 16 GB de RAM enquanto ligado e leva de 3 a 5 minutos para subir.\nSó texto novo precisa dele, e sem ligar aqui ele sobe e desce sozinho a cada texto novo.\nLigar e deixar no ar?')) return;
  const job = await guard(() => send('POST', '/api/ardy/start'));
  if (job) {
    state.myJobs.add(job.id);
    toast('Subindo o codificador de texto do ARDY: de 3 a 5 minutos.');
  }
}

async function stopArdy() {
  const out = await guard(() => send('POST', '/api/ardy/stop'));
  if (out) toast(out.message, 'ok');
}

// O que foi gravado no demo ao vivo do ARDY (aba IO, Export Session) entra como roteiro do
// personagem do projeto aberto.
async function pickArdySession() {
  const found = await guard(() => api('/api/ardy/sessions'));
  if (!found) return;
  const sessions = found.sessions.filter((s) => !s.error && s.frames);
  state.ardySessions = sessions.length ? sessions : null;
  if (!sessions.length) toast('Nenhuma sessão exportada ainda. No demo ao vivo do ARDY: aba IO, botão Export Session.', 'erro');
  renderList();
}

async function importArdySession(session) {
  const asset = currentProject();
  const job = await guard(() => send('POST', '/api/motions/import-ardy', { asset_id: asset.id, session: session.file }));
  if (!job) return;
  state.myJobs.add(job.id);
  state.ardySessions = null;
  toast(`Trazendo a sessão ${session.file} para ${asset.name}.`);
  renderList();
}

async function stopKimodo() {
  if (!confirm('Desligar o Kimodo libera cerca de 17 GB de RAM.\nA próxima geração vai levar uns 5 minutos a mais para religar. Desligar?')) return;
  if (await guard(() => send('POST', '/api/kimodo/stop'))) toast('Kimodo desligado.', 'ok');
}

// --- Listas ----------------------------------------------------------------------------------

// A tela de entrada: um cartão por personagem (como uma escolha de perfil) e um para começar outro.
function renderHome() {
  const rows = state.data.assets.map((asset) => {
    const results = state.data.results.filter((r) => r.asset_id === asset.id);
    const latest = results.find((r) => r.sheet);
    return {
      asset,
      pending: results.filter((r) => r.review?.status === 'pendente').length,
      sheet: latest && `${latest.files_base}/${latest.sheet}?v=${encodeURIComponent(latest.created_at)}`,
    };
  });
  if (!changed('home', [rows.map((r) => [r.asset.id, r.asset.name, r.asset.verdict, r.asset.status, r.pending, !!r.asset.final, r.sheet]), [...state.fresh]])) return;
  $('#home-projects').replaceChildren(
    ...rows.map(({ asset, pending, sheet }) => {
      const [tone, label] = VERDICT[asset.verdict] || ['info', asset.status === 'erro' ? 'Erro' : 'Inspecionando…'];
      return h(
        'div',
        { class: 'picker-slot' },
        h(
          'button',
          { class: 'picker-card', title: `Abrir o projeto ${asset.name}`, onclick: () => openProject(asset.id) },
          // O retrato é a tira de quadros da última prévia; sem prévia, a inicial do nome.
          sheet ? h('img', { class: 'avatar', loading: 'lazy', alt: '', src: sheet }) : h('div', { class: 'avatar letter', 'aria-hidden': 'true' }, (asset.name[0] || '?').toUpperCase()),
          h('div', { class: 'picker-name' }, state.fresh.has(asset.id) && h('span', { class: 'new-dot', title: 'Novo' }), asset.name),
          h('div', { class: 'item-chips' }, chip(tone, label), pending > 0 && chip('warn', `${pending} para validar`), asset.final && chip('ok', 'encerrado')),
        ),
        h('button', { class: 'picker-delete', title: `Excluir o projeto ${asset.name}`, 'aria-label': `Excluir o projeto ${asset.name}`, onclick: () => deleteProject(asset) }, '×'),
      );
    }),
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

// Na tela de entrada: os personagens pedidos ao Meshy. Primeiro chega a imagem, para aprovar;
// aprovada, ela vira o modelo 3D e um projeto novo. Reprovada, a nota volta a quem fez o pedido.
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
  if (!changed('meshy', [requests.map((r) => [r.id, r.status, r.note, r.error, r.asset_id, r.image_at]), state.data.jobs.filter((j) => j.kind === 'meshy').map((j) => [j.id, j.status])])) return;
  $('#meshy-head').hidden = !requests.length;
  $('#home-meshy').replaceChildren(
    ...requests.map((r) => {
      const [tone, label] = MESHY_STATUS[r.status] || ['info', r.status];
      const waiting = r.status === 'aguardando_aprovacao';
      // Gerando sem job no ar: o programa foi fechado no meio. O modelo que o Meshy já estava fazendo é retomado.
      const stalled = r.status === 'gerando_modelo' && !state.data.jobs.some((j) => j.kind === 'meshy' && ['fila', 'rodando'].includes(j.status));
      const exists = r.asset_id && find('asset', r.asset_id);
      return h(
        'div',
        { class: 'meshy-card', 'data-meshy': r.id },
        // A imagem é o que ele aprova: clicar abre inteira, em outra aba.
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

// Na tela de entrada: um atalho para o resultado de cada personagem encerrado.
function renderFinals() {
  const closed = records('final');
  if (!changed('finals', [closed.map((a) => [a.id, a.name, a.final.at, a.final.stale, a.final.clips.length])])) return;
  $('#finals-head').hidden = !closed.length;
  if (!closed.length) {
    $('#home-finals').replaceChildren();
    return;
  }
  $('#home-finals').replaceChildren(
    ...closed.map((asset) =>
      h(
        'button',
        { class: 'card', title: 'Abrir o resultado deste personagem', onclick: () => select('final', asset.id) },
        h('div', { class: 'card-title' }, h('span', { class: 'shortcut-mark', 'aria-hidden': 'true' }, '↗'), asset.name),
        h('div', { class: 'item-sub' }, `${asset.final.clips.length} animação(ões) · encerrado em ${when(asset.final.at)}`),
        asset.final.stale && h('div', { class: 'item-chips' }, chip('warn', 'desatualizado')),
      ),
    ),
  );
}

// Cabeçalho da tela do projeto: voltar, o nome dele e, se encerrado, o resultado dele.
function renderProjectHead() {
  const asset = currentProject();
  const f = asset?.final;
  const current = state.sel?.kind === 'final' && state.sel.id === asset?.id;
  if (!changed('projectHead', [asset?.id, asset?.name, f?.at, f?.stale, f?.clips?.length, current])) return;
  $('#project-name').textContent = asset?.name || '';
  $('#project-name').title = asset?.name || '';
  const box = $('#project-result');
  if (!f) return box.replaceChildren();
  box.replaceChildren(
    h(
      'button',
      { class: 'item shortcut', 'aria-current': current ? 'true' : null, title: 'O resultado deste personagem: todas as animações num arquivo só', onclick: () => select('final', asset.id) },
      h('div', { class: 'item-title' }, h('span', { class: 'shortcut-mark', 'aria-hidden': 'true' }, '↗'), 'Resultado'),
      h('div', { class: 'item-sub' }, `${f.clips.length} animação(ões) · encerrado em ${when(f.at)}`),
      f.stale && h('div', { class: 'item-chips' }, chip('warn', 'desatualizado')),
    ),
  );
}

function renderTabs() {
  const counts = { result: inProject('result').length, motion: inProject('motion').length };
  if (!changed('tabs', [state.tab, state.project, counts])) return;
  for (const button of document.querySelectorAll('#tabs button')) {
    button.setAttribute('aria-selected', String(button.dataset.tab === state.tab));
    button.querySelector('.count').textContent = counts[button.dataset.tab] || '';
  }
}

function reviewChip(rec) {
  const [tone, label] = REVIEW[rec.review?.status] || REVIEW.pendente;
  return chip(tone, label);
}

function listItem(kind, rec, title, sub, chips, extra) {
  const current = state.sel?.kind === kind && state.sel.id === rec.id;
  return h(
    'button',
    { class: 'item', 'aria-current': current ? 'true' : null, onclick: () => select(kind, rec.id) },
    h('div', { class: 'item-title' }, state.fresh.has(rec.id) && h('span', { class: 'new-dot', title: 'Novo' }), title),
    sub && h('div', { class: 'item-sub' }, sub),
    chips?.length ? h('div', { class: 'item-chips' }, chips) : null,
    extra,
  );
}

// As ações do personagem: cada passo com nome, uma vez só (um roteiro repete os passos de
// onde partiu). É a lista simples: clicar numa ação abre a prévia que a tem e toca só ela.
function projectActions() {
  const seen = new Map();
  const previews = inProject('result').filter((r) => !r.in_place).sort((a, b) => a.created_at.localeCompare(b.created_at));
  for (const result of previews) {
    const motion = find('motion', result.motion_id);
    (motion?.steps || []).forEach((step, index) => {
      if (!step.label) return;
      const key = `${step.text}|${step.start_frame}`;
      if (!seen.has(key)) seen.set(key, { resultId: result.id, motionId: motion.id, index, step });
    });
  }
  return [...seen.values()];
}

// A ação só toca depois que a prévia dela estiver no visualizador.
function playAction(action) {
  state.pendingStep = { id: action.motionId, index: action.index };
  if (state.sel?.kind === 'result' && state.sel.id === action.resultId) startPendingStep();
  else select('result', action.resultId);
}

function startPendingStep() {
  const pending = state.pendingStep;
  const motion = pending && find('motion', pending.id);
  if (!motion || !viewer.duration || chainMotion()?.id !== pending.id) return;
  state.pendingStep = null;
  if (!(state.loopStep?.id === pending.id && state.loopStep.index === pending.index)) toggleLoop(motion, pending.index);
}

async function starAction(action) {
  const motion = find('motion', action.motionId);
  const stars = motion.steps.map((_, i) => (i === action.index ? !action.step.star : null));
  if (await guard(() => send('PATCH', `/api/motions/${motion.id}`, { stars }))) await refresh();
}

function actionRows() {
  const actions = projectActions();
  if (!actions.length) return [];
  const row = (action) => {
    const playing = state.loopStep?.id === action.motionId && state.loopStep.index === action.index;
    return h(
      'div',
      { class: 'action-row' },
      h(
        'button',
        { class: 'item action', 'aria-current': playing ? 'true' : null, title: action.step.text, onclick: () => playAction(action) },
        h('span', { class: 'action-play' }, playing ? '■' : '▶'),
        h('span', { class: 'action-name' }, action.step.label),
        h('span', { class: 'sub' }, `${num(action.step.seconds, 1)} s`),
      ),
      h('button', { class: 'btn link small', title: action.step.star ? 'Tirar das ações principais' : 'Pôr entre as ações principais', onclick: () => starAction(action) }, action.step.star ? '★' : '☆'),
    );
  };
  const main = actions.filter((a) => a.step.star);
  const others = actions.filter((a) => !a.step.star);
  return [
    h('h3', { class: 'list-head' }, 'Ações'),
    ...(main.length ? main.map(row) : [h('div', { class: 'sub', style: 'margin:0 10px 6px' }, 'Marque com ★ as ações principais do personagem.')]),
    others.length ? h('details', { class: 'more-actions', open: !!state.moreActions, ontoggle: (e) => { state.moreActions = e.target.open; } }, h('summary', {}, `outras ações (${others.length})`), others.map(row)) : null,
  ].filter(Boolean);
}

// Animações prontas do Mixamo: o FBX baixado de lá é aplicado no personagem do projeto e vira
// uma ação dele, que se valida e sai no resultado como as do Kimodo.
async function importMixamo(files) {
  const asset = currentProject();
  if (asset?.verdict !== 'pronto') return toast('Abra um projeto com o personagem pronto para animar.', 'erro');
  for (const file of files) {
    if (!/\.fbx$/i.test(file.name)) {
      toast(`${file.name}: a animação do Mixamo precisa estar em FBX.`, 'erro');
      continue;
    }
    const job = await guard(() => api(`/api/motions/import-fbx?filename=${encodeURIComponent(file.name)}&asset_id=${asset.id}`, { method: 'POST', body: file }));
    if (job) {
      state.myJobs.add(job.id);
      toast(`Importando ${file.name}: o Blender aplica a animação em ${asset.name}. Leva uns 20 segundos.`);
    }
  }
  refresh();
}

function previewItem(rec) {
  const sheet = rec.sheet && h('img', { class: 'sheet', loading: 'lazy', alt: '', src: `${rec.files_base}/${rec.sheet}?v=${encodeURIComponent(rec.created_at)}` });
  const motion = find('motion', rec.motion_id);
  return listItem('result', rec, motionTitle(motion, rec.prompt), `${stepCount(motion)}${num(rec.stats?.duration_s, 1)} s${rec.in_place ? ' · parado no lugar' : ''}`, [reviewChip(rec)], sheet);
}

// A aba Prévias de um projeto: as ações, as animações trazidas do Mixamo, as capturas de
// movimento (só aparecem se houver alguma), as sessões do demo ao vivo do ARDY (com ele
// instalado) e os roteiros gerados.
function previewList(items) {
  const origin = (rec) => find('motion', rec.motion_id)?.source;
  const mixamo = items.filter((rec) => origin(rec) === 'mixamo');
  const capture = items.filter((rec) => origin(rec) === 'captura');
  const kimodo = items.filter((rec) => !['mixamo', 'captura'].includes(origin(rec)));
  const hint = (text) => h('div', { class: 'sub', style: 'margin:0 10px 8px' }, text);
  return [
    ...actionRows(),
    h(
      'div',
      { class: 'list-head-row' },
      h('h3', { class: 'list-head' }, 'Animações Mixamo'),
      h('button', { class: 'btn small', title: 'Escolha um ou mais FBX baixados do Mixamo. Cada um é aplicado neste personagem e vira uma ação.', onclick: () => $('#mixamo-input').click() }, 'Importar FBX'),
    ),
    ...(mixamo.length ? mixamo.map(previewItem) : [hint('Baixe a animação no site do Mixamo em FBX e importe aqui: ela é aplicada neste personagem e vira uma ação.')]),
    ...(capture.length ? [h('h3', { class: 'list-head' }, 'Capturas de movimento'), ...capture.map(previewItem)] : []),
    ...(state.data.ardy?.installed
      ? [
          h(
            'div',
            { class: 'list-head-row' },
            h('h3', { class: 'list-head' }, 'Sessões do ARDY'),
            h('button', { class: 'btn small', id: 'ardy-sessions', title: 'O que você gravou no demo ao vivo do ARDY (aba IO, Export Session) entra aqui como roteiro deste personagem, e dá para continuar dele.', onclick: pickArdySession }, 'Importar sessão'),
          ),
          ...(state.ardySessions || []).map((s) =>
            h(
              'div',
              { class: 'sub ardy-session', style: 'margin:0 10px 8px; display:flex; align-items:center; justify-content:space-between; gap:8px' },
              h('span', {}, `${s.file} · ${num(s.seconds, 1)} s · ${s.prompts.join(' → ') || 'sem texto'}`),
              h('button', { class: 'btn small', onclick: () => importArdySession(s) }, 'Trazer'),
            ),
          ),
        ]
      : []),
    h('h3', { class: 'list-head' }, 'Roteiros gerados'),
    ...(kimodo.length ? kimodo.map(previewItem) : [hint('Nenhum roteiro gerado ainda. Monte um na barra de baixo.')]),
  ];
}

function renderList() {
  const items = inProject(state.tab);
  if (!changed('list', [state.tab, state.project, state.sel, items, [...state.fresh], inProject('motion').map((m) => [m.id, m.name, (m.steps || []).map((s) => [s.label, s.star])]), state.loopStep, state.ardySessions, state.data.ardy?.installed])) return;
  const list = $('#list');
  if (state.tab === 'result' && state.project) return list.replaceChildren(...previewList(items));
  if (!items.length) {
    const empty = {
      result: 'Este projeto ainda não tem prévia: nenhuma animação foi aplicada no personagem. Monte um roteiro na barra de baixo.',
      asset: 'Abra ou crie um projeto para ver o personagem.',
      motion: 'Este projeto ainda não tem animações.',
    };
    list.replaceChildren(h('div', { class: 'empty' }, state.project ? empty[state.tab] : 'Nenhum projeto aberto.'));
    return;
  }
  list.replaceChildren(
    ...items.map((rec) => {
      if (state.tab === 'asset') {
        const s = rec.summary || {};
        const [tone, label] = VERDICT[rec.verdict] || ['info', rec.status === 'inspecionando' || rec.status === 'novo' ? 'Inspecionando…' : rec.status];
        const sub = rec.summary ? `${s.rig || 'Sem rig'} · ${num(s.bones)} ossos · ${num(s.triangles)} triângulos` : rec.filename;
        return listItem('asset', rec, rec.name, sub, [chip(tone, label), rec.verdict === 'pronto' && reviewChip(rec)]);
      }
      const uses = state.data.results.filter((r) => r.motion_id === rec.id).length;
      const origin = rec.source === 'kimodo' ? ENGINE_NAMES[rec.engine] || 'Kimodo' : { mixamo: 'Mixamo', captura: 'captura' }[rec.source] || 'importada';
      // Numa corrente de passos, a animação de onde o passo seguinte partiu fica guardada sem prévia.
      const longer = state.data.motions.some((m) => m.continued_from === rec.id);
      return listItem('motion', rec, motionTitle(rec, rec.prompt), `${stepCount(rec)}${num(rec.duration_s, 1)} s · ${origin}`, [chip(uses ? 'info' : '', uses ? `${uses} prévia(s)` : longer ? 'guardada: outro clipe continua dela' : 'ainda não aplicada')]);
    }),
  );
}

// --- Fila --------------------------------------------------------------------------------------

function renderJobs() {
  const recent = Date.now() - 15 * 60 * 1000;
  const shown = state.data.jobs.filter(
    (j) =>
      j.status === 'fila' || j.status === 'rodando' ||
      ((j.status === 'erro' || j.status === 'interrompido') && !state.dismissed.has(j.id) && new Date(j.ended_at || j.created_at) > recent),
  );
  if (!changed('jobs', [state.project, shown.map((j) => [j.id, j.status, j.progress])])) return;
  const row = (job) => {
    const active = job.status === 'fila' || job.status === 'rodando';
    return h(
      'div',
      { class: `job ${active ? '' : 'erro'}` },
      h('div', { class: 'job-title' }, active && h('span', { class: 'spinner' }), job.title),
      h('div', { class: 'job-progress' }, active ? job.progress : job.error || job.progress),
      !active && h('button', { class: 'btn link small', onclick: () => { state.dismissed.add(job.id); state.keys.jobs = null; renderJobs(); } }, 'dispensar'),
    );
  };
  // A tela de projetos vê a fila inteira; a tela do projeto, só o que mexe nele (e o que é global, como ligar o Kimodo).
  const inProject = shown.filter((j) => !j.params?.asset_id || j.params.asset_id === state.project);
  $('#jobs').replaceChildren(...inProject.map(row));
  $('#home-jobs').replaceChildren(...shown.map(row));
}

// --- Visualizador -------------------------------------------------------------------------------

function viewerSource() {
  if (!state.sel) return { empty: 'Envie um personagem para começar.' };
  const rec = find(state.sel.kind, state.sel.id);
  if (!rec) return { empty: '' };
  if (state.sel.kind === 'result') {
    return { url: `${rec.files_base}/${rec.files.glb}`, version: rec.created_at, title: `${motionTitle(find('motion', rec.motion_id), rec.prompt)} → ${rec.asset_name}`, fps: rec.stats?.fps, assetId: rec.asset_id };
  }
  if (state.sel.kind === 'final') {
    const f = rec.final;
    // Sem assetId: os acessórios já vêm gravados no arquivo, e aqui não se edita nada.
    return { url: `${f.files_base}/${f.files.glb}`, version: f.at, title: `${rec.name} — resultado, ${f.clips.length} animação(ões)`, fps: f.fps };
  }
  if (state.sel.kind === 'asset') {
    if (rec.preview) return { url: `${rec.files_base}/${rec.preview}`, version: rec.inspected_at || rec.created_at, title: `${rec.name} — pose de descanso`, assetId: rec.id };
    return { empty: rec.status === 'erro' ? 'Não foi possível abrir este arquivo. Veja o erro ao lado.' : 'Inspecionando o arquivo no Blender…' };
  }
  return { empty: 'Uma animação só aparece depois de aplicada num personagem. Escolha um ao lado e clique em Aplicar.' };
}

async function syncViewer() {
  const src = viewerSource();
  const key = src.url ? `${src.url}?${src.version}` : `empty:${src.empty}`;
  // Mesmo modelo na tela: só confere se os acessórios dele mudaram.
  if (state.loadedKey === key) return syncProps(src.assetId);
  state.loadedKey = key;
  state.propsKey = null;
  $('#viewport-title').textContent = src.title || '';
  $('#viewport-empty').textContent = src.url ? 'Carregando…' : src.empty;
  $('#clip').hidden = true;
  setTransport(false);
  if (!src.url) {
    viewer.clear();
    return;
  }
  state.fps = src.fps || 30;
  try {
    const clips = await viewer.load(`${src.url}?v=${encodeURIComponent(src.version)}`);
    if (clips === null) return;
    $('#viewport-empty').textContent = '';
    if (clips.length) {
      viewer.setSpeed(Number($('#speed').value));
      viewer.setPlaying(true);
      setTransport(true);
      const clip = $('#clip');
      clip.replaceChildren(...clips.map((name, i) => h('option', { value: i }, name || `Animação ${i + 1}`)));
      clip.hidden = clips.length < 2;
    }
    await syncProps(src.assetId);
    // O caminho desenhado continua valendo: sai de onde o passo novo começa neste modelo, na altura do chão dele.
    syncPathOrigin(true);
    startPendingStep(); // uma ação escolhida na lista esperava a prévia dela carregar
    // Atalho para abrir direto na tela de marcadores: #asset/<id> com ?rig no endereço.
    if (state.sel?.kind === 'asset' && new URLSearchParams(location.search).has('rig') && !state.rigging) startRig(find('asset', state.sel.id));
  } catch (err) {
    state.loadedKey = null;
    $('#viewport-empty').textContent = `Não consegui carregar o modelo: ${err.message}`;
  }
}

function setTransport(enabled) {
  $('#transport').classList.toggle('disabled', !enabled);
  $('#play').textContent = enabled && viewer.playing ? '❚❚' : '▶';
  if (!enabled) {
    $('#scrub').value = 0;
    $('#time').textContent = 'sem animação';
  }
}

viewer.onTime = (time, duration) => {
  if (!state.scrubbing) $('#scrub').value = duration ? time / duration : 0;
  $('#time').textContent = `${time.toFixed(2)} / ${duration.toFixed(2)} s · quadro ${Math.round(time * state.fps)}`;
};

function togglePlay() {
  if (!viewer.duration) return;
  viewer.setPlaying(!viewer.playing);
  $('#play').textContent = viewer.playing ? '❚❚' : '▶';
}

$('#play').addEventListener('click', togglePlay);
$('#scrub').addEventListener('input', (e) => {
  state.scrubbing = true;
  viewer.setPlaying(false);
  $('#play').textContent = '▶';
  viewer.seek(Number(e.target.value) * viewer.duration);
});
$('#scrub').addEventListener('change', () => { state.scrubbing = false; });
$('#speed').addEventListener('change', (e) => viewer.setSpeed(Number(e.target.value)));
$('#clip').addEventListener('change', (e) => viewer.selectClip(Number(e.target.value)));
for (const name of ['follow', 'bones', 'wire']) {
  $(`#${name}`).addEventListener('change', (e) => viewer.setOption(name, e.target.checked));
}
$('#in-place-view').addEventListener('change', (e) => viewer.setOption('inPlace', e.target.checked));

// Mexer num acessório com o manipulador vira uma alteração pendente, até Salvar.
viewer.onPropChange = (id) => {
  const prop = find('asset', viewerSource().assetId)?.props?.find((p) => p.id === id);
  if (!prop) return;
  const first = !state.propEdits[id]?.matrix;
  state.propEdits[id] = { bone: state.propEdits[id]?.bone ?? prop.bone, matrix: viewer.propMatrix(id) };
  if (first) renderDetail(true);
};
document.addEventListener('keydown', (e) => {
  if (e.target.closest('input, textarea, select, button')) return;
  if (e.code === 'Space') {
    e.preventDefault();
    togglePlay();
  } else if ((e.code === 'ArrowLeft' || e.code === 'ArrowRight') && viewer.duration) {
    viewer.setPlaying(false);
    $('#play').textContent = '▶';
    const step = (e.code === 'ArrowRight' ? 1 : -1) / state.fps;
    viewer.seek((viewer.action?.time || 0) + step);
  }
});

// --- Painel de detalhe ----------------------------------------------------------------------------

function facts(rows) {
  return h('dl', { class: 'facts' }, rows.filter(Boolean).flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]));
}

function reviewBox(kind, rec) {
  const review = rec.review || { status: 'pendente', notes: '' };
  const notes = h('textarea', {
    id: 'review-notes',
    placeholder: 'O que precisa mudar? Estas notas chegam a quem gera as animações.',
    'aria-label': 'Notas da revisão',
  });
  notes.value = review.notes || '';
  const save = async (status) => {
    const next = review.status === status ? 'pendente' : status;
    const saved = await guard(() => send('POST', `/api/review/${kind}/${rec.id}`, { status: next, notes: notes.value }));
    if (saved) {
      if (next === 'reprovado' && !notes.value.trim()) toast('Reprovado. Se puder, diga nas notas o que está errado.');
      await refresh();
    }
  };
  const meta = review.at ? `${REVIEW[review.status][1]} em ${when(review.at)}` : 'Aguardando a sua validação';
  return h(
    'section',
    { class: 'review' },
    h('h3', {}, 'Validação'),
    h(
      'div',
      { class: 'review-buttons' },
      h('button', { class: 'btn ok', 'aria-pressed': String(review.status === 'aprovado'), onclick: () => save('aprovado') }, 'Aprovar'),
      h('button', { class: 'btn bad', 'aria-pressed': String(review.status === 'reprovado'), onclick: () => save('reprovado') }, 'Reprovar'),
    ),
    notes,
    h(
      'div',
      { class: 'row' },
      h('span', { class: 'review-meta' }, meta),
      h('button', { class: 'btn link small', style: 'margin-left:auto', onclick: () => save(review.status) }, 'salvar notas'),
    ),
  );
}

async function removeItem(kind, rec, label) {
  const inside = kind === 'asset' ? `${state.data.motions.filter((m) => m.asset_id === rec.id).length} animação(ões) e ${state.data.results.filter((r) => r.asset_id === rec.id).length} prévia(s)` : '';
  const extra = { result: '', motion: '\nAs prévias feitas com ela também serão apagadas.', asset: `\nO personagem, ${inside}${rec.final ? ', o resultado com o atalho dele' : ''} e todos os arquivos do projeto serão apagados do disco.` }[kind];
  if (!confirm(`Apagar ${label}?${extra}`)) return;
  if (await guard(() => api(`/api/${kind}/${rec.id}`, { method: 'DELETE' }))) {
    state.sel = null;
    await refresh();
  }
}

// Excluir um projeto leva o personagem, as animações, as prévias e o resultado dele. Com
// trabalho rodando nele, não: o job ficaria gravando numa pasta que sumiu.
function deleteProject(asset) {
  const busy = state.data.jobs.filter((j) => (j.status === 'fila' || j.status === 'rodando') && j.params?.asset_id === asset.id);
  if (busy.length) return toast(`Ainda há trabalho rodando em ${asset.name} (${busy[0].title}). Espere terminar para excluir o projeto.`, 'erro');
  return removeItem('asset', asset, `o projeto "${asset.name}"`);
}

async function renameProject(asset) {
  const name = prompt('Nome do projeto:', asset.name);
  if (name == null || !name.trim() || name.trim() === asset.name) return;
  if (await guard(() => send('PATCH', `/api/assets/${asset.id}`, { name: name.trim() }))) await refresh();
}

const openFolder = (kind, id) => guard(() => send('POST', `/api/open-folder/${kind}/${id}`));

async function loadReport(asset) {
  const key = JSON.stringify([asset.status, asset.inspected_at]);
  const cached = state.reports.get(asset.id);
  if (cached?.key === key) return cached.report;
  if (asset.status !== 'inspecionado') return null;
  if (cached?.loading === key) return null;
  state.reports.set(asset.id, { loading: key });
  const report = await api(`/api/assets/${asset.id}/report`).catch(() => null);
  state.reports.set(asset.id, { key, report });
  state.keys.detail = null;
  renderDetail();
  return report;
}

// --- Rig no padrão Mixamo ---------------------------------------------------------------------
// O humano confere os 8 marcadores na vista de frente; o Blender monta o esqueleto e os pesos.

const MARKER_LABELS = { chin: 'queixo', groin: 'virilha', l_wrist: 'pulso esq.', r_wrist: 'pulso dir.', l_elbow: 'cotovelo esq.', r_elbow: 'cotovelo dir.', l_knee: 'joelho esq.', r_knee: 'joelho dir.' };
const MARKER_LEGEND = [['#f5d547', 'queixo: na ponta do queixo'], ['#4cc38a', 'pulsos: na dobra do pulso'], ['#6aa9f2', 'cotovelos: na dobra do cotovelo'], ['#e879c7', 'joelhos: no meio do joelho'], ['#f0a43a', 'virilha: onde as pernas se encontram']];

function startRig(asset) {
  if (!asset?.rig?.estimated || !viewer.root) return;
  state.rigging = { assetId: asset.id, fingers: asset.rig.fingers ?? true };
  // Parte dos marcadores usados da última vez, se já foi rigado aqui; senão, do chute do Blender.
  viewer.enterRig(asset.rig.markers || asset.rig.estimated, asset.rig.body, MARKER_LABELS);
  renderDetail(true);
}

function stopRig() {
  state.rigging = null;
  viewer.exitRig();
  renderDetail(true);
}

function rigBox(asset) {
  if (!asset.preview || !['precisa_rig', 'pronto', 'precisa_mapeamento', 'nao_suportado'].includes(asset.verdict)) return null;
  if (state.rigging?.assetId === asset.id && viewer.rig) {
    const symmetric = h('input', { type: 'checkbox', checked: viewer.rig.symmetric, onchange: (e) => { viewer.rig.symmetric = e.target.checked; } });
    const fingers = h('input', { type: 'checkbox', checked: state.rigging.fingers, onchange: (e) => { state.rigging.fingers = e.target.checked; } });
    const go = async () => {
      const job = await guard(() => send('POST', `/api/assets/${asset.id}/rig`, { markers: viewer.rigMarkers(), fingers: state.rigging.fingers }));
      if (!job) return;
      state.myJobs.add(job.id);
      stopRig();
      toast('Rigando no Blender: esqueleto, pesos e laudo novo. Leva em torno de um minuto.');
    };
    return h(
      'section',
      { class: 'review' },
      h('h3', {}, 'Rigar — confira os marcadores'),
      h('div', { class: 'sub', style: 'margin:0' }, 'Arraste cada círculo para o lugar certo, na vista de frente. Os braços precisam estar afastados do corpo (T-pose ou A-pose).'),
      h('div', { class: 'rig-legend' }, MARKER_LEGEND.flatMap(([color, text]) => [h('i', { style: `background:${color}` }), h('span', {}, text)])),
      h('label', { class: 'toggle' }, symmetric, ' Simetria (mexer num lado espelha o outro)'),
      h('label', { class: 'toggle', title: 'Com dedos são 65 ossos, como o esqueleto padrão do Mixamo. Sem dedos (25 ossos) a mão fica rígida: melhor quando os dedos da malha são grudados.' }, fingers, ' Com dedos (65 ossos)'),
      h(
        'div',
        { class: 'actions' },
        h('button', { class: 'btn primary', onclick: go }, 'Rigar'),
        h('button', { class: 'btn', onclick: () => viewer.setRigMarkers(asset.rig.estimated) }, 'Recomeçar'),
        h('button', { class: 'btn link', onclick: stopRig }, 'cancelar'),
      ),
    );
  }
  const begin = async () => {
    if (asset.rig?.estimated) return startRig(asset);
    const job = await guard(() => send('POST', `/api/assets/${asset.id}/rig/estimate`));
    if (!job) return;
    state.myJobs.add(job.id);
    state.rigWanted = asset.id;
    toast('Estimando os marcadores no Blender…');
  };
  const testWalk = async () => {
    const job = await guard(() => send('POST', `/api/assets/${asset.id}/test-walk`));
    if (job) state.myJobs.add(job.id);
  };
  const needs = asset.verdict === 'precisa_rig';
  return h(
    'section',
    {},
    h('h3', {}, 'Rig'),
    asset.rig?.at && h('div', { class: 'sub', style: 'margin:0 0 8px' }, `Rigado aqui em ${when(asset.rig.at)}: ${asset.rig.bones} ossos no padrão Mixamo, pesos por ${asset.rig.skinning.method}.`),
    needs && h('div', { class: 'sub', style: 'margin:0 0 8px' }, 'Este personagem veio sem esqueleto. Marque os pontos do corpo, como no Mixamo, e o esqueleto e os pesos são criados aqui.'),
    h(
      'div',
      { class: 'actions' },
      h('button', { class: needs ? 'btn primary' : 'btn', onclick: begin }, needs ? 'Rigar este personagem' : 'Rigar de novo'),
      asset.verdict === 'pronto' && h('button', { class: 'btn', title: 'Aplica uma caminhada de exemplo, para ver como a malha deforma.', onclick: testWalk }, 'Testar com caminhada'),
    ),
  );
}

function assetDetail(asset) {
  const cached = state.reports.get(asset.id);
  const report = cached?.report;
  loadReport(asset);
  const [tone, title, text] = VERDICT[asset.verdict] || ['info', 'Inspecionando…', 'O Blender está analisando o arquivo.'];
  const parts = [
    h(
      'header',
      {},
      h('h2', {}, asset.name, h('button', { class: 'btn link small rename', onclick: () => renameProject(asset) }, 'renomear')),
      h('div', { class: 'sub' }, `Projeto · ${asset.filename} · enviado em ${when(asset.created_at)}`),
    ),
    h('div', { class: `verdict ${tone}` }, h('strong', {}, title), h('span', {}, asset.error || text)),
  ];
  parts.push(rigBox(asset));
  if (asset.verdict === 'pronto' && !state.rigging) parts.push(reviewBox('asset', asset), closingBox(asset));

  if (report) {
    const { mesh, armature, dimensions, rest_pose: pose, mapping, animations, rig } = report;
    parts.push(
      h(
        'section',
        {},
        h('h3', {}, 'Laudo'),
        facts([
          ['Rig', rig?.label || '—'],
          armature && ['Ossos', `${num(armature.bones)} (${num(armature.deform_bones)} deformam)`],
          ['Triângulos', num(mesh.triangles)],
          ['Vértices', num(mesh.vertices)],
          dimensions && ['Altura', `${num(dimensions.height_m, 2)} m`],
          pose && ['Pose de descanso', `${pose.type === 'outra' ? 'incomum' : `${pose.type}-pose`} (braço a ${num(pose.arm_elevation_deg)}°)`],
          ['Materiais', num(mesh.materials)],
          ['Texturas', mesh.images ? `${num(mesh.images - mesh.missing_images.length)} de ${num(mesh.images)} encontradas` : 'nenhuma'],
          asset.files?.length && ['Arquivos junto do modelo', num(asset.files.length)],
          mesh.max_influences != null && ['Influências por vértice', `até ${num(mesh.max_influences)}`],
          ['Animações no arquivo', animations.length ? animations.map((a) => a.name).join(', ') : 'nenhuma'],
        ]),
      ),
      h(
        'section',
        {},
        h('h3', {}, 'Problemas'),
        report.issues.length
          ? h('ul', { class: 'issues' }, report.issues.map((i) => h('li', { class: i.level }, i.msg)))
          : h('div', { class: 'sub' }, 'Nenhum problema encontrado.'),
      ),
    );
    if (mapping) {
      const slots = Object.keys(mapping.slot_labels);
      const rows = [
        ...mapping.torso.map((bone, i) => [`coluna ${i + 1}`, bone]),
        ...mapping.neck.map((bone, i) => [`pescoço ${i + 1}`, bone]),
        ...slots.map((slot) => [mapping.slot_labels[slot], mapping.slots[slot]]),
      ];
      parts.push(
        h(
          'section',
          {},
          h('h3', {}, 'Mapeamento de ossos'),
          h(
            'details',
            { class: 'mapping' },
            h('summary', {}, `${mapping.coverage.mapped} de ${mapping.coverage.total} partes do corpo reconhecidas`),
            h(
              'table',
              { class: 'map-table' },
              h('thead', {}, h('tr', {}, h('th', {}, 'Parte'), h('th', {}, 'Osso do personagem'), h('th', {}, 'Junta do Kimodo'))),
              h('tbody', {}, rows.map(([part, bone]) => h('tr', {}, h('td', {}, part), h('td', { class: bone ? '' : 'missing' }, bone || 'não encontrado'), h('td', {}, (bone && mapping.sources[bone]) || '')))),
            ),
          ),
        ),
      );
    }
  }

  if (asset.verdict === 'pronto') parts.push(propsBox(asset.id, null));
  const textureInput = h('input', {
    type: 'file',
    multiple: true,
    hidden: true,
    accept: SIDECAR_ACCEPT,
    onchange: (e) => addTextures(asset, asEntries(e.target.files)),
  });
  parts.push(
    h(
      'section',
      { class: 'actions' },
      asset.verdict === 'pronto' &&
        h('button', { class: 'btn primary', onclick: () => $('#premise').focus() }, 'Animar este personagem'),
      h('button', { class: 'btn', onclick: () => textureInput.click() }, 'Adicionar texturas'),
      textureInput,
      h('button', { class: 'btn', onclick: async () => { const job = await guard(() => send('POST', `/api/assets/${asset.id}/inspect`)); if (job) state.myJobs.add(job.id); } }, 'Refazer laudo'),
      h('button', { class: 'btn', title: 'Abre no Explorer a pasta com o personagem, as animações e as prévias (e o resultado, depois de encerrado).', onclick: () => openFolder('asset', asset.id) }, 'Abrir pasta do projeto'),
      h('button', { class: 'btn link', onclick: () => removeItem('asset', asset, `o projeto "${asset.name}"`) }, 'Apagar projeto'),
    ),
  );
  return parts;
}

function resultDetail(result) {
  const s = result.stats;
  const base = result.files_base;
  // Animação pronta, feita no Blender e posta com `ponte anim add`: não passou pelo retarget,
  // então não tem as medidas dele, nem ajuste de pose, nem versão parada.
  if (!s.feet) {
    const ready = find('motion', result.motion_id);
    return [
      h(
        'header',
        {},
        h('h2', {}, motionTitle(ready, result.prompt), ready && h('button', { class: 'btn link small rename', onclick: () => renameMotion(ready) }, 'renomear')),
        h('div', { class: 'sub' }, `em ${result.asset_name} · ${num(s.duration_s, 1)} s · ${num(s.frames)} quadros · ${when(result.created_at)}`),
      ),
      reviewBox('result', result),
      h('section', {}, h('h3', {}, 'Animação pronta'), h('div', { class: 'sub' }, 'Feita no Blender e posta aqui já aplicada no personagem. Não passou pelo retarget: não há medidas, ajuste de pose nem versão parada.')),
      h(
        'section',
        { class: 'actions' },
        result.files.blend && h('button', { class: 'btn', onclick: async () => { if (await guard(() => send('POST', `/api/results/${result.id}/open-blender`))) toast('Abrindo no Blender…'); } }, 'Abrir no Blender'),
        h('button', { class: 'btn', onclick: () => openFolder('result', result.id) }, 'Abrir pasta'),
        h('button', { class: 'btn link', onclick: () => select('asset', result.asset_id) }, 'ver personagem'),
        h('button', { class: 'btn link', onclick: () => removeItem('result', result, 'esta prévia') }, 'Apagar'),
      ),
    ];
  }
  const maxAlign = (pattern) => Math.max(0, ...Object.entries(s.rest_alignment_deg).filter(([bone]) => pattern.test(bone)).map(([, deg]) => deg));
  const feet = ['l', 'r'].map((side) => s.feet[side]).filter(Boolean);
  const slide = feet.every((f) => f.slide_cm_per_s != null) && feet.length
    ? `${feet.map((f) => num(f.slide_cm_per_s, 1)).join(' / ')} cm/s (origem: ${feet.map((f) => num(f.source_slide_cm_per_s, 1)).join(' / ')})`
    : result.in_place ? 'não se aplica' : '—';
  // Refazer ou trocar de versão mantém o ajuste de pose que já estava salvo.
  const retarget = async (inPlace) => {
    const job = await guard(() => send('POST', '/api/results', { asset_id: result.asset_id, motion_id: result.motion_id, in_place: inPlace, adjust: result.adjust || null }));
    if (job) state.myJobs.add(job.id);
  };
  const redo = () => retarget(result.in_place);
  const motion = find('motion', result.motion_id);
  return [
    h(
      'header',
      {},
      h('h2', {}, motionTitle(motion, result.prompt), motion && h('button', { class: 'btn link small rename', onclick: () => renameMotion(motion) }, 'renomear')),
      h('div', { class: 'sub' }, `em ${result.asset_name} · ${num(s.duration_s, 1)} s · ${num(s.frames)} quadros · ${when(result.created_at)}`),
    ),
    stepsBox(motion),
    reviewBox('result', result),
    result.sheet && h('section', {}, h('h3', {}, 'Quadros'), h('img', { class: 'sheet-full', alt: 'Seis quadros da animação', src: `${base}/${result.sheet}?v=${encodeURIComponent(result.created_at)}` })),
    h(
      'section',
      {},
      h('h3', {}, 'Retarget'),
      facts([
        ['Ossos animados', `${num(s.bones_animated)} de ${num(s.bones_total)}`],
        // A escala compara o personagem com o esqueleto de onde a animação veio: o SOMA do
        // Kimodo, medido em centímetros, ou o do arquivo importado (em metros o do Mixamo, em
        // centímetros o de uma captura, que é convertida para o formato do Kimodo).
        motion?.source === 'mixamo' ? ['Tamanho em relação ao esqueleto do arquivo', `${num(s.scale * 100)} %`] : [`Tamanho em relação ao ${motion?.engine === 'ardy' ? 'esqueleto do ARDY' : motion?.source === 'captura' ? 'esqueleto do arquivo' : 'SOMA'}`, `${num(s.scale * 10000)} %`],
        ['Distância percorrida', result.in_place ? 'parado no lugar' : `${num(s.travel_m, 2)} m`],
        ['Correção de pose (braços / pernas)', `${num(maxAlign(/arm/i))}° / ${num(maxAlign(/leg/i))}°`],
        ['Deslize dos pés (esq. / dir.)', slide],
        ['Pé abaixo do chão', feet.length ? `${num(Math.max(0, ...feet.map((f) => f.sink_cm)), 1)} cm` : '—'],
        ['Conferência numérica', `${num(s.check.rotation_error_deg, 2)}° · ${num(s.check.position_error_cm, 2)} cm`],
      ]),
    ),
    s.warnings.length ? h('section', {}, h('h3', {}, 'Avisos'), h('ul', { class: 'issues' }, s.warnings.map((w) => h('li', { class: 'aviso' }, w)))) : null,
    h(
      'section',
      {},
      h('h3', {}, 'Conferir'),
      h('div', { class: 'sub', style: 'margin:0 0 8px' }, 'Isto é uma prévia, para validar. Os arquivos para a engine saem quando o personagem é encerrado, com todas as animações juntas.'),
      h(
        'div',
        { class: 'actions' },
        result.files.blend && h('button', { class: 'btn', onclick: async () => { if (await guard(() => send('POST', `/api/results/${result.id}/open-blender`))) toast('Abrindo no Blender…'); } }, 'Abrir no Blender'),
        h('button', { class: 'btn', onclick: () => openFolder('result', result.id) }, 'Abrir pasta'),
      ),
    ),
    poseBox(result),
    propsBox(result.asset_id, result),
    h(
      'section',
      { class: 'actions' },
      h('button', { class: 'btn', onclick: () => retarget(!result.in_place), title: 'Cria outra prévia da mesma animação, com ou sem o deslocamento no chão. As duas entram no resultado, a não ser que você reprove uma.' }, result.in_place ? 'Criar versão com deslocamento' : 'Criar versão parada'),
      h('button', { class: 'btn', onclick: redo }, 'Refazer retarget'),
      h('button', { class: 'btn link', onclick: () => select('asset', result.asset_id) }, 'ver personagem'),
      h('button', { class: 'btn link', onclick: () => removeItem('result', result, 'esta prévia') }, 'Apagar'),
    ),
  ];
}

// --- Ajuste de pose --------------------------------------------------------------------------
// Quaternions do ajuste salvo vêm na ordem do Blender [w, x, y, z]; os do visualizador são
// objetos do three.js. O espaço local do osso é o mesmo nos dois (tests/check_adjust.mjs).

const sanitizeBone = (name) => name.replace(/\s/g, '_').replace(/[[\].:/]/g, '');
const quatMul = ([aw, ax, ay, az], [bw, bx, by, bz]) => [
  aw * bw - ax * bx - ay * by - az * bz,
  aw * bx + ax * bw + ay * bz - az * by,
  aw * by - ax * bz + ay * bw + az * bx,
  aw * bz + ax * by - ay * bx + az * bw,
];

/** Ajuste total por osso: o que já está gravado na prévia composto com o que foi mexido agora. */
function totalAdjust(result) {
  const total = { ...(result.adjust || {}) };
  for (const bone of Object.keys(state.adjustBones || {})) {
    const pending = viewer.offsets.get(sanitizeBone(bone));
    if (!pending) continue;
    total[bone] = quatMul(total[bone] || [1, 0, 0, 0], [pending.w, pending.x, pending.y, pending.z]);
  }
  for (const [bone, quat] of Object.entries(total)) if (Math.abs(quat[0]) > 0.999999) delete total[bone];
  return total;
}

function poseBox(result) {
  const asset = find('asset', result.asset_id);
  if (!asset) return null;
  loadReport(asset);
  const mapping = state.reports.get(asset.id)?.report?.mapping;
  if (!mapping) return null;

  // Todos os ossos mapeados, por nome do Blender, agrupados para o seletor.
  const label = (slot) => mapping.slot_labels[slot];
  const groups = [
    ['Braços e mãos', ['shoulder', 'arm', 'forearm', 'hand'].flatMap((p) => ['l', 'r'].map((s) => `${s}_${p}`)).map((slot) => [label(slot), mapping.slots[slot]])],
    ['Tronco e cabeça', [...mapping.torso.map((b, i) => [`coluna ${i + 1}`, b]), ...mapping.neck.map((b, i) => [`pescoço ${i + 1}`, b]), ['cabeça', mapping.slots.head], ['quadril', mapping.slots.hips]]],
    ['Pernas', ['upleg', 'leg', 'foot', 'toe'].flatMap((p) => ['l', 'r'].map((s) => `${s}_${p}`)).map((slot) => [label(slot), mapping.slots[slot]])],
    ...['l', 'r'].map((s) => [`Dedos ${s === 'l' ? 'esq.' : 'dir.'}`, ['thumb', 'index', 'middle', 'ring', 'pinky'].flatMap((f) => [1, 2, 3].map((i) => `${s}_${f}${i}`)).map((slot) => [label(slot), mapping.slots[slot]])]),
  ].map(([title, items]) => [title, items.filter(([, bone]) => bone)]);
  state.adjustBones = Object.fromEntries(groups.flatMap(([, items]) => items.map(([text, bone]) => [bone, text])));

  const chooser = h(
    'select',
    { 'aria-label': 'Osso a ajustar', onchange: (e) => pick(e.target.value) },
    h('option', { value: '' }, '— escolha a parte do corpo —'),
    groups.map(([title, items]) => h('optgroup', { label: title }, items.map(([text, bone]) => h('option', { value: bone }, text)))),
  );
  const status = h('div', { class: 'sub' });
  const saveButton = h('button', { class: 'btn primary', onclick: save }, 'Salvar ajuste');

  function updateStatus() {
    const total = totalAdjust(result);
    const names = Object.keys(total).map((bone) => state.adjustBones[bone] || bone);
    const dirty = viewer.offsets.size > 0;
    status.textContent = names.length ? `Ajustados: ${names.join(', ')}${dirty ? ' — ainda não salvo' : ''}` : 'Nenhum osso ajustado.';
    saveButton.disabled = !dirty;
  }
  function pick(bone) {
    state.adjustBone = bone || null;
    if (bone && !viewer.selectBone(sanitizeBone(bone))) toast('Não achei esse osso no modelo carregado.', 'erro');
    if (!bone) viewer.selectBone(null);
    if (bone && viewer.playing) {
      viewer.setPlaying(false);
      $('#play').textContent = '▶';
    }
  }
  // Zerar = aplicar por cima o inverso do que já está gravado, para o osso voltar à animação pura.
  function zero(bones) {
    for (const bone of bones) {
      const saved = result.adjust?.[bone];
      if (saved) viewer.setOffset(sanitizeBone(bone), [-saved[1], -saved[2], -saved[3], saved[0]]);
      else viewer.resetOffsets(sanitizeBone(bone));
    }
  }
  async function save() {
    const job = await guard(() => send('POST', '/api/results', { asset_id: result.asset_id, motion_id: result.motion_id, in_place: result.in_place, adjust: totalAdjust(result) }));
    if (!job) return;
    state.myJobs.add(job.id);
    state.adjustBone = null;
    viewer.selectBone(null);
    toast('Regravando os arquivos com o ajuste. A validação volta para pendente.');
  }

  viewer.onOffsets = updateStatus;
  chooser.value = state.adjustBone && state.adjustBones[state.adjustBone] ? state.adjustBone : '';
  updateStatus();
  return h(
    'section',
    {},
    h('h3', {}, 'Ajustar pose'),
    h('div', { class: 'sub', style: 'margin:0 0 8px' }, 'Pause num quadro, escolha o osso e gire pelos arcos coloridos. O ajuste vale para a animação inteira.'),
    chooser,
    h(
      'div',
      { class: 'actions', style: 'margin-top:8px' },
      saveButton,
      h('button', { class: 'btn', onclick: () => state.adjustBone && zero([state.adjustBone]) }, 'Zerar este osso'),
      h('button', { class: 'btn link', onclick: () => zero(Object.keys({ ...(result.adjust || {}), ...Object.fromEntries(Object.keys(state.adjustBones).filter((b) => viewer.offsets.has(sanitizeBone(b))).map((b) => [b, 1])) })) }, 'zerar tudo'),
    ),
    status,
  );
}

// --- Acessórios (arma etc.) --------------------------------------------------------------------
// O acessório pertence ao personagem: fica preso a um osso e vale para todas as animações dele.
// state.propEdits guarda o que foi mexido e ainda não salvo: { id: { bone, matrix } }.

function shownProps(assetId) {
  const asset = find('asset', assetId);
  return (asset?.props || [])
    .filter((p) => p.glb)
    .map((p) => ({ ...p, ...(state.propEdits[p.id] || {}) }))
    .filter((p) => p.bone)
    .map((p) => ({ id: p.id, url: `${asset.files_base}/${p.glb}`, bone: sanitizeBone(p.bone), matrix: p.matrix }));
}

async function syncProps(assetId) {
  if (!assetId || !viewer.root) return;
  // A matriz em edição fica fora da chave: mexer no manipulador não pode recriar o objeto.
  const asset = find('asset', assetId);
  const key = JSON.stringify([state.loadedKey, (asset?.props || []).map((p) => [p.id, p.glb, p.bone, p.matrix]), Object.entries(state.propEdits).map(([id, e]) => [id, e.bone])]);
  if (state.propsKey === key) return;
  state.propsKey = key;
  await viewer.setProps(shownProps(assetId)).catch((err) => toast(`Não consegui carregar o acessório: ${err.message}`, 'erro'));
}

function propsBox(assetId, result) {
  const asset = find('asset', assetId);
  if (!asset) return null;
  loadReport(asset);
  const mapping = state.reports.get(assetId)?.report?.mapping;
  const bones = mapping
    ? [['mão dir.', mapping.slots.r_hand], ['mão esq.', mapping.slots.l_hand], ['antebraço dir.', mapping.slots.r_forearm], ['antebraço esq.', mapping.slots.l_forearm], ['costas', mapping.torso.at(-1)], ['quadril', mapping.slots.hips], ['cabeça', mapping.slots.head]].filter(([, b]) => b)
    : [];

  const pause = () => {
    if (!viewer.playing) return;
    viewer.setPlaying(false);
    $('#play').textContent = '▶';
  };
  const rebake = async () => {
    if (!result) return;
    const job = await guard(() => send('POST', '/api/results', { asset_id: result.asset_id, motion_id: result.motion_id, in_place: result.in_place, adjust: result.adjust || null }));
    if (job) state.myJobs.add(job.id);
  };

  const rows = (asset.props || []).map((prop) => {
    const edit = state.propEdits[prop.id];
    const bone = edit ? edit.bone : prop.bone;
    const size = prop.size_m ? prop.size_m.map((v) => num(v * 100)).join(' × ') + ' cm' : '';
    if (!prop.glb) return h('div', { class: 'prop' }, h('strong', {}, prop.name), h('div', { class: 'sub' }, 'Convertendo no Blender…'));

    const chooser = h(
      'select',
      {
        'aria-label': 'Prender em',
        onchange: (e) => {
          state.propEdits[prop.id] = { bone: e.target.value || null, matrix: null };
          syncProps(assetId).then(() => renderDetail(true));
        },
      },
      h('option', { value: '' }, '— solto (não aparece) —'),
      bones.map(([text, b]) => h('option', { value: b }, `preso em: ${text}`)),
    );
    chooser.value = bone || '';
    const mode = (name, text) =>
      h('button', { class: 'btn small', disabled: !bone, onclick: () => { pause(); if (!viewer.selectProp(prop.id, name)) toast('O acessório ainda está carregando.'); } }, text);
    const save = async () => {
      const matrix = bone ? viewer.propMatrix(prop.id) || edit?.matrix || prop.matrix : null;
      if (!(await guard(() => send('PUT', `/api/assets/${assetId}/props/${prop.id}`, { bone: bone || null, matrix })))) return;
      delete state.propEdits[prop.id];
      await refresh();
      if (result) {
        toast('Posição salva. Regravando esta prévia com o acessório.');
        await rebake();
      } else toast('Posição salva. Vale para as próximas animações; nas já feitas, use Refazer retarget.', 'ok');
    };
    const remove = async () => {
      if (!confirm(`Remover o acessório "${prop.name}" deste personagem?`)) return;
      if (await guard(() => api(`/api/assets/${assetId}/props/${prop.id}`, { method: 'DELETE' }))) {
        delete state.propEdits[prop.id];
        await refresh();
      }
    };
    const baked = result?.props?.[prop.id];
    const stale = result && !edit && prop.bone && JSON.stringify(baked) !== JSON.stringify({ bone: prop.bone, matrix: prop.matrix });
    return h(
      'div',
      { class: 'prop' },
      h('div', { class: 'row' }, h('strong', {}, prop.name), h('span', { class: 'sub', style: 'margin:0 0 0 auto' }, size)),
      chooser,
      h('div', { class: 'actions' }, mode('translate', 'Mover'), mode('rotate', 'Girar'), mode('scale', 'Escala'), h('button', { class: 'btn small primary', disabled: !edit, onclick: save }, 'Salvar'), h('button', { class: 'btn link small', onclick: remove }, 'remover')),
      edit && h('div', { class: 'sub' }, 'Alterado — ainda não salvo.'),
      stale && h('div', { class: 'sub' }, h('span', {}, 'Esta prévia está com a posição antiga. '), h('button', { class: 'btn link small', onclick: rebake }, 'regravar')),
    );
  });

  const input = h('input', {
    type: 'file',
    hidden: true,
    accept: '.fbx,.glb,.gltf,.obj,.blend',
    onchange: async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const out = await guard(() => api(`/api/assets/${assetId}/props?filename=${encodeURIComponent(file.name)}`, { method: 'POST', body: file }));
      if (!out) return;
      state.myJobs.add(out.job.id);
      // Uma arma costuma ir na mão direita: já sugere isso.
      if (mapping?.slots.r_hand) state.propEdits[out.prop.id] = { bone: mapping.slots.r_hand, matrix: null };
      await refresh();
      renderDetail(true);
    },
  });
  return h(
    'section',
    {},
    h('h3', {}, 'Acessórios'),
    rows.length ? rows : h('div', { class: 'sub', style: 'margin:0 0 8px' }, 'Arma, mochila ou outro objeto que o personagem carrega. Fica preso a um osso e acompanha todas as animações.'),
    h('div', { class: 'actions' }, h('button', { class: 'btn', onclick: () => input.click() }, 'Adicionar arma ou acessório'), input),
  );
}

// Os passos do roteiro: clicar leva ao ponto do clipe em que o passo começa, e ▶ toca só ele.
function stepsBox(motion) {
  if (!motion?.steps?.length) return null;
  const fps = motion.fps || 30;
  return h(
    'section',
    {},
    h('h3', {}, 'Roteiro'),
    h('div', { class: 'sub', style: 'margin:0 0 6px' }, 'Clique num passo para ir até ele, ou em ▶ para ver só ele, em repetição.'),
    motion.steps.map((step, i) => {
      const playing = state.loopStep?.id === motion.id && state.loopStep.index === i;
      return h(
        'div',
        { class: 'step-row' },
        h('button', { class: 'btn small step-play', 'aria-pressed': String(playing), title: playing ? 'Voltar ao clipe inteiro' : 'Tocar só este passo, em repetição', onclick: () => toggleLoop(motion, i) }, playing ? '■' : '▶'),
        h(
          'button',
          { class: 'btn link step-jump', title: step.label ? step.text : 'Ir para o começo deste passo', onclick: () => jumpTo(step.start_frame / fps) },
          h('span', { class: 'step-n' }, String(i + 1)),
          h('span', {}, stepLabel(step)),
          step.loop && h('span', { class: 'chip info', title: 'Termina na pose em que começou: pode tocar em laço, ou emendar de volta no passo de onde saiu.' }, '↻'),
          h('span', { class: 'sub' }, `${num(step.start_frame / fps, 1)} s`),
        ),
        h('button', { class: 'btn link small', title: 'Dar um nome a este passo', onclick: () => renameStep(motion, i) }, 'nome'),
      );
    }),
  );
}

async function renameMotion(motion) {
  const name = prompt('Nome do roteiro (ex.: Vagar, Reações):', motion.name || '');
  if (name == null) return;
  if (await guard(() => send('PATCH', `/api/motions/${motion.id}`, { name: name.trim() }))) await refresh();
}

async function renameStep(motion, index) {
  const step = motion.steps[index];
  const label = prompt(`Nome do passo ${index + 1}:\n${step.text}`, step.label || '');
  if (label == null || !label.trim()) return;
  const labels = motion.steps.map((_, i) => (i === index ? label.trim() : null));
  if (await guard(() => send('PATCH', `/api/motions/${motion.id}`, { labels }))) await refresh();
}

function motionDetail(motion) {
  const uses = state.data.results.filter((r) => r.motion_id === motion.id);
  // A animação é do projeto: só se aplica no personagem dele.
  const owner = find('asset', motion.asset_id);
  const inPlace = h('input', { type: 'checkbox' });
  const apply = async () => {
    const job = await guard(() => send('POST', '/api/results', { asset_id: motion.asset_id, motion_id: motion.id, in_place: inPlace.checked }));
    if (job) state.myJobs.add(job.id);
  };
  return [
    h('header', {}, h('h2', {}, motionTitle(motion, motion.prompt), h('button', { class: 'btn link small rename', onclick: () => renameMotion(motion) }, 'renomear')), h('div', { class: 'sub' }, `${motion.source === 'kimodo' ? `${ENGINE_NAMES[motion.engine] || 'Kimodo'} · ${motion.model}${motion.session ? ` · sessão do demo ao vivo (${motion.session.file})` : ''}` : `importada de ${motion.filename}`} · ${when(motion.created_at)}`)),
    h(
      'section',
      {},
      h('h3', {}, 'Animação'),
      facts([
        ['Esqueleto', motion.engine === 'ardy' ? 'Core 27 (o do ARDY)' : { mixamo: 'o do arquivo (Mixamo)', captura: 'o do arquivo (captura)' }[motion.source] || 'SOMA 77'],
        ['Duração', `${num(motion.duration_s, 2)} s`],
        ['Quadros', `${num(motion.frames)} a ${num(motion.fps)} fps`],
        // Captura: de que trecho da tomada o clipe saiu e o crédito que a licença do arquivo pede.
        motion.capture?.source?.seconds && ['Trecho do arquivo', `de ${num(motion.capture.source.seconds[0], 2)} a ${num(motion.capture.source.seconds[1], 2)} s`],
        motion.credit && ['Crédito', motion.credit],
        motion.seed != null && ['Seed', String(motion.seed)],
        motion.samples > 1 && ['Variação', `${motion.sample} de ${motion.samples}`],
      ]),
    ),
    h(
      'section',
      {},
      h('h3', {}, 'Aplicar no personagem'),
      owner?.verdict === 'pronto'
        ? h('div', { class: 'row' }, h('label', { class: 'toggle' }, inPlace, ' Parado no lugar'), h('button', { class: 'btn primary', style: 'margin-left:auto', onclick: apply }, uses.length ? 'Aplicar de novo' : 'Aplicar'))
        : h('div', { class: 'sub' }, 'O personagem deste projeto ainda não está pronto para animar.'),
    ),
    stepsBox(motion),
    uses.length
      ? h('section', {}, h('h3', {}, 'Prévias com esta animação'), uses.map((r) => h('button', { class: 'btn link', style: 'text-align:left', onclick: () => select('result', r.id) }, `${r.in_place ? 'parada no lugar' : 'com deslocamento'} — ${REVIEW[r.review.status][1].toLowerCase()}`)))
      : null,
    h(
      'section',
      { class: 'actions' },
      motion.source === 'mixamo'
        ? h('a', { class: 'btn', href: `${motion.files_base}/motion.fbx`, download: motion.filename || `${motion.id}.fbx` }, 'FBX')
        : h('a', { class: 'btn', href: `${motion.files_base}/motion.bvh`, download: `${motion.id}.bvh` }, 'BVH'),
      h('button', { class: 'btn', onclick: () => openFolder('motion', motion.id) }, 'Abrir pasta'),
      h('button', { class: 'btn link', onclick: () => removeItem('motion', motion, 'esta animação') }, 'Apagar'),
    ),
  ];
}

// --- Encerramento ---------------------------------------------------------------------------
// O resultado de um personagem só existe depois de encerrado: as prévias que não foram
// reprovadas viram um arquivo só, e o atalho dele aparece em Resultados, fora do projeto.

function closingCounts(assetId) {
  const previews = state.data.results.filter((r) => r.asset_id === assetId);
  const count = (status) => previews.filter((r) => (r.review?.status || 'pendente') === status).length;
  return { total: previews.length, pending: count('pendente'), rejected: count('reprovado'), entering: previews.length - count('reprovado') };
}

async function closeProject(asset) {
  const { total, pending, rejected, entering } = closingCounts(asset.id);
  if (!entering) return toast(total ? 'Todas as prévias deste projeto foram reprovadas: não há o que encerrar.' : 'Este projeto ainda não tem animação aplicada no personagem.', 'erro');
  const lines = [
    `Encerrar "${asset.name}"?`,
    '',
    `${entering} animação(ões) entram no resultado, num arquivo só (GLB, FBX e BLEND).`,
    asset.unreal ? 'Sai também o arquivo para a Unreal 5 (FBX com o esqueleto do Mannequin).' : null,
    pending ? `${pending} ainda sem validação: entra(m) assim mesmo.` : null,
    rejected ? `${rejected} reprovada(s): fica(m) de fora.` : null,
    '',
    'O atalho do resultado fica na tela de projetos, em Resultados. O projeto continua aqui: se mexer depois, é só encerrar de novo.',
  ];
  if (!confirm(lines.filter((line) => line != null).join('\n'))) return;
  const job = await guard(() => send('POST', `/api/assets/${asset.id}/close`));
  if (!job) return;
  state.myJobs.add(job.id);
  toast('Montando o resultado no Blender. O progresso aparece na fila, à esquerda.');
  refresh();
}

async function reopenProject(asset) {
  if (!confirm(`Desfazer o encerramento de "${asset.name}"?\nO resultado e o atalho dele são apagados. O projeto, as animações e as prévias ficam como estão, e dá para encerrar de novo.`)) return;
  if (!(await guard(() => send('POST', `/api/assets/${asset.id}/reopen`)))) return;
  await refresh();
  select('asset', asset.id);
}

// A opção vale no encerramento seguinte: ligar ou desligar deixa o resultado desatualizado.
async function setUnreal(asset, enabled, input) {
  const out = await guard(() => send('POST', `/api/assets/${asset.id}/unreal`, { enabled }));
  input.blur(); // com o foco na caixa, o painel não se redesenha
  if (!out) input.checked = !enabled;
  await refresh();
}

function closingBox(asset) {
  const f = asset.final;
  const { pending, entering } = closingCounts(asset.id);
  const text = f
    ? `Encerrado em ${when(f.at)}, com ${f.clips.length} animação(ões).${f.stale ? ' O projeto mudou depois disso: encerre de novo para o resultado acompanhar.' : ''}`
    : 'O resultado é o personagem com todas as animações num arquivo só, pronto para a engine. Ele só sai quando você encerra o personagem, e fica como atalho na tela de projetos.';
  const unreal = h('input', { type: 'checkbox', checked: !!asset.unreal, onchange: (e) => setUnreal(asset, e.target.checked, e.target) });
  return h(
    'section',
    {},
    h('h3', {}, 'Resultado'),
    h('div', { class: 'sub', style: 'margin:0 0 8px' }, text),
    h(
      'label',
      { class: 'toggle', style: 'margin:0 0 8px', title: 'O resultado ganha mais um FBX, com o personagem e as animações no esqueleto do Mannequin da Unreal 5 (root, pelvis, spine_01...). O que sai para a Godot não muda.' },
      unreal,
      ' Gerar também para a Unreal 5',
    ),
    h(
      'div',
      { class: 'actions' },
      h('button', { class: entering && !pending && (!f || f.stale) ? 'btn primary' : 'btn', disabled: !entering, title: entering ? '' : 'Ainda não há prévia para entrar no resultado.', onclick: () => closeProject(asset) }, f ? 'Encerrar de novo' : 'Encerrar personagem'),
      f && h('button', { class: 'btn', onclick: () => select('final', asset.id) }, 'Ver resultado'),
    ),
  );
}

function finalDetail(asset) {
  const f = asset.final;
  const play = (name) => {
    const index = viewer.clips.findIndex((clip) => clip.name === name);
    if (index < 0) return toast('O arquivo ainda está carregando.');
    $('#clip').value = index;
    viewer.selectClip(index);
    viewer.setPlaying(true);
    $('#play').textContent = '❚❚';
  };
  return [
    h('header', {}, h('h2', {}, asset.name), h('div', { class: 'sub' }, `Resultado · encerrado em ${when(f.at)}`)),
    f.stale && h('div', { class: 'verdict warn' }, h('strong', {}, 'Desatualizado'), h('span', {}, 'O projeto mudou depois de encerrado. Encerre de novo para o resultado acompanhar.')),
    h(
      'section',
      {},
      h('h3', {}, `Animações (${f.clips.length})`),
      f.clips.map((clip, i) =>
        h('button', { class: 'btn link step-jump', title: `Tocar: ${clip.prompt}`, onclick: () => play(clip.name) }, h('span', { class: 'step-n' }, String(i + 1)), h('span', {}, clip.name), h('span', { class: 'sub' }, `${num(clip.duration_s, 1)} s`)),
      ),
      f.rejected.length ? h('div', { class: 'sub' }, `${f.rejected.length} prévia(s) reprovada(s) ficou(aram) de fora.`) : null,
    ),
    f.warnings.length ? h('section', {}, h('h3', {}, 'Avisos'), h('ul', { class: 'issues' }, f.warnings.map((w) => h('li', { class: 'aviso' }, w)))) : null,
    h(
      'section',
      {},
      h('h3', {}, 'Arquivos'),
      h('div', { class: 'sub', style: 'margin:0 0 8px' }, 'Cada arquivo traz o personagem com todas as animações acima.'),
      h(
        'div',
        { class: 'actions' },
        Object.entries(f.files).map(([ext, file]) => h('a', { class: 'btn', href: `${f.files_base}/${file}`, download: file }, ext.toUpperCase())),
        h('button', { class: 'btn', onclick: () => openFolder('final', asset.id) }, 'Abrir pasta'),
      ),
    ),
    f.unreal &&
      h(
        'section',
        {},
        h('h3', {}, 'Unreal 5'),
        h(
          'div',
          { class: 'sub', style: 'margin:0 0 8px' },
          `O mesmo personagem, com as mesmas animações, no esqueleto do Mannequin (${f.unreal.bones} ossos: root, pelvis, spine_01...). Arraste o arquivo para o Content Browser da Unreal: entram a malha, o esqueleto e uma animação por clipe.`,
        ),
        h('div', { class: 'actions' }, h('a', { class: 'btn', href: `${f.files_base}/${f.unreal.file}`, download: f.unreal.file.split('/').pop() }, 'FBX para Unreal 5')),
      ),
    h(
      'section',
      { class: 'actions' },
      h('button', { class: f.stale ? 'btn primary' : 'btn', onclick: () => closeProject(asset) }, 'Encerrar de novo'),
      h('button', { class: 'btn link', onclick: () => select('asset', asset.id) }, 'ver projeto'),
      h('button', { class: 'btn link', onclick: () => reopenProject(asset) }, 'Desfazer o encerramento'),
    ),
  ];
}

function renderDetail(force = false) {
  const detail = $('#detail');
  const rec = state.sel && find(state.sel.kind, state.sel.id);
  const related =
    state.sel?.kind === 'motion'
      ? [currentProject()?.verdict, state.data.results.filter((r) => r.motion_id === state.sel.id).map((r) => [r.id, r.review])]
      : state.sel?.kind === 'asset'
        ? [state.reports.get(state.sel.id)?.key, state.propEdits, state.rigging, inProject('result').map((r) => r.review?.status)]
        : state.sel?.kind === 'result' && rec
          ? [find('asset', rec.asset_id)?.props, state.reports.get(rec.asset_id)?.key, state.propEdits, find('motion', rec.motion_id), state.loopStep]
          : null;
  // Não redesenha por baixo de quem está digitando as notas ou escolhendo numa lista.
  const typing = detail.contains(document.activeElement) && /TEXTAREA|SELECT|INPUT/.test(document.activeElement.tagName);
  if (typing && !force) return;
  if (!changed('detail', [state.sel, rec, related]) && !force) return;
  if (!rec) {
    detail.replaceChildren(
      h('header', {}, h('h2', {}, 'Nada selecionado')),
      h('div', { class: 'sub' }, 'Envie um personagem. Depois do laudo, peça uma animação ao Kimodo na barra de baixo e valide a prévia aqui. Com todas prontas, encerre o personagem: é aí que o resultado aparece.'),
    );
    return;
  }
  viewer.onOffsets = () => {};
  const build = { asset: assetDetail, result: resultDetail, motion: motionDetail, final: finalDetail }[state.sel.kind];
  detail.replaceChildren(...build(rec).filter(Boolean));
  detail.scrollTop = 0;
}

// --- Pedido de animação -----------------------------------------------------------------------------

// A animação é sempre gerada para o personagem do projeto aberto, e fica guardada nele.
function renderComposerProject() {
  const asset = currentProject();
  if (!changed('composerProject', [asset?.id, asset?.name, asset?.verdict])) return;
  $('#composer-project').textContent = asset ? asset.name : 'nenhum projeto aberto';
}

// Pedir ao Claude: abre uma conversa nova do Claude Code no VS Code com o contexto já escrito
// na caixa (o projeto e o que está aberto), sem enviar; a pessoa completa com o que quer.
// O link é o da extensão: vscode://anthropic.claude-code/open?prompt=<texto codificado>.
function claudeLink() {
  const asset = currentProject();
  if (!asset) return null;
  const lines = [`PonteAnimada: animação para o projeto "${asset.name}" (id ${asset.id}).`];
  const rec = state.sel && find(state.sel.kind, state.sel.id);
  if (rec && state.sel.kind === 'result') lines.push(`Prévia aberta: ${rec.id} (${rec.review?.status || 'pendente'}).`);
  else if (rec && state.sel.kind === 'motion') lines.push(`Animação aberta: ${rec.id}.`);
  lines.push('O que eu quero: ');
  return `vscode://anthropic.claude-code/open?prompt=${encodeURIComponent(lines.join('\n'))}`;
}
$('#ask-claude').addEventListener('click', (e) => {
  const link = claudeLink();
  if (!link) {
    e.preventDefault();
    return toast('Abra um projeto antes de pedir uma animação ao Claude.', 'erro');
  }
  e.currentTarget.href = link; // o clique segue para o link já com o projeto de agora
  toast('Abrindo o Claude Code no VS Code. O projeto já está escrito na caixa: complete com a animação que você quer e envie.');
});

// Quanto o personagem é menor/maior que o esqueleto do Kimodo: um caminho desenhado em volta
// dele precisa ser convertido para os metros do Kimodo antes de virar trajetória.
function motionScale(assetId) {
  const asset = find('asset', assetId);
  const result = state.data.results.find((r) => r.asset_id === assetId && r.stats?.scale); // a animação pronta não tem escala de retarget
  return asset?.summary?.motion_scale || (result ? result.stats.scale * 100 : (asset?.summary?.height_m || 1.75) / 1.75);
}

// --- Roteiro -----------------------------------------------------------------------------------
// Um passo de cada vez. O roteiro mostra os passos já entregues da animação aberta e um só
// passo novo para escrever; ele é gerado partindo dos últimos quadros do anterior, e o clipe
// cresce. O próximo passo só libera quando este for entregue: é vendo a prévia que se decide
// o que vem depois, ou se o passo precisa ser refeito.
// O contexto entra em todo passo: o Kimodo não lembra do prompt anterior.

const DIRECTION_OPTIONS = [['', 'livre (só o texto)'], ['0', 'frente'], ['45', 'frente-direita'], ['90', 'direita'], ['135', 'trás-direita'], ['180', 'trás'], ['225', 'trás-esquerda'], ['270', 'esquerda'], ['315', 'frente-esquerda']];
const PACE_OPTIONS = [['0.7', 'devagar'], ['1.0', 'andando'], ['1.4', 'andando rápido'], ['2.4', 'trotando'], ['3.6', 'correndo']];
// Quanto o Kimodo obedece ao texto do passo: o padrão dele, ou mais, para um gesto que saiu fraco.
const WEIGHT_OPTIONS = [['', 'gesto normal'], ['3.5', 'gesto marcado'], ['5', 'gesto exagerado']];
const newStep = () => ({ text: '', seconds: 3, direction: '', pace: '1.0', lock: true, loop: false, weight: '', label: '' });

function loadScript() {
  try {
    const saved = JSON.parse(localStorage.getItem('ponte.roteiro'));
    if (saved) {
      // O caminho desenhado volta junto com o rascunho; sem pontos salvos, o passo volta a "livre".
      const waypoints = Array.isArray(saved.waypoints) ? saved.waypoints.filter((p) => Array.isArray(p) && p.length === 2) : [];
      // Rascunhos antigos guardavam vários passos; agora o rascunho é o do passo a gerar.
      const step = { ...newStep(), ...(saved.step || saved.steps?.[0] || {}) };
      if (step.direction === 'path' && !waypoints.length) step.direction = '';
      return { premise: saved.premise || '', waypoints, step };
    }
  } catch { /* sem armazenamento, ou conteúdo inválido: começa vazio */ }
  return { premise: '', waypoints: [], step: newStep() };
}
function saveScript() {
  try {
    localStorage.setItem('ponte.roteiro', JSON.stringify(state.script));
  } catch { /* é só conveniência */ }
}
state.script = loadScript();

const composeText = (premise, action) => {
  const p = premise.trim().replace(/\.+$/, '');
  const a = action.trim().replace(/\.+$/, '');
  return p && a ? `${p} ${a}.` : p || a ? `${p || a}.` : '';
};
// O texto de um passo entregue traz o contexto na frente; para reescrevê-lo, só a ação.
const stripPremise = (text, premise) => {
  const p = (premise || '').trim().replace(/\.+$/, '');
  const t = text.trim().replace(/\.+$/, '');
  return p && t.toLowerCase().startsWith(`${p.toLowerCase()} `) ? t.slice(p.length + 1) : t;
};

// A animação em que o roteiro está: a aberta, pela prévia ou pela aba Animações. Com o
// personagem aberto, o roteiro começa uma animação nova.
function chainMotion() {
  const rec = state.sel && find(state.sel.kind, state.sel.id);
  if (!rec) return null;
  if (state.sel.kind === 'result') return find('motion', rec.motion_id) || null;
  return state.sel.kind === 'motion' ? rec : null;
}

// De onde o último passo de uma animação partiu, para refazê-lo: null se ela é de um passo só
// (refaz do zero), ou a animação que ela continuou, se ainda existe. Sem resposta (undefined)
// quando o passo não foi gerado sozinho: aí não há de onde partir.
function redoBase(motion) {
  const steps = motion.steps || [];
  if (motion.source !== 'kimodo' || !steps.length) return undefined;
  if (!motion.continued_from) return steps.length === 1 ? null : undefined;
  const parent = find('motion', motion.continued_from);
  return parent?.source === 'kimodo' && (parent.steps || []).length === steps.length - 1 ? parent : undefined;
}

// Enquanto um pedido do projeto não é entregue, o passo seguinte fica travado.
const generatingHere = () =>
  state.data.jobs.find((j) => j.kind === 'animacao' && (j.status === 'fila' || j.status === 'rodando') && j.params?.asset_id === state.project);

// O instante do clipe aberto de que o passo novo parte: o fim dele, ou o começo do último
// passo quando é ele que está sendo refeito.
function anchorTime(motion) {
  const last = (motion.steps || []).at(-1);
  return state.redo && last ? last.start_frame / (motion.fps || 30) : viewer.duration;
}

// Onde o passo novo começa, no chão do visualizador: a origem numa animação nova; numa
// continuação, onde o personagem está (e para onde olha) no instante de que o passo parte.
// null quando a prévia da animação não está no visualizador: sem ela não se sabe onde ele está.
function pathAnchor() {
  const motion = chainMotion();
  if (!motion || (state.redo && redoBase(motion) === null)) return { x: 0, z: 0, heading: 0 };
  const slots = state.reports.get(motion.asset_id)?.report?.mapping?.slots;
  if (!slots?.l_upleg || !slots?.r_upleg) return null;
  return viewer.poseAt(anchorTime(motion), sanitizeBone(slots.l_upleg), sanitizeBone(slots.r_upleg));
}

// A linha do caminho sai de onde o passo novo começa.
function syncPathOrigin(redraw = false) {
  const anchor = pathAnchor();
  const origin = anchor ? [anchor.x, anchor.z] : [0, 0];
  const moved = origin[0] !== viewer.pathOrigin[0] || origin[1] !== viewer.pathOrigin[1];
  viewer.pathOrigin = origin;
  if ((moved || redraw) && viewer.waypoints.length) viewer.drawWaypoints();
}

// Pontos do chão do visualizador → [direita, frente] em metros do Kimodo, a partir de onde o
// personagem está e para onde olha no começo do passo (olhando para +Z, a esquerda dele é +X).
function pathTravel(scale, lock) {
  const anchor = pathAnchor();
  if (!anchor) return null;
  const sin = Math.sin(anchor.heading);
  const cos = Math.cos(anchor.heading);
  const waypoints = viewer.waypoints.map(([x, z]) => {
    const dx = x - anchor.x;
    const dz = z - anchor.z;
    return [(-dx * cos + dz * sin) / scale, (dx * sin + dz * cos) / scale];
  });
  return { waypoints, lock_facing: lock };
}

function jumpTo(seconds) {
  if (state.loopStep) {
    state.loopStep = null;
    viewer.setLoopRange(null);
    renderScript(true);
    renderDetail(true);
    renderList();
  }
  viewer.setPlaying(false);
  $('#play').textContent = '▶';
  viewer.seek(seconds);
}

// Toca só um passo, em repetição. Num passo que fecha em laço, o último quadro tem a pose do
// quadro de antes do primeiro: o trecho vai de um ao outro e a volta emenda, como no jogo.
function toggleLoop(motion, index) {
  const on = !(state.loopStep?.id === motion.id && state.loopStep.index === index);
  state.loopStep = on ? { id: motion.id, index } : null;
  if (on) {
    const step = motion.steps[index];
    const fps = motion.fps || 30;
    const frames = Math.round(step.seconds * fps);
    // Num clipe que é o laço inteiro (uma captura) não há quadro antes do primeiro: ele repete o último.
    viewer.setLoopRange([Math.max(0, step.start_frame - (step.loop ? 1 : 0)) / fps, (step.start_frame + frames - 1) / fps]);
    // O deslocamento fica à vista (num ataque, é ele avançando que importa). Quem quiser ver só
    // a emenda de um laço que anda marca "Parado" na barra do visualizador.
    viewer.setPlaying(true);
    $('#play').textContent = '❚❚';
  } else viewer.setLoopRange(null);
  renderScript(true);
  renderDetail(true);
  renderList();
}

// Refazer o último passo: o rascunho vira o passo como foi pedido, para corrigir e gerar de novo.
function startRedo(motion) {
  const last = motion.steps.at(-1);
  const travel = last.travel || null;
  state.redo = { id: motion.id, stash: state.script.step };
  state.script.step = {
    text: stripPremise(last.text, motion.premise),
    seconds: last.seconds,
    direction: DIRECTION_OPTIONS.find(([value]) => value !== '' && Number(value) === travel?.direction_deg)?.[0] || '',
    pace: PACE_OPTIONS.find(([value]) => Number(value) === travel?.speed)?.[0] || '1.0',
    lock: travel ? !!travel.lock_facing : true,
    loop: !!last.loop,
    label: last.label || '',
    weight: WEIGHT_OPTIONS.find(([value]) => value !== '' && Number(value) === last.text_weight)?.[0] || '',
  };
  if (travel?.waypoints) toast('Este passo seguia um caminho desenhado. Desenhe de novo se quiser que o passo refeito também siga.');
  renderScript(true);
  document.querySelector('#steps .step-text')?.focus();
}

function cancelRedo() {
  if (!state.redo) return;
  state.script.step = state.redo.stash;
  state.redo = null;
}

// O passo foi entregue: o rascunho esvazia para o próximo, e o caminho já usado sai do chão.
function resetDraft() {
  state.sentDraft = null;
  state.redo = null;
  state.script.step = { ...newStep(), seconds: state.script.step.seconds };
  saveScript();
  if (viewer.waypoints.length) viewer.clearWaypoints();
  else renderScript(true);
}

function renderPreview() {
  const { step } = state.script;
  const text = step.text.trim() ? composeText($('#premise').value, step.text) : '';
  $('#script-preview').textContent = text ? `O Kimodo recebe: “${text}” · ${num(Number(step.seconds) || 0, 1)} s` : '';
}

function renderScript(force = false) {
  const asset = currentProject();
  const motion = chainMotion();
  if (state.redo && state.redo.id !== motion?.id) cancelRedo();
  if (state.loopStep && state.loopStep.id !== motion?.id) state.loopStep = null;
  const redo = !!state.redo;
  const delivered = motion?.steps || [];
  const shown = redo ? delivered.slice(0, -1) : delivered;
  const busy = generatingHere();
  const foreign = !!motion && motion.source !== 'kimodo'; // importada de um BVH: não dá para continuar dela
  const hasPath = viewer.waypoints.length > 0;
  // Animação sem roteiro registrado: ela inteira conta como o que já foi entregue.
  const whole = !!motion && !delivered.length;
  const n = whole ? 2 : shown.length + 1;
  if (!changed('script', [asset?.id, asset?.verdict, motion?.id, delivered.length, redo, busy?.id, busy?.progress, foreign, hasPath, state.loopStep, delivered.map((s) => s.label), state.data.engines?.current, noEngine()]) && !force) return;

  // O contexto é o da animação aberta; numa animação nova, o do rascunho.
  const premiseFor = motion?.id || 'new';
  if (state.premiseFor !== premiseFor) {
    state.premiseFor = premiseFor;
    $('#premise').value = motion ? motion.premise || '' : state.script.premise;
  }
  syncPathOrigin();

  const lead = redo ? `Refazendo o passo ${n}` : foreign ? 'Animação que veio pronta' : motion ? 'Roteiro da animação aberta' : 'Nova animação';
  const hint = redo
    ? `${shown.length ? `o clipe volta ao fim do passo ${n - 1} e este passo é gerado de novo` : 'o passo é gerado de novo, do zero'}. A versão atual só é apagada quando a nova ficar pronta.`
    : foreign
      ? 'aqui embaixo é onde se gera com o Kimodo. Para gerar outra coisa para este personagem, clique em nova animação.'
      : motion
      ? `um passo de cada vez, em inglês. O passo ${n} parte do fim do anterior, com transição, e o clipe continua um só.`
      : 'um passo de cada vez, em inglês: diga quem é e o que faz. Entregue este, você vê a prévia e escreve o próximo em cima dele.';
  const aside = redo
    ? h('button', { type: 'button', class: 'btn link small', onclick: () => { cancelRedo(); renderScript(true); } }, 'cancelar')
    : motion && h('button', { type: 'button', class: 'btn link small', title: 'Começa outra animação neste projeto, do zero. Esta continua guardada.', onclick: () => select('asset', state.project) }, 'nova animação');
  $('#script-title').replaceChildren(...[h('span', {}, h('strong', {}, lead), h('em', {}, ` — ${hint}`)), aside].filter(Boolean));

  const fps = motion?.fps || 30;
  const canRedo = !!motion && !redo && !busy && redoBase(motion) !== undefined;
  const link = (text) => h('div', { class: 'chain' }, text);
  const rows = whole ? [h('div', { class: 'step done' }, h('span', { class: 'step-n' }, '1'), h('span', { class: 'step-done-text' }, motion.prompt), h('span', { class: 'sub' }, `${num(motion.duration_s, 1)} s`)), link(foreign ? '' : 'o passo 2 continua daqui, com transição')] : [];
  // Aqui só o passo de onde o novo parte: a lista inteira, com ▶ em cada passo, fica no painel
  // da direita. Com todos os passos nesta caixa, um roteiro longo não cabia e não se via o resto.
  if (shown.length > 1) rows.push(h('div', { class: 'chain-note' }, `passos 1 a ${shown.length - 1}: na lista Roteiro, no painel à direita`));
  shown.forEach((s, i) => {
    const last = i === shown.length - 1;
    if (!last) return;
    rows.push(
      h(
        'div',
        { class: 'step done' },
        h('span', { class: 'step-n' }, String(i + 1)),
        h('button', { type: 'button', class: 'btn link step-done-text', title: s.label ? s.text : 'Ir para o começo deste passo', onclick: () => jumpTo(s.start_frame / fps) }, stepLabel(s)),
        h('span', { class: 'sub' }, `${num(s.seconds, 1)} s`),
        h('button', { type: 'button', class: 'btn link small', 'aria-pressed': String(state.loopStep?.index === i), title: 'Tocar só este passo, em repetição', onclick: () => toggleLoop(motion, i) }, state.loopStep?.index === i ? '■' : s.loop ? '↻' : '▶'),
        last && canRedo && h('button', { type: 'button', class: 'btn link small', title: 'Gera este passo de novo, partindo do fim do anterior. O que veio antes fica como está.', onclick: () => startRedo(motion) }, 'refazer'),
      ),
      link(last && !foreign ? `o passo ${n} continua daqui, com transição` : ''),
    );
  });

  let draft;
  if (busy) {
    draft = h('div', { class: 'step waiting' }, h('span', { class: 'spinner' }), h('div', {}, h('strong', {}, 'Gerando…'), h('div', { class: 'sub' }, `${busy.progress}. O próximo passo libera quando este for entregue.`)));
  } else if (foreign) {
    draft = h('div', { class: 'step waiting' }, h('div', { class: 'sub' }, 'Esta animação veio pronta de um arquivo: o Kimodo não tem como continuar a partir dela. Comece uma nova animação.'));
  } else {
    const step = state.script.step;
    const set = (key, value, redraw) => {
      step[key] = value;
      saveScript();
      if (redraw) renderScript(true);
      else renderPreview();
    };
    const directions = [...DIRECTION_OPTIONS, ...(hasPath ? [['path', 'caminho desenhado']] : [])];
    const direction = h('select', { 'aria-label': `Direção do passo ${n}`, title: 'Impõe por onde o quadril anda neste passo. O texto precisa concordar com a direção.', onchange: (e) => { if (e.target.value === 'path') step.lock = false; set('direction', e.target.value, true); } }, directions.map(([value, text]) => h('option', { value }, text)));
    // O kimodo.cpp ainda não aceita trajetória, laço nem força do gesto: com ele em uso esses
    // controles ficam desligados, e o que estava marcado no rascunho não vai no pedido.
    const absent = `O ${engineNow()?.name || 'gerador em uso'} ainda não faz isto. Para usar, escolha outro gerador em “trocar gerador”, na barra de cima.`;
    const dir = engineLacks('travel') ? '' : step.direction;
    direction.value = dir;
    if (engineLacks('travel')) Object.assign(direction, { disabled: true, title: absent });
    const pace = h('select', { 'aria-label': `Ritmo do passo ${n}`, hidden: dir === '' || dir === 'path', onchange: (e) => set('pace', e.target.value) }, PACE_OPTIONS.map(([value, text]) => h('option', { value }, text)));
    pace.value = step.pace;
    const lock = h('input', { type: 'checkbox', checked: step.lock, onchange: (e) => set('lock', e.target.checked) });
    // O laço fecha na pose em que o passo começa: só existe quando há um passo antes dele.
    const canLoop = (redo ? !!redoBase(motion) : !!motion) && !engineLacks('loop');
    const loop = h('input', { type: 'checkbox', checked: !!step.loop && canLoop, disabled: !canLoop, onchange: (e) => set('loop', e.target.checked) });
    const weight = h('select', { 'aria-label': `Força do gesto do passo ${n}`, title: 'Quanto o Kimodo obedece ao texto. Se o passo saiu parecido com o anterior, sem o gesto pedido, refaça com mais força.', onchange: (e) => set('weight', e.target.value) }, WEIGHT_OPTIONS.map(([value, label]) => h('option', { value }, label)));
    weight.value = engineLacks('text_weight') ? '' : step.weight || '';
    if (engineLacks('text_weight')) Object.assign(weight, { disabled: true, title: absent });
    const label = h('input', { type: 'text', class: 'step-label', maxLength: 60, autocomplete: 'off', placeholder: 'nome do passo (ex.: agitado)', title: 'Um nome curto, em português, para achar este passo depois.', 'aria-label': `Nome do passo ${n}`, oninput: (e) => { step.label = e.target.value; saveScript(); } });
    label.value = step.label || '';
    const text = h('input', { type: 'text', class: 'step-text', maxLength: 300, autocomplete: 'off', placeholder: n === 1 ? 'A zombie stands still, breathing' : 'walks forward slowly', 'aria-label': `Ação do passo ${n} (em inglês)`, oninput: (e) => set('text', e.target.value) });
    text.value = step.text;
    const seconds = h('input', { type: 'number', min: 0.5, max: 10, step: 0.5, title: 'Segundos (até 10 por passo)', 'aria-label': `Segundos do passo ${n}`, onchange: (e) => set('seconds', Number(e.target.value)) });
    seconds.value = step.seconds;
    draft = h(
      'div',
      { class: 'step' },
      h('div', { class: 'step-head' }, h('span', { class: 'step-n' }, String(n)), text),
      h(
        'div',
        { class: 'step-opts' },
        seconds,
        h('span', { class: 'sub' }, 's'),
        direction,
        pace,
        h('label', { class: 'toggle', hidden: dir === '', title: 'Mantém o corpo olhando para frente enquanto anda (de lado, de ré). Desmarcado, ele vira para onde vai.' }, lock, ' corpo para frente'),
        h('label', { class: 'toggle', title: engineLacks('loop') ? absent : canLoop ?'O passo termina na pose em que começou: é o trecho que o jogo toca em repetição (ocioso, andar). Num passo que anda, escolha também a direção.' : 'O laço fecha na pose em que o passo começa: gere antes um passo de entrada (o personagem já na postura) e ponha o laço no seguinte.' }, loop, ' em laço'),
        weight,
        label,
      ),
    );
  }
  const steps = $('#steps');
  steps.replaceChildren(...rows, draft);
  steps.scrollTop = steps.scrollHeight; // o passo a escrever fica sempre à vista

  const ready = asset?.verdict === 'pronto';
  const button = $('#generate');
  button.textContent = redo ? `Refazer passo ${n}` : `Gerar passo ${n}`;
  button.disabled = !ready || !!busy || foreign || noEngine();
  button.title = noEngine()
    ? 'Nenhum gerador de animação está instalado neste PC. Dá para importar animações prontas na aba Prévias; para voltar a gerar, reinstale o Kimodo (docs/kimodo-setup/GUIA-KIMODO.md).'
    : !ready
      ? asset ? 'O personagem deste projeto ainda não está pronto para animar (veja o laudo).' : 'Abra um projeto.'
      : busy ? 'Há um passo sendo gerado neste projeto: o próximo libera quando ele for entregue.' : '';
  renderPreview();
}

$('#premise').addEventListener('input', (e) => {
  // O contexto de uma animação nova fica no rascunho; o de uma continuação vale só para o passo.
  if (!chainMotion()) {
    state.script.premise = e.target.value;
    saveScript();
  }
  renderPreview();
});

// O caminho salvo da última vez volta para o visualizador (antes de o roteiro passar a ouvi-lo).
if (state.script.waypoints.length) {
  viewer.waypoints = state.script.waypoints.map((p) => [...p]);
  viewer.drawWaypoints();
  $('#clear-path').hidden = false;
}
// O caminho desenhado vale para o passo a gerar: ele parte de onde o personagem está no começo do passo.
viewer.onWaypoints = (points) => {
  const step = state.script.step;
  $('#clear-path').hidden = !points.length;
  if (points.length && step.direction !== 'path') Object.assign(step, { direction: 'path', lock: false });
  else if (!points.length && step.direction === 'path') step.direction = '';
  state.script.waypoints = points.map((p) => [...p]);
  saveScript();
  renderScript(true);
};
$('#draw-path').addEventListener('click', () => {
  const on = $('#draw-path').getAttribute('aria-pressed') !== 'true';
  if (on) {
    const motion = chainMotion();
    if (!pathAnchor()) return toast('Para desenhar o caminho de um passo que continua uma animação, abra a prévia dela: é de onde o personagem parte.', 'erro');
    // Mostra o personagem onde ele vai estar quando o passo começar: é dali que o caminho sai.
    if (motion && viewer.duration) jumpTo(anchorTime(motion));
    syncPathOrigin();
    toast(motion ? 'Clique no chão para marcar por onde ele deve andar neste passo. O caminho sai de onde o personagem está agora, no fim do clipe.' : 'Clique no chão para marcar por onde ele deve andar neste passo. O caminho sai de onde o personagem começa.');
  }
  $('#draw-path').setAttribute('aria-pressed', String(on));
  viewer.setDrawing(on);
});
$('#clear-path').addEventListener('click', () => viewer.clearWaypoints());

$('#composer').addEventListener('submit', async (e) => {
  e.preventDefault();
  const asset = currentProject();
  if (asset?.verdict !== 'pronto') return toast('Abra um projeto com o personagem pronto para animar.', 'erro');
  if (generatingHere()) return toast('Ainda há um passo sendo gerado neste projeto. O próximo libera quando ele for entregue.', 'erro');
  const motion = chainMotion();
  if (motion && motion.source !== 'kimodo') return toast('Esta animação foi importada: não dá para continuar a partir dela. Comece uma nova animação.', 'erro');
  // De onde o passo parte: da animação aberta; refazendo, de onde o último passo dela partiu (null = do zero).
  const redo = !!state.redo && state.redo.id === motion?.id;
  const base = redo ? redoBase(motion) : motion;
  if (base === undefined) return toast('Não dá mais para refazer este passo: a animação de onde ele partiu foi apagada.', 'erro');
  const { step } = state.script;
  const n = redo ? motion.steps.length : motion ? (motion.steps?.length || 1) + 1 : 1;
  if (step.text.trim().length < 2) {
    document.querySelector('#steps .step-text')?.focus();
    return toast(`Escreva a ação do passo ${n} (em inglês).`, 'erro');
  }
  // O que o gerador em uso não faz (trajetória, laço, força do gesto) não vai no pedido.
  const direction = engineLacks('travel') ? '' : step.direction;
  let travel = null;
  if (direction === 'path') {
    if (!viewer.waypoints.length) return toast('O caminho desenhado se perdeu. Desenhe de novo no chão do visualizador, ou troque a direção do passo.', 'erro');
    travel = pathTravel(motionScale(asset.id), step.lock);
    if (!travel) return toast('Não consegui achar onde o personagem está no começo do passo. Abra a prévia da animação, ou use uma direção em vez do caminho.', 'erro');
  } else if (direction !== '') {
    travel = { direction_deg: Number(direction), speed: Number(step.pace), lock_facing: step.lock };
  }
  const body = {
    premise: $('#premise').value.trim(),
    steps: [{ text: step.text.trim(), seconds: Number(step.seconds), travel, loop: !!step.loop && !!base && !engineLacks('loop'), text_weight: step.weight && !engineLacks('text_weight') ? Number(step.weight) : null, label: (step.label || '').trim() || null }],
    samples: Number($('#samples').value),
    asset_id: asset.id,
    in_place: $('#in-place').checked,
    continue_from: base?.id ?? null,
    replaces: redo ? motion.id : null,
    engine: state.data.engines?.current ?? null,
  };
  // Prévia parada desconta o deslocamento: com caminho ou direção no passo, parece que o trajeto foi ignorado.
  if (body.in_place && travel) {
    const ok = confirm(
      '“Gerar parado no lugar” está marcado, mas o passo tem direção ou caminho desenhado.\n' +
        'A prévia parada mostra o personagem andando sem sair do lugar — vai parecer que o trajeto foi ignorado.\n\n' +
        'Gerar assim mesmo? (Para ver o trajeto, desmarque e gere; a versão parada dá para criar depois, na prévia.)',
    );
    if (!ok) return;
  }
  $('#generate').disabled = true;
  const job = await guard(() => send('POST', '/api/motions/generate', body));
  if (!job) {
    $('#generate').disabled = false;
    return;
  }
  state.myJobs.add(job.id);
  state.sentDraft = job.id;
  const queued = state.data.kimodo.generating > 0 ? ' Há outro pedido gerando: este entra na fila e começa quando ele terminar.' : '';
  toast(`Passo ${n} enviado ao ${engineNow()?.name || 'Kimodo'}.${queued} O próximo passo libera quando este for entregue.`);
  refresh();
});
renderScript();

// --- Envio de arquivos --------------------------------------------------------------------------------

const MODEL_RE = /\.(fbx|glb|gltf|blend|obj|zip)$/i; // o .zip traz o modelo e as texturas juntos
const SIDECAR_RE = /\.(png|jpe?g|tga|bmp|tiff?|webp|exr|dds|mtl|bin)$/i;
const SIDECAR_ACCEPT = '.png,.jpg,.jpeg,.tga,.bmp,.tif,.tiff,.webp,.exr,.dds,.mtl,.bin';
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

async function addTextures(asset, sidecars) {
  const sent = await sendSidecars(asset.id, sidecars, '');
  if (!sent) return;
  const job = await guard(() => send('POST', `/api/assets/${asset.id}/inspect`));
  if (job) state.myJobs.add(job.id);
  const stale = state.data.results.some((r) => r.asset_id === asset.id);
  toast(`${sent} arquivo(s) de textura adicionado(s) a ${asset.name}.${stale ? ' Para as prévias antigas mostrarem as texturas, use Refazer retarget.' : ''}`, 'ok');
}

async function upload(entries) {
  const models = entries.filter((e) => MODEL_RE.test(e.file.name));
  const sidecars = entries.filter((e) => SIDECAR_RE.test(e.file.name));
  const motions = entries.filter((e) => /\.bvh$/i.test(e.file.name));
  const ignored = entries.length - models.length - sidecars.length - motions.length;
  if (ignored) toast(`${ignored} arquivo(s) ignorado(s): formato não reconhecido.`);

  // BVH e texturas soltas entram no projeto aberto; um modelo 3D sempre cria um projeto novo.
  for (const { file } of motions) {
    if (!state.project) {
      toast('Abra um projeto antes de importar uma animação: ela fica guardada nele.', 'erro');
      break;
    }
    const motion = await guard(() => api(`/api/motions/import?filename=${encodeURIComponent(file.name)}&asset_id=${state.project}`, { method: 'POST', body: file }));
    if (motion) {
      toast(`Animação importada no projeto: ${motion.prompt}`, 'ok');
      await refresh();
      select('motion', motion.id);
    }
  }

  if (!models.length && sidecars.length) {
    const asset = currentProject();
    if (asset) await addTextures(asset, sidecars);
    else toast('Texturas precisam de um projeto: arraste-as junto com o modelo, ou abra o projeto antes de soltar.', 'erro');
    return;
  }

  if (state.project && models.length && !sidecars.length && models.every((m) => /\.fbx$/i.test(m.file.name))) {
    const what = models.length === 1 ? `"${models[0].file.name}"` : `${models.length} arquivos`;
    const asMixamo = confirm(`Importar ${what} como animação do Mixamo para ${currentProject()?.name}?\n\nOK: animação deste personagem.\nCancelar: criar um projeto novo com o arquivo.`);
    if (asMixamo) return importMixamo(models.map((m) => m.file));
  }

  for (const model of models) {
    // Com texturas na mesma leva, o laudo espera elas chegarem.
    const loose = sidecars.length > 0 && !/\.zip$/i.test(model.file.name);
    const query = `filename=${encodeURIComponent(model.file.name)}${loose ? '&defer=true' : ''}`;
    const out = await guard(() => api(`/api/assets?${query}`, { method: 'POST', body: model.file }));
    if (!out) continue;
    state.seen?.add(out.asset.id);
    let job = out.job;
    if (loose) {
      const sent = await sendSidecars(out.asset.id, sidecars, model.path);
      toast(`${out.asset.name}: ${sent} arquivo(s) de textura enviado(s) com o modelo.`);
      job = await guard(() => send('POST', `/api/assets/${out.asset.id}/inspect`));
    }
    if (job) state.myJobs.add(job.id);
    await refresh();
    select('asset', out.asset.id);
  }
}

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

for (const button of document.querySelectorAll('#tabs button')) {
  button.addEventListener('click', () => {
    // O projeto tem um personagem só: a aba já abre nele.
    if (button.dataset.tab === 'asset' && state.project) return select('asset', state.project);
    state.tab = button.dataset.tab;
    renderTabs();
    renderList();
  });
}

$('#open-shortcuts').addEventListener('click', () => guard(() => send('POST', '/api/open-shortcuts')));
$('#back-home').addEventListener('click', goHome);

refresh();
setInterval(refresh, 2000);
