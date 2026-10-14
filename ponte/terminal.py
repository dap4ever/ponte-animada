"""O terminal da tela: um por espaço, aberto na pasta dele. O jogo, cada personagem, cada asset e a tela de entrada.

É um PowerShell de verdade (ConPTY, pelo ``pywinpty``), parado no prompt da pasta de onde o dono
está na tela: a do jogo (``ponte/games.py``) na tela do jogo, a do personagem ou do asset quando
ele entra num, e a da própria ponte na tela de entrada (``HOME``). Cada um é um terminal à parte,
com a conversa dele. No primeiro formato dos jogos (13/10/2026) era um só por jogo, que acompanhava
a tela pelos personagens e pelos assets; no mesmo dia o dono pediu espaços separados: "o projeto
precisa ter espaços diferentes, por exemplo clico dentro do assets casa vc já saiba onde está e
que assets vai editar a mesma coisa para os personagens".
**Ele não chama nenhuma IA sozinho**: quem chama é o dono, e pode ser o ``claude`` ou outra (ordem
dele em 11/10/2026: "tem que vir apenas dentro da pasta, pronto para ser chamado, pois posso
querer usar outra IA"). Para a IA que entrar saber onde está e no que vai mexer, cada pasta ganha
um guia (``GUIDES``).

O terminal parado é leve, mas o que se chama nele não (um Claude Code são uns 250 MB e mais de
dez processos, com os conectores), então ele não fica para trás à toa:

- com alguém olhando, vive;
- sem ninguém olhando e sem que ninguém tenha escrito nele (o personagem foi aberto só para ver o
  modelo), fecha em ``GRACE`` segundos, o bastante para recarregar a página sem perdê-lo;
- com alguma coisa escrita, espera a volta: sair dali ou fechar a janela só solta a tela, e ao
  voltar o que já tinha sido escrito reaparece (``BACKLOG``). Só fecha depois de ``IDLE``
  segundos calado e sem ninguém olhando, ou quando o servidor para.

Um terminal na página é um shell na máquina. Por isso ele só atende à própria página da ponte:
a origem tem de ser local e o pedido tem de trazer o ``TOKEN`` deste servidor, que uma página de
outro site não consegue ler.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import threading
import time
from pathlib import Path

from . import games, store
from .config import ROOT, SETTINGS

TOKEN = secrets.token_urlsafe(24)
# O terminal da tela de entrada (pedido do dono em 13/10/2026: "adicione um terminal na home"). Não é
# de projeto nenhum: abre na pasta da ponte, onde o guia é o CLAUDE.md dela, que a ponte não regrava.
# O nome não se confunde com um projeto: o id de um projeto só tem letras, números e hífen.
HOME = "_home"
# Quanto do que o terminal já escreveu fica guardado para reaparecer ao reabrir a tela (caracteres).
BACKLOG = 400_000
# O guia de cada pasta, com o nome que cada IA procura: o Claude Code lê CLAUDE.md; o
# Codex, o opencode e outros leem AGENTS.md. O texto é o mesmo.
GUIDES = ("CLAUDE.md", "AGENTS.md")
# O que é só daquele personagem (onde está o trabalho dele, o que já foi aprovado) fica num arquivo
# escrito à mão na pasta do projeto. A ponte nunca o grava: o guia só aponta para ele.
NOTES = "NOTAS.md"
GUIDE_MARK = "<!-- gerado pela PonteAnimada; se editar, apague esta linha para a ponte nao regravar -->"
# Terminal em que ninguém escreveu, sem ninguém olhando: fecha depois deste tempo (segundos).
GRACE = 20.0
# Terminal em que alguém escreveu, sem ninguém olhando e calado (a IA trabalhando escreve): fecha
# depois deste tempo. Num terminal novo, `claude --continue` retoma a conversa do Claude.
IDLE = 3 * 3600.0
SWEEP = 5.0  # de quanto em quanto tempo os terminais são conferidos

_sessions: dict[str, "Session"] = {}
_lock = threading.Lock()
_sweeper: threading.Thread | None = None


def problem() -> str | None:
    """Por que o terminal não pode abrir, ou None."""
    if os.name != "nt":
        return "O terminal da ponte só existe no Windows."
    try:
        import winpty  # noqa: F401
    except ImportError:
        return "Falta o pywinpty no ambiente da ponte (rode `uv sync` na pasta dela)."
    return None


def _environment() -> dict[str, str]:
    """O ambiente do terminal: o do servidor, sem o que marcaria um Claude chamado ali como filho de outro.

    Se quem subiu o servidor foi uma sessão do Claude Code, as variáveis dela viriam junto e o
    Claude chamado no terminal se recusaria a abrir, ou abriria preso à sessão de fora.
    """
    keep = {"CLAUDE_CONFIG_DIR"}
    env = {k: v for k, v in os.environ.items() if not (k.upper().startswith(("CLAUDE", "MCP_")) and k.upper() not in keep)}
    env.pop("VIRTUAL_ENV", None)  # o ambiente Python é o que o `uv run` achar na pasta
    return env


def _facts(asset: dict) -> str:
    """O que o laudo diz do modelo, numa linha."""
    summary = asset.get("summary") or {}
    return ", ".join(
        part
        for part in (
            f"rig {summary['rig']}" if summary.get("rig") else "sem esqueleto",
            f"{summary['bones']} ossos" if summary.get("bones") else "",
            f"{summary['triangles']} triângulos" if summary.get("triangles") else "",
            f"{summary['height_m']:.2f} m de altura" if summary.get("height_m") else "",
        )
        if part
    )


def _mine(paths: list[Path]) -> list[Path]:
    """Dos guias de uma pasta, os que a ponte pode gravar: os que não existem e os que ainda têm a linha de marca."""
    return [path for path in paths if not path.exists() or path.read_text(encoding="utf-8", errors="replace").startswith(GUIDE_MARK)]


def _game_line(game_id: str | None) -> str:
    """De que jogo é um personagem ou um asset, para o guia dele: o jogo, a pasta dele na ponte e a do código."""
    if not game_id or not games.exists(game_id):
        return 'ainda não está em nenhum jogo: o dono escolhe na tela de entrada, em "Sem jogo".'
    game = games.get(game_id)
    code = game.get("code_path")
    where = (
        f"O código do jogo fica em `{code}`: antes de mexer lá, leia o `CLAUDE.md` ou o `AGENTS.md` de lá."
        if code
        else "A pasta do código do jogo ainda não foi dita."
    )
    return (
        f"**{game['name']}** (id `{game_id}`). O jogo inteiro, com a jogabilidade, é assunto do terminal\n"
        f"  do jogo (`{games.folder(game_id)}`); `uv run ponte game show {game_id}` lista os outros\n"
        f"  personagens e assets, com a pasta de cada um. {where}"
    )


def write_game_guide(game_id: str) -> list[Path]:
    """O guia da pasta do jogo: diz à IA chamada no terminal que jogo é, o que há nele e como mostrar o trabalho na tela.

    É regravado a cada tela que se liga ao terminal (``get``), porque o que há no jogo muda. Um
    guia escrito à mão (sem a linha de marca) não é tocado.
    """
    content = games.contents(game_id)
    game, folder = content["game"], games.folder(game_id)
    paths = [folder / name for name in GUIDES]
    mine = _mine(paths)
    if not mine:
        return paths

    tabs = content["tabs"]
    builtin = {tab["id"] for tab in games.BUILTIN_TABS}
    tab_names = {tab["id"]: tab["name"] for tab in tabs}

    def line(asset: dict) -> str:
        project = store.project_folder(asset["id"])
        notes = f" **Tem notas próprias: leia `{project / NOTES}` antes de mexer nele.**" if (project / NOTES).is_file() else ""
        tab = games.tab_of(game, asset, games.asset_tab_kind(asset))
        where_tab = f", na aba {tab_names[tab]}" if tab not in builtin else ""
        return f"- **{asset['name']}** (id `{asset['id']}`){where_tab}, em `{project}`: {_facts(asset)}.{notes}"

    def tab_line(tab: dict) -> str:
        if tab["kind"] == "personagens":
            what = f"de personagens · {len(tab['characters'])}"
        elif tab["kind"] == "assets":
            what = f"de assets · {len(tab['models'])} modelo(s) 3D, {len(tab['files'])} textura(s) e som(ns)"
        else:
            waiting = sum(1 for task in tab["tasks"] if task.get("status") != games.TASK_STATES[-1])
            what = f"de gestão · {waiting} tarefa(s) por fazer, {len(tab['tasks']) - waiting} feita(s), {len(tab['documents'])} documento(s)"
        return f"- **{tab['name']}** (id `{tab['id']}`): {what}"

    def document_line(document: dict) -> str:
        return f"  - **{document['name']}** (id `{document['id']}`), na aba {tab_names.get(games.tab_of(game, document, 'gestao'), '?')}: `{games.item_path(document)}`"

    characters = "\n".join(line(a) for a in content["characters"]) or "- (nenhum ainda)"
    models = "\n".join(line(a) for a in content["models"]) or "- (nenhum ainda)"
    if any(tab["kind"] == "gestao" for tab in tabs):
        documents = "\n".join(document_line(d) for d in content["documents"]) or "  - (nenhum ainda)"
        management = f"""Numa aba de gestão o dono vê um quadro de tarefas (A fazer, Fazendo, Feito) e os documentos do
