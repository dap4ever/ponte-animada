"""Armazenamento em arquivos, organizado por projeto.

Cada personagem enviado é um projeto, e tudo que nasce dele fica na pasta dele:

    data/projects/<projeto>/
        personagem/              asset.json, source/<arquivo>, rig/, props/, report.json, preview.glb
        animacoes/<id>/          motion.json, motion.bvh, motion.npz (do Mixamo: motion.fbx; de uma captura: mais captura.bvh, o arquivo como veio)
        previas/<id>/            result.json, result.glb, result.blend, sheet.png
        resultado/               só depois de encerrado: <nome>.glb, .fbx e .blend com todas as animações
    data/resultados/<Nome>.lnk   atalho para o resultado de cada personagem encerrado

O id do projeto é o id do personagem ("asset" no código). Uma prévia ("result" no código) é
uma animação aplicada no personagem, para validar. Animações e prévias guardam em
``asset_id`` de que projeto são. O resultado é um só por personagem e fica descrito no
registro dele, em ``final``.

O servidor e a CLI leem e escrevem aqui, então o que um faz o outro enxerga.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from .config import DATA

PROJECTS = DATA / "projects"
# Os atalhos para o resultado dos personagens encerrados ficam fora das pastas dos projetos.
SHORTCUTS = DATA / "resultados"
# Tipo de registro -> subpasta dentro do projeto.
KINDS = {"asset": "personagem", "motion": "animacoes", "result": "previas"}
# Subpasta do resultado do personagem, que só existe depois de encerrado.
FINAL = "resultado"
REVIEW_STATES = ("pendente", "aprovado", "reprovado")


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def slugify(text: str, max_len: int = 36) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:max_len].strip("-") or "item"


def new_id(label: str) -> str:
    return f"{slugify(label)}-{secrets.token_hex(2)}"


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    """Escrita atômica; no Windows o replace falha se alguém está lendo, então tenta de novo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(3)}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    tmp.unlink(missing_ok=True)
    raise PermissionError(f"Não foi possível gravar {path}")


def _check_id(item_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]*", item_id):
        raise ValueError(f"Identificador inválido: {item_id!r}")
    return item_id


def project_folder(asset_id: str) -> Path:
    return PROJECTS / _check_id(asset_id)


def final_folder(asset_id: str) -> Path:
    """Onde fica o resultado do personagem depois de encerrado."""
    return project_folder(asset_id) / FINAL


def folder(kind: str, item_id: str, project: str | None = None) -> Path:
    """Pasta de um registro.

    Para animação e resultado, ``project`` diz em que projeto ela fica; é obrigatório ao
    criar. Sem ele, a pasta é procurada entre os projetos (os ids não se repetem).
    """
    _check_id(item_id)
    if kind == "asset":
        return PROJECTS / item_id / KINDS["asset"]
    if project is not None:
        return project_folder(project) / KINDS[kind] / item_id
    found = next(PROJECTS.glob(f"*/{KINDS[kind]}/{item_id}"), None)
    if found is None:
        raise KeyError(f"{kind} não encontrado: {item_id}")
    return found


def record_path(kind: str, item_id: str, project: str | None = None) -> Path:
    return folder(kind, item_id, project) / f"{kind}.json"


def get(kind: str, item_id: str) -> dict:
    data = read_json(record_path(kind, item_id))
    if data is None:
        raise KeyError(f"{kind} não encontrado: {item_id}")
    return data


def save(kind: str, record: dict) -> dict:
    """Grava o registro. Animação e resultado vão para o projeto dito em ``asset_id``."""
    write_json(record_path(kind, record["id"], None if kind == "asset" else record["asset_id"]), record)
    return record


def list_all(kind: str, project: str | None = None) -> list[dict]:
    """Registros de um tipo, do mais novo para o mais antigo; de um projeto só, se pedido."""
    pattern = f"{_check_id(project) if project else '*'}/{KINDS[kind]}" + ("" if kind == "asset" else "/*") + f"/{kind}.json"
    records = [read_json(path) for path in PROJECTS.glob(pattern)]
    return sorted((r for r in records if r), key=lambda r: r.get("created_at", ""), reverse=True)


def update(kind: str, item_id: str, **fields) -> dict:
    record = get(kind, item_id)
    record.update(fields)
    return save(kind, record)


def set_review(kind: str, item_id: str, status: str, notes: str = "") -> dict:
    if status not in REVIEW_STATES:
        raise ValueError(f"Status de revisão inválido: {status!r} (use {', '.join(REVIEW_STATES)})")
    return update(kind, item_id, review={"status": status, "notes": notes.strip(), "at": now()})


def delete(kind: str, item_id: str) -> None:
    """Apaga o registro. Apagar o personagem apaga o projeto inteiro."""
    try:
        target = project_folder(item_id) if kind == "asset" else folder(kind, item_id)
    except KeyError:
        return
    shutil.rmtree(target, ignore_errors=True)


def blank_review() -> dict:
    return {"status": "pendente", "notes": "", "at": None}


