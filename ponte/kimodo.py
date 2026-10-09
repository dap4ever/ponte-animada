"""Geração de animações no Kimodo (Docker dentro do WSL).

Duas regras fixas do projeto são impostas aqui, não por disciplina:

- esqueleto único: o modelo vem de ``config.KIMODO_MODEL`` e não é parâmetro de
  ninguém; todo BVH gerado é conferido contra a assinatura do SOMA 77;
- um pedido de cada vez (``config.KIMODO_MAX_SIMULTANEOUS``): quem chega com outro
  gerando espera na fila e entra na ordem em que chegou. Vale entre processos
  (servidor e CLI), porque a vaga e a senha de cada um na fila são arquivos
  travados em ``data/.locks``.
"""

from __future__ import annotations

import msvcrt
import os
import secrets
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from . import store
from .config import DATA, KIMODO_MAX_SIMULTANEOUS, KIMODO_MODEL, KIMODO_SKELETON, KIMODO_SKELETON_SIGNATURE, ROOT, SETTINGS

LOCKS = DATA / ".locks"
QUEUE = LOCKS / "fila"
Log = Callable[[str], None]


class KimodoError(RuntimeError):
    pass


def to_wsl_path(path: Path) -> str:
    p = path.resolve()
    return f"/mnt/{p.drive[0].lower()}{p.as_posix()[2:]}"


