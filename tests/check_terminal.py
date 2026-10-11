"""O terminal da tela: abre parado na pasta do projeto, só atende à própria página e não fica para trás.

Sobe um servidor próprio (porta 8767) num acervo descartável (PONTE_DATA), com dois projetos de
mentira, e fala com o terminal pelo mesmo caminho da página (WebSocket). Não usa o Blender e não
chama IA nenhuma. Leva uns 2 minutos, por causa das esperas da faxina (``terminal.GRACE``).

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


def api(path: str, method: str = "GET") -> dict:
    request = urllib.request.Request(f"http://{BASE}{path}", method=method, data=b"{}" if method == "POST" else None, headers={"content-type": "application/json"})
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
