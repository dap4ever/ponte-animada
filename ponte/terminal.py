"""Um terminal por projeto, aberto na pasta dele, dentro da tela.

É um PowerShell de verdade (ConPTY, pelo ``pywinpty``), parado no prompt da pasta do projeto.
**Ele não chama nenhuma IA sozinho**: quem chama é o dono, e pode ser o ``claude`` ou outra (ordem
dele em 11/10/2026: "tem que vir apenas dentro da pasta, pronto para ser chamado, pois posso
querer usar outra IA"). Para a IA que entrar saber onde está, a pasta do projeto ganha um guia
(``GUIDES``).

O terminal parado é leve, mas o que se chama nele não (um Claude Code são uns 250 MB e mais de
dez processos, com os conectores), então ele não fica para trás à toa:

- com alguém olhando, vive;
- sem ninguém olhando e sem que ninguém tenha escrito nele (o projeto foi aberto só para ver o
  modelo), fecha em ``GRACE`` segundos, o bastante para recarregar a página sem perdê-lo;
- com alguma coisa escrita, espera a volta: trocar de projeto ou fechar a janela só solta a
  tela, e ao voltar o que já tinha sido escrito reaparece (``BACKLOG``). Só fecha depois de
  ``IDLE`` segundos calado e sem ninguém olhando, ou quando o servidor para.

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

from . import store
from .config import ROOT, SETTINGS

TOKEN = secrets.token_urlsafe(24)
# Quanto do que o terminal já escreveu fica guardado para reaparecer ao reabrir a tela (caracteres).
BACKLOG = 400_000
# O guia da pasta do projeto, com o nome que cada IA procura: o Claude Code lê CLAUDE.md; o
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


def write_guide(asset_id: str) -> list[Path]:
    """O guia da pasta do projeto: diz à IA chamada no terminal onde ela está e como mostrar o trabalho na tela.

    Sai com os nomes de ``GUIDES``. Um guia escrito à mão (sem a linha de marca) não é tocado.
    """
    asset = store.get("asset", asset_id)
    folder = store.project_folder(asset_id)
    paths = [folder / name for name in GUIDES]
    mine = [path for path in paths if not path.exists() or path.read_text(encoding="utf-8", errors="replace").startswith(GUIDE_MARK)]
    if not mine:
        return paths
    summary = asset.get("summary") or {}
    facts = ", ".join(
        part
        for part in (
            f"rig {summary['rig']}" if summary.get("rig") else "sem esqueleto",
            f"{summary['bones']} ossos" if summary.get("bones") else "",
            f"{summary['triangles']} triângulos" if summary.get("triangles") else "",
            f"{summary['height_m']:.2f} m de altura" if summary.get("height_m") else "",
        )
        if part
    )
    notes = f"\n**Este personagem tem notas próprias: leia `{NOTES}`, nesta pasta, antes de mexer em qualquer coisa.**\n" if (folder / NOTES).is_file() else ""
    text = f"""{GUIDE_MARK}
# Projeto: {asset["name"]}

Você está no terminal da tela deste projeto na PonteAnimada. Quem escreve aqui é o dono do
projeto, olhando o visor 3D ao lado do terminal. Ele não é programador: responda curto, em
português, sem jargão. As regras e o histórico do trabalho estão em `{ROOT / "CLAUDE.md"}`:
leia a parte "A tela nova" antes de começar.
{notes}
- **Pasta do projeto**: `{folder}` (id `{asset_id}`). Cada personagem é um projeto separado.
- **O personagem** (FBX com as texturas): `personagem/{asset.get("source", "source/")}` ({facts}).
  O visor mostra `personagem/preview.glb` quando nenhuma animação está escolhida.
- **As animações da tela**: uma pasta em `previas/` para cada, com um `result.glb`.
- **O Blender roda escondido, por você**, sem janela:
  `& "{SETTINGS.blender_exe}" --background <arquivo.blend> --python <script.py> -- <argumentos>`.
  O dono não abre o Blender: o que ele vê é o visor da ponte.
- **Para uma animação aparecer na tela dele**: exporte um GLB com o personagem (e os acessórios)
  já animado e rode `uv run ponte anim add {asset_id} <arquivo.glb> --name "<nome>"`.
  Ela entra na lista "Animações" em 2 segundos. `--replace` troca a de mesmo nome.
- **Animação do Mixamo** ele mesmo importa, pelo botão da tela.
- **Gerar movimento novo por texto**: `uv run ponte engine` diz qual gerador está em uso, e
  `uv run ponte gen "<texto em inglês>" --asset {asset_id} --duration 5` gera com ele.
  O kimodo.cpp não faz laço nem direção: o ciclo é recortado e fechado no Blender.
- **Uma animação de cada vez**: mostre na tela e espere o que ele achou antes da próxima.
"""
    for path in mine:
        path.write_text(text, encoding="utf-8", newline="\n")
    return paths


class Session:
    """O terminal de um projeto: o processo, o que ele já escreveu e quem está olhando."""

    def __init__(self, asset_id: str):
        from winpty import PtyProcess

        self.asset_id = asset_id
        self.cwd = store.project_folder(asset_id)
        write_guide(asset_id)
        # Só o prompt, na pasta do projeto: a IA é chamada por quem está na tela. "Bypass" deixa
        # rodar as que se instalam como script (.ps1), que a regra padrão do Windows barraria.
        command = ["powershell.exe", "-NoLogo", "-ExecutionPolicy", "Bypass"]
        self.proc = PtyProcess.spawn(command, cwd=str(self.cwd), env=_environment(), dimensions=(30, 110))
        self.backlog = ""
        self.listeners: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}
        self.lock = threading.Lock()
        self.closed = False
        self.touched = False  # alguém já escreveu aqui?
        self.alone_since = self.last_output = time.monotonic()
        threading.Thread(target=self._pump, name=f"terminal-{asset_id}", daemon=True).start()

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
            if _sessions.get(self.asset_id) is self:
                del _sessions[self.asset_id]

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

    def attach(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> str:
        """Liga uma tela ao terminal. Devolve o que já foi escrito, para ela começar de onde está."""
        with self.lock:
            self.listeners[queue] = loop
            return self.backlog

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
        do projeto, que é onde ele está.
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
            del _sessions[session.asset_id]
    for session in gone:
        session.kill()


def _sweep() -> None:
    while True:
        time.sleep(SWEEP)
        _close_expired()


def get(asset_id: str) -> Session:
    """O terminal do projeto, criado na primeira vez."""
    global _sweeper
    with _lock:
        session = _sessions.get(asset_id)
        if session is None or session.closed:
            session = _sessions[asset_id] = Session(asset_id)
        session.expected()  # quem pediu vai se ligar em seguida: a faxina não fecha no meio
        if _sweeper is None:
            _sweeper = threading.Thread(target=_sweep, name="terminal-faxina", daemon=True)
            _sweeper.start()
        return session


def restart(asset_id: str) -> None:
    """Fecha o terminal do projeto. O próximo que abrir a tela recebe um novo."""
    with _lock:
        session = _sessions.pop(asset_id, None)
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
        "open": sorted(session.asset_id for session in sessions),
        "talking": sorted(session.asset_id for session in sessions if session.touched),  # onde alguém já escreveu
    }
