"""API local + interface web do PonteAnimada."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ardy, blender, engines, games, jobs, kimodo, kimodo_cpp, meshy, pipeline, store, terminal
from .config import DATA, KIMODO_MAX_SAMPLES, WEB

DATA.mkdir(parents=True, exist_ok=True)
store.PROJECTS.mkdir(exist_ok=True)
store.migrate_layout_safely()  # acervo do formato antigo vai para a pasta do projeto dele


@asynccontextmanager
async def _lifespan(_: FastAPI):
    yield
    terminal.close_all()  # servidor parado com Ctrl+C: nenhum Claude de terminal fica rodando sem dono


app = FastAPI(title="PonteAnimada", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=_lifespan)
POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="ponte-job")
_kimodo_cache: tuple[float, dict] = (0.0, {})
_ardy_cache: tuple[float, dict] = (0.0, {})


def submit(kind: str, title: str, params: dict, work: Callable[[Callable[[str], None]], dict | None]) -> dict:
    job = jobs.create(kind, title, params)
    POOL.submit(jobs.run, job, lambda job_id: work(lambda line: jobs.log(job_id, line)))
    return job


def _check(kind: str, item_id: str) -> dict:
    if kind not in store.KINDS:
        raise HTTPException(404, f"Tipo desconhecido: {kind}")
    try:
        return store.get(kind, item_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, str(exc.args[0])) from exc


async def _receive(request: Request, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
    if target.stat().st_size == 0:
        target.unlink()
        raise HTTPException(400, "Arquivo vazio.")


def _kimodo_status() -> dict:
    global _kimodo_cache
    at, value = _kimodo_cache
    if time.monotonic() - at > 4.0:
        value = kimodo.status()
        _kimodo_cache = (time.monotonic(), value)
    return value


def _ardy_status() -> dict:
    global _ardy_cache
    at, value = _ardy_cache
    if time.monotonic() - at > 4.0:
        value = ardy.status()
        _ardy_cache = (time.monotonic(), value)
    return value


# --- Estado ---------------------------------------------------------------------------


def _with_files(kind: str, records: list[dict]) -> list[dict]:
    """Acrescenta a cada registro o endereço da pasta dele, dentro do projeto a que pertence."""
    for record in records:
        project = record["id"] if kind == "asset" else record["asset_id"]
        tail = "" if kind == "asset" else f"/{record['id']}"
        record["files_base"] = f"/files/projects/{project}/{store.KINDS[kind]}{tail}"
    return records


def _item_view(item: dict) -> dict:
    """Uma textura, um som ou um documento, como a tela recebe.

    O documento diz o tamanho e a hora em que foi gravado pela última vez, lidos do arquivo: é
    assim que a tela mostra, sozinha, o que a IA do terminal acabou de escrever nele.
    """
    view = {**item, "files_base": f"/files/games/{item['game']}/{games.ITEMS}/{item['id']}"}
    if item["kind"] == games.DOCUMENT:
        try:
            stat = games.item_path(item).stat()
        except OSError:
            return view
        view.update(size_bytes=stat.st_size, modified=int(stat.st_mtime * 1000))
    return view


@app.get("/api/state")
def state() -> dict:
    """Tudo que a interface mostra.

    Cada personagem é um projeto; animações e prévias ("results") dizem em ``asset_id`` de
    qual. O personagem encerrado traz o resultado em ``final``. Os projetos dizem em ``game`` de
    que jogo são, em ``role`` se são personagem ou modelo 3D (um asset do jogo) e, em ``tab``, em
    que aba da tela do jogo estão.
    """
    assets = _with_files("asset", store.list_all("asset"))
    previews = _with_files("result", store.list_all("result"))
    for asset in assets:
        final = asset.get("final")
        if final:
            final["files_base"] = f"/files/projects/{asset['id']}/{store.FINAL}"
            # O projeto mudou depois de encerrado: o resultado não acompanha sozinho.
            final["stale"] = final.get("signature") != pipeline.final_signature(asset, [p for p in previews if p["asset_id"] == asset["id"]])
    return {
        # Os jogos, com as abas da tela de cada um, e as texturas, os sons e os documentos deles
        # ("items"; os modelos 3D são projetos, em "assets"). "tasks" são as tarefas das abas de gestão.
        "games": [{**game, "tabs": games.tabs(game), "files_base": f"/files/games/{game['id']}"} for game in games.list_games()],
        "items": [_item_view(item) for item in games.list_items()],
        "tasks": games.list_tasks(),
        "assets": assets,
        "motions": _with_files("motion", store.list_all("motion")),
        "results": previews,
        "jobs": jobs.list_jobs(),
        "kimodo": _kimodo_status(),
        # O ARDY: instalado? o codificador de texto dele está no ar?
        "ardy": _ardy_status(),
        # Os personagens pedidos ao Meshy: a imagem de cada um, para aprovar, e o que já virou projeto.
        "meshy": meshy.status(),
        # Os geradores e qual está em uso: a interface pergunta ao abrir.
        "engines": engines.status(),
    }


class EngineBody(BaseModel):
    engine: str


@app.put("/api/engine")
def choose_engine(body: EngineBody) -> dict:
    """Troca o gerador em uso: o Kimodo original, o kimodo.cpp ou o ARDY."""
    try:
        engines.choose(body.engine)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return engines.status()


@app.get("/api/jobs/{job_id}/log", response_class=PlainTextResponse)
def job_log(job_id: str) -> str:
    path = jobs.log_path(job_id)
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


# --- Assets ---------------------------------------------------------------------------


def _game(game_id: str) -> dict:
    try:
        return games.get(game_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, str(exc.args[0])) from exc


def _into_game(asset: dict, game: str | None, role: str | None, tab: str | None = None) -> dict:
    """Põe o projeto recém-criado no jogo a que ele foi enviado, com o papel dito e na aba dita."""
    if game or role:
        asset = games.assign(asset["id"], game, role)
    return games.place(asset["id"], tab) if tab else asset


def _tab(game_id: str, tab: str) -> dict:
    try:
        return games.get_tab(game_id, tab)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc


@app.post("/api/assets")
async def upload_asset(request: Request, filename: str, name: str | None = None, defer: bool = False, game: str | None = None, role: str | None = None, tab: str | None = None) -> dict:
    """Recebe o modelo (ou um .zip com modelo e texturas).

    Com ``defer`` o laudo espera: o cliente ainda vai mandar as texturas. ``game`` é o jogo em que
    ele entra e ``role``, o que ele é lá: "personagem" (o padrão) ou "modelo", um asset. ``tab`` é
    a aba do jogo em que ele fica; ela diz também o papel.
    """
    if game:
        _game(game)
    if role and role not in games.ROLES:
        raise HTTPException(400, f"Papel desconhecido: {role}.")
    if tab:
        if not game:
            raise HTTPException(400, "A aba é de um jogo: diga o jogo.")
        if _tab(game, tab)["kind"] == "gestao":
            raise HTTPException(400, "Numa aba de gestão ficam tarefas e documentos, não personagens nem modelos.")
    if filename.lower().endswith(".zip"):
        tmp = DATA / "tmp" / f"{store.new_id(Path(filename).stem)}.zip"
        await _receive(request, tmp)
        try:
            asset = _into_game(pipeline.add_zip(tmp, name or Path(filename).stem), game, role, tab)
        except zipfile.BadZipFile as exc:
            raise HTTPException(400, "O arquivo .zip está corrompido ou não é um zip.") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            tmp.unlink(missing_ok=True)
        job = submit("inspecao", f"Inspecionar {asset['name']}", {"asset_id": asset["id"]}, lambda log: {"asset_id": pipeline.inspect_asset(asset["id"], log)["id"]})
        return {"asset": asset, "job": job}
    try:
        asset = _into_game(pipeline.create_asset(filename, name), game, role, tab)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        await _receive(request, pipeline.source_path(asset))
    except Exception:
        store.delete("asset", asset["id"])
        raise
    if defer:
        return {"asset": asset, "job": None}
    job = submit("inspecao", f"Inspecionar {asset['name']}", {"asset_id": asset["id"]}, lambda log: {"asset_id": pipeline.inspect_asset(asset["id"], log)["id"]})
    return {"asset": asset, "job": job}


@app.post("/api/assets/{asset_id}/inspect")
def reinspect(asset_id: str) -> dict:
    asset = _check("asset", asset_id)
    return submit("inspecao", f"Inspecionar {asset['name']}", {"asset_id": asset_id}, lambda log: {"asset_id": pipeline.inspect_asset(asset_id, log)["id"]})


@app.post("/api/assets/{asset_id}/files")
async def upload_asset_file(request: Request, asset_id: str, path: str) -> dict:
    """Recebe uma textura (ou .mtl/.bin) para ficar junto do modelo. Depois, refaça o laudo."""
    _check("asset", asset_id)
    try:
        target = pipeline.sidecar_path(asset_id, path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await _receive(request, target)
    return {"path": path, "size_bytes": target.stat().st_size}


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class RigBody(BaseModel):
    # Marcadores da vista de frente, [x, altura] em metros: chin, groin, l_/r_ wrist, elbow, knee.
    markers: dict[str, tuple[float, float]]
    fingers: bool = True


@app.post("/api/assets/{asset_id}/rig/estimate")
def rig_estimate(asset_id: str) -> dict:
    """Estima os marcadores do rig, para o humano conferir (ficam em asset.rig.estimated)."""
    asset = _check("asset", asset_id)
    return submit("rig", f"Marcadores de {asset['name']}", {"asset_id": asset_id}, lambda log: {"asset_id": asset_id, "rig": pipeline.estimate_rig_markers(asset_id, log)})


@app.post("/api/assets/{asset_id}/rig")
def rig(asset_id: str, body: RigBody) -> dict:
    """Riga o personagem no padrão Mixamo com os marcadores conferidos."""
    asset = _check("asset", asset_id)
    missing = [m for m in pipeline.RIG_MARKERS if m not in body.markers]
    if missing:
        raise HTTPException(400, f"Faltam marcadores: {', '.join(missing)}.")
    markers = {name: list(body.markers[name]) for name in pipeline.RIG_MARKERS}
    return submit("rig", f"Rigar {asset['name']}", {"asset_id": asset_id, "fingers": body.fingers}, lambda log: {"asset_id": pipeline.rig_asset(asset_id, markers, fingers=body.fingers, log=log)["id"]})


@app.post("/api/assets/{asset_id}/test-walk")
def test_walk(asset_id: str) -> dict:
    """Aplica a caminhada de exemplo no personagem, para ver como o rig deforma."""
    asset = _ready_asset(asset_id)
    return submit("retarget", f"Caminhada de teste em {asset['name']}", {"asset_id": asset_id}, lambda log: {"result_ids": [pipeline.test_walk(asset_id, log)["id"]]})


@app.post("/api/assets/{asset_id}/props")
async def upload_prop(request: Request, asset_id: str, filename: str) -> dict:
    """Recebe o arquivo de um acessório (arma etc.) e o converte para o visualizador."""
    asset = _check("asset", asset_id)
    try:
        prop, target = pipeline.create_prop(asset_id, filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        await _receive(request, target)
    except Exception:
        pipeline.delete_prop(asset_id, prop["id"])
        raise

    def work(log):
        try:
            pipeline.convert_prop(asset_id, prop["id"], log)
        except Exception:
            pipeline.delete_prop(asset_id, prop["id"])
            raise
        return {"asset_id": asset_id, "prop_id": prop["id"]}

    return {"prop": prop, "job": submit("inspecao", f"Acessório {prop['name']} em {asset['name']}", {"asset_id": asset_id}, work)}


class PropPlacement(BaseModel):
    bone: str | None = None
    # Matriz local ao osso, 16 números por colunas (como o three.js guarda).
    matrix: list[float] | None = Field(default=None, min_length=16, max_length=16)


@app.put("/api/assets/{asset_id}/props/{prop_id}")
def place_prop(asset_id: str, prop_id: str, body: PropPlacement) -> dict:
    _check("asset", asset_id)
    try:
        return pipeline.place_prop(asset_id, prop_id, body.bone, body.matrix)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc


@app.delete("/api/assets/{asset_id}/props/{prop_id}")
def delete_prop(asset_id: str, prop_id: str) -> dict:
    _check("asset", asset_id)
    pipeline.delete_prop(asset_id, prop_id)
    return {"deleted": prop_id}


@app.get("/api/assets/{asset_id}/report")
def asset_report(asset_id: str) -> dict:
    _check("asset", asset_id)
    report = store.read_json(store.folder("asset", asset_id) / "report.json")
    if report is None:
        raise HTTPException(404, "Este asset ainda não tem laudo.")
    return report


class MappingBody(BaseModel):
    slots: dict[str, str | None] = Field(default_factory=dict)
    torso: list[str] | None = None
    neck: list[str] | None = None


@app.put("/api/assets/{asset_id}/mapping")
def put_mapping(asset_id: str, body: MappingBody) -> dict:
    asset = _check("asset", asset_id)
    override = body.model_dump(exclude_none=False)
    return submit("inspecao", f"Remapear {asset['name']}", {"asset_id": asset_id}, lambda log: {"asset_id": pipeline.set_mapping(asset_id, override, log)["id"]})


# --- Jogos ----------------------------------------------------------------------------
# Cada jogo junta os personagens e os assets dele (ponte/games.py). Estas rotas ficam antes de
# "/api/{kind}/{item_id}", lá embaixo, que casaria com "/api/games/<id>" e "/api/items/<id>".


class GameBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    # A pasta onde está o código do jogo (opcional): é o que a IA do terminal lê no guia.
    code_path: str | None = Field(default=None, max_length=400)


@app.post("/api/games")
def create_game(body: GameBody) -> dict:
    try:
        return games.create(body.name, body.code_path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class GamePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    code_path: str | None = Field(default=None, max_length=400)


@app.patch("/api/games/{game_id}")
def change_game(game_id: str, body: GamePatch) -> dict:
    """Muda o nome do jogo ou a pasta do código dele (vazia: tira a que estava)."""
    game = _game(game_id)
    try:
        if body.name is not None:
            game = games.rename(game_id, body.name)
        if "code_path" in body.model_fields_set:
            game = games.set_code_path(game_id, body.code_path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return game


@app.delete("/api/games/{game_id}")
def delete_game(game_id: str) -> dict:
    """Apaga o jogo, com as texturas e os sons dele. Os personagens e os modelos 3D ficam, sem jogo."""
    _game(game_id)
    # Os terminais abertos na pasta do jogo a segurariam no disco: o dele e os das texturas e dos sons, que ficam dentro dela.
    for item in games.list_items(game_id):
        terminal.restart(item["id"])
    terminal.restart(game_id)
    games.delete(game_id)
    for _ in range(10):  # o Windows demora um instante para soltar a pasta depois que o terminal fecha
        if not games.folder(game_id).exists():
            break
        time.sleep(0.3)
        games.delete(game_id)
    return {"deleted": game_id}


def _gone(folders: list[Path]) -> None:
    """Insiste em apagar pastas que um terminal recém-fechado ainda segura: o Windows demora um instante para soltá-las."""
    for _ in range(10):
        left = [folder for folder in folders if folder.exists()]
        if not left:
            break
        time.sleep(0.3)
        for folder in left:
            shutil.rmtree(folder, ignore_errors=True)


@app.post("/api/games/{game_id}/items")
async def upload_item(request: Request, game_id: str, filename: str, name: str | None = None, tab: str | None = None) -> dict:
    """Recebe uma textura ou um som para os assets do jogo, ou um documento para uma aba de gestão."""
    _game(game_id)
    try:
        record, target = games.new_item(game_id, filename, name, tab)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        await _receive(request, target)
    except Exception:
        games.discard_item(record)
        raise
    return games.save_item(record)


def _item(item_id: str) -> dict:
    try:
        return games.get_item(item_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, str(exc.args[0])) from exc


class ItemPatch(BaseModel):
    """O que dá para mudar numa textura, num som ou num documento: o nome e a aba em que está."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    tab: str | None = Field(default=None, max_length=80)


