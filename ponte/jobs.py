"""Registro de jobs (inspeção, geração, retarget) visível para o servidor e para a CLI."""

from __future__ import annotations

import ctypes
import os
import secrets
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import store
from .config import DATA

JOBS = DATA / "jobs"
ACTIVE = ("fila", "rodando")


def _path(job_id: str) -> Path:
    return JOBS / f"{job_id}.json"


def log_path(job_id: str) -> Path:
    return JOBS / f"{job_id}.log"


def create(kind: str, title: str, params: dict | None = None) -> dict:
    job = {
        "id": f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}",
        "kind": kind,
        "title": title,
        "params": params or {},
        "status": "fila",
        "progress": "na fila",
        "pid": os.getpid(),
        "created_at": store.now(),
        "started_at": None,
        "ended_at": None,
        "error": None,
        "output": None,
    }
    store.write_json(_path(job["id"]), job)
    return job


def get(job_id: str) -> dict | None:
    return store.read_json(_path(job_id))


def update(job_id: str, **fields) -> None:
    job = get(job_id)
    if job:
        job.update(fields)
        store.write_json(_path(job_id), job)


def log(job_id: str | None, line: str) -> None:
    """Acrescenta uma linha ao log do job e a mostra como progresso."""
    line = line.strip()
    if not line or job_id is None:
        return
    with log_path(job_id).open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    update(job_id, progress=line[:200])


def run(job: dict, work: Callable[[str], dict | None]) -> dict:
    """Executa ``work(job_id)`` registrando início, fim e erro. Devolve o job final."""
    job_id = job["id"]
    update(job_id, status="rodando", started_at=store.now(), pid=os.getpid(), progress="iniciando")
    try:
        output = work(job_id)
        update(job_id, status="ok", ended_at=store.now(), output=output, progress="concluído")
    except Exception as exc:  # noqa: BLE001 - o motivo vai para quem está validando
        with log_path(job_id).open("a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        update(job_id, status="erro", ended_at=store.now(), error=str(exc), progress="erro")
    return get(job_id)


def _pid_alive(pid: int) -> bool:
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


def list_jobs(limit: int = 40) -> list[dict]:
    """Jobs mais recentes primeiro. Job ativo cujo processo morreu vira 'interrompido'."""
    if not JOBS.exists():
        return []
    out = []
    for path in sorted(JOBS.glob("*.json"), reverse=True)[:limit]:
        job = store.read_json(path)
        if not job:
            continue
        if job["status"] in ACTIVE and not _pid_alive(job["pid"]):
            job.update(status="interrompido", ended_at=store.now(), progress="o processo que rodava este job foi encerrado")
            store.write_json(path, job)
        out.append(job)
    return out
