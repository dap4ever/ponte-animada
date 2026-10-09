"""As operações do projeto: entrar com asset, gerar animação, fazer retarget, encerrar.

Cada função recebe um ``log`` (linha de progresso) e trabalha só sobre o store,
então serve igual para o servidor (em thread) e para a CLI (direto).
"""

from __future__ import annotations

import random
import re
import shutil
import zipfile
from pathlib import Path
from typing import Callable

from . import blender, engines, jobs, kimodo, shortcuts, store
from .config import DATA, KIMODO_MODEL, KIMODO_SKELETON, ROOT

Log = Callable[[str], None]
ASSET_EXTENSIONS = (".fbx", ".glb", ".gltf", ".blend", ".obj")
# Arquivos que acompanham o modelo: texturas, o .mtl de um OBJ, o .bin de um glTF.
SIDECAR_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp", ".exr", ".dds", ".mtl", ".bin")


def _quiet(_line: str) -> None:
    pass


# --- Assets ---------------------------------------------------------------------------


def create_asset(filename: str, name: str | None = None) -> dict:
    """Registra um asset novo e devolve o registro; o arquivo vai em ``source_path``."""
    ext = Path(filename).suffix.lower()
    if ext not in ASSET_EXTENSIONS:
        raise ValueError(f"Formato não suportado: {ext or '(sem extensão)'}. Aceitos: {', '.join(ASSET_EXTENSIONS)}")
    label = name or Path(filename).stem
    asset_id = store.new_id(label)
    safe_name = store.slugify(Path(filename).stem, 60) + ext
    (store.folder("asset", asset_id) / "source").mkdir(parents=True)
    return store.save(
        "asset",
        {
            "id": asset_id,
            "name": label,
            "filename": filename,
            "source": f"source/{safe_name}",
            "created_at": store.now(),
            "status": "novo",
            "verdict": None,
            "review": store.blank_review(),
        },
    )


def add_zip(zip_path: Path, name: str | None = None) -> dict:
    """Registra um asset a partir de um .zip com o modelo e as texturas, como o Mixamo aceita.

    O modelo é o maior arquivo 3D do pacote; as texturas ficam no mesmo lugar relativo a ele.
    """
    with zipfile.ZipFile(zip_path) as archive:
        members = [m for m in archive.infolist() if not m.is_dir() and "__MACOSX" not in m.filename]
        if sum(m.file_size for m in members) > 4 * 1024**3:
            raise ValueError("O .zip descompactado passa de 4 GB.")
        models = [m for m in members if Path(m.filename).suffix.lower() in ASSET_EXTENSIONS]
        if not models:
            raise ValueError(f"O .zip não tem nenhum modelo 3D ({', '.join(ASSET_EXTENSIONS)}).")
        model = max(models, key=lambda m: m.file_size)
        asset = create_asset(Path(model.filename).name, name)
        try:
            with archive.open(model) as src, source_path(asset).open("wb") as dst:
                shutil.copyfileobj(src, dst)
            base = model.filename.rsplit("/", 1)[0] + "/" if "/" in model.filename else ""
            for member in members:
                if member is model or Path(member.filename).suffix.lower() not in SIDECAR_EXTENSIONS:
                    continue
                relative = member.filename[len(base) :] if base and member.filename.startswith(base) else Path(member.filename).name
                with archive.open(member) as src, sidecar_path(asset["id"], relative).open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        except Exception:
            store.delete("asset", asset["id"])
            raise
    return asset


def source_path(asset: dict) -> Path:
    return store.folder("asset", asset["id"]) / asset["source"]