jogo. É por ali que ele acompanha o que falta fazer; você lê e atualiza os dois por aqui.

- **As tarefas**: `uv run ponte game task list {game_id}` mostra o quadro de agora, com o id de
  cada uma. `uv run ponte game task add {game_id} "<título>" [--notes "<detalhe>"] [--tab "<aba>"]`
  cria uma; `uv run ponte game task move <id> a_fazer|fazendo|feito` muda de coluna;
  `uv run ponte game task edit <id> [--title "<título>"] [--notes "<detalhe>"]` corrige. A tela
  mostra em 2 segundos. O quadro é dele: não apague tarefa nem dê uma por feita sem ele dizer.
- **Os documentos**: textos do jogo (ideias, regras, roteiro de missão), um arquivo `.md` cada.
{documents}
  Para mudar um, grave o arquivo: a tela mostra o texto novo em 2 segundos. Ele também escreve
  ali, pelo botão "Editar": leia o arquivo de novo antes de gravar. Documento novo:
  `uv run ponte game doc {game_id} "<nome>" [--tab "<aba>"]` cria em branco e diz onde ficou o
  arquivo; um `.md` ou `.txt` que já existe entra com `uv run ponte game file {game_id} <arquivo>`."""
    else:
        management = f"""O jogo ainda não tem aba de gestão: é nela que ficam o quadro de tarefas (A fazer, Fazendo,
Feito) e os documentos do jogo. O dono cria pela tela ("+ Nova aba"); se ele pedir a você,
`uv run ponte game tab new {game_id} "Gestão" --kind gestao`."""
    code = game.get("code_path")
    where = (
        f"fica em `{code}`. A jogabilidade é feita por você, lá. Se aquela pasta tiver um `CLAUDE.md`\n  ou um `AGENTS.md`, leia antes de mexer: as regras de lá valem dentro dela."
        if code
        else f'ainda não tem pasta dita. Antes de mexer na jogabilidade, pergunte ao dono onde ele\n  fica e guarde com `uv run ponte game path {game_id} "<pasta>"`.'
    )
    text = f"""{GUIDE_MARK}
