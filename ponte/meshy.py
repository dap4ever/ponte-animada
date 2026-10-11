"""Personagens pelo Meshy (https://www.meshy.ai), em duas etapas, com aprovação no meio.

1. **Imagem**: o pedido (um texto em inglês) vira uma imagem do personagem (*Text to Image*).
   Ela aparece na tela de entrada da ponte, para o usuário aprovar ou reprovar.
2. **Modelo 3D**: só depois de aprovada, a imagem vira o modelo (*Image to 3D*), que entra na
   ponte como projeto novo, com laudo, pronto para rigar.

Gastar créditos no modelo antes de a imagem ser aprovada é o que este fluxo evita: a imagem
custa 3 créditos; o modelo, dezenas.

A chave da API vem da variável ``MESHY_API_KEY`` ou do arquivo ``meshy.key``, na raiz do projeto
(fora do git). Não fica em ``data/``: tudo que está lá é servido pela interface.

Cada pedido é uma pasta em ``data/meshy/<id>/``: ``pedido.json``, ``imagem.png`` e, depois de
aprovado, ``modelo.glb``. A API é a REST documentada em https://docs.meshy.ai (lida em 09/10/2026).
"""

from __future__ import annotations

import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from . import store
from .config import DATA, ROOT

Log = Callable[[str], None]
API = "https://api.meshy.ai"
KEY_FILE = ROOT / "meshy.key"
REQUESTS = DATA / "meshy"
IMAGE_MODEL = "nano-banana"  # o mais barato (3 créditos por imagem); os outros custam 6 ou 9
IMAGE_MODELS = ("nano-banana", "nano-banana-2", "nano-banana-pro", "gpt-image-2")
POSES = ("a-pose", "t-pose")
# Triângulos do modelo. Sem reduzir, os do Meshy passam de 800 mil e o Blender fica lento para
# rigar e animar. 0 deixa como o Meshy gerar.
POLYCOUNT = 50_000
WAITING, REJECTED, BUILDING, READY = "aguardando_aprovacao", "reprovado", "gerando_modelo", "pronto"
STATES = ("gerando_imagem", WAITING, REJECTED, BUILDING, READY, "erro")


class MeshyError(RuntimeError):
    pass


class MeshyTaskFailed(MeshyError):
    """O Meshy deu a tarefa por falha ou cancelada (os créditos dela voltam)."""


def api_key() -> str | None:
    key = (os.environ.get("MESHY_API_KEY") or "").strip()
    if not key and KEY_FILE.is_file():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    return key or None


def save_key(key: str) -> None:
    """Guarda a chave em ``meshy.key`` (fora do git e fora do que a interface serve)."""
    key = key.strip()
    if not key.startswith("msy_") or len(key) < 20:
        raise MeshyError("Isto não parece uma chave da API do Meshy (elas começam com msy_).")
    KEY_FILE.write_text(key + "\n", encoding="utf-8")