def migrate_layout() -> list[str]:
    """Leva o acervo do formato antigo (assets/, motions/, results/ soltos) para o de projetos.

    Também dá às prévias o nome novo da pasta delas dentro do projeto. Pode rodar a cada
    partida: sem as pastas antigas não faz nada, e o que já está no lugar não é levado de
    novo. Devolve o que não soube encaixar em nenhum projeto.
    """
    old = {kind: DATA / name for kind, name in (("asset", "assets"), ("motion", "motions"), ("result", "results"))}
    # As prévias já se chamaram "resultados" dentro do projeto; resultado hoje é só o do personagem encerrado.
    old_previews = sorted(p for p in PROJECTS.glob("*/resultados/*") if p.is_dir())
    if not old_previews and not any(path.exists() for path in old.values()):
        return []
    leftovers: list[str] = []

    def children(kind: str) -> list[Path]:
        return sorted(p for p in old[kind].iterdir() if p.is_dir()) if old[kind].exists() else []

    def move(src: Path, dst: Path, record_name: str, record: dict | None) -> None:
        """Leva a pasta de um registro para ``dst``, onde o registro deve ficar como ``record``.

        O Windows não deixa renomear uma pasta enquanto outro programa tiver algo aberto
        dentro dela; aí a pasta é copiada, com o registro por último. Destino com registro
        está inteiro (e a pasta antiga pode ser apagada); sem registro é cópia interrompida,
        que é refeita.
        """
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not (dst / record_name).exists():
            write_json(src / record_name, record)
            try:
                src.rename(dst)
                return
            except OSError:
                pass
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=lambda folder, names: [record_name] if Path(folder) == src else [])
            write_json(dst / record_name, record)
        shutil.rmtree(src, ignore_errors=True)

    for src in children("asset"):
        target = folder("asset", src.name)
        record = read_json(src / "asset.json")
        # Sem registro, só interessa o resto de uma pasta já levada que não pôde ser apagada na hora.
        if record or (target / "asset.json").exists():
            move(src, target, "asset.json", record)

    # Um resultado diz de que personagem é; o id perde o prefixo do personagem, que agora é a pasta.
    owner_of_motion: dict[str, str] = {}
    for src in children("result"):
        record = read_json(src / "result.json")
        if not record or not record_path("asset", record["asset_id"]).exists():
            leftovers.append(f"resultado {src.name}")
            continue
        record["id"] = record["id"].removeprefix(record["asset_id"] + "--")
        move(src, folder("result", record["id"], record["asset_id"]), "result.json", record)
        owner_of_motion.setdefault(record["motion_id"], record["asset_id"])

    # Uma animação vai para o projeto do resultado que a usa; sem resultado, para o único projeto que houver.
    projects = [asset["id"] for asset in list_all("asset")]
    for src in children("motion"):
        record = read_json(src / "motion.json")
        if not record:  # pasta de trabalho de uma geração que não terminou
            shutil.rmtree(src, ignore_errors=True)
            continue
        owner = record.get("asset_id") or owner_of_motion.get(record["id"]) or (projects[0] if len(projects) == 1 else None)
        if owner is None:
            leftovers.append(f"animação {src.name}")
            continue
        record["asset_id"] = owner
        move(src, folder("motion", record["id"], owner), "motion.json", record)

    for src in old_previews:
        record = read_json(src / "result.json")
        if record:
            move(src, folder("result", src.name, src.parent.parent.name), "result.json", record)

    for path in [*old.values(), *{src.parent for src in old_previews}]:
        try:
            path.rmdir()  # só sai se já estiver vazia
        except OSError:
            pass
    return leftovers


def migrate_layout_safely() -> None:
    """Migra na partida sem nunca impedir o programa de subir."""
    try:
        leftovers = migrate_layout()
    except (OSError, KeyError, ValueError) as exc:
        print(f"AVISO: não consegui reorganizar o acervo em projetos ({exc}). Os itens do formato antigo continuam em data/.", file=sys.stderr)
        return
    if leftovers:
        print(f"AVISO: sem projeto para encaixar: {', '.join(leftovers)}. Continuam em data/.", file=sys.stderr)


def bvh_summary(path: Path) -> dict:
    """Lê o cabeçalho de um BVH: juntas, frames, fps e a assinatura do esqueleto."""
    text = path.read_text(encoding="utf-8", errors="replace")
    head, _, motion = text.partition("MOTION")
    names = re.findall(r"^\s*(?:ROOT|JOINT)\s+(\S+)", head, flags=re.M)
    frames = re.search(r"Frames:\s*(\d+)", motion)
    frame_time = re.search(r"Frame Time:\s*([0-9.eE+\-]+)", motion)
    if not names or not frames or not frame_time:
        raise ValueError(f"BVH inválido: {path.name}")
    # A assinatura cobre nomes, hierarquia e offsets: é o que define "o mesmo esqueleto".
    signature = hashlib.sha1(" ".join(head.split()).encode()).hexdigest()
    fps = 1.0 / float(frame_time.group(1))
    return {
        "joints": len([n for n in names if n != "Root"]),
        "frames": int(frames.group(1)),
        "fps": round(fps, 3),
        "duration_s": round(int(frames.group(1)) / fps, 3),
        "signature": signature,
    }