@app.patch("/api/items/{item_id}")
def change_item(item_id: str, body: ItemPatch) -> dict:
    item = _item(item_id)
    try:
        if body.name is not None:
            item = games.rename_item(item_id, body.name)
        if body.tab is not None:
            item = games.place_item(item_id, body.tab)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return item


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str) -> dict:
    _item(item_id)
    folder = games.item_folder(item_id)
    terminal.restart(item_id)  # o terminal aberto na pasta do asset seguraria ela no disco
    games.delete_item(item_id)
    _gone([folder])
    return {"deleted": item_id}


# As abas da tela do jogo: duas vêm com ele (Characters e Assets) e as outras o dono cria, de
# personagens, de assets ou de gestão (tarefas e documentos).


class TabBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    kind: str


@app.post("/api/games/{game_id}/tabs")
def create_tab(game_id: str, body: TabBody) -> dict:
    _game(game_id)
    try:
        return games.add_tab(game_id, body.name, body.kind)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class TabPatch(BaseModel):
    name: str = Field(min_length=1, max_length=40)


@app.patch("/api/games/{game_id}/tabs/{tab_id}")
def rename_tab(game_id: str, tab_id: str, body: TabPatch) -> dict:
    _game(game_id)
    _tab(game_id, tab_id)
    try:
        return games.rename_tab(game_id, tab_id, body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/games/{game_id}/tabs/{tab_id}")
def delete_tab(game_id: str, tab_id: str) -> dict:
    """Apaga uma aba criada pelo dono.

    Os personagens e os assets que estavam nela voltam para a aba que vem com o jogo. De uma aba
    de gestão, as tarefas e os documentos saem do disco.
    """
    _game(game_id)
    tab = _tab(game_id, tab_id)
    folders = []
    if tab["kind"] == "gestao":
        for document in games.documents(game_id, tab["id"]):
            folders.append(games.item_folder(document["id"]))
            terminal.restart(document["id"])  # o terminal aberto na pasta do documento seguraria ela no disco
    try:
        games.delete_tab(game_id, tab["id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _gone(folders)
    return {"deleted": tab["id"]}


# Numa aba de gestão: os documentos (arquivos de texto, guardados como as texturas e os sons) e o
# quadro de tarefas.


class DocumentBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    tab: str | None = Field(default=None, max_length=80)


@app.post("/api/games/{game_id}/documents")
def create_document(game_id: str, body: DocumentBody) -> dict:
    """Cria um documento em branco numa aba de gestão (sem aba dita, na primeira do jogo)."""
    _game(game_id)
    try:
        return _item_view(games.new_document(game_id, body.name, body.tab))
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class TextBody(BaseModel):
    text: str = Field(max_length=2_000_000)


@app.put("/api/items/{item_id}/text")
def write_document(item_id: str, body: TextBody) -> dict:
    """Grava o texto de um documento: o que o dono escreveu na tela."""
    _item(item_id)
    try:
        return _item_view(games.write_document(item_id, body.text))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class TaskBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    tab: str | None = Field(default=None, max_length=80)
    notes: str = Field(default="", max_length=4000)
    status: str = games.TASK_STATES[0]


@app.post("/api/games/{game_id}/tasks")
def create_task(game_id: str, body: TaskBody) -> dict:
    _game(game_id)
    try:
        return games.add_task(game_id, body.title, body.tab, body.notes, body.status)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = None
    notes: str | None = Field(default=None, max_length=4000)
    tab: str | None = Field(default=None, max_length=80)


@app.patch("/api/tasks/{task_id}")
def change_task(task_id: str, body: TaskPatch) -> dict:
    """Muda o título, a nota, a coluna (a_fazer, fazendo, feito) ou a aba de uma tarefa."""
    try:
        return games.update_task(task_id, title=body.title, status=body.status, notes=body.notes, tab=body.tab)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str) -> dict:
    try:
        games.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    games.delete_task(task_id)
    return {"deleted": task_id}


# --- Animações ------------------------------------------------------------------------


class TravelBody(BaseModel):
    """Trajetória imposta: direção + velocidade, ou pontos [direita, frente] em metros do Kimodo."""

    direction_deg: float | None = None
    speed: float | None = Field(default=None, gt=0, le=8)
    waypoints: list[tuple[float, float]] | None = Field(default=None, min_length=1, max_length=40)
    lock_facing: bool = False

    def as_travel(self, seconds: float) -> dict:
        if self.waypoints:
            points = [(0.0, 0.0), *self.waypoints]
            length = sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(points, points[1:]))
            if length / seconds > 6.0:
                raise HTTPException(400, f"O caminho tem {length:.1f} m para {seconds:g} s: rápido demais. Aumente os segundos ou encurte o caminho.")
            return {"waypoints": [list(p) for p in self.waypoints], "lock_facing": self.lock_facing}
        if self.direction_deg is None or self.speed is None:
            raise HTTPException(400, "A trajetória precisa de direção e ritmo, ou de um caminho desenhado.")
        return {"direction_deg": self.direction_deg % 360, "speed": self.speed, "lock_facing": self.lock_facing}


class StepBody(BaseModel):
    """Um passo do roteiro: a ação, quanto dura e, opcionalmente, por onde o quadril anda."""

    text: str = Field(min_length=2, max_length=300)
    seconds: float = Field(gt=0, le=10)
    travel: TravelBody | None = None
    # O passo termina na pose em que começou: é o trecho que o jogo toca em laço.
    loop: bool = False
    # Quanto o Kimodo obedece ao texto (padrão dele: 2). Mais peso dá um gesto mais marcado.
    text_weight: float | None = Field(default=None, ge=0.5, le=8)
    # Nome do passo, para achá-lo na interface (ex.: "agitado").
    label: str | None = Field(default=None, max_length=60)


class GenerateBody(BaseModel):
    """Pedido de animação: um roteiro (premissa + passos em sequência) num clipe contínuo.

    ``prompt`` + ``durations`` é a forma curta: cada frase vira um passo.
    """

    premise: str = Field(default="", max_length=300)
    steps: list[StepBody] | None = Field(default=None, min_length=1, max_length=12)
    prompt: str | None = Field(default=None, max_length=600)
    durations: list[float] = Field(default_factory=lambda: [5.0], min_length=1)
    seed: int | None = None
    samples: int = Field(default=1, ge=1, le=KIMODO_MAX_SAMPLES)
    asset_id: str | None = None
    in_place: bool = False
    continue_from: str | None = None
    # Animação que este pedido refaz: é apagada, com as prévias, quando a nova fica pronta.
    replaces: str | None = None
    # Nome do roteiro (ex.: "Reações"). Numa continuação, sem ele vale o que o roteiro já tinha.
    name: str | None = Field(default=None, max_length=60)
    # O gerador: "kimodo" (o original), "cpp" ou "ardy". Sem ele, o que está em uso.
    engine: str | None = None


def _ready_asset(asset_id: str) -> dict:
    asset = _check("asset", asset_id)
    if asset.get("verdict") != "pronto":
        raise HTTPException(400, f"O asset '{asset['name']}' não está pronto para animar.")
    return asset


@app.post("/api/motions/generate")
def generate(body: GenerateBody) -> dict:
    try:
        if body.steps:
            steps = [{"text": s.text, "seconds": s.seconds, "travel": s.travel.as_travel(s.seconds) if s.travel else None, "loop": s.loop, "text_weight": s.text_weight, "label": s.label} for s in body.steps]
            if steps[0]["loop"] and not body.continue_from:
                raise HTTPException(400, "Um passo em laço precisa de um passo antes dele: gere primeiro a entrada e ponha o laço no passo seguinte.")
        elif body.prompt and body.prompt.strip():
            steps = kimodo.steps_from_prompt(body.prompt, body.durations)
        else:
            raise HTTPException(400, "Escreva pelo menos um passo do roteiro.")
        if any(s["seconds"] > 10 for s in steps):
            raise HTTPException(400, "O Kimodo gera no máximo 10 segundos por passo. Para mais, acrescente passos.")
        title = " → ".join(pipeline.compose_step_text(body.premise, s["text"]) for s in steps)
        if body.continue_from:
            _check("motion", body.continue_from)
        # O gerador do pedido. O que ele não sabe fazer é recusado já, e não no meio do job.
        engine, previous = pipeline.resolve_engine(body.engine, body.continue_from)
        if engine == "cpp":
            kimodo_cpp.check_script([*((previous or {}).get("steps") or []), *steps])
            if previous and body.samples > 1:
                raise ValueError("No kimodo.cpp as variações só valem no primeiro passo do roteiro.")
        if engine == "ardy":
            ardy.check_script(steps)
    except (kimodo.KimodoError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    # Toda animação nasce dentro de um projeto (o do personagem que a recebe).
    if not body.asset_id:
        raise HTTPException(400, "Escolha o projeto: a animação é gerada para um personagem.")
    asset = _ready_asset(body.asset_id)
    if previous:
        if previous.get("asset_id") != body.asset_id:
            raise HTTPException(400, "A animação a continuar é de outro projeto.")
        if engine in ("kimodo", "ardy") and not (store.folder("motion", previous["id"]) / "motion.npz").exists():
            raise HTTPException(400, "Esta animação não traz os dados para continuar dela. Comece uma nova animação.")
    if body.replaces:
        if body.replaces == body.continue_from:
            raise HTTPException(400, "A animação a refazer não pode ser a mesma de onde o passo parte.")
        if _check("motion", body.replaces).get("asset_id") != body.asset_id:
            raise HTTPException(400, "A animação a refazer é de outro projeto.")
    options = dict(premise=body.premise, seed=body.seed, samples=body.samples, continue_from=body.continue_from, replaces=body.replaces, name=body.name, engine=engine)
    verb = "Refazer" if body.replaces else "Continuar" if body.continue_from else "Gerar"

    def work(log):
        results = pipeline.animate(body.asset_id, steps, in_place=body.in_place, log=log, **options)
        return {"result_ids": [r["id"] for r in results], "motion_ids": [r["motion_id"] for r in results]}

    return submit("animacao", f"{verb} em {asset['name']}: {title}", body.model_dump(), work)


class MotionLabels(BaseModel):
    """Nome do roteiro e dos passos dele (na ordem; None deixa o passo como está)."""

    name: str | None = Field(default=None, max_length=60)
    labels: list[str | None] | None = Field(default=None, max_length=40)
    # Passos que são as ações principais do personagem: aparecem primeiro na lista de ações.
    stars: list[bool | None] | None = Field(default=None, max_length=40)


@app.patch("/api/motions/{motion_id}")
def label_motion(motion_id: str, body: MotionLabels) -> dict:
    _check("motion", motion_id)
    try:
        return pipeline.label_motion(motion_id, body.name, body.labels, body.stars)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/motions/import")
async def import_motion(request: Request, filename: str, asset_id: str, label: str | None = None) -> dict:
    """Importa um BVH do Kimodo para dentro do projeto ``asset_id``."""
    if not filename.lower().endswith(".bvh"):
        raise HTTPException(400, "Só BVH pode ser importado como animação.")
    _check("asset", asset_id)
    tmp = DATA / "tmp" / f"{store.new_id(Path(filename).stem)}.bvh"
    await _receive(request, tmp)
    try:
        return _with_files("motion", [pipeline.import_motion(asset_id, tmp, label or Path(filename).stem)])[0]
    except (kimodo.KimodoError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp.unlink(missing_ok=True)


@app.post("/api/motions/import-fbx")
async def import_fbx_motion(request: Request, filename: str, asset_id: str, label: str | None = None) -> dict:
    """Recebe uma animação pronta em FBX (as do Mixamo) e a aplica no personagem do projeto."""
    if not filename.lower().endswith(".fbx"):
        raise HTTPException(400, "A animação do Mixamo precisa estar em FBX.")
    asset = _ready_asset(asset_id)
    tmp = DATA / "tmp" / f"{store.new_id(Path(filename).stem)}.fbx"
    await _receive(request, tmp)
    name = (label or Path(filename).stem).strip()

    def work(log):
        try:
            preview = pipeline.import_mixamo(asset_id, tmp, name, filename, log)
        finally:
            tmp.unlink(missing_ok=True)
        return {"result_ids": [preview["id"]], "motion_ids": [preview["motion_id"]]}

    return submit("retarget", f"Importar do Mixamo: {name} → {asset['name']}", {"asset_id": asset_id}, work)


# --- Prévias (a animação aplicada no personagem, para validar) ------------------------------


class RetargetBody(BaseModel):
    asset_id: str
    motion_id: str
    in_place: bool = False
    # Ajuste de pose: {osso: [w, x, y, z]}, rotação extra no espaço local do osso.
    adjust: dict[str, tuple[float, float, float, float]] | None = None


@app.post("/api/results")
def create_result(body: RetargetBody) -> dict:
    asset = _check("asset", body.asset_id)
    motion = _check("motion", body.motion_id)
    if motion.get("asset_id") != body.asset_id:
        raise HTTPException(400, "Esta animação é de outro projeto: cada projeto usa só as animações dele.")
    if asset.get("verdict") != "pronto":
        raise HTTPException(400, f"O asset '{asset['name']}' não está pronto para animar.")
    title = f"Retarget {motion.get('prompt', motion['id'])} → {asset['name']}"
    adjust = {bone: list(quat) for bone, quat in (body.adjust or {}).items()}
    return submit(
        "retarget",
        title,
        body.model_dump(),
        lambda log: {"result_ids": [pipeline.retarget(body.asset_id, body.motion_id, in_place=body.in_place, adjust=adjust, log=log)["id"]]},
    )


@app.post("/api/results/{result_id}/open-blender")
def open_in_blender(result_id: str) -> dict:
    result = _check("result", result_id)
    blend = store.folder("result", result_id) / result["files"].get("blend", "")
    if not blend.is_file():
        raise HTTPException(404, "Esta prévia não tem arquivo .blend.")
    blender.open_in_blender(blend)
    return {"opened": blend.name}


# --- Revisão, pastas, exclusão ------------------------------------------------------------


class ReviewBody(BaseModel):
    status: str
    notes: str = ""


@app.post("/api/review/{kind}/{item_id}")
def review(kind: str, item_id: str, body: ReviewBody) -> dict:
    _check(kind, item_id)
    if kind == "motion":
        raise HTTPException(400, "A revisão é feita no personagem ou na prévia.")
    try:
        return store.set_review(kind, item_id, body.status, body.notes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/open-folder/{kind}/{item_id}")
def open_folder(kind: str, item_id: str) -> dict:
    """Abre a pasta no Explorer. Para o personagem, a do projeto inteiro; ``final`` é o resultado dele."""
    if kind == "final":
        _check("asset", item_id)
        target = store.final_folder(item_id)
        if not target.is_dir():
            raise HTTPException(404, "Este personagem ainda não foi encerrado.")
    else:
        _check(kind, item_id)
        target = store.project_folder(item_id) if kind == "asset" else store.folder(kind, item_id)
    os.startfile(target)  # noqa: S606 - servidor local, pasta do próprio projeto
    return {"opened": True}


@app.post("/api/open-shortcuts")
def open_shortcuts() -> dict:
    """Abre no Explorer a pasta dos atalhos para os resultados (fica fora das pastas dos projetos)."""
    store.SHORTCUTS.mkdir(parents=True, exist_ok=True)
    os.startfile(store.SHORTCUTS)  # noqa: S606 - servidor local, pasta do próprio acervo
    return {"opened": True}


# --- Encerramento ---------------------------------------------------------------------------


def _free_project(asset_id: str) -> None:
    busy = pipeline.active_jobs(asset_id)
    if busy:
        raise HTTPException(409, f"Ainda há trabalho rodando neste projeto ({'; '.join(j['title'] for j in busy)}). Espere terminar.")


@app.post("/api/assets/{asset_id}/close")
def close_asset(asset_id: str) -> dict:
    """Encerra o personagem: monta o resultado (todas as animações num arquivo só) e cria o atalho dele."""
    asset = _ready_asset(asset_id)
    _free_project(asset_id)
    return submit("encerramento", f"Encerrar {asset['name']}", {"asset_id": asset_id}, lambda log: {"asset_id": asset_id, "final": pipeline.close_project(asset_id, log)["final"]["at"]})


@app.post("/api/assets/{asset_id}/reopen")
def reopen_asset(asset_id: str) -> dict:
    """Desfaz o encerramento: somem o resultado e o atalho; o projeto fica como está."""
    _check("asset", asset_id)
    _free_project(asset_id)
    pipeline.reopen_project(asset_id)
    return {"reopened": asset_id}


class UnrealBody(BaseModel):
    enabled: bool


@app.post("/api/assets/{asset_id}/unreal")
def set_unreal(asset_id: str, body: UnrealBody) -> dict:
    """Liga ou desliga o arquivo para a Unreal 5 no resultado. Vale no próximo encerramento."""
    _check("asset", asset_id)
    return pipeline.set_unreal(asset_id, body.enabled)


class AssetPatch(BaseModel):
    """O que dá para mudar num projeto: o nome, o jogo em que ele está, o que ele é lá e em que aba fica."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    game: str | None = None  # nulo, se vier dito, deixa o projeto sem jogo
    role: str | None = None  # "personagem" ou "modelo" (um asset do jogo)
    tab: str | None = Field(default=None, max_length=80)  # a aba do jogo; ela diz também o papel


@app.patch("/api/assets/{asset_id}")
def change_asset(asset_id: str, body: AssetPatch) -> dict:
    """Muda o nome do projeto, o jogo em que ele está, o papel dele (personagem ou modelo) ou a aba."""
    asset = _check("asset", asset_id)
    try:
        if body.name is not None:
            asset = pipeline.rename_asset(asset_id, body.name)
        if "game" in body.model_fields_set:
            asset = games.assign(asset_id, body.game, body.role)
        elif body.role is not None and body.tab is None:
            asset = games.set_role(asset_id, body.role)
        if body.tab is not None:
            asset = games.place(asset_id, body.tab)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return asset


@app.delete("/api/{kind}/{item_id}")
def delete(kind: str, item_id: str) -> dict:
    _check(kind, item_id)
    if kind == "asset":
        _free_project(item_id)  # com trabalho rodando no projeto, o job gravaria numa pasta que sumiu
        terminal.restart(item_id)  # o terminal aberto na pasta do projeto seguraria ela no disco
    pipeline.delete(kind, item_id)
    if kind == "asset":
        # O Windows demora um instante para soltar a pasta depois que o terminal dela fecha.
        folder = store.project_folder(item_id)
        for _ in range(10):
            if not folder.exists():
                break
            time.sleep(0.3)
            store.delete(kind, item_id)
    return {"deleted": item_id}


# --- Kimodo ---------------------------------------------------------------------------


@app.post("/api/kimodo/start")
def kimodo_start() -> dict:
    return submit("kimodo", "Ligar o Kimodo", {}, lambda log: kimodo.ensure_ready(log))


@app.post("/api/kimodo/stop")
def kimodo_stop() -> dict:
    try:
        kimodo.stop()
    except kimodo.KimodoError as exc:
        raise HTTPException(409, str(exc)) from exc
    global _kimodo_cache
    _kimodo_cache = (0.0, {})
    return {"stopped": True}


# --- ARDY -----------------------------------------------------------------------------


@app.post("/api/ardy/start")
def ardy_start() -> dict:
    """Sobe o codificador de texto do ARDY e o deixa no ar, para vários textos novos em seguida."""
    try:
        if not ardy.encoder_ready() and (trouble := ardy.encoder_blocker()):
            raise kimodo.KimodoError(trouble)
    except kimodo.KimodoError as exc:
        raise HTTPException(409, str(exc)) from exc
    return submit("kimodo", "Ligar o codificador de texto do ARDY", {}, lambda log: ardy.start_encoder(log))


@app.post("/api/ardy/stop")
def ardy_stop() -> dict:
    try:
        message = ardy.stop()
    except kimodo.KimodoError as exc:
        raise HTTPException(409, str(exc)) from exc
    global _ardy_cache
    _ardy_cache = (0.0, {})
    return {"stopped": True, "message": message}


@app.get("/api/ardy/sessions")
def ardy_sessions() -> dict:
    """As sessões exportadas pelo demo ao vivo do ARDY (aba IO, Export Session)."""
    try:
        return ardy.sessions()
    except kimodo.KimodoError as exc:
        raise HTTPException(409, str(exc)) from exc


class ArdySessionBody(BaseModel):
    asset_id: str
    session: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=60)
    # Recorte da sessão, em segundos.
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)


@app.post("/api/motions/import-ardy")
def import_ardy_session(body: ArdySessionBody) -> dict:
    """Traz uma sessão do demo ao vivo do ARDY para o projeto e a aplica no personagem."""
    asset = _ready_asset(body.asset_id)
    name = (body.label or Path(body.session).stem).strip()

    def work(log):
        preview = pipeline.import_ardy_session(body.asset_id, body.session, body.label, start=body.start, end=body.end, log=log)
        return {"result_ids": [preview["id"]], "motion_ids": [preview["motion_id"]]}

    return submit("retarget", f"Importar do ARDY: {name} → {asset['name']}", {"asset_id": body.asset_id}, work)


# --- Meshy ----------------------------------------------------------------------------


def _meshy_request(request_id: str) -> dict:
    try:
        return meshy.get(request_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, str(exc.args[0])) from exc


def _meshy_jobs(request_id: str | None = None) -> list[dict]:
    """Jobs do Meshy em andamento (os de um pedido, ou todos)."""
    return [j for j in jobs.list_jobs() if j["status"] in jobs.ACTIVE and j["kind"] == "meshy" and (request_id is None or (j.get("params") or {}).get("meshy_request") == request_id)]


class MeshyBody(BaseModel):
    """Pedido de personagem ao Meshy: o texto, em inglês, do que a imagem deve mostrar."""

    prompt: str = Field(min_length=3, max_length=800)
    name: str | None = Field(default=None, max_length=60)
    pose: str = "a-pose"
    ai_model: str = meshy.IMAGE_MODEL
    # Pedido reprovado que este refaz: sai da lista quando a imagem nova chega.
    replaces: str | None = None


@app.post("/api/meshy/requests")
def meshy_image(body: MeshyBody) -> dict:
    """Etapa 1: pede ao Meshy a imagem do personagem. Ela fica na tela de entrada, para aprovar."""
    if not meshy.api_key():
        raise HTTPException(409, "Falta a chave da API do Meshy. Guarde-a com `uv run ponte meshy key <chave>`.")
    name = (body.name or body.prompt[:40]).strip()
    return submit("meshy", f"Meshy: imagem de {name}", {}, lambda log: {"meshy_request": meshy.request_image(body.prompt, body.name, pose=body.pose, ai_model=body.ai_model, replaces=body.replaces, log=log)["id"]})


@app.post("/api/meshy/requests/{request_id}/approve")
def meshy_approve(request_id: str) -> dict:
    """Etapa 2: a imagem foi aprovada. Gera o modelo 3D e cria o projeto dele."""
    record = _meshy_request(request_id)
    try:
        if record["status"] == meshy.BUILDING:
            if _meshy_jobs(request_id):
                raise meshy.MeshyError("O modelo 3D deste pedido já está sendo gerado.")
        else:
            meshy.claim(request_id)  # já, no clique: um segundo clique é recusado
    except meshy.MeshyError as exc:
        raise HTTPException(409, str(exc)) from exc
    return submit("meshy", f"Meshy: modelo 3D de {record['name']}", {"meshy_request": request_id}, lambda log: {"asset_id": pipeline.approve_meshy(request_id, log=log)["id"]})


class MeshyReject(BaseModel):
    note: str = Field(default="", max_length=600)


@app.post("/api/meshy/requests/{request_id}/reject")
def meshy_reject(request_id: str, body: MeshyReject) -> dict:
    """A imagem não serve. A nota diz o que mudar: é o que quem faz o pedido lê em `ponte status`."""
    _meshy_request(request_id)
    try:
        return meshy.reject(request_id, body.note)
    except meshy.MeshyError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.delete("/api/meshy/requests/{request_id}")
def meshy_delete(request_id: str) -> dict:
    record = _meshy_request(request_id)
    if record["status"] in ("gerando_imagem", meshy.BUILDING) and _meshy_jobs():
        raise HTTPException(409, "Este pedido está sendo gerado. Espere terminar.")
    meshy.delete(request_id)
    return {"deleted": request_id}


# --- Terminal da tela -----------------------------------------------------------------------
# Um terminal por espaço, já na pasta dele e parado no prompt: a IA é chamada por quem está na
# tela (ponte/terminal.py). O nome na rota é o id do jogo, do projeto (personagem ou modelo 3D) ou
# da textura ou do som em que se está; o da tela de entrada usa as mesmas rotas, com
# `terminal.HOME`, e abre na pasta da ponte.
# A página fala com ele por WebSocket: {"type": "input", "data"} e {"type": "resize", "cols", "rows"}
# na ida; {"type": "output", "data"}, {"type": "exit"} e {"type": "error", "message"} na volta. A
# primeira mensagem é o que já estava escrito ("replay"), com "answered" dizendo se outra tela já o leu.


@app.get("/api/terminal")
def terminal_info() -> dict:
    """O que a página precisa para abrir o terminal. Só a própria página consegue ler o ``token``."""
    return {**terminal.status(), "token": terminal.TOKEN}


@app.post("/api/terminal/{asset_id}/restart")
def terminal_restart(asset_id: str) -> dict:
    if not terminal.known(asset_id):
        raise HTTPException(404, f"Não há terminal para {asset_id}.")
    terminal.restart(asset_id)
    return {"restarted": asset_id}


def _from_this_page(ws: WebSocket) -> bool:
    """A conexão vem da página da ponte, nesta máquina? Página de outro site não abre terminal aqui."""
    origin = urlsplit(ws.headers.get("origin") or "")
    return origin.hostname in ("127.0.0.1", "localhost") and origin.port == ws.url.port


@app.websocket("/api/terminal/{asset_id}")
async def terminal_socket(ws: WebSocket, asset_id: str, token: str = "") -> None:
    if not _from_this_page(ws) or not secrets.compare_digest(token, terminal.TOKEN):
        await ws.close(code=4403)
        return
    await ws.accept()
    trouble = terminal.problem()
    if not terminal.known(asset_id):
        trouble = "O que estava aberto aqui não existe mais."
    if trouble:
        await ws.send_text(json.dumps({"type": "error", "message": trouble}))
        await ws.close()
        return
    try:
        session = await asyncio.to_thread(terminal.get, asset_id)
    except Exception as exc:  # noqa: BLE001 - o terminal não abriu: a tela mostra por quê
        await ws.send_text(json.dumps({"type": "error", "message": f"O terminal não abriu: {exc}"}))
        await ws.close()
        return
    queue: asyncio.Queue = asyncio.Queue()
    backlog, answered = session.attach(asyncio.get_running_loop(), queue)
    # "answered": outra tela já respondeu às perguntas que estão nesse texto; esta não deve responder de novo.
    await ws.send_text(json.dumps({"type": "output", "data": backlog, "replay": True, "answered": answered}))

    async def forward() -> None:
        while True:
            data = await queue.get()
            if data is None:
                await ws.send_text(json.dumps({"type": "exit"}))
                return
            await ws.send_text(json.dumps({"type": "output", "data": data}))

    task = asyncio.create_task(forward())
    try:
        while True:
            message = json.loads(await ws.receive_text())
            if message.get("type") == "input":
                session.write(str(message.get("data", "")))
            elif message.get("type") == "resize":
                session.resize(int(message.get("cols", 100)), int(message.get("rows", 30)))
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        task.cancel()
        session.detach(queue)


# --- Arquivos estáticos (por último: "/" casa com tudo) -------------------------------------

class RevalidatedFiles(StaticFiles):
    """Arquivos que mudam no lugar (interface, GLB refeito): o navegador sempre confere se há versão nova."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/files", RevalidatedFiles(directory=DATA), name="files")
app.mount("/vendor/three", StaticFiles(directory=WEB / "node_modules" / "three", check_dir=False), name="three")
app.mount("/vendor/xterm", StaticFiles(directory=WEB / "node_modules" / "@xterm" / "xterm", check_dir=False), name="xterm")
app.mount("/vendor/xterm-fit", StaticFiles(directory=WEB / "node_modules" / "@xterm" / "addon-fit", check_dir=False), name="xterm-fit")
app.mount("/", RevalidatedFiles(directory=WEB, html=True), name="web")