def sidecar_path(asset_id: str, relative: str) -> Path:
    """Onde gravar um arquivo que acompanha o modelo (textura etc.), dentro de ``source/``.

    Mantém o nome e as subpastas originais, porque é por eles que o modelo acha a textura.
    """
    asset = store.get("asset", asset_id)
    source_dir = (store.folder("asset", asset_id) / "source").resolve()
    parts = [p for p in relative.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or ".." in parts or ":" in relative:
        raise ValueError(f"Caminho de arquivo inválido: {relative!r}")
    if Path(parts[-1]).suffix.lower() not in SIDECAR_EXTENSIONS:
        raise ValueError(f"'{parts[-1]}' não é textura nem arquivo auxiliar. Aceitos: {', '.join(SIDECAR_EXTENSIONS)}")
    target = source_dir.joinpath(*parts).resolve()
    if source_dir not in target.parents or target == _unrigged_source(asset).resolve():
        raise ValueError(f"Caminho de arquivo inválido: {relative!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def list_sidecars(asset_id: str) -> list[str]:
    asset = store.get("asset", asset_id)
    source_dir = store.folder("asset", asset_id) / "source"
    model = _unrigged_source(asset)
    return sorted(p.relative_to(source_dir).as_posix() for p in source_dir.rglob("*") if p.is_file() and p != model)


def add_sidecars(asset_id: str, extra: list[Path]) -> list[str]:
    """Copia texturas para junto do modelo. Uma pasta entra inteira, com as subpastas."""
    added = []
    for item in extra:
        if item.is_dir():
            files = [(p, p.relative_to(item).as_posix()) for p in item.rglob("*") if p.is_file() and p.suffix.lower() in SIDECAR_EXTENSIONS]
        else:
            files = [(item, item.name)]
        for src, relative in files:
            shutil.copy2(src, sidecar_path(asset_id, relative))
            added.append(relative)
    return added


def inspect_asset(asset_id: str, log: Log = _quiet) -> dict:
    asset = store.get("asset", asset_id)
    folder = store.folder("asset", asset_id)
    log(f"inspecionando {asset['filename']} no Blender")
    store.update("asset", asset_id, status="inspecionando")
    try:
        report = blender.run_script(
            "inspect_asset.py",
            ["--input", source_path(asset), "--out-dir", folder, "--mapping", folder / "mapping.json"],
            folder / "report.json",
            folder / "inspect.log",
        )
    except Exception as exc:
        store.update("asset", asset_id, status="erro", verdict="erro", error=str(exc))
        raise
    rig = report.get("rig") or {}
    summary = {
        "rig": rig.get("label"),
        "rig_type": rig.get("type"),
        "bones": (report.get("armature") or {}).get("bones", 0),
        "triangles": report["mesh"]["triangles"],
        "height_m": (report.get("dimensions") or {}).get("height_m"),
        "rest_pose": (report.get("rest_pose") or {}).get("type"),
        "textures": report["mesh"]["images"] - len(report["mesh"]["missing_images"]),
        "motion_scale": rig.get("motion_scale"),
        "errors": sum(1 for i in report["issues"] if i["level"] == "erro"),
        "warnings": sum(1 for i in report["issues"] if i["level"] == "aviso"),
    }
    log(f"laudo: {report['verdict']} ({summary['rig']}, {summary['bones']} ossos, {summary['textures']} textura(s))")
    return store.update(
        "asset",
        asset_id,
        status="inspecionado",
        verdict=report["verdict"],
        summary=summary,
        preview=report.get("preview"),
        files=list_sidecars(asset_id),
        inspected_at=store.now(),
        error=None,
    )


def add_asset(path: Path, name: str | None = None, log: Log = _quiet, extra: list[Path] | None = None) -> dict:
    asset = create_asset(path.name, name)
    shutil.copy2(path, source_path(asset))
    if extra:
        log(f"{len(add_sidecars(asset['id'], extra))} arquivo(s) de textura copiado(s)")
    return inspect_asset(asset["id"], log)


# --- Rig automático (padrão Mixamo) -----------------------------------------------------------
# O personagem chega sem esqueleto; como no Mixamo, o humano confere 8 marcadores na vista
# de frente e o Blender monta o esqueleto (mesmos nomes e hierarquia) e calcula os pesos.
# O arquivo rigado passa a ser a fonte do asset; o original fica guardado.

RIG_MARKERS = ("chin", "groin", "l_wrist", "r_wrist", "l_elbow", "r_elbow", "l_knee", "r_knee")
TEST_WALK = ROOT / "tests" / "fixtures" / "kimodo_walk_forward.bvh"
TEST_WALK_ID = "caminhada-de-teste"


def _unrigged_source(asset: dict) -> Path:
    """O arquivo como foi enviado, mesmo que o asset já tenha sido rigado aqui."""
    return store.folder("asset", asset["id"]) / asset.get("source_original", asset["source"])


def estimate_rig_markers(asset_id: str, log: Log = _quiet) -> dict:
    """Chute inicial dos marcadores, para o humano conferir e ajustar na interface."""
    asset = store.get("asset", asset_id)
    folder = store.folder("asset", asset_id) / "rig"
    folder.mkdir(exist_ok=True)
    log(f"estimando os marcadores de {asset['name']} no Blender")
    out = blender.run_script("rig_asset.py", ["--input", _unrigged_source(asset), "--estimate", folder / "estimate.json"], folder / "estimate.json", folder / "estimate.log")
    rig = {**asset.get("rig", {}), "estimated": out["markers"], "body": out["body"]}
    store.update("asset", asset_id, rig=rig)
    return rig


def rig_asset(asset_id: str, markers: dict, *, fingers: bool = True, log: Log = _quiet) -> dict:
    """Riga o personagem com os marcadores conferidos e refaz o laudo."""
    missing = [m for m in RIG_MARKERS if m not in markers]
    if missing:
        raise ValueError(f"Faltam marcadores: {', '.join(missing)}.")
    asset = store.get("asset", asset_id)
    root = store.folder("asset", asset_id)
    folder = root / "rig"
    folder.mkdir(exist_ok=True)
    store.write_json(folder / "markers.json", {name: markers[name] for name in RIG_MARKERS})
    log(f"rigando {asset['name']} no padrão Mixamo ({'com' if fingers else 'sem'} dedos)")
    args = ["--input", _unrigged_source(asset), "--markers", folder / "markers.json", "--out", folder / "rigged.blend"]
    if not fingers:
        args.append("--no-fingers")
    out = blender.run_script("rig_asset.py", args, folder / "rigged.json", folder / "rigged.log")
    for note in out["skinning"]["notes"]:
        log(note)
    rig = {
        **asset.get("rig", {}),
        "markers": markers,
        "fingers": fingers,
        "at": store.now(),
        "bones": out["bones"],
        "skinning": out["skinning"],
    }
    store.update("asset", asset_id, rig=rig, source_original=asset.get("source_original", asset["source"]), source="rig/rigged.blend")
    log(f"esqueleto de {out['bones']} ossos, pesos por {out['skinning']['method']}")
    return inspect_asset(asset_id, log)


def test_walk(asset_id: str, log: Log = _quiet) -> dict:
    """Aplica a caminhada de exemplo, para ver como o rig deforma (como o Mixamo faz depois de rigar)."""
    _require_ready(asset_id)
    # Uma cópia por projeto: os ids não se repetem entre projetos.
    motion_id = f"{TEST_WALK_ID}-{asset_id.rsplit('-', 1)[-1]}"
    try:
        store.get("motion", motion_id)
    except KeyError:
        _register_motion(asset_id, motion_id, TEST_WALK, None, {"source": "importado", "prompt": "Caminhada de teste (exemplo, não gerada agora)", "filename": TEST_WALK.name})
    return retarget(asset_id, motion_id, log=log)


# --- Acessórios (arma na mão etc.) -----------------------------------------------------------
# Cada acessório é um arquivo 3D guardado no asset, o osso que o carrega e a matriz dele no
# espaço local desse osso. Fica no registro do asset: vale para todas as animações dele.


def create_prop(asset_id: str, filename: str) -> tuple[dict, Path]:
    """Registra um acessório novo. Devolve (registro, caminho onde gravar o arquivo)."""
    ext = Path(filename).suffix.lower()
    if ext not in ASSET_EXTENSIONS:
        raise ValueError(f"Formato não suportado: {ext or '(sem extensão)'}. Aceitos: {', '.join(ASSET_EXTENSIONS)}")
    asset = store.get("asset", asset_id)
    prop_id = store.slugify(Path(filename).stem, 20) + "-" + store.new_id("p")[-4:]
    relative = f"props/{prop_id}/{store.slugify(Path(filename).stem, 60)}{ext}"
    target = store.folder("asset", asset_id) / relative
    target.parent.mkdir(parents=True)
    prop = {"id": prop_id, "name": Path(filename).stem, "file": relative, "glb": None, "size_m": None, "bone": None, "matrix": None}
    store.update("asset", asset_id, props=[*asset.get("props", []), prop])
    return prop, target


def _update_prop(asset_id: str, prop_id: str, **fields) -> dict:
    asset = store.get("asset", asset_id)
    props = asset.get("props", [])
    prop = next((p for p in props if p["id"] == prop_id), None)
    if prop is None:
        raise KeyError(f"acessório não encontrado: {prop_id}")
    prop.update(fields)
    store.update("asset", asset_id, props=props)
    return prop


def convert_prop(asset_id: str, prop_id: str, log: Log = _quiet) -> dict:
    """Gera o GLB que o visualizador carrega e mede o acessório."""
    folder = store.folder("asset", asset_id)
    prop = _update_prop(asset_id, prop_id)
    log(f"convertendo o acessório {prop['name']} no Blender")
    out = folder / "props" / prop_id / "prop.glb"
    info = blender.run_script("convert_prop.py", ["--input", folder / prop["file"], "--out", out], out.with_suffix(".json"), out.with_suffix(".log"))
    return _update_prop(asset_id, prop_id, glb=f"props/{prop_id}/prop.glb", size_m=info["size_m"])


def place_prop(asset_id: str, prop_id: str, bone: str | None, matrix: list[float] | None) -> dict:
    """Guarda em que osso o acessório fica e a posição dele em relação a esse osso."""
    if matrix is not None and len(matrix) != 16:
        raise ValueError("A matriz do acessório precisa ter 16 números.")
    return _update_prop(asset_id, prop_id, bone=bone, matrix=matrix)


def delete_prop(asset_id: str, prop_id: str) -> None:
    asset = store.get("asset", asset_id)
    store.update("asset", asset_id, props=[p for p in asset.get("props", []) if p["id"] != prop_id])
    shutil.rmtree(store.folder("asset", asset_id) / "props" / prop_id, ignore_errors=True)


def placed_props(asset: dict) -> list[dict]:
    """Acessórios já presos a um osso, com o caminho completo do arquivo."""
    folder = store.folder("asset", asset["id"])
    return [
        {"id": p["id"], "name": p["name"], "file": str(folder / p["file"]), "bone": p["bone"], "matrix": p["matrix"]}
        for p in asset.get("props", [])
        if p.get("bone") and p.get("matrix")
    ]


def set_mapping(asset_id: str, override: dict, log: Log = _quiet) -> dict:
    """Grava o mapeamento manual de ossos e refaz o laudo."""
    store.write_json(store.folder("asset", asset_id) / "mapping.json", override)
    return inspect_asset(asset_id, log)


# --- Animações ------------------------------------------------------------------------


def _register_motion(asset_id: str, motion_id: str, bvh: Path, npz: Path | None, meta: dict) -> dict:
    """Guarda a animação dentro do projeto do personagem ``asset_id``."""
    folder = store.folder("motion", motion_id, asset_id)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bvh, folder / "motion.bvh")
    if npz:
        shutil.copy2(npz, folder / "motion.npz")
    info = kimodo.check_skeleton(folder / "motion.bvh")
    return store.save(
        "motion",
        {
            "id": motion_id,
            "asset_id": asset_id,
            "created_at": store.now(),
            "skeleton": KIMODO_SKELETON,
            "frames": info["frames"],
            "fps": info["fps"],
            "duration_s": info["duration_s"],
            **meta,
        },
    )


def _npz_to_continue(motion_id: str) -> tuple[dict, Path]:
    motion = store.get("motion", motion_id)
    npz = store.folder("motion", motion_id) / "motion.npz"
    if not npz.exists():
        raise ValueError("Só dá para continuar animações geradas pelo Kimodo aqui (as importadas de BVH não trazem os dados necessários).")
    return motion, npz


def resolve_engine(engine: str | None, continue_from: str | None) -> tuple[str, dict | None]:
    """O gerador de um pedido e, numa continuação, a animação de onde ele parte.

    Sem ``engine`` vale o que o usuário escolheu ao abrir a ponte. Um gerador não continua o
    clipe do outro: o original parte dos dados que ele mesmo gravou, e o kimodo.cpp refaz o
    roteiro inteiro com a mesma semente.
    """
    engine = engine or engines.current()
    if engine not in engines.ENGINES:
        raise ValueError(f"Gerador desconhecido: {engine}. Use um de: {', '.join(engines.ENGINES)}.")
    trouble = engines.problem(engine)
    if trouble:
        raise ValueError(f"{engines.ENGINES[engine]['name']}: {trouble}")
    if not continue_from:
        return engine, None
    previous = store.get("motion", continue_from)
    if previous.get("source") != "kimodo":
        raise ValueError("Só dá para continuar animações geradas aqui (as importadas não trazem os dados necessários).")
    made_in = engines.of(previous)
    if made_in != engine:
        raise ValueError(
            f"Esta animação foi gerada no {engines.ENGINES[made_in]['name']} e o gerador em uso é o {engines.ENGINES[engine]['name']}: "
            "um não continua o clipe do outro. Troque o gerador ou comece uma animação nova."
        )
    return engine, previous


def compose_step_text(premise: str, action: str) -> str:
    """Frase que o Kimodo recebe para um passo: a premissa do roteiro + a ação do passo.

    Repetir a premissa em todo passo é o que mantém o contexto (quem é, o que carrega,
    como segura) de um passo para o outro; o Kimodo não lembra do prompt anterior.
    """
    premise = premise.strip().rstrip(".")
    action = action.strip().rstrip(".")
    text = f"{premise} {action}" if premise and action else premise or action
    if not text:
        raise ValueError("Passo vazio: escreva a ação (ou a premissa).")
    return text + "."


def generate_motion(
    asset_id: str,
    steps: list[dict],
    *,
    premise: str = "",
    seed: int | None = None,
    samples: int = 1,
    denoise: int = 100,
    continue_from: str | None = None,
    name: str | None = None,
    engine: str | None = None,
    log: Log = _quiet,
) -> list[dict]:
    """Gera um roteiro no Kimodo (sempre SOMA 77) e registra uma animação por variação.

    ``engine`` é o gerador (``engines.ENGINES``): o Kimodo original ou o kimodo.cpp. Sem ele,
    vale o que o usuário escolheu ao abrir a ponte. Um não continua o clipe do outro.

    A animação nasce dentro do projeto do personagem ``asset_id``.
    ``steps``: [{text, seconds, travel?, loop?}], em ordem. Cada passo parte dos últimos
    quadros do anterior, então há transição entre eles e o resultado é um clipe contínuo.
    Um passo com ``loop`` termina na pose em que começou: é o trecho que o jogo toca em laço.
    ``continue_from`` é o id de uma animação do mesmo projeto: o roteiro parte do fim dela.
    ``name`` é o nome do roteiro e cada passo pode trazer um ``label``: é por eles que se acha
    cada trecho na interface. Numa continuação, o nome que o roteiro já tinha continua.
    """
    if not steps:
        raise ValueError("O roteiro precisa de pelo menos um passo.")
    store.get("asset", asset_id)
    seed = random.randrange(2**31) if seed is None else seed
    engine, previous = resolve_engine(engine, continue_from)
    previous_npz = _npz_to_continue(continue_from)[1] if previous and engine == "kimodo" else None
    if previous and previous.get("asset_id") != asset_id:
        raise ValueError("A animação a continuar é de outro projeto.")
    # text_weight: quanto o Kimodo obedece ao texto do passo (padrão dele 2; mais dá um gesto mais marcado).
    script = [
        {"text": compose_step_text(premise, s["text"]), "seconds": float(s["seconds"]), "travel": s.get("travel"), "loop": bool(s.get("loop")), "text_weight": s.get("text_weight"), "label": (s.get("label") or "").strip() or None}
        for s in steps
    ]
    if any(s["text_weight"] is not None and not 0.5 <= s["text_weight"] <= 8 for s in script):
        raise ValueError("O peso do texto vai de 0.5 a 8 (o padrão do Kimodo é 2).")
    if script[0]["loop"] and not previous:
        raise ValueError("Um passo em laço fecha na pose em que começa, então precisa de um passo antes dele: gere primeiro a entrada (o personagem já na postura) e ponha o laço no passo seguinte.")
    if any(s["loop"] and s["seconds"] < 2 for s in script):
        raise ValueError("Um passo em laço precisa de pelo menos 2 segundos: uma parte para o movimento e outra para voltar à pose inicial.")
    title = " → ".join(([previous["prompt"]] if previous else []) + [s["text"] for s in script])
    base_id = store.new_id(script[0]["text"])
    work = DATA / "tmp" / f"geracao-{base_id}"
    chain = script
    if engine == "cpp":
        # O kimodo.cpp não parte de uma animação gravada: o roteiro inteiro é gerado de novo, com
        # a mesma semente e os mesmos passos de difusão, e os passos de antes saem iguais.
        chain = [*((previous or {}).get("steps") or []), *script]
        if previous and samples > 1:
            raise ValueError("No kimodo.cpp as variações só valem no primeiro passo do roteiro: numa continuação a semente é a do clipe continuado.")
        if previous:
            seed, denoise = previous["seed"], previous.get("diffusion_steps", denoise)
    take = {"name": "motion", "steps": chain, "seed": seed, "samples": samples, "continue_from": previous_npz}
    try:
        outputs = engines.module(engine).generate(work, [take], steps=denoise, log=log)
        motions = []
        for out in outputs:
            motion_id = base_id if samples == 1 else f"{base_id}-s{out['sample']}"
            meta = {
                "source": "kimodo",
                "model": KIMODO_MODEL,
                "engine": engine,
                "prompt": title,
                "name": (name or "").strip() or (previous or {}).get("name", ""),
                "premise": premise.strip() or (previous or {}).get("premise", ""),
                # Onde cada passo começa no clipe, para a interface marcar e pular até lá.
                # Numa continuação os passos da animação anterior vêm junto: o clipe é um só.
                # No kimodo.cpp vêm os começos do roteiro inteiro: os deste pedido são os últimos.
                "steps": [*((previous or {}).get("steps") or []), *({**step, "start_frame": start} for step, start in zip(script, out["step_frames"][-len(script) :]))],
                "seed": seed + out["sample"] - 1,
                "sample": out["sample"],
                "samples": samples,
                "diffusion_steps": denoise,
                "continued_from": continue_from,
            }
            motions.append(_register_motion(asset_id, motion_id, out["bvh"], out["npz"], meta))
            log(f"animação registrada: {motion_id} ({out['frames']} frames)")
        return motions
    finally:
        kimodo.cleanup_work_dir(work)


def _same_step(step: dict) -> tuple:
    """O que identifica um passo entre os clipes de um projeto: o mesmo texto, no mesmo ponto."""
    return step.get("text"), step.get("start_frame"), step.get("seconds")


def label_motion(motion_id: str, name: str | None = None, labels: list[str | None] | None = None, stars: list[bool | None] | None = None) -> dict:
    """Dá nome ao roteiro e aos passos dele, e marca os passos que são as ações principais do personagem.

    ``labels`` e ``stars`` seguem a ordem dos passos; None deixa o passo como está. O mesmo
    passo aparece em todo clipe que continua dele: o nome e a marca valem para todas as cópias.
    """
    motion = store.get("motion", motion_id)
    steps = motion.get("steps") or []
    for values in (labels, stars):
        if values and len(values) > len(steps):
            raise ValueError(f"Esta animação tem {len(steps)} passo(s), mas vieram {len(values)} valores.")
    changes: dict[tuple, dict] = {}
    for i, step in enumerate(steps):
        change = {}
        if labels and i < len(labels) and (labels[i] or "").strip():
            change["label"] = labels[i].strip()
        if stars and i < len(stars) and stars[i] is not None:
            change["star"] = bool(stars[i])
        if change:
            changes[_same_step(step)] = change
    if name is not None:
        motion = store.update("motion", motion_id, name=name.strip())
    if changes:
        for other in store.list_all("motion", motion.get("asset_id")):
            before = other.get("steps") or []
            after = [{**step, **changes.get(_same_step(step), {})} for step in before]
            if after != before:
                store.update("motion", other["id"], steps=after)
    return store.get("motion", motion_id)


# Direções de deslocamento, relativas a para onde o personagem olha (0 = frente, 90 = direita dele).
DIRECTIONS = {
    "frente": 0,
    "frente-direita": 45,
    "direita": 90,
    "tras-direita": 135,
    "tras": 180,
    "tras-esquerda": 225,
    "esquerda": 270,
    "frente-esquerda": 315,
}


def import_motion(asset_id: str, bvh: Path, label: str | None = None, log: Log = _quiet) -> dict:
    """Registra no projeto um BVH já existente. Precisa estar no esqueleto padrão (SOMA 77)."""
    store.get("asset", asset_id)
    kimodo.check_skeleton(bvh)
    label = label or bvh.stem
    motion = _register_motion(asset_id, store.new_id(label), bvh, None, {"source": "importado", "prompt": label, "filename": bvh.name})
    log(f"animação importada: {motion['id']}")
    return motion


def import_mixamo(asset_id: str, fbx: Path, label: str | None = None, filename: str | None = None, log: Log = _quiet) -> dict:
    """Traz para o projeto uma animação pronta em FBX (as do Mixamo) e já a aplica no personagem.

    O arquivo fica guardado na pasta da animação e passa pelo mesmo retarget das do Kimodo,
    então serve em qualquer personagem, tenha ele ou não o esqueleto do arquivo. Devolve a prévia.
    """
    _require_ready(asset_id)
    filename = filename or fbx.name
    if Path(filename).suffix.lower() != ".fbx":
        raise ValueError("A animação do Mixamo precisa estar em FBX.")
    label = (label or Path(filename).stem).strip() or "Animação do Mixamo"
    motion_id = store.new_id(label)
    folder = store.folder("motion", motion_id, asset_id)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fbx, folder / "motion.fbx")
    store.save(
        "motion",
        {"id": motion_id, "asset_id": asset_id, "created_at": store.now(), "source": "mixamo", "filename": filename, "prompt": label, "name": label, "premise": "", "frames": 0, "fps": 30.0, "duration_s": 0.0, "steps": []},
    )
    log(f"animação do Mixamo recebida: {label}")
    try:
        return retarget(asset_id, motion_id, log=log)
    except Exception:
        store.delete("motion", motion_id)
        raise