# Jogo: {game["name"]}

Você está no terminal da tela deste jogo na PonteAnimada. Quem escreve aqui é o dono do jogo,
olhando a tela ao lado: as abas do jogo, com os personagens, os assets e a gestão. Ele não é
programador: responda curto, em português, sem jargão. As regras e o histórico do trabalho estão em
`{ROOT / "CLAUDE.md"}`: leia as partes "Gestor de jogos" e "A tela nova" antes de começar.

- **Esta pasta** (`{folder}`, id `{game_id}`) é a do jogo dentro da ponte: é onde o terminal
  abre. Não é a pasta do código do jogo.
- **Aqui é o espaço do jogo inteiro**: a jogabilidade e o que envolve mais de um personagem ou
  asset. Cada personagem e cada asset tem o espaço dele: quando o dono entra num deles na tela, o
  terminal ao lado passa a ser o da pasta daquele, com outra conversa, e este fica esperando a
  volta. Se ele pedir aqui algo de um só, confirme de qual está falando.
- **O código do jogo** {where}
- **O que há no jogo agora**: `uv run ponte game show {game_id}`. As listas abaixo são de quando
  esta tela foi aberta.

## Characters (os personagens)

{characters}

Cada personagem tem a pasta dele: o modelo fica em `personagem/` e cada animação que está na
tela, numa pasta de `previas/`, com um `result.glb`.

