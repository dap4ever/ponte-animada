"""Geração de animações no ARDY (NVIDIA), instalado no Ubuntu do WSL.

O ARDY (https://github.com/nv-tlabs/ardy) é irmão do Kimodo, em tempo real: gera em janelas de
2 s, cada uma partindo do que já existe. Aqui ele entra como mais um gerador da ponte, com o
mesmo contrato dos outros dois (``generate``). O que é dele:

- esqueleto próprio: o Core, de 27 juntas, a 20 quadros por segundo. Não é o SOMA 77 do Kimodo.
  O clipe chega em BVH nesse esqueleto, já a 30 quadros por segundo, e entra no projeto pelo
  caminho das capturas (``blender/ponte_bl/capture.py``): nomes do SOMA de mesmo papel;
- um pedido de cada vez: a vaga e a fila são as de ``kimodo.py``, somando os três geradores;
- o codificador de texto (o mesmo Llama 3 do Kimodo) roda no processador e ocupa uns 16 GB de
  RAM. Cada texto é codificado uma vez e fica guardado, então só texto novo precisa dele. A
  ponte o sobe para codificar e o desliga em seguida, a não ser que ele já estivesse no ar
  (o demo ao vivo aberto, ou ligado à mão): aí fica como estava;
- as sessões exportadas pelo demo ao vivo (aba IO, *Export Session*) viram animação do projeto.

Quem fala com o ARDY é ``ardy_scripts/gerar.py``, que roda no ambiente dele, dentro do Ubuntu.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from . import kimodo, store
from .config import DATA, ROOT, SETTINGS
from .kimodo import KimodoError, to_wsl_path

Log = Callable[[str], None]
MODEL = "ARDY-Core-RP-20FPS-Horizon40"
SKELETON = "cskel27"
FPS = 20  # o ritmo do modelo
PROJECT_FPS = 30  # o das animações do projeto: o BVH já chega nele
DIFFUSION_STEPS = 10  # os deste modelo; mais que isso ele não aceita
MIN_SECONDS, MAX_SECONDS = 0.5, 10.0
ENCODER_RAM_GB = 16
# Com menos memória livre que isto, ou com a Unreal aberta, o codificador deixa o PC sem
# resposta (aconteceu em 08/10/2026). São os limites do atalho "ARDY - ao vivo".
ENCODER_FREE_GB = 14.0
ENCODER_LOG = "~/ardy-logs/codificador-ponte.log"
SCRIPT = ROOT / "ardy_scripts" / "gerar.py"
_SCRIPTS = DATA / "tmp" / "ardy"


def missing() -> list[str]:
    """O que falta para gerar por aqui. Lista vazia: está instalado."""
    return [] if SETTINGS.ardy_installed else ["o ARDY no Ubuntu (os scripts estão em docs/ardy-setup/; depois, installed = true na seção [ardy] do ponte.toml)"]


def to_project_frame(frame: int) -> int:
    """Um quadro do ARDY (20 por segundo) no ritmo das animações do projeto (a mesma conta de ``ardy_scripts/gerar.py``)."""
    return (PROJECT_FPS * frame + FPS // 2) // FPS


def check_script(steps: list[dict]) -> None:
    """Recusa, antes de ocupar a vaga, o roteiro que o ARDY não gera."""
    for i, step in enumerate(steps):
        if not MIN_SECONDS <= float(step["seconds"]) <= MAX_SECONDS:
            raise KimodoError(f"No ARDY cada passo vai de {MIN_SECONDS:g} a {MAX_SECONDS:g} segundos (o passo {i + 1} tem {step['seconds']:g}).")


# --- O Ubuntu -------------------------------------------------------------------------


def _wsl() -> list[str]:
    return ["wsl.exe", "-d", SETTINGS.ardy_distro, *(["-u", SETTINGS.ardy_user] if SETTINGS.ardy_user else []), "--"]


def _repo() -> str:
    repo = SETTINGS.ardy_repo
    return "$HOME" + repo[1:] if repo.startswith("~") else repo


def _env() -> str:
    """O começo de todo script que roda no ambiente do ARDY."""
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f'cd "{_repo()}"',
            ". .venv/bin/activate",
            # Sem internet: os modelos já estão no disco. O codificador é sempre o serviço, nunca
            # carregado junto do gerador (na placa pediria 14 GB e a RTX 3060 tem 12).
            f"export HF_HUB_OFFLINE=1 TEXT_ENCODER_MODE=api TEXT_ENCODER_URL={SETTINGS.ardy_encoder_url} PYTHONUNBUFFERED=1",
            "",
        ]
    )


def _script(name: str, body: str) -> str:
    """Grava um script de shell com fim de linha do Linux e devolve o caminho dele visto do Ubuntu."""
    path = _SCRIPTS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")
    return to_wsl_path(path)


def _bash(name: str, body: str, *, root: bool = False, timeout: float = 120.0) -> subprocess.CompletedProcess:
    argv = ["wsl.exe", "-d", SETTINGS.ardy_distro, "-u", "root", "--"] if root else _wsl()
    return subprocess.run([*argv, "bash", _script(name, body)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)


def _run(args: list[str | Path], log: Log) -> None:
    """Roda ``ardy_scripts/gerar.py`` no ambiente do ARDY e repassa o andamento."""
    runner = _script("rodar.sh", _env() + 'exec python "$@"\n')
    argv = [to_wsl_path(a) if isinstance(a, Path) else str(a) for a in args]
    proc = subprocess.Popen(
        [*_wsl(), "bash", runner, to_wsl_path(SCRIPT), *argv],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    tail: list[str] = []
    reason = None
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.replace("\x00", "").split("\r")[-1].strip()
        if not line:
            continue
        tail = (tail + [line])[-12:]
        if line.startswith("[ponte] ERRO: "):
            reason = line.removeprefix("[ponte] ERRO: ")
        elif line.startswith("[ponte] "):  # o resto é aviso das bibliotecas do ARDY
            log(line.removeprefix("[ponte] "))
    if proc.wait() != 0:
        raise KimodoError("O ARDY falhou: " + (reason or " | ".join(tail[-4:]) or f"o Ubuntu ({SETTINGS.ardy_distro}) não respondeu"))


# --- Codificador de texto -------------------------------------------------------------


def encoder_ready(timeout: float = 1.5) -> bool:
    """O codificador responde? Pergunta daqui do Windows: não acorda o Ubuntu se ele estiver desligado."""
    try:
        with urllib.request.urlopen(SETTINGS.ardy_encoder_url, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _free_ram_gb() -> float:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(name, ctypes.c_ulonglong) for name in ("total", "free", "page_total", "page_free", "virtual_total", "virtual_free", "extended")]

    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.free / 1024**3


def _unreal_open() -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq UnrealEditor*", "/NH", "/FO", "CSV"], capture_output=True, text=True, errors="replace", timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "unrealeditor" in out.stdout.lower()


def encoder_blocker() -> str | None:
    """Por que não dá para subir o codificador de texto agora, ou None."""
    hint = "Texto que já foi usado não precisa dele; com o atalho “ARDY - ao vivo” aberto, a ponte usa o codificador de lá."
    if _unreal_open():
        return f"A Unreal está aberta e o codificador de texto do ARDY ocupa uns {ENCODER_RAM_GB} GB de RAM: os dois juntos deixam o PC sem resposta. Feche a Unreal e peça de novo. {hint}"
    free = _free_ram_gb()
    if free < ENCODER_FREE_GB:
        return f"O codificador de texto do ARDY ocupa uns {ENCODER_RAM_GB} GB de RAM e há {free:.0f} GB livres. Feche programas pesados e peça de novo. {hint}"
    return None


def start_encoder(log: Log) -> None:
    """Sobe o codificador de texto, se não estiver no ar, e espera ele responder."""
    if encoder_ready():
        return
    trouble = encoder_blocker()
    if trouble:
        raise KimodoError(trouble)
    log(f"subindo o codificador de texto do ARDY (ocupa uns {ENCODER_RAM_GB} GB de RAM; leva de 3 a 5 minutos)")
    script = _script(
        "codificador.sh",
        _env()
        + "\n".join(
            [
                "export TEXT_ENCODER_DEVICE=cpu GRADIO_ANALYTICS_ENABLED=False",
                f'mkdir -p "$(dirname {ENCODER_LOG.replace("~", "$HOME")})"',
                f'exec python scripts/run_text_encoder_server.py --device cpu --host 127.0.0.1 --port {SETTINGS.ardy_encoder_url.rstrip("/").rsplit(":", 1)[-1]} > "{ENCODER_LOG.replace("~", "$HOME")}" 2>&1',
                "",
            ]
        ),
    )
    # Fica no ar depois que este pedido termina: quem o encerra é ``stop`` (ou quem o subiu para codificar).
    proc = subprocess.Popen(
        [*_wsl(), "bash", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    started = last = time.monotonic()
    while not encoder_ready(3.0):
        now = time.monotonic()
        if proc.poll() is not None:
            raise KimodoError(f"O codificador de texto do ARDY parou ao carregar (o registro está em {ENCODER_LOG}, no Ubuntu).")
        if now - started > 1800:
            proc.kill()
            raise KimodoError("O codificador de texto do ARDY não subiu em 30 minutos.")
        if now - last >= 30:
            log(f"carregando o codificador de texto há {now - started:.0f} s")
            last = now
        time.sleep(3)
    log(f"codificador de texto no ar em {time.monotonic() - started:.0f} s")


def _demo_open() -> bool:
    """O demo ao vivo está aberto? Ele usa o mesmo codificador: encerrá-lo derruba o demo sem aviso."""
    return _bash("demo-no-ar.sh", "#!/usr/bin/env bash\npgrep -f 'scripts/run_demo\\.py' > /dev/null\n").returncode == 0


def _kill_encoder() -> None:
    _bash(
        "parar-codificador.sh",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "pkill -f run_text_encoder_server.py || exit 0",
                "for _ in $(seq 1 20); do pgrep -f run_text_encoder_server.py > /dev/null || break; sleep 0.5; done",
                "pkill -9 -f run_text_encoder_server.py 2>/dev/null",
                "exit 0",
                "",
            ]
        ),
    )
    # O modelo lido do disco fica na memória do Ubuntu como cópia de arquivo: soltá-la é o que
    # devolve a memória ao Windows. Não apaga nada.
    _bash("liberar-cache.sh", "#!/usr/bin/env bash\nsync\necho 1 > /proc/sys/vm/drop_caches\n", root=True)


def stop() -> str:
    """Desliga o codificador de texto (libera uns 16 GB de RAM)."""
    if not encoder_ready():
        return "O codificador de texto do ARDY não estava no ar."
    if kimodo.slots_in_use():
        raise KimodoError("Há animação sendo gerada; espere terminar antes de desligar o codificador de texto.")
    if _demo_open():
        raise KimodoError("O demo ao vivo do ARDY está aberto e usa este codificador de texto: feche a janela do atalho “ARDY - ao vivo”, que ela mesma o encerra.")
    _kill_encoder()
    return "Codificador de texto do ARDY desligado."


def status() -> dict:
    """Barato o bastante para a interface consultar sempre."""
    return {"installed": SETTINGS.ardy_installed, "model": MODEL, "skeleton": SKELETON, "encoder": SETTINGS.ardy_installed and encoder_ready()}


# --- Geração --------------------------------------------------------------------------


def _encode_texts(job: Path, log: Log) -> None:
    """Deixa codificado todo texto do pedido. O codificador só sobe se houver texto novo."""
    _run([job, "--textos"], log)
    new = (store.read_json(job.with_name("textos.json")) or {}).get("missing") or []
    if not new:
        return
    mine = not encoder_ready()
    log(f"{len(new)} texto(s) novo(s) para codificar" + ("" if mine else " (o codificador de texto já está no ar)"))
    start_encoder(log)
    try:
        _run([job, "--codificar"], log)
    finally:
        # Subiu só para este pedido: desliga já, antes de gerar. Se nesse meio tempo o demo ao
        # vivo abriu, ele passou a depender deste codificador e é ele quem o encerra.
        if mine and not _demo_open():
            _kill_encoder()
            log("codificador de texto desligado: a memória volta ao Windows")


def generate(work_dir: Path, takes: list[dict], *, steps: int = DIFFUSION_STEPS, dry_run: bool = False, log: Log = lambda _line: None) -> list[dict]:
    """O mesmo contrato de ``kimodo.generate``, no ARDY.

    Cada tomada traz os passos novos em ``steps``, ``seed`` e, opcionalmente, ``samples`` e
    ``continue_from`` (Path do .npz de onde o roteiro parte). ``steps`` (o argumento) não é
    usado: o ARDY tem os passos de difusão dele. ``dry_run`` não carrega o modelo: grava o
    clipe com o personagem parado, só para conferir que o roteiro monta.

    Devolve [{take, sample, bvh, npz, frames, step_frames}]: o BVH está no esqueleto do ARDY, já a
    30 quadros por segundo, e ``frames`` e ``step_frames`` vêm nesse ritmo. O .npz fica nos 20 do ARDY.
    """
    for take in takes:
        check_script(take["steps"])
    lacking = missing()
    if lacking:
        raise KimodoError("O ARDY não está instalado. Falta: " + "; ".join(lacking) + ".")
    work_dir.mkdir(parents=True, exist_ok=True)
    job_takes = []
    for i, take in enumerate(takes):
        item = {k: v for k, v in take.items() if v is not None}
        if take.get("continue_from"):
            shutil.copy2(take["continue_from"], work_dir / f"anterior_{i}.npz")
            item["continue_from"] = f"anterior_{i}.npz"
        job_takes.append(item)
    job = work_dir / "job.json"
    store.write_json(job, {"model": MODEL, "takes": job_takes})

    # Dentro do job tudo roda em sequência (passos, variações, tomadas): ocupa uma vaga só.
    with kimodo.generation_slots(1, log):
        total = sum(s["seconds"] for t in takes for s in t["steps"]) * max(int(t.get("samples", 1)) for t in takes)
        if dry_run:
            log(f"conferindo o roteiro (sem gerar): {sum(len(t['steps']) for t in takes)} passo(s), {total:g}s no total")
            _run([job, "--dry-run"], log)
        else:
            _encode_texts(job, log)
            log(f"gerando no ARDY: {sum(len(t['steps']) for t in takes)} passo(s), {total:g}s no total")
            _run([job], log)

    result = store.read_json(work_dir / "result.json")
    if not result:
        raise KimodoError("O ARDY terminou sem gravar o resultado.")
    out = []
    for item in result["outputs"]:
        bvh, npz = work_dir / f"{item['stem']}.bvh", work_dir / f"{item['stem']}.npz"
        if not bvh.exists():
            raise KimodoError(f"O ARDY terminou sem gravar {bvh.name}.")
        out.append({**item, "bvh": bvh, "npz": npz if npz.exists() else None, "frames": to_project_frame(item["frames"]), "step_frames": [to_project_frame(f) for f in item["step_frames"]], "fps": PROJECT_FPS})
    return out


# --- Sessões do demo ao vivo ----------------------------------------------------------


def sessions() -> dict:
    """As sessões exportadas pelo demo ao vivo (``~/ardy/.cache/export``), da mais nova para a mais antiga."""
    lacking = missing()
    if lacking:
        raise KimodoError("O ARDY não está instalado. Falta: " + "; ".join(lacking) + ".")
    out = _SCRIPTS / "sessoes.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    _run(["--sessoes", out], lambda _line: None)
    return store.read_json(out) or {"folder": "", "sessions": []}


def convert_session(name: str, work_dir: Path, *, start: float | None = None, end: float | None = None, log: Log = lambda _line: None) -> dict:
    """Leva uma sessão do demo para o formato de um clipe gerado aqui.

    Devolve ``bvh``, ``npz`` (None se a sessão não traz de onde continuar) e o que o script
    apurou: ``frames`` e ``steps`` (os textos da sessão, cada um com o quadro em que começa),
    já no ritmo do projeto.
    """
    lacking = missing()
    if lacking:
        raise KimodoError("O ARDY não está instalado. Falta: " + "; ".join(lacking) + ".")
    work_dir.mkdir(parents=True, exist_ok=True)
    args: list[str | Path] = ["--sessao", Path(name).name, work_dir]
    if start is not None:
        args += ["--inicio", str(start)]
    if end is not None:
        args += ["--fim", str(end)]
    _run(args, log)
    info = store.read_json(work_dir / "sessao.json")
    if not info or not (work_dir / "sessao.bvh").exists():
        raise KimodoError("O ARDY terminou sem gravar a sessão.")
    return {
        **info,
        "bvh": work_dir / "sessao.bvh",
        "npz": work_dir / "sessao.npz" if info.get("continuable") else None,
        "frames": to_project_frame(info["frames"]),
        "steps": [{"text": s["text"], "start_frame": to_project_frame(s["start_frame"])} for s in info["steps"]],
    }
