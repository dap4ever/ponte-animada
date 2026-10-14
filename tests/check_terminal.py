"""O terminal da tela: um por espaço, parado na pasta dele (a do jogo, a do personagem ou do modelo 3D, a
da textura, do som ou do documento, e a da ponte na tela de entrada); só atende à própria página e não fica para trás.

Sobe um servidor próprio (porta 8767) num acervo descartável (PONTE_DATA), com dois projetos de
mentira, e fala com o terminal pelo mesmo caminho da página (WebSocket). O jogo, a textura e o som
são criados pela API, como a tela faz. Não usa o Blender e não chama IA nenhuma. Leva uns 3
minutos, por causa das esperas da faxina (``terminal.GRACE``).

    uv run python tests/check_terminal.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parent.parent
PORT = 8767
BASE = f"127.0.0.1:{PORT}"
KEEP, DROP = "teste-fica-0001", "teste-some-0002"
MARK = "<!-- gerado pela PonteAnimada"
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|[\x00-\x08\x0b-\x1f]")
# O que um terminal parado tem: o PowerShell e o console por trás dele. Mais que isso é algo chamado sozinho.
BARE = {"powershell.exe", "OpenConsole.exe"}


def api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode() if method in ("POST", "PATCH", "PUT") else None
    request = urllib.request.Request(f"http://{BASE}{path}", method=method, data=data, headers={"content-type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=30))


def upload(game: str, filename: str, content: bytes) -> dict:
    """Manda uma textura ou um som para os assets do jogo, como a tela faz."""
    request = urllib.request.Request(f"http://{BASE}/api/games/{game}/items?filename={urllib.parse.quote(filename)}", method="POST", data=content, headers={"content-type": "application/octet-stream"})
    return json.load(urllib.request.urlopen(request, timeout=30))


def powershell(command: str) -> str:
    return subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True).stdout.strip()


def listening() -> int | None:
    out = powershell(f"(Get-NetTCPConnection -State Listen -LocalPort {PORT} -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1")
    return int(out) if out.isdigit() else None


def hanging(server: int) -> list[str]:
    """Os processos pendurados no servidor: os terminais e o que nasceu deles."""
    rows = json.loads(powershell("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name | ConvertTo-Json -Compress"))
    kids: dict[int, list[dict]] = {}
    for row in rows:
        kids.setdefault(row["ParentProcessId"], []).append(row)
    out, todo = [], [server]
    while todo:
        for row in kids.get(todo.pop(), []):
            out.append(row["Name"])
            todo.append(row["ProcessId"])
    return sorted(out)


async def settled(server: int, limit: float = 12.0) -> list[str]:
    """O que continua pendurado depois de dar tempo de o console sair (ele leva uns 5 s)."""
    start = time.monotonic()
    while True:
        names = hanging(server)
        if not names or time.monotonic() - start > limit:
            return names
        await asyncio.sleep(1)


def socket(asset: str, *, token: str | None = None, origin: str | None = None):
    token = api("/api/terminal")["token"] if token is None else token
    return websockets.connect(f"ws://{BASE}/api/terminal/{asset}?token={token}", origin=origin or f"http://{BASE}", max_size=None)


async def refused(asset: str, **how) -> bool:
    try:
        async with socket(asset, **how) as ws:
            await asyncio.wait_for(ws.recv(), 3)
            return False
    except Exception:  # noqa: BLE001 - recusar é fechar a conexão, de um jeito ou de outro
        return True


async def listen(ws, seconds: float) -> tuple[str, list[str]]:
    """O que o terminal escreveu nesse tempo (sem os códigos de cor e de cursor) e os outros avisos."""
    text, kinds = "", []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            message = json.loads(await asyncio.wait_for(ws.recv(), 0.5))
        except asyncio.TimeoutError:
            continue
        except websockets.exceptions.ConnectionClosed:
            kinds.append("conexão fechada")
            break
        if message["type"] == "output":
            text += message["data"]
        else:
            kinds.append(message["type"])
    return ANSI.sub("", text), kinds


async def wait_closed(asset: str, limit: float) -> float | None:
    start = time.monotonic()
    while time.monotonic() - start < limit:
        if asset not in api("/api/terminal")["open"]:
            return time.monotonic() - start
        await asyncio.sleep(1)
    return None


async def checks(data: Path, server: int, check) -> None:
    keep, drop = data / "projects" / KEEP, data / "projects" / DROP

    check("página de outro site não abre o terminal", await refused(KEEP, origin="http://exemplo.com"))
    check("senha errada não abre o terminal", await refused(KEEP, token="errada"))
    check("nada abriu com as duas recusas", not api("/api/terminal")["open"] and not hanging(server))

    # 0. O terminal da tela de entrada: sem projeto, na pasta da ponte, com as mesmas travas.
    home = api("/api/terminal").get("home")
    check("o servidor diz o nome do terminal da tela de entrada", bool(home) and home not in (KEEP, DROP), str(home))
    check("página de outro site não abre o terminal da entrada", await refused(home, origin="http://exemplo.com"))
    check("senha errada não abre o terminal da entrada", await refused(home, token="errada"))
    guides = {name: (ROOT / name).read_bytes() if (ROOT / name).is_file() else None for name in ("CLAUDE.md", "AGENTS.md")}
    async with socket(home) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 10))
        check("à primeira tela, avisa que ninguém respondeu ainda às perguntas do programa", first.get("replay") is True and first.get("answered") is False, str(first)[:120])
        text, _ = await listen(ws, 6)
        text = ANSI.sub("", first.get("data", "")) + text
        names = hanging(server)
        check("o da entrada abre parado, sem chamar nada", "powershell.exe" in names and set(names) <= BARE, ", ".join(names))
        check("o prompt dele está na pasta da ponte", f"{ROOT.name}>" in text, text[-160:].strip())
        await ws.send(json.dumps({"type": "input", "data": "Write-Output ('en'+'trada-ok')\r"}))
        text, _ = await listen(ws, 4)
        check("ele responde ao que se escreve", "entrada-ok" in text, text[-160:].strip())
        info = api("/api/terminal")
        check("aparece entre os abertos e os em uso, como os de projeto", home in info["open"] and home in info["talking"], str(info))
    check("o guia da pasta da ponte não é regravado", all(((ROOT / name).read_bytes() if (ROOT / name).is_file() else None) == was for name, was in guides.items()))
    api(f"/api/terminal/{home}/restart", "POST")
    names = await settled(server)
    check('"reiniciar" fecha o da entrada e não deixa processo para trás', home not in api("/api/terminal")["open"] and not names, ", ".join(names))

    # 1. Aberto só para olhar: vem parado no prompt da pasta, e fecha sozinho depois de a tela sair.
    async with socket(KEEP) as ws:
        text, _ = await listen(ws, 6)
        names = hanging(server)
        check("abre parado, sem chamar nada", "powershell.exe" in names and set(names) <= BARE, ", ".join(names))
        check("o prompt está na pasta do projeto", f"{KEEP}>" in text, text[-160:].strip())
        guides = [keep / name for name in ("CLAUDE.md", "AGENTS.md")]
        check("a pasta ganhou o guia com os dois nomes", all(g.is_file() and g.read_text(encoding="utf-8").startswith(MARK) and KEEP in g.read_text(encoding="utf-8") for g in guides))
    took = await wait_closed(KEEP, 45)
    check("sem nada escrito, fecha sozinho depois de a tela sair", took is not None, f"{took:.0f} s depois" if took is not None else "continuou aberto por 45 s")
    names = await settled(server)
    check("e não deixa processo para trás", not names, ", ".join(names))

    # 2. Com alguma coisa escrita: espera a volta, e ao voltar o que estava escrito reaparece.
    async with socket(KEEP) as ws:
        await listen(ws, 5)
        await ws.send(json.dumps({"type": "input", "data": "Write-Output ('pon'+'te-ok')\r"}))
        text, _ = await listen(ws, 4)
        check("o que se escreve chega ao terminal e a resposta volta", "ponte-ok" in text, text[-160:].strip())
    await asyncio.sleep(32)
    info = api("/api/terminal")
    check("com algo escrito, continua aberto 32 s depois de a tela sair", KEEP in info["open"] and KEEP in info["talking"], str(info))
    async with socket(KEEP) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 5))
        check("ao voltar, o que estava escrito reaparece", first.get("replay") is True and "ponte-ok" in ANSI.sub("", first.get("data", "")))
        check("e a tela é avisada de que outra já respondeu às perguntas do programa", first.get("answered") is True, str(first.get("answered")))
    api(f"/api/terminal/{KEEP}/restart", "POST")
    names = await settled(server)
    check('"reiniciar" fecha o terminal e o que nasceu dele', KEEP not in api("/api/terminal")["open"] and not names, ", ".join(names))

    # 3. Guia escrito à mão não é regravado.
    (drop / "AGENTS.md").write_text("notas do dono\n", encoding="utf-8")
    # 4. Apagar o projeto com o terminal dele aberto: o Windows não apaga a pasta em que um programa está.
    async with socket(DROP) as ws:
        await listen(ws, 5)
        check("guia escrito à mão fica como está", (drop / "AGENTS.md").read_text(encoding="utf-8") == "notas do dono\n" and (drop / "CLAUDE.md").read_text(encoding="utf-8").startswith(MARK))
        answer = await asyncio.to_thread(api, f"/api/asset/{DROP}", "DELETE")
        _, kinds = await listen(ws, 3)
        check("apagar o projeto com o terminal aberto é aceito e avisa a tela", answer.get("deleted") == DROP and "exit" in kinds, str(kinds))
    check("a pasta do projeto sai inteira do disco", not drop.exists(), "" if not drop.exists() else "sobrou: " + ", ".join(p.name for p in drop.iterdir()))
    names = await settled(server)
    check("e não deixa processo para trás", not names, ", ".join(names))
    check("o outro projeto continua no lugar", [a["id"] for a in api("/api/state")["assets"]] == [KEEP])

    # 5. O terminal do jogo: abre na pasta do jogo, com o guia do que há nele, e sai junto com o jogo.
    game = api("/api/games", "POST", {"name": "Jogo do teste"})["id"]
    api(f"/api/assets/{KEEP}", "PATCH", {"game": game})
    folder = data / "games" / game
    guide = folder / "CLAUDE.md"
    check("página de outro site não abre o terminal do jogo", await refused(game, origin="http://exemplo.com"))
    async with socket(game) as ws:
        text, _ = await listen(ws, 6)
        names = hanging(server)
        check("o do jogo abre parado, sem chamar nada", "powershell.exe" in names and set(names) <= BARE, ", ".join(names))
        check("o prompt dele está na pasta do jogo", f"{game}>" in text, text[-160:].strip())
        written = guide.read_text(encoding="utf-8") if guide.is_file() else ""
        check("a pasta do jogo ganhou o guia, com o personagem dele", written.startswith(MARK) and "Jogo do teste" in written and KEEP in written and (folder / "AGENTS.md").is_file(), written[:200])
        await ws.send(json.dumps({"type": "input", "data": "Write-Output ('jo'+'go-ok')\r"}))
        text, _ = await listen(ws, 4)
        check("ele responde ao que se escreve", "jogo-ok" in text, text[-160:].strip())
    api(f"/api/assets/{KEEP}", "PATCH", {"game": None})
    async with socket(game) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 5))
        check("ao voltar ao jogo, o terminal é o mesmo", first.get("replay") is True and "jogo-ok" in ANSI.sub("", first.get("data", "")))
        check("e o guia foi regravado com o que mudou no jogo", KEEP not in guide.read_text(encoding="utf-8"))
        api(f"/api/assets/{KEEP}", "PATCH", {"game": game})
        answer = await asyncio.to_thread(api, f"/api/games/{game}", "DELETE")
        _, kinds = await listen(ws, 3)
        check("apagar o jogo com o terminal aberto é aceito e avisa a tela", answer.get("deleted") == game and "exit" in kinds, str(kinds))
    check("a pasta do jogo sai inteira do disco", not folder.exists(), "" if not folder.exists() else "sobrou: " + ", ".join(p.name for p in folder.iterdir()))
    names = await settled(server)
    check("e não deixa processo para trás", not names, ", ".join(names))
    state = api("/api/state")
    check("o personagem do jogo fica no disco, sem jogo", [(a["id"], a.get("game")) for a in state["assets"]] == [(KEEP, None)] and not state["games"], str([(a["id"], a.get("game")) for a in state["assets"]]))
    async with socket(game) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 5))
        check("jogo que não existe mais não abre terminal: a tela é avisada", first.get("type") == "error", str(first)[:120])
    check("e nada fica aberto", game not in api("/api/terminal")["open"] and not hanging(server))

    # 6. Cada espaço tem o terminal dele: o modelo 3D, a textura e o som abrem na pasta deles, com o guia de cada um.
    check("o servidor diz à página que textura e som têm terminal", api("/api/terminal").get("items") is True)
    game = api("/api/games", "POST", {"name": "Jogo dos espaços"})["id"]
    folder = data / "games" / game
    api(f"/api/assets/{KEEP}", "PATCH", {"game": game, "role": "modelo"})
    async with socket(KEEP) as ws:
        text, _ = await listen(ws, 6)
        written = (keep / "CLAUDE.md").read_text(encoding="utf-8")
        check("o terminal do modelo 3D abre na pasta dele", f"{KEEP}>" in text, text[-160:].strip())
        check("o guia dele diz que é um asset do jogo e que é nele que se mexe", written.startswith(MARK) and "# Asset: Teste fica" in written and "Jogo dos espaços" in written and "neste asset que você vai mexer" in written, written[:300])
    api(f"/api/assets/{KEEP}", "PATCH", {"role": "personagem"})
    async with socket(KEEP) as ws:
        await listen(ws, 3)
        check("o guia acompanha o papel, a cada tela que se liga", "# Personagem: Teste fica" in (keep / "CLAUDE.md").read_text(encoding="utf-8"))
    api(f"/api/terminal/{KEEP}/restart", "POST")

    texture = upload(game, "Muro Velho.png", b"\x89PNG" + b"0" * 60)["id"]
    spot = folder / "assets" / texture
    check("página de outro site não abre o terminal da textura", await refused(texture, origin="http://exemplo.com"))
    async with socket(texture) as ws:
        text, _ = await listen(ws, 6)
        names = hanging(server)
        check("o da textura abre parado, sem chamar nada", "powershell.exe" in names and set(names) <= BARE, ", ".join(names))
        check("o prompt dele está na pasta da textura", f"{texture}>" in text, text[-160:].strip())
        written = (spot / "CLAUDE.md").read_text(encoding="utf-8") if (spot / "CLAUDE.md").is_file() else ""
        check("a pasta da textura ganhou o guia, com o arquivo e o jogo", written.startswith(MARK) and "`Muro Velho.png`" in written and "Jogo dos espaços" in written and (spot / "AGENTS.md").is_file(), written[:300])
        check("a textura continua na lista, com o arquivo dela", [(i["id"], i["file"]) for i in api("/api/state")["items"]] == [(texture, "Muro Velho.png")])
        answer = await asyncio.to_thread(api, f"/api/items/{texture}", "DELETE")
        _, kinds = await listen(ws, 3)
        check("apagar a textura com o terminal aberto é aceito e avisa a tela", answer.get("deleted") == texture and "exit" in kinds, str(kinds))
    check("a pasta da textura sai inteira do disco", not spot.exists(), "" if not spot.exists() else "sobrou: " + ", ".join(p.name for p in spot.iterdir()))
    async with socket(texture) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 5))
        check("textura que não existe mais não abre terminal: a tela é avisada", first.get("type") == "error", str(first)[:120])

    # 6b. A aba de gestão: o documento tem o terminal dele, e apagar a aba com ele aberto leva tudo.
    board = api(f"/api/games/{game}/tabs", "POST", {"name": "Gestão", "kind": "gestao"})
    check("o jogo ganha a aba de gestão, depois das duas que vêm com ele", [(t["id"], t["kind"]) for t in api("/api/state")["games"][0]["tabs"]] == [("characters", "personagens"), ("assets", "assets"), (board["id"], "gestao")], str(board))
    document = api(f"/api/games/{game}/documents", "POST", {"name": "Regras do jogo", "tab": board["id"]})
    task = api(f"/api/games/{game}/tasks", "POST", {"title": "Fazer o portão", "tab": board["id"]})
    page = folder / "assets" / document["id"]
    check("o documento nasce como um arquivo de texto, com o endereço que a tela usa", (page / "Regras do jogo.md").read_text(encoding="utf-8") == "# Regras do jogo\n\n" and document.get("files_base", "").endswith(document["id"]) and bool(document.get("modified")), str(document))
    check("página de outro site não abre o terminal do documento", await refused(document["id"], origin="http://exemplo.com"))
    async with socket(document["id"]) as ws:
        text, _ = await listen(ws, 6)
        check("o prompt do terminal do documento está na pasta dele", f"{document['id']}>" in text, text[-160:].strip())
        written = (page / "CLAUDE.md").read_text(encoding="utf-8") if (page / "CLAUDE.md").is_file() else ""
        check("a pasta do documento ganhou o guia, com o arquivo e o jogo", written.startswith(MARK) and "# Documento: Regras do jogo" in written and "`Regras do jogo.md`" in written and "Jogo dos espaços" in written, written[:300])
        saved = api(f"/api/items/{document['id']}/text", "PUT", {"text": "# Regras\n\n- [ ] uma\n"})
        check("o texto escrito na tela é gravado, com o terminal aberto na pasta", (page / "Regras do jogo.md").read_text(encoding="utf-8") == "# Regras\n\n- [ ] uma\n" and saved["size_bytes"] == 20, str(saved))
        state = api("/api/state")
        check("o estado traz a tarefa e o documento, e só o documento entre os arquivos", [t["id"] for t in state["tasks"]] == [task["id"]] and [(i["id"], i["kind"]) for i in state["items"]] == [(document["id"], "documento")])
        check("mudar a tarefa de coluna", api(f"/api/tasks/{task['id']}", "PATCH", {"status": "feito"})["status"] == "feito")
        answer = await asyncio.to_thread(api, f"/api/games/{game}/tabs/{board['id']}", "DELETE")
        _, kinds = await listen(ws, 3)
        check("apagar a aba de gestão com o terminal de um documento aberto é aceito e avisa a tela", answer.get("deleted") == board["id"] and "exit" in kinds, str(kinds))
    state = api("/api/state")
    check("a pasta do documento sai inteira do disco, com as tarefas da aba", not page.exists() and state["tasks"] == [] and state["items"] == [] and [t["id"] for t in state["games"][0]["tabs"]] == ["characters", "assets"], "" if not page.exists() else "sobrou: " + ", ".join(p.name for p in page.iterdir()))

    sound = upload(game, "passo.wav", b"RIFF" + b"0" * 96)["id"]
    async with socket(sound) as ws:
        await listen(ws, 5)
        await ws.send(json.dumps({"type": "input", "data": "Write-Output ('s'+'om-ok')\r"}))
        text, _ = await listen(ws, 4)
        check("o terminal do som responde ao que se escreve", "som-ok" in text, text[-160:].strip())
        answer = await asyncio.to_thread(api, f"/api/games/{game}", "DELETE")
        _, kinds = await listen(ws, 3)
        check("apagar o jogo com o terminal de um som aberto é aceito e avisa a tela", answer.get("deleted") == game and "exit" in kinds, str(kinds))
    check("a pasta do jogo sai inteira do disco, com a do som", not folder.exists(), "" if not folder.exists() else "sobrou: " + ", ".join(str(p.relative_to(folder)) for p in folder.rglob("*")))
    names = await settled(server)
    check("e não deixa processo para trás", not api("/api/terminal")["open"] and not names, ", ".join(names))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if listening():
        print(f"FALHA: a porta {PORT} já está em uso (um teste anterior ficou aberto?).")
        return 1
    work = Path(tempfile.mkdtemp(prefix="ponte-terminal-"))
    data = work / "data"
    for project, name in ((KEEP, "Teste fica"), (DROP, "Teste some")):
        record = {"id": project, "name": name, "created_at": "2026-10-11T00:00:00-03:00", "status": "inspecionado", "verdict": "pronto", "source": "source/modelo.fbx", "summary": {"rig": "Mixamo", "bones": 65, "triangles": 1000, "height_m": 1.8}}
        path = data / "projects" / project / "personagem" / "asset.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    problems: list[str] = []

    def check(label: str, passed: bool, detail: str = "") -> None:
        print(("ok    " if passed else "FALHA ") + label + (f": {detail}" if detail and not passed else ""))
        if not passed:
            problems.append(label)

    launcher = subprocess.Popen(
        [sys.executable, "-c", "from ponte.cli import main; main()", "serve", "--port", str(PORT)],
        cwd=ROOT,
        env={**os.environ, "PONTE_DATA": str(data)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    server = None
    try:
        for _ in range(60):
            try:
                api("/api/state")
                break
            except OSError:
                time.sleep(0.5)
        server = listening()
        if server is None:
            print("FALHA: o servidor de teste não subiu.")
            return 1
        asyncio.run(checks(data, server, check))
    finally:
        if server:
            subprocess.run(["taskkill", "/PID", str(server), "/T", "/F"], capture_output=True, check=False)
        launcher.kill()
        time.sleep(1)
        shutil.rmtree(work, ignore_errors=True)
    print("\n" + ("tudo ok" if not problems else f"{len(problems)} FALHA(S): " + "; ".join(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