def import_capture(
    asset_id: str,
    bvh: Path,
    label: str | None = None,
    filename: str | None = None,
    *,
    start: float | None = None,
    end: float | None = None,
    loop: bool | tuple[float, float] = False,
    direction: str | None = None,
    credit: str | None = None,
    log: Log = _quiet,
) -> dict:
    """Traz para o projeto uma captura de movimento em BVH, de esqueleto qualquer, e já a aplica no personagem.

    ``start`` e ``end`` recortam a tomada, em segundos do arquivo. ``loop`` fica só com o melhor
    laço do recorte, já fechado: ``True``, ou a duração mínima e a máxima em segundos.
    ``direction`` (uma de ``DIRECTIONS``) diz para onde anda um laço que se desloca; sem ela,
    vale a mais próxima entre frente, lados e trás. ``credit`` é o crédito que a licença do
    arquivo pede: fica no registro da animação.

    O arquivo como veio fica guardado (``captura.bvh``) ao lado do convertido (``motion.bvh``,
    no formato das animações do Kimodo, que o retarget e as medidas já leem). Devolve a prévia.
    """
    _require_ready(asset_id)
    filename = filename or bvh.name
    if Path(filename).suffix.lower() != ".bvh":
        raise ValueError("A captura precisa estar em BVH.")
    if direction is not None and direction not in DIRECTIONS:
        raise ValueError(f"Direção desconhecida: {direction}. Use uma de: {', '.join(DIRECTIONS)}.")
    label = (label or Path(filename).stem).strip() or "Captura"
    motion_id = store.new_id(label)
    folder = store.folder("motion", motion_id, asset_id)
    folder.mkdir(parents=True, exist_ok=True)
    args: list[str | Path] = ["--bvh", folder / "captura.bvh", "--out", folder / "motion.bvh"]
    if start is not None:
        args += ["--start", str(start)]
    if end is not None:
        args += ["--end", str(end)]
    if loop:
        args += ["--loop", *([] if loop is True else [str(seconds) for seconds in loop])]
    if direction is not None:
        args += ["--direction", str(DIRECTIONS[direction])]
    log(f"captura recebida: {label}")
    try:
        shutil.copy2(bvh, folder / "captura.bvh")
        info = blender.run_script("import_capture.py", args, folder / "captura.json", folder / "captura.log")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    found = info.get("loop")
    log(f"trecho de {info['source']['seconds'][0]:g} a {info['source']['seconds'][1]:g} s do arquivo" + (f", laço de {found['seconds']:g} s a {info['speed_m_s']:g} m/s" if found else ""))
    # Uma ação só, já com nome, que entra entre as principais do personagem (como as do Mixamo).
    step = {"text": label, "label": label, "start_frame": 0, "seconds": info["duration_s"], "travel": None, "loop": bool(found), "star": True}
    store.save(
        "motion",
        {
            "id": motion_id,
            "asset_id": asset_id,
            "created_at": store.now(),
            "source": "captura",
            "filename": filename,
            "prompt": label,
            "name": label,
            "premise": "",
            "frames": info["frames"],
            "fps": info["fps"],
            "duration_s": info["duration_s"],
            # O esqueleto é o do arquivo: o retarget precisa da altura do quadril dele em pé (cm).
            "stand_height": info["stand_height"],
            "capture": {k: info[k] for k in ("source", "loop", "speed_m_s", "travel_m", "floor_cm")},
            "credit": (credit or "").strip() or None,
            "steps": [step],
        },
    )
    try:
        return retarget(asset_id, motion_id, log=log)
    except Exception:
        store.delete("motion", motion_id)
        raise


