"""API local + interface web do PonteAnimada."""

from __future__ import annotations

import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import blender, engines, jobs, kimodo, kimodo_cpp, pipeline, store
from .config import DATA, KIMODO_MAX_SAMPLES, WEB

DATA.mkdir(parents=True, exist_ok=True)
store.PROJECTS.mkdir(exist_ok=True)
store.migrate_layout_safely()  # acervo do formato antigo vai para a pasta do projeto dele
app = FastAPI(title="PonteAnimada", docs_url="/api/docs", openapi_url="/api/openapi.json")
POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="ponte-job")
_kimodo_cache: tuple[float, dict] = (0.0, {})


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


# --- Estado ---------------------------------------------------------------------------


def _with_files(kind: str, records: list[dict]) -> list[dict]:
    """Acrescenta a cada registro o endereço da pasta dele, dentro do projeto a que pertence."""
    for record in records:
        project = record["id"] if kind == "asset" else record["asset_id"]
        tail = "" if kind == "asset" else f"/{record['id']}"
        record["files_base"] = f"/files/projects/{project}/{store.KINDS[kind]}{tail}"
    return records


@app.get("/api/state")
def state() -> dict:
    """Tudo que a interface mostra.

    Cada personagem é um projeto; animações e prévias ("results") dizem em ``asset_id`` de
    qual. O personagem encerrado traz o resultado em ``final``.
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
        "assets": assets,
        "motions": _with_files("motion", store.list_all("motion")),
        "results": previews,
        "jobs": jobs.list_jobs(),
        "kimodo": _kimodo_status(),
        # Os dois geradores e qual está em uso: a interface pergunta ao abrir.
        "engines": engines.status(),
    }


class EngineBody(BaseModel):
    engine: str


@app.put("/api/engine")
def choose_engine(body: EngineBody) -> dict:
    """Troca o gerador em uso: o Kimodo original ou o kimodo.cpp."""
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


@app.post("/api/assets")
async def upload_asset(request: Request, filename: str, name: str | None = None, defer: bool = False) -> dict:
    """Recebe o modelo (ou um .zip com modelo e texturas).

    Com ``defer`` o laudo espera: o cliente ainda vai mandar as texturas.
    """
    if filename.lower().endswith(".zip"):
        tmp = DATA / "tmp" / f"{store.new_id(Path(filename).stem)}.zip"
        await _receive(request, tmp)
        try:
            asset = pipeline.add_zip(tmp, name or Path(filename).stem)
        except zipfile.BadZipFile as exc:
            raise HTTPException(400, "O arquivo .zip está corrompido ou não é um zip.") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            tmp.unlink(missing_ok=True)
        job = submit("inspecao", f"Inspecionar {asset['name']}", {"asset_id": asset["id"]}, lambda log: {"asset_id": pipeline.inspect_asset(asset["id"], log)["id"]})
        return {"asset": asset, "job": job}
    try:
        asset = pipeline.create_asset(filename, name)
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
    # O gerador: "kimodo" (o original) ou "cpp". Sem ele, o que está em uso.
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
    except (kimodo.KimodoError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    # Toda animação nasce dentro de um projeto (o do personagem que a recebe).
    if not body.asset_id:
        raise HTTPException(400, "Escolha o projeto: a animação é gerada para um personagem.")
    asset = _ready_asset(body.asset_id)
    if previous:
        if previous.get("asset_id") != body.asset_id:
            raise HTTPException(400, "A animação a continuar é de outro projeto.")
        if engine == "kimodo" and not (store.folder("motion", previous["id"]) / "motion.npz").exists():
            raise HTTPException(400, "Só dá para continuar animações geradas pelo Kimodo aqui.")
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


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@app.patch("/api/assets/{asset_id}")
def rename_asset(asset_id: str, body: RenameBody) -> dict:
    """Muda o nome do projeto."""
    _check("asset", asset_id)
    try:
        return pipeline.rename_asset(asset_id, body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/{kind}/{item_id}")
def delete(kind: str, item_id: str) -> dict:
    _check(kind, item_id)
    if kind == "asset":
        _free_project(item_id)  # com trabalho rodando no projeto, o job gravaria numa pasta que sumiu
    pipeline.delete(kind, item_id)
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


# --- Arquivos estáticos (por último: "/" casa com tudo) -------------------------------------

class RevalidatedFiles(StaticFiles):
    """Arquivos que mudam no lugar (interface, GLB refeito): o navegador sempre confere se há versão nova."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/files", RevalidatedFiles(directory=DATA), name="files")
app.mount("/vendor/three", StaticFiles(directory=WEB / "node_modules" / "three", check_dir=False), name="three")
app.mount("/", RevalidatedFiles(directory=WEB, html=True), name="web")
