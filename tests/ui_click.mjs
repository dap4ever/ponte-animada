// Dirige a interface com cliques de verdade, pelo protocolo de depuração do Edge, e mostra o
// que aparece: serve para conferir os botões que uma captura parada não testa.
//
//   node tests/ui_click.mjs <url> <pasta das capturas> <passo>...
//
// Cada passo é "click:<seletor css>", "clicktext:<seletor>|<texto>", "file:<seletor>|<arquivo>"
// (escolhe um arquivo num campo de envio), "wait:<ms>", "shot:<nome>", "eval:<expressão js>"
// "time" (lê o relógio do visualizador) ou "dialogs:accept" / "dialogs:dismiss" (o que
// responder às caixas de confirmação que aparecerem dali em diante; o padrão é aceitar).

import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [url, outDir, ...steps] = process.argv.slice(2);
const edge = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe'];
const port = 9300 + Math.floor(Math.random() * 500);
const profile = mkdtempSync(join(tmpdir(), 'ponte-cdp-'));
const { existsSync } = await import('node:fs');
const exe = edge.find((p) => existsSync(p));
// Sem estas opções o navegador sem janela para de animar a página uns 10 s depois de abri-la.
const awake = ['--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows', '--disable-background-timer-throttling', '--disable-features=CalculateNativeWinOcclusion'];
const browser = spawn(exe, ['--headless=new', ...awake, `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--window-size=1500,1000', 'about:blank'], { stdio: 'ignore' });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 50 && !target; i++) {
  await sleep(200);
  try {
    target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === 'page');
  } catch { /* ainda subindo */ }
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r));
let seq = 0;
let acceptDialogs = true;
const pending = new Map();
ws.addEventListener('message', (e) => {
  const msg = JSON.parse(e.data);
  // Erros da página: é o que explica um botão que "não faz nada".
  if (msg.method === 'Runtime.exceptionThrown') {
    const d = msg.params.exceptionDetails;
    console.log('ERRO NA PAGINA:', d.exception?.description?.split('\n').slice(0, 4).join(' | ') || d.text);
  }
  if (msg.method === 'Runtime.consoleAPICalled' && ['error', 'warning', 'log'].includes(msg.params.type)) {
    console.log(`console.${msg.params.type}:`, msg.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300));
  }
  // Caixa de confirmação: sem resposta a página fica parada nela.
  if (msg.method === 'Page.javascriptDialogOpening') {
    console.log(`dialogo (${acceptDialogs ? 'OK' : 'Cancelar'}):`, msg.params.message.replace(/\n/g, ' | ').slice(0, 300));
    ws.send(JSON.stringify({ id: ++seq, method: 'Page.handleJavaScriptDialog', params: { accept: acceptDialogs } }));
  }
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
});
const send = (method, params = {}) => new Promise((resolve) => {
  const id = ++seq;
  pending.set(id, resolve);
  ws.send(JSON.stringify({ id, method, params }));
});
const evaluate = async (expression) => {
  const out = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  return out.result?.result?.value ?? out.result?.exceptionDetails?.text ?? null;
};

await send('Runtime.enable');
await send('Page.enable');
// Sem janela, a página é dada como fora de foco e a animação para depois de uns 10 s: aqui ela
// fica como a de um usuário olhando para a tela.
await send('Emulation.setFocusEmulationEnabled', { enabled: true });
await send('Page.setWebLifecycleState', { state: 'active' });
await send('Emulation.setDeviceMetricsOverride', { width: 1500, height: 1000, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url });
// Espera o modelo carregar. Na tela nova o visor avisa (data-visor no body) e a tela de projetos não
// tem o que esperar; na antiga (/antiga/) o relógio passa a mostrar o tempo do clipe
// ("1.23 / 20.00 s · quadro 37").
for (let i = 0; i < 150; i++) {
  await sleep(400);
  const ready = await evaluate("document.body.dataset.visor || (!/^#(p|asset|result|final)\\//.test(location.hash) && document.querySelector('#home') && !document.querySelector('#home').hidden ? 'entrada' : '') || (/ s · quadro/.test(document.querySelector('#time')?.textContent || '') ? 'relogio' : '')");
  if (ready && i > 3) break;
}

for (const step of steps) {
  const [kind, ...rest] = step.split(':');
  const arg = rest.join(':');
  if (kind === 'wait') await sleep(Number(arg));
  else if (kind === 'dialogs') acceptDialogs = arg === 'accept';
  else if (kind === 'click') console.log('click', arg, '->', await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(arg)}); if (!el) return 'NAO ACHEI'; el.click(); return 'ok'; })()`));
  else if (kind === 'clicktext') {
    const [selector, wanted] = arg.split('|');
    console.log('clicktext', wanted, '->', await evaluate(`(() => { const el = [...document.querySelectorAll(${JSON.stringify(selector)})].find((e) => e.textContent.includes(${JSON.stringify(wanted)})); if (!el) return 'NAO ACHEI'; el.click(); return 'ok'; })()`));
  } else if (kind === 'file') {
    // Escolhe um arquivo num <input type="file">, como se a pessoa o tivesse selecionado.
    const [selector, file] = arg.split('|');
    const { result: doc } = await send('DOM.getDocument');
    const { result: node } = await send('DOM.querySelector', { nodeId: doc.root.nodeId, selector });
    const out = node?.nodeId ? await send('DOM.setFileInputFiles', { nodeId: node.nodeId, files: [file] }) : { error: { message: 'NAO ACHEI' } };
    console.log('file', selector, '->', out.error ? out.error.message : 'ok');
  } else if (kind === 'time') console.log('relogio:', await evaluate("document.querySelector('#time').textContent"));
  else if (kind === 'eval') console.log('eval:', JSON.stringify(await evaluate(arg)));
  else if (kind === 'shot') {
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(join(outDir, `${arg}.png`), Buffer.from(shot.result.data, 'base64'));
    console.log('captura', `${arg}.png`);
  }
}
ws.close();
browser.kill();
process.exit(0);