# --- Retarget ---------------------------------------------------------------------------


def result_id_for(motion_id: str, in_place: bool) -> str:
    """Uma prévia por animação (e por versão parada), dentro do projeto dela."""
    return motion_id + ("--parado" if in_place else "")


def retarget(asset_id: str, motion_id: str, *, in_place: bool = False, adjust: dict | None = None, log: Log = _quiet) -> dict:
    """Aplica a animação no personagem do projeto dela: é a prévia que o humano valida.

    Refazer substitui a prévia e zera a revisão. Sai o GLB (para o visualizador) e o BLEND
    (para conferir no Blender e para o encerramento); os arquivos para a engine só saem
    quando o personagem é encerrado, com todas as animações juntas.
    """
    asset = store.get("asset", asset_id)
    motion = store.get("motion", motion_id)
    if motion.get("asset_id") != asset_id:
        raise ValueError("Esta animação é de outro projeto: cada projeto usa só as animações dele.")
    if asset.get("verdict") != "pronto":
        raise ValueError(f"O asset '{asset['name']}' não está pronto para animar (laudo: {asset.get('verdict')}).")

    result_id = result_id_for(motion_id, in_place)
    folder = store.folder("result", result_id, asset_id)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    log(f"retarget no Blender: {motion.get('prompt', motion_id)} → {asset['name']}")
    # A animação é um BVH (do Kimodo, no SOMA 77, ou uma captura convertida para os nomes dele)
    # ou veio pronta num FBX, como as do Mixamo.
    motion_folder = store.folder("motion", motion_id)
    source = ["--fbx", motion_folder / "motion.fbx"] if (motion_folder / "motion.fbx").exists() else ["--bvh", motion_folder / "motion.bvh"]
    args = [
        "--asset", source_path(asset),
        *source,
        "--out-dir", folder,
        "--name", store.slugify(motion.get("prompt", motion_id), 48),
        "--mapping", store.folder("asset", asset_id) / "mapping.json",
        "--no-fbx",
    ]  # fmt: skip
    if in_place:
        args.append("--in-place")
    if motion.get("stand_height"):
        # Captura: o BVH está no esqueleto do arquivo, e a altura do quadril em pé é a dele.
        args += ["--stand-height", str(motion["stand_height"])]
    if adjust:
        # Ajuste de pose feito na interface: {osso: [w, x, y, z]}, gravado junto da prévia.
        store.write_json(folder / "adjust.json", adjust)
        args += ["--adjust", folder / "adjust.json"]
    props = placed_props(asset)
    if props:
        store.write_json(folder / "props.json", props)
        args += ["--props", folder / "props.json"]
    try:
        out = blender.run_script("retarget_motion.py", args, folder / "retarget.json", folder / "retarget.log")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    sheet = None
    try:
        log("renderizando a tira de frames")
        blender.run_script(
            "render_sheet.py",
            ["--input", folder / out["files"]["blend"], "--out", folder / "sheet.png", "--frames", "6", "--size", "256"],
            folder / "sheet.json",
            folder / "sheet.log",
        )
        sheet = "sheet.png"
    except Exception as exc:  # noqa: BLE001 - a miniatura é opcional; a prévia vale sem ela
        log(f"tira de frames não gerada: {exc}")

    stats = out["stats"]
    if motion.get("source") == "mixamo" and not motion.get("steps"):
        # Só o Blender sabe quanto dura a animação do arquivo. Ela é uma ação só, já com nome,
        # e entra entre as principais do personagem.
        label = motion.get("name") or motion.get("prompt") or motion_id
        step = {"text": label, "label": label, "start_frame": 0, "seconds": stats["duration_s"], "travel": None, "loop": False, "star": True}
        store.update("motion", motion_id, frames=stats["frames"], fps=stats["fps"], duration_s=stats["duration_s"], steps=[step])
    log(f"prévia pronta: {stats['frames']} frames, {stats['bones_animated']} ossos animados")
    return store.save(
        "result",
        {
            "id": result_id,
            "created_at": store.now(),
            "asset_id": asset_id,
            "asset_name": asset["name"],
            "motion_id": motion_id,
            "prompt": motion.get("prompt", motion_id),
            "in_place": in_place,
            "adjust": adjust or None,
            # Com que posição cada acessório foi gravado: a interface compara com a atual
            # para avisar quando os arquivos estão desatualizados.
            "props": {p["id"]: {"bone": p["bone"], "matrix": p["matrix"]} for p in props},
            "files": out["files"],
            "sheet": sheet,
            "stats": stats,
            "review": store.blank_review(),
        },
    )