## Assets

Modelos 3D (arma, objeto, cenário), cada um numa pasta igual à de um personagem:

{models}

Texturas: {len(content["textures"])}. Sons: {len(content["sounds"])}. Ficam em `{folder / games.ITEMS}`, uma
pasta por arquivo.

## As abas da tela

A tela do jogo é dividida em abas. Duas vêm com o jogo e as outras o dono cria, de três tipos:
de personagens, de assets e de gestão. As de agora:

{chr(10).join(tab_line(tab) for tab in tabs)}

- **Aba nova**: `uv run ponte game tab new {game_id} "<nome>" --kind personagens|assets|gestao`.
- **Pôr um personagem ou um modelo numa aba**: `uv run ponte game add {game_id} <id> --tab "<aba>"`
  (pelo nome ou pelo id da aba). A aba diz o que ele é: numa de personagens, personagem; numa de
  assets, modelo.
- Mudar o nome de uma aba e apagar uma é com o dono, na tela.

## Gestão: as tarefas e os documentos do jogo

{management}

## Como pôr o trabalho na tela dele

- **O Blender roda escondido, por você**, sem janela:
  `& "{SETTINGS.blender_exe}" --background <arquivo.blend> --python <script.py> -- <argumentos>`.
  O dono não abre o Blender: o que ele vê é o visor da ponte.
- **Animação de um personagem**: exporte um GLB com o personagem (e os acessórios) já animado e
  rode `uv run ponte anim add <id do personagem> <arquivo.glb> --name "<nome>"`. Ela entra na
  lista "Animações" dele em 2 segundos. `--replace` troca a de mesmo nome.
- **Ele testa como num jogo no simulador** (botão "Simular", na tela do personagem): anda com o
  personagem e as animações trocam sozinhas. O simulador escolhe pelo nome: `idle` é o parado,
  `walk` o andar, `run` o correr. Dê às animações os nomes que o jogo usa.
- **Animação do Mixamo** ele mesmo importa, pelo botão da tela do personagem.
- **Gerar movimento novo por texto**: `uv run ponte engine` diz qual gerador está em uso, e
  `uv run ponte gen "<texto em inglês>" --asset <id do personagem> --duration 5` gera com ele.
  O kimodo.cpp não faz laço nem direção: o ciclo é recortado e fechado no Blender.
- **Personagem novo**: `uv run ponte asset add <arquivo> --name "<nome>" --game {game_id}`.
- **Asset novo**: um modelo 3D entra com
  `uv run ponte asset add <arquivo> --name "<nome>" --game {game_id} --role modelo`; uma textura
  ou um som, com `uv run ponte game file {game_id} <arquivo> --name "<nome>"`.