def _http(method: str, url: str, body: dict | None = None, *, timeout: float = 60.0) -> bytes:
    """Uma chamada à API (caminho começando em /) ou o download de um arquivo (endereço completo)."""
    headers = {}
    if url.startswith("/"):
        key = api_key()
        if not key:
            raise MeshyError("Falta a chave da API do Meshy. Crie uma em https://www.meshy.ai/developers/keys e guarde com `uv run ponte meshy key <chave>`.")
        url, headers = API + url, {"Authorization": f"Bearer {key}"}
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode("utf-8"), "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        try:
            detail = json.loads(detail).get("message") or detail
        except (ValueError, AttributeError):
            pass
        hints = {401: "a chave foi recusada", 402: "créditos insuficientes", 429: "pedidos demais; espere um pouco"}
        raise MeshyError(f"O Meshy recusou ({exc.code}{', ' + hints[exc.code] if exc.code in hints else ''}): {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise MeshyError(f"Não consegui falar com o Meshy: {exc}") from exc


def _call(method: str, path: str, body: dict | None = None) -> dict:
    return json.loads(_http(method, path, body) or b"{}")


def balance() -> int | None:
    """Créditos que restam na conta, ou None se o Meshy não disser."""
    try:
        return int(_call("GET", "/openapi/v1/balance")["balance"])
    except (MeshyError, KeyError, ValueError, TypeError):
        return None


def _wait(kind: str, task_id: str, log: Log, *, minutes: float, every: float = 5.0) -> dict:
    """Acompanha uma tarefa do Meshy até ela terminar. Devolve a tarefa pronta."""
    deadline = time.monotonic() + minutes * 60
    shown = -1
    while True:
        task = _call("GET", f"/openapi/v1/{kind}/{task_id}")
        status = task.get("status")
        if status == "SUCCEEDED":
            return task
        if status in ("FAILED", "CANCELED"):
            raise MeshyTaskFailed(f"O Meshy não concluiu a tarefa ({status.lower()}):{(task.get('task_error') or {}).get('message') or 'sem motivo informado'}")
        progress = int(task.get("progress") or 0)
        if progress >= shown + 10 or (status == "PENDING" and shown < 0):
            ahead = task.get("preceding_tasks") or 0
            log(f"Meshy: na fila ({ahead} na frente)" if status == "PENDING" else f"Meshy: {progress} %")
            shown = max(progress, 0)
        if time.monotonic() > deadline:
            raise MeshyError(f"O Meshy não terminou em {minutes:g} minutos (tarefa {task_id}).")
        time.sleep(every)


# --- Pedidos --------------------------------------------------------------------------


def _folder(request_id: str) -> Path:
    return REQUESTS / store._check_id(request_id)


def get(request_id: str) -> dict:
    record = store.read_json(_folder(request_id) / "pedido.json")
    if record is None:
        raise KeyError(f"pedido ao Meshy não encontrado: {request_id}")
    return record


def update(request_id: str, **fields) -> dict:
    record = {**get(request_id), **fields}
    store.write_json(_folder(request_id) / "pedido.json", record)
    return record


def list_requests() -> list[dict]:
    """Os pedidos, do mais novo para o mais antigo."""
    records = [store.read_json(path) for path in REQUESTS.glob("*/pedido.json")] if REQUESTS.is_dir() else []
    return sorted((r for r in records if r), key=lambda r: r.get("created_at", ""), reverse=True)


def request_image(prompt: str, name: str | None = None, *, pose: str = "a-pose", ai_model: str = IMAGE_MODEL, replaces: str | None = None, log: Log = lambda _line: None) -> dict:
    """Etapa 1: pede ao Meshy a imagem do personagem e a deixa na tela para aprovação.

    ``prompt`` em inglês. ``pose`` (``a-pose`` ou ``t-pose``) deixa os braços afastados do corpo,
    que é o que o rig precisa. ``replaces`` é o id de um pedido reprovado que este refaz: ele
    sai da lista quando a imagem nova chega.
    """
    prompt = prompt.strip()
    if len(prompt) < 3:
        raise MeshyError("Descreva o personagem (em inglês).")
    if pose not in POSES:
        raise MeshyError(f"Pose desconhecida: {pose}. Use uma de: {', '.join(POSES)}.")
    if ai_model not in IMAGE_MODELS:
        raise MeshyError(f"Modelo de imagem desconhecido: {ai_model}. Use um de: {', '.join(IMAGE_MODELS)}.")
    if not api_key():
        _http("GET", "/openapi/v1/balance")  # levanta o erro que explica como pôr a chave
    name = (name or prompt[:40]).strip()
    request_id = store.new_id(name)
    folder = _folder(request_id)
    folder.mkdir(parents=True)
    record = {"id": request_id, "name": name, "prompt": prompt, "pose": pose, "image_model": ai_model, "status": "gerando_imagem", "created_at": store.now(), "image": None, "note": "", "asset_id": None, "error": None}
    store.write_json(folder / "pedido.json", record)
    try:
        log(f"pedindo a imagem ao Meshy ({ai_model}, {pose}): {prompt}")
        task_id = _call("POST", "/openapi/v1/text-to-image", {"ai_model": ai_model, "prompt": prompt, "pose_mode": pose, "aspect_ratio": "3:4"})["result"]
        update(request_id, image_task=task_id)
        task = _wait("text-to-image", task_id, log, minutes=10)
        urls = task.get("image_urls") or []
        if not urls:
            raise MeshyError("O Meshy concluiu a tarefa sem devolver imagem.")
        (folder / "imagem.png").write_bytes(_http("GET", urls[0], timeout=120))
    except Exception as exc:
        update(request_id, status="erro", error=str(exc))
        raise
    record = update(request_id, status=WAITING, image="imagem.png", image_credits=task.get("consumed_credits"), image_at=store.now())
    if replaces:
        try:
            if get(replaces).get("status") in (REJECTED, "erro"):
                delete(replaces)
        except KeyError:
            pass
    log(f"imagem pronta: aguardando a aprovação em {folder / 'imagem.png'}")
    return record


def reject(request_id: str, note: str = "") -> dict:
    """O usuário não quer esta imagem. A nota diz o que mudar no pedido seguinte."""
    record = get(request_id)
    if record["status"] not in (WAITING, REJECTED):
        raise MeshyError(f"Este pedido não está aguardando aprovação (está {record['status']}).")
    return update(request_id, status=REJECTED, note=note.strip(), reviewed_at=store.now())


def claim(request_id: str) -> dict:
    """Marca a imagem como aprovada, uma vez só: dois cliques não pedem (nem pagam) dois modelos."""
    record = get(request_id)
    if record["status"] != WAITING or not record.get("image_task"):
        raise MeshyError(f"Este pedido não está aguardando aprovação (está {record['status']}).")
    return update(request_id, status=BUILDING, approved_at=store.now(), error=None)


def generate_model(request_id: str, *, polycount: int = POLYCOUNT, log: Log = lambda _line: None) -> Path:
    """Etapa 2, depois da aprovação (``claim``): a imagem vira o modelo 3D. Devolve o GLB baixado.

    Quem cria o projeto com ele é ``pipeline.approve_meshy``. Se o pedido já tinha uma tarefa de
    modelo no Meshy (o programa foi fechado no meio), ela é retomada, sem pagar outra.
    """
    record = get(request_id)
    if record["status"] != BUILDING:
        raise MeshyError(f"A imagem deste pedido ainda não foi aprovada (está {record['status']}).")
    folder = _folder(request_id)
    if (folder / "modelo.glb").is_file() and record.get("model_task"):
        log("o modelo deste pedido já tinha sido baixado: aproveitando")
        return folder / "modelo.glb"
    body: dict = {"input_task_id": record["image_task"], "pose_mode": record.get("pose") or "a-pose", "should_texture": True, "target_formats": ["glb"]}
    if polycount:
        body.update(should_remesh=True, topology="triangle", target_polycount=int(polycount))
    try:
        task_id = record.get("model_task")
        if task_id:
            log("retomando o modelo 3D que já estava sendo gerado no Meshy")
        else:
            log("imagem aprovada: pedindo o modelo 3D ao Meshy (leva alguns minutos)")
            task_id = _call("POST", "/openapi/v1/image-to-3d", body)["result"]
            update(request_id, model_task=task_id)
        task = _wait("image-to-3d", task_id, log, minutes=30, every=8.0)
        url = (task.get("model_urls") or {}).get("glb")
        if not url:
            raise MeshyError("O Meshy concluiu a tarefa sem devolver o GLB.")
        log("baixando o modelo")
        (folder / "modelo.glb").write_bytes(_http("GET", url, timeout=600))
    except Exception as exc:
        # A imagem continua aprovável: dá para tentar o modelo de novo sem pagar outra imagem.
        # Só se o Meshy desistiu da tarefa (e devolveu os créditos) a próxima tentativa pede
        # outra; caindo a rede ou o prazo daqui, a mesma tarefa é retomada.
        update(request_id, status=WAITING, error=str(exc), **({"model_task": None} if isinstance(exc, MeshyTaskFailed) else {}))
        raise
    update(request_id, model_credits=task.get("consumed_credits"))
    return folder / "modelo.glb"


def delete(request_id: str) -> None:
    """Tira o pedido da lista. O projeto criado a partir dele, se houver, fica."""
    shutil.rmtree(_folder(request_id), ignore_errors=True)


def status() -> dict:
    """Para a interface: há chave? e os pedidos, com o endereço da imagem de cada um."""
    requests = list_requests()
    for record in requests:
        record["files_base"] = f"/files/meshy/{record['id']}"
    return {"configured": api_key() is not None, "requests": requests}