def _require_ready(asset_id: str) -> dict:
    asset = store.get("asset", asset_id)
    if asset.get("verdict") != "pronto":
        raise ValueError(f"O asset '{asset['name']}' não está pronto para animar (laudo: {asset.get('verdict')}).")
    return asset


def animate(
    asset_id: str,
    steps: list[dict],
    *,
    premise: str = "",
    seed: int | None = None,
    samples: int = 1,
    in_place: bool = False,
    continue_from: str | None = None,
    replaces: str | None = None,
    name: str | None = None,
    engine: str | None = None,
    log: Log = _quiet,
) -> list[dict]:
    """Gera o roteiro no Kimodo, dentro do projeto do personagem, e já aplica nele.

    ``engine`` escolhe o gerador (ver ``generate_motion``); sem ele, o que está em uso.

    O roteiro cresce um passo de cada vez, e cada corrente de passos é um clipe só. Por isso
    o clipe novo toma o lugar do que ele estende ou refaz, e só depois de pronto:

    - numa continuação, a prévia da animação continuada sai da lista (o clipe novo a contém).
      A animação fica guardada: é dela que se parte para refazer o passo;
    - ``replaces`` é o id de uma animação do projeto que este pedido refaz: ela é apagada,
      com as prévias dela.
    """
    _require_ready(asset_id)
    if replaces:
        if replaces == continue_from:
            raise ValueError("A animação a refazer não pode ser a mesma de onde o passo parte.")
        if store.get("motion", replaces).get("asset_id") != asset_id:
            raise ValueError("A animação a refazer é de outro projeto.")
    motions = generate_motion(asset_id, steps, premise=premise, seed=seed, samples=samples, continue_from=continue_from, name=name, engine=engine, log=log)
    previews = [retarget(asset_id, m["id"], in_place=in_place, log=log) for m in motions]
    if replaces:
        delete("motion", replaces)
    if continue_from:
        for preview in store.list_all("result", asset_id):
            if preview.get("motion_id") == continue_from:
                store.delete("result", preview["id"])
    return previews