- **Uma coisa de cada vez**: mostre na tela e espere o que ele achou antes da próxima.
"""
    for path in mine:
        path.write_text(text, encoding="utf-8", newline="\n")
    return paths


def write_guide(asset_id: str) -> list[Path]:
    """O guia da pasta de um personagem ou de um modelo 3D: diz à IA chamada ali que é nele que ela vai mexer e como mostrar o trabalho na tela.

    Sai com os nomes de ``GUIDES`` e é regravado a cada tela que se liga ao terminal (``get``): o
    jogo do projeto e o papel dele lá mudam. Um guia escrito à mão (sem a linha de marca) não é tocado.
    """
    asset = store.get("asset", asset_id)
    folder = store.project_folder(asset_id)
    paths = [folder / name for name in GUIDES]
    mine = _mine(paths)
    if not mine:
        return paths
    facts = _facts(asset)
    game_id = asset.get("game") if asset.get("game") and games.exists(asset["game"]) else None
    source = asset.get("source", "source/")
    blender = f"""- **O Blender roda escondido, por você**, sem janela:
  `& "{SETTINGS.blender_exe}" --background <arquivo.blend> --python <script.py> -- <argumentos>`.
  O dono não abre o Blender: o que ele vê é o visor da ponte."""
    if games.role_of(asset) == "modelo":
        kind, this = "Asset", "este asset"
        beside = f'`uv run ponte asset add <arquivo> --name "<nome>"{f" --game {game_id}" if game_id else ""} --role modelo`'
        body = f"""- **O modelo** (com as texturas ao lado): `personagem/{source}` ({facts}). A pasta se chama
  `personagem/` também num asset. O visor mostra `personagem/preview.glb`.
{blender}
- **Para o modelo mudado aparecer na tela dele**: guarde uma cópia do arquivo original fora de
  `personagem/source/`, grave o novo por cima, com o mesmo nome, e rode
  `uv run ponte asset inspect {asset_id}`: o laudo e o `preview.glb` são refeitos e o visor troca
  sozinho. Textura a mais para o modelo: `uv run ponte asset textures {asset_id} <arquivos>`.
- **Para mostrar uma versão ao lado, sem trocar esta**: {beside}.
- **Se ele for um personagem** (vai receber animação), quem o passa para Characters é o dono,
  pelo botão da tela.
- **Uma coisa de cada vez**: mostre na tela e espere o que ele achou antes da próxima."""
    else:
        kind, this = "Personagem", "este personagem"
        body = f"""- **O personagem** (FBX com as texturas): `personagem/{source}` ({facts}).
  O visor mostra `personagem/preview.glb` quando nenhuma animação está escolhida.
- **As animações da tela**: uma pasta em `previas/` para cada, com um `result.glb`.
{blender}
- **Para uma animação aparecer na tela dele**: exporte um GLB com o personagem (e os acessórios)
  já animado e rode `uv run ponte anim add {asset_id} <arquivo.glb> --name "<nome>"`.
  Ela entra na lista "Animações" em 2 segundos. `--replace` troca a de mesmo nome.
- **Ele testa como num jogo no simulador** (botão "Simular" da tela): anda com o personagem e as
  animações trocam sozinhas. O simulador escolhe pelo nome: `idle` é o parado, `walk` o andar,
  `run` o correr. Dê às animações os nomes que o jogo usa.
- **Animação do Mixamo** ele mesmo importa, pelo botão da tela.
- **Gerar movimento novo por texto**: `uv run ponte engine` diz qual gerador está em uso, e
  `uv run ponte gen "<texto em inglês>" --asset {asset_id} --duration 5` gera com ele.
  O kimodo.cpp não faz laço nem direção: o ciclo é recortado e fechado no Blender.
- **Uma animação de cada vez**: mostre na tela e espere o que ele achou antes da próxima."""
    notes = f"\n**{this.capitalize()} tem notas próprias: leia `{NOTES}`, nesta pasta, antes de mexer em qualquer coisa.**\n" if (folder / NOTES).is_file() else ""
    text = f"""{GUIDE_MARK}
# {kind}: {asset["name"]}

Você está no espaço d{this} na PonteAnimada: o dono entrou nele na tela e o terminal ao lado
abriu aqui, na pasta dele. **É n{this} que você vai mexer**: o que ele pedir sem dizer o nome é
sobre ele. Quem escreve é o dono, olhando o visor 3D ao lado do terminal. Ele não é programador:
responda curto, em português, sem jargão. As regras e o histórico do trabalho estão em
`{ROOT / "CLAUDE.md"}`: leia as partes "Gestor de jogos" e "A tela nova" antes de começar.
{notes}
- **Esta pasta**: `{folder}` (id `{asset_id}`). Cada personagem e cada asset tem a pasta e o
  terminal dele.
