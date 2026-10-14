// Mostra um texto em Markdown como elementos da página, sem passar por HTML: o que estiver escrito
// no documento nunca vira marcação nem script. Cobre o que um documento de jogo usa: títulos,
// parágrafos, listas (com caixas de marcar), citações, blocos de código, linha, tabelas simples,
// negrito, itálico, riscado, `código` e links.
//
//   renderMarkdown(texto, { onToggle(linha, marcada) })  ->  DocumentFragment
//
// `onToggle` é chamado quando alguém clica numa caixa de marcar; `linha` é a posição dela no texto
// (contando de 0, com o texto partido em "\n"). Sem ele, as caixas ficam só para ler.

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
  node.append(...children.flat().filter((child) => child != null && child !== false));
  return node;
}

// --- Dentro da linha -------------------------------------------------------------------------

const INLINE = [
  // [o que procurar, como mostrar o que achou]
  [/`([^`\n]+)`/, (m) => el('code', {}, m[1])],
  [/\[([^\]\n]+)\]\(([^)\s]+)\)/, (m) => link(m[2], inline(m[1]))],
  [/\*\*([^\n]+?)\*\*/, (m) => el('strong', {}, inline(m[1]))],
  [/__([^\n]+?)__/, (m) => el('strong', {}, inline(m[1]))],
  [/~~([^\n]+?)~~/, (m) => el('del', {}, inline(m[1]))],
  [/\*([^\s*][^*\n]*?)\*/, (m) => el('em', {}, inline(m[1]))],
  [/(?<![\p{L}\p{N}_])_([^\s_][^_\n]*?)_(?![\p{L}\p{N}_])/u, (m) => el('em', {}, inline(m[1]))],
  [/https?:\/\/[^\s<>()]*[^\s<>().,;:!?'"]/, (m) => link(m[0], [m[0]])],
];

// Só endereço de página ou de e-mail vira link: o resto fica como texto.
function link(href, children) {
  if (!/^(https?:\/\/|mailto:)/i.test(href)) return el('span', {}, children);
  return el('a', { href, target: '_blank', rel: 'noopener noreferrer' }, children);
}

function inline(text) {
  const out = [];
  let rest = text;
  while (rest) {
    let first = null;
    for (const [pattern, show] of INLINE) {
      const match = pattern.exec(rest);
      if (match && (!first || match.index < first.match.index)) first = { match, show };
    }
    if (!first) break;
    if (first.match.index) out.push(rest.slice(0, first.match.index));
    out.push(first.show(first.match));
    rest = rest.slice(first.match.index + first.match[0].length);
  }
  if (rest) out.push(rest);
  return out;
}

// Várias linhas de um parágrafo: cada quebra de linha do texto é uma quebra na tela.
function lines(rows) {
  return rows.flatMap((row, index) => (index ? [el('br'), ...inline(row)] : inline(row)));
}

// --- Os blocos -------------------------------------------------------------------------------

const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const FENCE = /^\s*(```|~~~)/;
const QUOTE = /^\s*>\s?/;
const ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const TABLE_RULE = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/;
const BOX = /^\[( |x|X)\]\s+(.*)$/;

const indentOf = (line) => line.match(/^\s*/)[0].replace(/\t/g, '    ').length;
const cells = (line) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
const startsBlock = (line) => HEADING.test(line) || RULE.test(line) || FENCE.test(line) || QUOTE.test(line) || ITEM.test(line);