def rename_asset(asset_id: str, name: str) -> dict:
    """Muda o nome do projeto (o do personagem). As prévias guardam o nome para exibir."""
    name = name.strip()
    if not name:
        raise ValueError("O nome do projeto não pode ficar vazio.")
    asset = store.update("asset", asset_id, name=name)
    for result in store.list_all("result", asset_id):
        store.update("result", result["id"], asset_name=name)
    if asset.get("final"):  # o atalho do resultado leva o nome do personagem
        asset = store.update("asset", asset_id, final={**asset["final"], "shortcut": _write_shortcut(asset)})
    return asset


def delete(kind: str, item_id: str) -> None:
    """Apaga o item. O personagem leva o projeto inteiro e o atalho do resultado; a animação leva as prévias dela."""
    if kind == "motion":
        motion = store.get("motion", item_id)
        for result in store.list_all("result", motion.get("asset_id")):
            if result.get("motion_id") == item_id:
                store.delete("result", result["id"])
    if kind == "asset":
        _remove_shortcut(store.get("asset", item_id))
    store.delete(kind, item_id)


# --- Encerramento -----------------------------------------------------------------------
# O resultado de um personagem só existe depois que ele é encerrado. Aí as prévias que não
# foram reprovadas viram os clipes de um arquivo só (GLB, FBX e BLEND) em resultado/, dentro
# do projeto, e um atalho para essa pasta aparece em data/resultados/, fora dos projetos.
# O projeto não fica travado: dá para continuar mexendo, e encerrar de novo refaz o resultado.