- **O jogo**: {_game_line(game_id)}
{body}
"""
    for path in mine:
        path.write_text(text, encoding="utf-8", newline="\n")
    return paths


def write_item_guide(item_id: str) -> list[Path]:
    """O guia da pasta de uma textura ou de um som: diz à IA chamada ali que é naquele arquivo que ela vai mexer.

    Como os outros: regravado a cada tela que se liga, menos o que foi escrito à mão.
    """
    item = games.get_item(item_id)
    folder = games.item_folder(item_id)
    paths = [folder / name for name in GUIDES]
    mine = _mine(paths)
    if not mine:
        return paths
    sound = item["kind"] == "som"
    text = f"""{GUIDE_MARK}
# Documento: {item["name"]}

Você está no espaço deste documento na PonteAnimada: o dono entrou nele na tela e o terminal ao
lado abriu aqui, na pasta dele. **É neste documento que você vai mexer**: o que ele pedir sem
dizer o nome é sobre ele. Quem escreve é o dono, lendo o documento ao lado do terminal. Ele não é
programador: responda curto, em português, sem jargão. As regras e o histórico do trabalho estão
em `{ROOT / "CLAUDE.md"}`: leia a parte "Gestor de jogos" antes de começar.

- **Esta pasta**: `{folder}` (id `{item_id}`). Cada personagem, cada asset e cada documento tem a
  pasta e o terminal dele.
- **O arquivo**: `{item["file"]}`, um texto em Markdown. `item.json`, ao lado, é o registro da
  ponte: não apague nem mude de lugar.
- **O jogo**: {_game_line(item.get("game"))}
- **Para a mudança aparecer na tela dele**: grave o arquivo. A tela mostra o texto novo em 2
  segundos, sem recarregar. Ele também escreve ali, pelo botão "Editar": leia o arquivo de novo
  antes de gravar, para não passar por cima do que ele escreveu.
- **O que a tela mostra do Markdown**: títulos (`#`), listas (`-` e `1.`), caixas de marcar
  (`- [ ]` e `- [x]`), negrito, itálico, `código`, blocos de código, citações (`>`), links, linha
  (`---`) e tabelas simples. HTML não é mostrado.
- **As tarefas do jogo** não ficam aqui: estão no quadro da aba de gestão
  (`uv run ponte game task list {item["game"]}`).
- **Uma coisa de cada vez**: mostre na tela e espere o que ele achou antes da próxima.
""" if item["kind"] == games.DOCUMENT else f"""{GUIDE_MARK}
# Asset: {item["name"]} ({item["kind"]})

Você está no espaço deste asset na PonteAnimada: o dono entrou nele na tela e o terminal ao lado
abriu aqui, na pasta dele. **É neste arquivo que você vai mexer**: o que ele pedir sem dizer o
nome é sobre ele. Quem escreve é o dono, olhando {"o tocador do som" if sound else "a imagem"} ao lado do terminal. Ele não é
programador: responda curto, em português, sem jargão. As regras e o histórico do trabalho estão
em `{ROOT / "CLAUDE.md"}`: leia a parte "Gestor de jogos" antes de começar.

- **Esta pasta**: `{folder}` (id `{item_id}`). Cada personagem e cada asset tem a pasta e o
  terminal dele.
- **O arquivo**: `{item["file"]}` ({"um som" if sound else "uma textura"}). O nome dele é o que o jogo usa: não mude.
  `item.json`, ao lado, é o registro da ponte: não apague nem mude de lugar.
- **O jogo**: {_game_line(item.get("game"))}
- **Para a mudança aparecer na tela dele**: guarde uma cópia do original fora desta pasta e grave
  o novo por cima, com o mesmo nome. A tela mostra o novo quando ele recarregar a página (Ctrl+R).