// `rows` são as linhas do texto e `offset`, a posição da primeira delas no texto inteiro (uma
// citação é lida de novo por dentro, e as caixas de marcar precisam saber a linha de verdade).
function blocks(rows, offset, options) {
  const out = [];
  let i = 0;
  while (i < rows.length) {
    const line = rows[i];
    if (!line.trim()) {
      i += 1;
    } else if (FENCE.test(line)) {
      const mark = line.match(FENCE)[1];
      const body = [];
      i += 1;
      while (i < rows.length && !rows[i].trim().startsWith(mark)) body.push(rows[i++]);
      i += 1;
      out.push(el('pre', {}, el('code', {}, body.join('\n'))));
    } else if (HEADING.test(line)) {
      const [, marks, title] = line.match(HEADING);
      out.push(el(`h${marks.length}`, {}, inline(title)));
      i += 1;
    } else if (RULE.test(line)) {
      out.push(el('hr'));
      i += 1;
    } else if (QUOTE.test(line)) {
      const start = i;
      const body = [];
      while (i < rows.length && QUOTE.test(rows[i])) body.push(rows[i++].replace(QUOTE, ''));
      out.push(el('blockquote', {}, blocks(body, offset + start, options)));
    } else if (ITEM.test(line)) {
      const [list, next] = listAt(rows, i, offset, options);
      out.push(list);
      i = next;
    } else if (line.includes('|') && i + 1 < rows.length && TABLE_RULE.test(rows[i + 1]) && rows[i + 1].includes('-')) {
      const head = cells(line);
      const body = [];
      i += 2;
      while (i < rows.length && rows[i].trim() && rows[i].includes('|')) body.push(cells(rows[i++]));
      out.push(
        el('table', {}, el('thead', {}, el('tr', {}, head.map((cell) => el('th', {}, inline(cell))))), el('tbody', {}, body.map((row) => el('tr', {}, head.map((_, column) => el('td', {}, inline(row[column] || ''))))))),
      );
    } else {
      const body = [];
      while (i < rows.length && rows[i].trim() && !(body.length && startsBlock(rows[i]))) body.push(rows[i++].trim());
      out.push(el('p', {}, lines(body)));
    }
  }
  return out;
}

// Uma lista, a partir da linha `start`. Devolve a lista e a linha em que ela acaba. Um item mais
// para dentro abre uma lista dentro do item de cima.
function listAt(rows, start, offset, options) {
  const [, lead, marker] = rows[start].match(ITEM);
  const indent = indentOf(lead);
  const numbered = /\d/.test(marker);
  const list = el(numbered ? 'ol' : 'ul');
  let i = start;
  let item = null;
  while (i < rows.length) {
    const line = rows[i];
    if (!line.trim()) {
      // Uma linha em branco só continua a lista se depois dela vier outro item, ou texto para dentro.
      const next = rows.slice(i + 1).find((row) => row.trim());
      if (next === undefined || indentOf(next) < indent || (indentOf(next) === indent && !ITEM.test(next))) break;
      i += 1;
      continue;
    }
    const found = line.match(ITEM);
    const depth = indentOf(line);
    if (found && depth > indent + 1 && item) {
      const [inner, next] = listAt(rows, i, offset, options);
      item.append(inner);
      i = next;
    } else if (found && depth >= indent - 1 && depth <= indent + 1) {
      if (/\d/.test(found[2]) !== numbered) break; // de "-" para "1." (ou o contrário) começa outra lista
      const box = found[3].match(BOX);
      const row = offset + i;
      item = el('li', {});
      if (box) {
        item.className = 'check';
        const input = el('input', { type: 'checkbox', checked: box[1] !== ' ', disabled: !options.onToggle, onchange: (e) => options.onToggle(row, e.target.checked) });
        item.append(el('label', {}, input, el('span', {}, inline(box[2]))));
      } else item.append(...inline(found[3]));
      list.append(item);
      i += 1;
    } else if (!found && depth > indent && item) {
      item.append(el('br'), ...inline(line.trim())); // o texto do item continua na linha de baixo
      i += 1;
    } else break;
  }
  if (numbered) {
    const first = Number(marker.slice(0, -1));
    if (first !== 1) list.start = first;
  }
  return [list, i];
}

export function renderMarkdown(text, options = {}) {
  const fragment = document.createDocumentFragment();
  fragment.append(...blocks(String(text ?? '').replace(/\r\n?/g, '\n').split('\n'), 0, options));
  return fragment;
}