def _enters(preview: dict) -> bool:
    """Entra no resultado tudo que o humano não reprovou."""
    return (preview.get("review") or {}).get("status") != "reprovado"


def final_signature(asset: dict, previews: list[dict]) -> dict:
    """O que define o conteúdo do resultado; se mudar depois de encerrado, ele ficou para trás."""
    signature = {
        "previews": sorted([p["id"], p["created_at"]] for p in previews if _enters(p)),
        "props": {p["id"]: {"bone": p["bone"], "matrix": p["matrix"]} for p in placed_props(asset)},
    }
    if asset.get("unreal"):  # só quando ligado: o resultado de quem nunca ligou continua em dia
        signature["unreal"] = True
    return signature


# Dentro da pasta do resultado: o arquivo para a Unreal 5, com o personagem no esqueleto do Mannequin.
UNREAL_FOLDER = "unreal5"


def set_unreal(asset_id: str, enabled: bool) -> dict:
    """Liga ou desliga o arquivo para a Unreal 5 no resultado deste personagem. Vale no próximo encerramento."""
    return store.update("asset", asset_id, unreal=bool(enabled))


def active_jobs(asset_id: str) -> list[dict]:
    """Jobs em andamento que mexem neste projeto."""
    return [j for j in jobs.list_jobs() if j["status"] in jobs.ACTIVE and (j.get("params") or {}).get("asset_id") == asset_id]


def _clip_names(previews: list[dict]) -> list[str]:
    """Nome de cada clipe no resultado: o pedido, sem a premissa que se repete em todos."""
    names: list[str] = []
    for preview in previews:
        label = preview.get("prompt") or preview["id"]
        try:
            premise = (store.get("motion", preview["motion_id"]).get("premise") or "").strip().rstrip(".")
        except KeyError:
            premise = ""
        short = re.sub(re.escape(premise), " ", label, flags=re.IGNORECASE) if premise else label
        base = store.slugify(short if re.search(r"\w", short) else label, 40).replace("-", "_") + ("_parado" if preview.get("in_place") else "")
        name, n = base, 2
        while name in names:
            name, n = f"{base}_{n}", n + 1
        names.append(name)
    return names


def _remove_shortcut(asset: dict) -> None:
    name = (asset.get("final") or {}).get("shortcut")
    if name:
        (store.SHORTCUTS / Path(name).name).unlink(missing_ok=True)