def _wsl(*argv: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["wsl.exe", "-d", SETTINGS.wsl_distro, "-u", SETTINGS.wsl_user, "--", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _repo() -> str:
    repo = SETTINGS.kimodo_repo
    return "$HOME" + repo[1:] if repo.startswith("~") else repo


# --- Vagas de geração -------------------------------------------------------------


def _lock_file(path: Path):
    """Abre e trava ``path``. Devolve None se outro processo (ou outra thread) já o tem travado."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return handle
    except OSError:
        handle.close()
        return None


def _try_lock(index: int):
    return _lock_file(LOCKS / f"kimodo-{index}.lock")


# A fila: cada pedido que espera tem uma senha, um arquivo com a hora de chegada no nome,
# travado enquanto o dono espera. Senha destravada é de quem morreu esperando e sai da fila.


def _take_ticket() -> tuple[Path, object]:
    path = QUEUE / f"{time.time_ns():020d}-{os.getpid()}-{secrets.token_hex(2)}.senha"
    for _ in range(100):  # quem confere a fila trava a senha por um instante, para ver se o dono vive
        handle = _lock_file(path)
        if handle:
            return path, handle
        time.sleep(0.02)
    raise KimodoError("Não consegui entrar na fila do Kimodo.")


def _drop_ticket(path: Path, handle) -> None:
    _release(handle)
    try:
        path.unlink()
    except OSError:
        pass  # alguém a estava conferindo; destravada, ela sai na próxima conferência


def _waiting(before: str = "~") -> int:
    """Pedidos vivos na fila que chegaram antes da senha ``before`` (todos, sem ela)."""
    if not QUEUE.exists():
        return 0
    alive = 0
    for path in sorted(QUEUE.glob("*.senha")):
        if path.name >= before:
            break
        handle = _lock_file(path)
        if handle is None:
            alive += 1
        else:
            _drop_ticket(path, handle)
    return alive


def slots_in_use() -> int:
    used = 0
    for i in range(KIMODO_MAX_SIMULTANEOUS):
        handle = _try_lock(i)
        if handle is None:
            used += 1
        else:
            _release(handle)
    return used


def _release(handle) -> None:
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    handle.close()


@contextmanager
def generation_slots(count: int, log: Log) -> Iterator[None]:
    """Reserva ``count`` vagas, esperando a vez na fila se preciso: entra quem chegou primeiro."""
    if not 1 <= count <= KIMODO_MAX_SIMULTANEOUS:
        raise KimodoError(f"Regra do projeto: no máximo {KIMODO_MAX_SIMULTANEOUS} geração(ões) por vez (pedido: {count}).")
    limit = "um pedido de cada vez" if KIMODO_MAX_SIMULTANEOUS == 1 else f"no máximo {KIMODO_MAX_SIMULTANEOUS} ao mesmo tempo"
    held: list = []
    ticket, ticket_handle = _take_ticket()
    waiting_since = time.monotonic()
    announced = None  # quantos havia na frente no último aviso
    misses = 0
    try:
        while len(held) < count:
            ahead = _waiting(ticket.name)
            handle = None
            if not ahead:
                # Quem quer todas as vagas pega em ordem; quem quer uma pega a primeira livre.
                candidates = [len(held)] if count == KIMODO_MAX_SIMULTANEOUS else range(KIMODO_MAX_SIMULTANEOUS)
                handle = next((h for h in map(_try_lock, candidates) if h), None)
            if handle:
                held.append(handle)
                continue
            # As primeiras falhas podem ser só a consulta de status testando a vaga.
            misses += 1
            if misses >= 4 and announced != ahead:
                where = f"{ahead} pedido(s) na frente, além do que está gerando" if ahead else "é o próximo, assim que o atual terminar"
                log(f"na fila do Kimodo ({limit}): {where}")
                announced = ahead
            time.sleep(0.4 if announced is None else 2.0)
        _drop_ticket(ticket, ticket_handle)
        ticket_handle = None
        if announced is not None:
            log(f"chegou a vez, após {time.monotonic() - waiting_since:.0f}s na fila")
        yield
    finally:
        if ticket_handle:
            _drop_ticket(ticket, ticket_handle)
        for handle in held:
            _release(handle)


# --- Estado dos serviços -----------------------------------------------------------


def engine_ready(timeout: float = 20.0) -> bool:
    try:
        out = _wsl("docker", "version", "--format", "{{.Server.Version}}", timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return out.returncode == 0 and out.stdout.strip()[:1].isdigit()


def encoder_ready(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(SETTINGS.text_encoder_url, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _docker_pipe_open() -> bool:
    # os.path.exists não enxerga named pipes; listar a pasta de pipes enxerga.
    try:
        return "docker_engine" in os.listdir("\\\\.\\pipe\\")
    except OSError:
        return False


def status() -> dict:
    """Barato o bastante para a interface consultar sempre."""
    return {
        "model": KIMODO_MODEL,
        "skeleton": KIMODO_SKELETON,
        "limit": KIMODO_MAX_SIMULTANEOUS,
        "generating": slots_in_use(),
        "queued": _waiting(),
        "docker": _docker_pipe_open(),
        "encoder": encoder_ready(),
    }


def ensure_ready(log: Log) -> None:
    """Sobe o Docker Desktop e o text encoder se não estiverem de pé."""
    if not engine_ready():
        if not SETTINGS.docker_desktop or not Path(SETTINGS.docker_desktop).exists():
            raise KimodoError("O Docker não está rodando e o Docker Desktop não foi encontrado.")
        log("iniciando o Docker Desktop")
        subprocess.Popen([SETTINGS.docker_desktop], creationflags=subprocess.DETACHED_PROCESS)
        deadline = time.monotonic() + 300
        while not engine_ready():
            if time.monotonic() > deadline:
                raise KimodoError("O motor do Docker não subiu em 5 minutos.")
            time.sleep(5)
    if encoder_ready():
        return
    log("subindo o text encoder do Kimodo (na primeira vez leva ~5 min carregando na CPU)")
    up = _wsl("bash", "-lc", f'cd "{_repo()}" && docker compose up -d text-encoder', timeout=300)
    if up.returncode != 0:
        raise KimodoError("Falha ao subir o text encoder: " + (up.stderr or up.stdout).strip()[-400:])
    deadline = time.monotonic() + 900
    while not encoder_ready():
        if time.monotonic() > deadline:
            raise KimodoError("O text encoder não respondeu em 15 minutos (docker logs text-encoder).")
        time.sleep(5)
    log("text encoder pronto")


def stop() -> str:
    """Derruba os containers do Kimodo (libera ~17 GB de RAM do text encoder)."""
    if slots_in_use():
        raise KimodoError("Há animações sendo geradas; espere terminarem antes de desligar o Kimodo.")
    out = _wsl("bash", "-lc", f'cd "{_repo()}" && docker compose down', timeout=180)
    return (out.stdout + out.stderr).strip()


# --- Geração -------------------------------------------------------------------------


def split_prompt(prompt: str, durations: list[float]) -> tuple[str, list[float]]:
    """Normaliza o prompt como o Kimodo faz: uma frase por ponto, uma duração por frase."""
    sentences = [s.strip() for s in prompt.replace("\n", " ").split(".") if s.strip()]
    if not sentences:
        raise KimodoError("Prompt vazio.")
    if len(durations) == 1:
        durations = durations * len(sentences)
    if len(durations) != len(sentences):
        raise KimodoError(f"O prompt tem {len(sentences)} frase(s), mas foram dadas {len(durations)} duração(ões).")
    if any(d <= 0 for d in durations):
        raise KimodoError("Duração precisa ser positiva.")
    return ". ".join(sentences) + ".", durations


def check_skeleton(bvh: Path) -> dict:
    info = store.bvh_summary(bvh)
    if info["signature"] != KIMODO_SKELETON_SIGNATURE:
        raise KimodoError(
            f"{bvh.name} não usa o esqueleto padrão do projeto ({KIMODO_SKELETON}, {info['joints']} juntas encontradas). "
            "Regra do projeto: todas as animações no mesmo esqueleto."
        )
    return info


def steps_from_prompt(prompt: str, durations: list[float], travel: dict | None = None, loop: bool = False, text_weight: float | None = None) -> list[dict]:
    """Prompt + durações como passos de roteiro: um passo por frase. ``loop`` vale para o último."""
    prompt, durations = split_prompt(prompt, durations)
    sentences = [s.strip() + "." for s in prompt.split(".") if s.strip()]
    steps = [{"text": text, "seconds": seconds, "travel": travel, "loop": False, "text_weight": text_weight} for text, seconds in zip(sentences, durations)]
    steps[-1]["loop"] = loop
    return steps


def generate(work_dir: Path, takes: list[dict], *, steps: int = 100, dry_run: bool = False, log: Log = lambda _line: None) -> list[dict]:
    """Roda as tomadas no Kimodo, uma depois da outra, com o modelo carregado uma vez.

    Cada tomada é um roteiro: ``name``, ``seed``, ``steps`` ([{text, seconds, travel?, loop?}]) e
    opcionais ``samples``, ``continue_from`` (Path do .npz de onde o roteiro parte) e
    ``transition_frames``. Cada passo continua o anterior e tudo vira um clipe só; ver
    ``kimodo_scripts/gerar.py``. ``steps`` (o argumento) são os passos de difusão.

    ``dry_run`` não carrega o modelo nem gera: só confere que o roteiro monta.

    Devolve [{take, sample, bvh, npz, frames, step_frames, **bvh_summary}].
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    tag = work_dir.name
    job_takes = []
    for i, take in enumerate(takes):
        item = {k: v for k, v in take.items() if v is not None}
        if take.get("continue_from"):
            # O container só enxerga a pasta do job: a animação anterior vai junto.
            shutil.copy2(take["continue_from"], work_dir / f"anterior_{i}.npz")
            item["continue_from"] = f"anterior_{i}.npz"
        job_takes.append(item)
    store.write_json(work_dir / "job.json", {"model": KIMODO_MODEL, "steps": steps, "takes": job_takes})
    shutil.copy2(ROOT / "kimodo_scripts" / "gerar.py", work_dir / "gerar.py")

    inside = f"/workspace/ponte_out/{tag}"
    cmd = ["docker", "compose", "run", "--rm", "-T", "--no-deps", "demo", "python", f"{inside}/gerar.py", f"{inside}/job.json"]
    if dry_run:
        cmd.append("--dry-run")
    script = work_dir / "run.sh"
    script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f'cd "{_repo()}"',
                f"mkdir -p ponte_out/{shlex.quote(tag)}",
                f"trap 'rm -rf ponte_out/{shlex.quote(tag)}' EXIT",
                f"cp {shlex.quote(to_wsl_path(work_dir))}/*.json {shlex.quote(to_wsl_path(work_dir))}/*.py ponte_out/{shlex.quote(tag)}/",
                f"cp {shlex.quote(to_wsl_path(work_dir))}/anterior_*.npz ponte_out/{shlex.quote(tag)}/ 2>/dev/null || true",
                shlex.join(cmd) + " 2>&1",
                f"cp ponte_out/{shlex.quote(tag)}/*.bvh ponte_out/{shlex.quote(tag)}/*.npz ponte_out/{shlex.quote(tag)}/result.json {shlex.quote(to_wsl_path(work_dir))}/",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )

    # Dentro do job tudo roda em sequência (passos, variações, tomadas): ocupa uma vaga só.
    with generation_slots(1, log):
        if not dry_run:
            ensure_ready(log)
        total = sum(s["seconds"] for t in takes for s in t["steps"]) * max(int(t.get("samples", 1)) for t in takes)
        log(f"{'conferindo o roteiro (sem gerar)' if dry_run else 'gerando no Kimodo'}: {sum(len(t['steps']) for t in takes)} passo(s), {total:g}s no total")
        proc = subprocess.Popen(
            ["wsl.exe", "-d", SETTINGS.wsl_distro, "-u", SETTINGS.wsl_user, "--", "bash", "-l", to_wsl_path(script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        tail: list[str] = []
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.replace("\x00", "").rstrip()
            # tqdm reescreve a linha com \r: só o último trecho interessa.
            line = line.split("\r")[-1].strip()
            if not line or "Warning" in line or "warnings.warn" in line or "torch.load(" in line:
                continue
            tail = (tail + [line])[-12:]
            log(line.removeprefix("[ponte] "))
        if proc.wait() != 0:
            raise KimodoError("O Kimodo falhou: " + " | ".join(tail[-4:]))

    result = store.read_json(work_dir / "result.json")
    if not result:
        raise KimodoError("O Kimodo terminou sem gravar o resultado.")
    out = []
    for item in result["outputs"]:
        bvh, npz = work_dir / f"{item['stem']}.bvh", work_dir / f"{item['stem']}.npz"
        if not bvh.exists():
            raise KimodoError(f"O Kimodo terminou sem gravar {bvh.name}.")
        out.append({**item, "bvh": bvh, "npz": npz if npz.exists() else None, **check_skeleton(bvh)})
    return out


def cleanup_work_dir(work_dir: Path) -> None:
    shutil.rmtree(work_dir, ignore_errors=True)