- **Para mostrar uma versão ao lado, sem trocar esta**:
  `uv run ponte game file {item["game"]} <arquivo> --name "<nome>"`.
- **Uma coisa de cada vez**: mostre na tela e espere o que ele achou antes da próxima.
"""
    for path in mine:
        path.write_text(text, encoding="utf-8", newline="\n")
    return paths


def folder(target: str) -> Path:
    """A pasta em que o terminal abre: a da ponte, a do jogo, a do personagem ou do modelo, a da textura ou do som."""
    if target == HOME:
        return ROOT
    if games.exists(target):
        return games.folder(target)
    if games.has_item(target):
        return games.item_folder(target)
    return store.project_folder(target)


def _write_guide_of(target: str) -> None:
    """O guia da pasta, regravado a cada tela que se liga: o que há no jogo muda, e o jogo e o papel de um projeto também."""
    if target == HOME:
        return  # o guia da pasta da ponte é o CLAUDE.md dela
    if games.exists(target):
        write_game_guide(target)
    elif games.has_item(target):
        write_item_guide(target)
    else:
        write_guide(target)


class Session:
    """O terminal de um espaço (um jogo, um personagem, um asset ou a tela de entrada): o processo, o que ele já escreveu e quem está olhando."""

    def __init__(self, target: str):
        from winpty import PtyProcess

        self.target = target
        self.cwd = folder(target)  # o guia da pasta é gravado em ``get``, a cada tela que se liga
        # Só o prompt, na pasta do espaço: a IA é chamada por quem está na tela. "Bypass" deixa
        # rodar as que se instalam como script (.ps1), que a regra padrão do Windows barraria.
        command = ["powershell.exe", "-NoLogo", "-ExecutionPolicy", "Bypass"]
        self.proc = PtyProcess.spawn(command, cwd=str(self.cwd), env=_environment(), dimensions=(30, 110))
        self.backlog = ""
        self.listeners: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}
        self.lock = threading.Lock()
        self.closed = False
        self.touched = False  # alguém já escreveu aqui?
        self.answered = False  # alguma tela já se ligou (e respondeu às perguntas que o programa faz ao terminal)?
        self.alone_since = self.last_output = time.monotonic()
        threading.Thread(target=self._pump, name=f"terminal-{target}", daemon=True).start()

    def _pump(self) -> None:
        """Lê o que o terminal escreve e entrega a quem está olhando."""
        while True:
            try:
                data = self.proc.read(8192)
            except Exception:  # noqa: BLE001 - EOFError ao fechar; qualquer outro erro também encerra
                break
            if not data:
                if not self.proc.isalive():
                    break
                continue
            self._deliver(data)
        self.closed = True
        self._deliver(None)
        with _lock:
            if _sessions.get(self.target) is self:
                del _sessions[self.target]

    def _deliver(self, data: str | None) -> None:
        with self.lock:
            if data is not None:
                self.backlog = (self.backlog + data)[-BACKLOG:]
                self.last_output = time.monotonic()
            listeners = list(self.listeners.items())
        for queue, loop in listeners:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, data)
            except RuntimeError:  # o laço daquela tela já fechou
                pass

    def attach(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> tuple[str, bool]:
        """Liga uma tela ao terminal. Devolve o que já foi escrito, para ela começar de onde está, e se outra tela já o tinha lido.

        O que já foi escrito traz as perguntas que o programa fez ao terminal (que tipo ele é, onde
        está o cursor). A primeira tela precisa respondê-las; as seguintes, não: a resposta repetida
        chegaria ao programa como texto digitado ("[?1;2c" no prompt, ao voltar à tela).
        """
        with self.lock:
            self.listeners[queue] = loop
            seen, self.answered = self.answered, True
            return self.backlog, seen

    def detach(self, queue: asyncio.Queue) -> None:
        with self.lock:
            self.listeners.pop(queue, None)
            if not self.listeners:
                self.alone_since = time.monotonic()

    def expected(self) -> None:
        """Uma tela vem aí: conta de novo o prazo de quem está sem ninguém olhando."""
        with self.lock:
            self.alone_since = time.monotonic()

    def expired(self, now: float) -> bool:
        """Já pode fechar? Ver ``GRACE`` e ``IDLE``."""
        with self.lock:
            if self.listeners:
                return False
            if not self.touched:
                return now - self.alone_since >= GRACE
            return now - max(self.alone_since, self.last_output) >= IDLE

    def write(self, data: str) -> None:
        if not data or self.closed:
            return
        # O que começa com ESC é a tela respondendo ao programa (foco, tamanho, setas), não alguém escrevendo.
        if not data.startswith("\x1b"):
            self.touched = True
        self.proc.write(data)

    def resize(self, cols: int, rows: int) -> None:
        if self.closed:
            return
        try:
            self.proc.setwinsize(max(2, min(rows, 400)), max(10, min(cols, 600)))
        except Exception:  # noqa: BLE001 - o processo pode ter acabado de fechar
            pass

    def kill(self) -> None:
        """Fecha o terminal e tudo o que nasceu dele: a IA chamada ali e os programas que ela abriu.

        Só volta com o PowerShell encerrado: enquanto ele vive, o Windows não deixa apagar a pasta
        em que ele está.
        """
        self.closed = True
        pid = getattr(self.proc, "pid", None)
        if pid:
            # Encerrar só o PowerShell deixaria a IA e os conectores dela rodando sem dono.
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        try:
            self.proc.close(force=True)
        except Exception:  # noqa: BLE001 - já estava fechado
            pass
        # O console por trás (OpenConsole.exe) só sai quando a leitura do pywinpty para: fechar os
        # dois lados da ligação apressa isso, em vez de esperar o Python recolher o objeto.
        for name in ("fileobj", "_server"):
            try:
                getattr(self.proc, name).close()
            except Exception:  # noqa: BLE001
                pass
        for _ in range(30):
            try:
                if not self.proc.isalive():
                    break
            except Exception:  # noqa: BLE001
                break
            time.sleep(0.1)


def _close_expired() -> None:
    """Fecha os terminais que ninguém usa mais (``Session.expired``)."""
    now = time.monotonic()
    with _lock:
        gone = [session for session in _sessions.values() if session.expired(now)]
        for session in gone:
            del _sessions[session.target]
    for session in gone:
        session.kill()


def _sweep() -> None:
    while True:
        time.sleep(SWEEP)
        _close_expired()


def known(target: str) -> bool:
    """Há o que abrir com este nome? A tela de entrada, um jogo, um projeto, uma textura ou um som."""
    if target == HOME or games.exists(target) or games.has_item(target):
        return True
    try:
        store.get("asset", target)
    except (KeyError, ValueError):
        return False
    return True


def get(target: str) -> Session:
    """O terminal do espaço (o jogo, o personagem, o asset ou a entrada), criado na primeira vez."""
    global _sweeper
    _write_guide_of(target)
    with _lock:
        session = _sessions.get(target)
        if session is None or session.closed:
            session = _sessions[target] = Session(target)
        session.expected()  # quem pediu vai se ligar em seguida: a faxina não fecha no meio
        if _sweeper is None:
            _sweeper = threading.Thread(target=_sweep, name="terminal-faxina", daemon=True)
            _sweeper.start()
        return session


def restart(target: str) -> None:
    """Fecha o terminal. O próximo que abrir a tela recebe um novo."""
    with _lock:
        session = _sessions.pop(target, None)
    if session:
        session.kill()


def close_all() -> None:
    with _lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    for session in sessions:
        session.kill()


def status() -> dict:
    with _lock:
        sessions = list(_sessions.values())
    return {
        "problem": problem(),
        "home": HOME,  # o nome do terminal da tela de entrada, que aparece em "open" e "talking" como os outros
        "items": True,  # textura e som também têm terminal (a página pergunta: o servidor de antes não tinha)
        "open": sorted(session.target for session in sessions),
        "talking": sorted(session.target for session in sessions if session.touched),  # onde alguém já escreveu
    }