def _write_shortcut(asset: dict) -> str:
    """Cria em data/resultados/ o atalho para o resultado do personagem. Devolve o nome do arquivo."""
    _remove_shortcut(asset)
    label = shortcuts.file_name(asset["name"])
    taken = {((a.get("final") or {}).get("shortcut") or "").lower() for a in store.list_all("asset") if a["id"] != asset["id"]}
    # Dois personagens com o mesmo nome: o segundo atalho leva o fim do id, para não tomar o lugar do primeiro.
    name = f"{label}.lnk" if f"{label}.lnk".lower() not in taken else f"{label} ({asset['id'].rsplit('-', 1)[-1]}).lnk"
    shortcuts.create(store.SHORTCUTS / name, store.final_folder(asset["id"]), f"Resultado de {asset['name']} (PonteAnimada)")
    return name


def close_project(asset_id: str, log: Log = _quiet) -> dict:
    """Encerra o personagem: monta o resultado com as prévias não reprovadas e cria o atalho dele."""
    asset = _require_ready(asset_id)
    previews = sorted(store.list_all("result", asset_id), key=lambda p: p["created_at"])
    entering = [p for p in previews if _enters(p)]
    if not entering:
        raise ValueError("Não há o que encerrar: " + ("todas as prévias deste projeto foram reprovadas." if previews else "este projeto ainda não tem animação aplicada no personagem."))
    blends = [store.folder("result", p["id"]) / p["files"].get("blend", "sem-blend") for p in entering]
    missing = [p["prompt"] for p, blend in zip(entering, blends) if not blend.is_file()]
    if missing:
        raise ValueError(f"Prévia sem o arquivo de trabalho (.blend): {'; '.join(missing)}. Use Refazer retarget nela e encerre de novo.")
    rates = {round(p["stats"]["fps"]) for p in entering}
    if len(rates) > 1:
        raise ValueError(f"As prévias têm taxas de quadros diferentes ({', '.join(map(str, sorted(rates)))} fps): não cabem no mesmo arquivo.")
    fps = rates.pop()

    work = DATA / "tmp" / f"encerrar-{asset_id}"
    shutil.rmtree(work, ignore_errors=True)
    out_dir = work / "saida"
    out_dir.mkdir(parents=True, exist_ok=True)
    store.write_json(work / "clips.json", [{"name": name, "blend": str(blend)} for name, blend in zip(_clip_names(entering), blends)])
    args = ["--asset", source_path(asset), "--clips", work / "clips.json", "--out-dir", out_dir, "--name", store.slugify(asset["name"], 40), "--fps", fps]
    props = placed_props(asset)
    if props:
        store.write_json(work / "props.json", props)
        args += ["--props", work / "props.json"]
    if asset.get("unreal"):
        # SK_ é como a Unreal chama uma malha com esqueleto; os clipes entram lá como SK_<nome>_<clipe>.
        unreal_file = out_dir / UNREAL_FOLDER / f"SK_{store.slugify(asset['name'], 40).replace('-', '_')}.fbx"
        args += ["--unreal", unreal_file, "--mapping", store.folder("asset", asset_id) / "mapping.json"]
    log(f"montando o resultado de {asset['name']} no Blender: {len(entering)} animação(ões) num arquivo só" + (", e o arquivo para a Unreal 5" if asset.get("unreal") else ""))
    out = blender.run_script("build_result.py", args, out_dir / "build.json", work / "build.log")
    for note in out["warnings"]:
        log(note)
    unreal = out.get("unreal")
    if unreal:
        check = unreal["check"]
        log(f"Unreal 5: {unreal['bones']} ossos no esqueleto do Mannequin; a malha mudou {check['vertex_error_cm']} cm e as juntas {check['joint_error_cm']} cm em relação ao resultado")

    # Os arquivos entram um a um na pasta do resultado: trocar a pasta inteira o Windows nega
    # quando outro programa tem algo aberto nela.
    final_dir = store.final_folder(asset_id)
    try:
        final_dir.mkdir(parents=True, exist_ok=True)
        for old in [*final_dir.iterdir(), *(final_dir / UNREAL_FOLDER).glob("*")]:
            if old.is_file():
                old.unlink()
        for name in out["files"].values():
            shutil.copy2(out_dir / name, final_dir / name)
        if unreal:
            (final_dir / UNREAL_FOLDER).mkdir(exist_ok=True)
            shutil.copy2(out_dir / UNREAL_FOLDER / unreal["file"], final_dir / UNREAL_FOLDER / unreal["file"])
        elif (final_dir / UNREAL_FOLDER).is_dir():
            try:
                (final_dir / UNREAL_FOLDER).rmdir()
            except OSError:
                pass  # pasta vazia aberta em outro programa: fica, sem atrapalhar
    except PermissionError as exc:
        raise ValueError("Não consegui trocar os arquivos do resultado: feche o programa que está com eles abertos (o Blender, a engine) e encerre de novo.") from exc
    final = {
        "at": store.now(),
        "files": out["files"],
        "fps": fps,
        "clips": [
            {"name": clip["name"], "preview": p["id"], "prompt": p["prompt"], "in_place": p["in_place"], "frames": clip["frames"], "duration_s": clip["duration_s"], "review": p["review"]["status"]}
            for p, clip in zip(entering, out["clips"])
        ],
        "rejected": [p["id"] for p in previews if not _enters(p)],
        "warnings": out["warnings"],
        "signature": final_signature(asset, previews),
        "shortcut": _write_shortcut(asset),
    }
    if unreal:
        final["unreal"] = {"file": f"{UNREAL_FOLDER}/{unreal['file']}", "bones": unreal["bones"], "extra_bones": unreal["extra"], "check": unreal["check"]}
    asset = store.update("asset", asset_id, final=final)
    shutil.rmtree(work, ignore_errors=True)
    log(f"resultado pronto, com atalho em {store.SHORTCUTS / final['shortcut']}")
    return asset


def reopen_project(asset_id: str) -> dict:
    """Desfaz o encerramento: somem o resultado e o atalho. O projeto e as prévias ficam como estão."""
    asset = store.get("asset", asset_id)
    _remove_shortcut(asset)
    shutil.rmtree(store.final_folder(asset_id), ignore_errors=True)
    return store.update("asset", asset_id, final=None)
