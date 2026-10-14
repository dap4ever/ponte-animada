"""Os jogos: cada um junta os personagens e os assets dele, e tem a pasta onde o terminal da tela abre.

    data/games/<jogo>/
        game.json              o nome, as abas da tela e, se o dono disser, a pasta onde está o código do jogo
        assets/<id>/           item.json e o arquivo: uma textura, um som ou um documento (e o guia do terminal dele)
        tarefas.json           as tarefas das abas de gestão
        CLAUDE.md, AGENTS.md   o guia para a IA chamada no terminal do jogo (ponte/terminal.py)

Os personagens continuam onde sempre estiveram, em ``data/projects/<id>/`` (ver ``ponte/store.py``),
e dizem em ``game`` de que jogo são. Um modelo 3D que não é personagem (arma, objeto, cenário) é um
projeto igual, com ``role`` "modelo": passa pelo mesmo laudo e abre no mesmo visor. Texturas e sons
são arquivos soltos, guardados aqui ("item" no código; na tela, tudo isso junto são os Assets).

A tela do jogo é dividida em abas (``tabs`` em ``game.json``). Duas vêm com o jogo, Characters e
Assets; as outras o dono cria, de um de três tipos (pedido dele em 13/10/2026: "adicione uma opção
onde eu possa criar minhas abas seja ela de personagens, assets e gestão"). Cada projeto, textura
ou som diz em ``tab`` em que aba está; sem dizer, fica na que vem com o jogo. Numa aba de gestão
ficam as tarefas (um quadro: a fazer, fazendo, feito) e os documentos do jogo, que são arquivos de
texto guardados como as texturas e os sons, com ``kind`` "documento".

Projeto sem ``game`` (o que veio de antes dos jogos, ou do Meshy) aparece na tela de entrada como
"sem jogo", até o dono dizer de qual é.
"""

from __future__ import annotations

import re
import shutil
import threading
from pathlib import Path

from . import store
from .config import DATA

GAMES = DATA / "games"
ITEMS = "assets"  # dentro da pasta do jogo: as texturas, os sons e os documentos
# O papel de um projeto dentro do jogo. O personagem recebe animação; o modelo é um asset. Sem papel dito, é personagem.
ROLES = ("personagem", "modelo")
DOCUMENT = "documento"
ITEM_KINDS = {
    "textura": (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tga", ".tif", ".tiff", ".exr", ".hdr", ".dds", ".psd"),
    "som": (".wav", ".ogg", ".mp3", ".flac"),
    DOCUMENT: (".md", ".txt"),
}
# Os tipos de aba da tela do jogo: de personagens, de assets (modelos 3D, texturas e sons) e de gestão (tarefas e documentos).
TAB_KINDS = ("personagens", "assets", "gestao")
# As duas abas que vêm com o jogo. Não são apagadas: é nelas que fica o que não foi posto em outra.
BUILTIN_TABS = (
    {"id": "characters", "name": "Characters", "kind": "personagens"},
    {"id": "assets", "name": "Assets", "kind": "assets"},
)
TASKS = "tarefas.json"
# As colunas do quadro de tarefas, na ordem da tela.
TASK_STATES = ("a_fazer", "fazendo", "feito")

_tasks_lock = threading.Lock()  # o servidor atende vários pedidos ao mesmo tempo, e o quadro é um arquivo só


def folder(game_id: str) -> Path:
    return GAMES / store._check_id(game_id)


def exists(game_id: str) -> bool:
    try:
        return (folder(game_id) / "game.json").is_file()
    except ValueError:
        return False


def get(game_id: str) -> dict:
    record = store.read_json(folder(game_id) / "game.json")
    if record is None:
        raise KeyError(f"jogo não encontrado: {game_id}")
    return record


def list_games() -> list[dict]:
    """Os jogos, do mais antigo para o mais novo: a ordem em que aparecem na tela de entrada."""
    records = [store.read_json(path) for path in GAMES.glob("*/game.json")]
    return sorted((r for r in records if r), key=lambda r: r.get("created_at", ""))


def _save(record: dict) -> dict:
    store.write_json(folder(record["id"]) / "game.json", record)
    return record


def _code_path(path: str | None) -> str | None:
    """A pasta do código do jogo, conferida. Vazio tira a que estava."""
    if not path or not path.strip():
        return None
    target = Path(path.strip().strip('"')).expanduser()
    if not target.is_dir():
        raise ValueError(f"Pasta não encontrada: {target}")
    return str(target.resolve())


def create(name: str, code_path: str | None = None) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("O jogo precisa de um nome.")
    game_id = store.new_id(name)
    # O terminal distingue jogo de personagem pelo id: os dois não podem coincidir.
    while exists(game_id) or store.project_folder(game_id).exists():
        game_id = store.new_id(name)
    return _save({"id": game_id, "name": name, "created_at": store.now(), "code_path": _code_path(code_path)})


def rename(game_id: str, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("O nome do jogo não pode ficar vazio.")
    return _save({**get(game_id), "name": name})


def set_code_path(game_id: str, path: str | None) -> dict:
    """Diz onde está o código do jogo (a pasta dele na Godot, por exemplo): é lá que a IA do terminal faz a jogabilidade."""
    return _save({**get(game_id), "code_path": _code_path(path)})


def delete(game_id: str) -> None:
    """Apaga o jogo: a pasta dele sai do disco, com as texturas, os sons, os documentos e as tarefas.

    Os personagens e os modelos 3D não são apagados: ficam sem jogo.
    """
    for asset in members(game_id):
        store.update("asset", asset["id"], game=None, **({"tab": None} if asset.get("tab") else {}))
    shutil.rmtree(folder(game_id), ignore_errors=True)


# --- As abas da tela do jogo ------------------------------------------------------------------


def tabs(game: dict | str) -> list[dict]:
    """As abas do jogo, na ordem da tela. As duas que vêm com o jogo estão sempre lá, mesmo num jogo de antes das abas."""
    record = get(game) if isinstance(game, str) else game
    builtin = {tab["id"]: tab for tab in BUILTIN_TABS}
    saved = [
        {"id": tab["id"], "name": str(tab.get("name") or tab["id"]), "kind": builtin[tab["id"]]["kind"] if tab["id"] in builtin else tab["kind"]}
        for tab in record.get("tabs") or []
        if isinstance(tab, dict) and isinstance(tab.get("id"), str) and (tab["id"] in builtin or tab.get("kind") in TAB_KINDS)
    ]
    return [dict(tab) for tab in BUILTIN_TABS if not any(s["id"] == tab["id"] for s in saved)] + saved


def get_tab(game_id: str, tab: str) -> dict:
    """Uma aba do jogo, pelo id ou pelo nome (quem pede pela linha de comando costuma dizer o nome)."""
    current = tabs(game_id)
    found = next((t for t in current if t["id"] == tab), None) or next((t for t in current if t["name"].casefold() == tab.strip().casefold()), None)
    if found is None:
        raise KeyError(f"aba não encontrada: {tab} (as do jogo: {', '.join(t['name'] for t in current)})")
    return found


def _tab_name(game: dict, name: str, but: str | None = None) -> str:
    name = name.strip()
    if not name:
        raise ValueError("A aba precisa de um nome.")
    if any(t["name"].casefold() == name.casefold() and t["id"] != but for t in tabs(game)):
        raise ValueError(f"Já existe uma aba chamada {name}.")
    return name


def add_tab(game_id: str, name: str, kind: str) -> dict:
    """Cria uma aba na tela do jogo: de personagens, de assets ou de gestão."""
    if kind not in TAB_KINDS:
        raise ValueError(f"Tipo de aba desconhecido: {kind!r} (use {', '.join(TAB_KINDS)})")
    record = get(game_id)
    name = _tab_name(record, name)
    current = tabs(record)
    tab_id = store.new_id(name)
    while any(t["id"] == tab_id for t in current):
        tab_id = store.new_id(name)
    tab = {"id": tab_id, "name": name, "kind": kind}
    _save({**record, "tabs": current + [tab]})
    return tab


def rename_tab(game_id: str, tab: str, name: str) -> dict:
    record = get(game_id)
    target = get_tab(game_id, tab)
    renamed = {**target, "name": _tab_name(record, name, but=target["id"])}
    _save({**record, "tabs": [renamed if t["id"] == target["id"] else t for t in tabs(record)]})
    return renamed


def delete_tab(game_id: str, tab: str) -> dict:
    """Apaga uma aba criada pelo dono.

    Os personagens e os assets que estavam nela não são apagados: voltam para a aba que vem com o
    jogo. De uma aba de gestão, as tarefas e os documentos saem do disco.
    """
    target = get_tab(game_id, tab)
    if any(target["id"] == builtin["id"] for builtin in BUILTIN_TABS):
        raise ValueError(f"A aba {target['name']} vem com o jogo: dá para mudar o nome dela, mas não apagar.")
    record = get(game_id)
    if target["kind"] == "gestao":
        for document in documents(game_id, target["id"]):
            delete_item(document["id"])
        with _tasks_lock:
            store.write_json(folder(game_id) / TASKS, [t for t in _read_tasks(game_id) if tab_of(record, t, "gestao") != target["id"]])
    else:
        for asset in members(game_id):
            if asset.get("tab") == target["id"]:
                store.update("asset", asset["id"], tab=None)
        for item in list_items(game_id):
            if item.get("tab") == target["id"]:
                store.write_json(_item_record(item["id"]), {**item, "tab": None})
    _save({**record, "tabs": [t for t in tabs(record) if t["id"] != target["id"]]})
    return target


def tab_of(game: dict | str, thing: dict, kind: str) -> str | None:
    """Em que aba uma coisa aparece: a que ela diz em ``tab``, se existe e é do tipo dela; senão, a primeira desse tipo.

    ``kind`` é o tipo de aba em que a coisa cabe (``asset_tab_kind``, ``item_tab_kind``; tarefa, "gestao").
    Só não há aba para tarefa e documento num jogo sem nenhuma de gestão.
    """
    same = [tab["id"] for tab in tabs(game) if tab["kind"] == kind]
    return thing["tab"] if thing.get("tab") in same else (same[0] if same else None)


# --- Os projetos do jogo: personagens e modelos 3D ------------------------------------------


def role_of(asset: dict) -> str:
    return asset.get("role") or ROLES[0]


def asset_tab_kind(asset: dict) -> str:
    """O tipo de aba em que um projeto cabe: o personagem, numa de personagens; o modelo 3D, numa de assets."""
    return "personagens" if role_of(asset) == ROLES[0] else "assets"


def members(game_id: str, role: str | None = None) -> list[dict]:
    """Os projetos do jogo, do mais antigo para o mais novo; só os de um papel, se pedido."""
    mine = [a for a in store.list_all("asset") if a.get("game") == game_id and (role is None or role_of(a) == role)]
    return sorted(mine, key=lambda a: a.get("created_at", ""))


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"Papel desconhecido: {role!r} (use {' ou '.join(ROLES)})")
    return role


def assign(asset_id: str, game_id: str | None, role: str | None = None) -> dict:
    """Põe um projeto num jogo (``None`` o deixa sem jogo) e, se dito, muda o papel dele."""
    asset = store.get("asset", asset_id)
    if game_id is not None:
        get(game_id)
    fields = {"game": game_id}
    if role is not None:
        fields["role"] = _check_role(role)
    # A aba é de um jogo e de um tipo: mudou um dos dois, o projeto volta para a aba que vem com o jogo.
    if asset.get("tab") and (asset.get("game") != game_id or (role is not None and role != role_of(asset))):
        fields["tab"] = None
    return store.update("asset", asset_id, **fields)


def set_role(asset_id: str, role: str) -> dict:
    """Passa um projeto de personagem para asset (modelo), ou de volta."""
    asset = store.get("asset", asset_id)
    fields = {"role": _check_role(role)}
    if asset.get("tab") and role != role_of(asset):
        fields["tab"] = None
    return store.update("asset", asset_id, **fields)


def place(asset_id: str, tab: str) -> dict:
    """Põe um personagem ou um modelo 3D numa aba do jogo dele.

    A aba diz o que ele é: numa de personagens, personagem; numa de assets, modelo.
    """
    asset = store.get("asset", asset_id)
    if not asset.get("game") or not exists(asset["game"]):
        raise ValueError(f"{asset['name']} ainda não está em nenhum jogo.")
    target = get_tab(asset["game"], tab)
    if target["kind"] == "gestao":
        raise ValueError(f"A aba {target['name']} é de gestão: nela ficam tarefas e documentos, não personagens nem modelos.")
    return store.update("asset", asset_id, role=ROLES[0] if target["kind"] == "personagens" else ROLES[1], tab=target["id"])


# --- Texturas, sons e documentos -----------------------------------------------------------


def kind_of(filename: str) -> str | None:
    """Textura, som, documento ou nenhum dos três, pela extensão."""
    ext = Path(filename).suffix.lower()
    return next((kind for kind, extensions in ITEM_KINDS.items() if ext in extensions), None)


def item_tab_kind(item: dict) -> str:
    """O tipo de aba em que um arquivo cabe: o documento, numa de gestão; a textura e o som, numa de assets."""
    return "gestao" if item.get("kind") == DOCUMENT else "assets"


def _safe_filename(filename: str) -> str:
    """O nome do arquivo como veio (é o nome que o jogo usa), sem o que o Windows não aceita."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(filename.replace("\\", "/")).name).strip(" .")
    stem, ext = Path(name).stem[:80], Path(name).suffix.lower()
    if not stem or re.fullmatch(r"(?i)con|prn|aux|nul|com\d|lpt\d", stem):
        stem = f"arquivo_{stem}".rstrip("_")
    return stem + ext


def _item_folder(game_id: str, item_id: str) -> Path:
    return folder(game_id) / ITEMS / store._check_id(item_id)


def _item_record(item_id: str) -> Path:
    """O registro de uma textura, de um som ou de um documento, procurado em todos os jogos (os ids não se repetem)."""
    found = next(GAMES.glob(f"*/{ITEMS}/{store._check_id(item_id)}/item.json"), None)
    if found is None:
        raise KeyError(f"asset não encontrado: {item_id}")
    return found


def has_item(item_id: str) -> bool:
    try:
        _item_record(item_id)
    except (KeyError, ValueError):
        return False
    return True


def item_folder(item_id: str) -> Path:
    """A pasta de uma textura, de um som ou de um documento: é onde o terminal dele abre (ponte/terminal.py)."""
    return _item_record(item_id).parent


def get_item(item_id: str) -> dict:
    record = store.read_json(_item_record(item_id))
    if record is None:
        raise KeyError(f"asset não encontrado: {item_id}")
    return record


def item_path(record: dict) -> Path:
    return _item_folder(record["game"], record["id"]) / record["file"]


def list_items(game_id: str | None = None) -> list[dict]:
    """Texturas, sons e documentos, do mais novo para o mais antigo; de um jogo só, se pedido."""
    pattern = f"{store._check_id(game_id) if game_id else '*'}/{ITEMS}/*/item.json"
    records = [store.read_json(path) for path in GAMES.glob(pattern)]
    return sorted((r for r in records if r), key=lambda r: r.get("created_at", ""), reverse=True)


def documents(game_id: str, tab: str | None = None) -> list[dict]:
    """Os documentos do jogo; os de uma aba de gestão só, se pedido."""
    game = get(game_id)
    return [i for i in list_items(game_id) if i["kind"] == DOCUMENT and (tab is None or tab_of(game, i, "gestao") == tab)]


def _item_tab(game_id: str, kind: str, tab: str | None) -> str | None:
    """A aba em que um arquivo novo entra, conferida. O documento precisa de uma de gestão; textura e som, sem aba dita, ficam na que vem com o jogo."""
    wanted = item_tab_kind({"kind": kind})
    if tab:
        chosen = get_tab(game_id, tab)
        if chosen["kind"] != wanted:
            raise ValueError(f"A aba {chosen['name']} não recebe {kind}: {'documento fica numa aba de gestão' if kind == DOCUMENT else 'textura e som ficam numa aba de assets'}.")
        return chosen["id"]
    if kind != DOCUMENT:
        return None
    first = tab_of(game_id, {}, wanted)
    if first is None:
        raise ValueError('Documento fica numa aba de gestão, e este jogo ainda não tem nenhuma: crie uma na tela do jogo ("+ Nova aba") ou com `ponte game tab new`.')
    return first


def new_item(game_id: str, filename: str, name: str | None = None, tab: str | None = None) -> tuple[dict, Path]:
    """Abre lugar para uma textura, um som ou um documento. Devolve o registro, ainda não gravado, e onde o arquivo deve ficar.

    Com o arquivo no lugar, ``save_item`` grava o registro; se não chegar, ``discard_item`` desfaz.
    """
    get(game_id)
    kind = kind_of(filename)
    if kind is None:
        accepted = ", ".join(ext for extensions in ITEM_KINDS.values() for ext in extensions)
        raise ValueError(f"'{Path(filename).name}' não é textura, som nem documento. Aceitos: {accepted}")
    tab_id = _item_tab(game_id, kind, tab)
    label = (name or "").strip() or Path(filename).stem
    item_id = store.new_id(label)
    # O terminal distingue jogo, projeto e arquivo pelo id: os três não podem coincidir.
    while exists(item_id) or store.project_folder(item_id).exists() or has_item(item_id):
        item_id = store.new_id(label)
    record = {"id": item_id, "game": game_id, "kind": kind, "name": label, "file": _safe_filename(filename), "created_at": store.now()}
    if tab_id:
        record["tab"] = tab_id
    target = item_path(record)
    target.parent.mkdir(parents=True)
    return record, target


def save_item(record: dict) -> dict:
    record["size_bytes"] = item_path(record).stat().st_size
    store.write_json(_item_folder(record["game"], record["id"]) / "item.json", record)
    return record


def discard_item(record: dict) -> None:
    shutil.rmtree(_item_folder(record["game"], record["id"]), ignore_errors=True)


def add_item(game_id: str, source: Path, name: str | None = None, tab: str | None = None) -> dict:
    """Copia para o jogo uma textura, um som ou um documento que já está no disco."""
    if not source.is_file():
        raise ValueError(f"Arquivo não encontrado: {source}")
    record, target = new_item(game_id, source.name, name, tab)
    try:
        shutil.copy2(source, target)
        return save_item(record)
    except Exception:
        discard_item(record)
        raise


def new_document(game_id: str, name: str, tab: str | None = None, text: str | None = None) -> dict:
    """Cria um documento numa aba de gestão: um arquivo .md com o nome dito, que começa só com o título."""
    name = name.strip()
    if not name:
        raise ValueError("O documento precisa de um nome.")
    record, target = new_item(game_id, f"{name}.md", name, tab)
    try:
        target.write_text(f"# {name}\n\n" if text is None else text, encoding="utf-8", newline="\n")
        return save_item(record)
    except Exception:
        discard_item(record)
        raise


def write_document(item_id: str, text: str) -> dict:
    """Grava o texto de um documento (o que o dono escreveu na tela)."""
    record = get_item(item_id)
    if record["kind"] != DOCUMENT:
        raise ValueError(f"{record['name']} não é um documento.")
    item_path(record).write_text(text, encoding="utf-8", newline="\n")
    return save_item(record)


def rename_item(item_id: str, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("O nome do asset não pode ficar vazio.")
    path = _item_record(item_id)
    record = {**get_item(item_id), "name": name}
    store.write_json(path, record)
    return record


def place_item(item_id: str, tab: str) -> dict:
    """Põe uma textura ou um som noutra aba de assets, ou um documento noutra aba de gestão."""
    record = get_item(item_id)
    record = {**record, "tab": _item_tab(record["game"], record["kind"], tab)}
    store.write_json(_item_record(item_id), record)
    return record


def delete_item(item_id: str) -> None:
    try:
        path = _item_record(item_id)
    except KeyError:
        return
    shutil.rmtree(path.parent, ignore_errors=True)


# --- As tarefas das abas de gestão -----------------------------------------------------------
# Um quadro por aba, com três colunas (TASK_STATES). Ficam todas num arquivo só do jogo, na ordem em
# que aparecem em cada coluna; cada uma diz em ``tab`` de que aba é.


def _read_tasks(game_id: str) -> list[dict]:
    data = store.read_json(folder(game_id) / TASKS, [])
    return [task for task in data if isinstance(task, dict) and task.get("id")] if isinstance(data, list) else []


def list_tasks(game_id: str | None = None) -> list[dict]:
    """As tarefas, na ordem do quadro; de um jogo só, se pedido. Cada uma diz em ``game`` de que jogo é."""
    ids = [game_id] if game_id else [game["id"] for game in list_games()]
    return [{**task, "game": gid} for gid in ids for task in _read_tasks(gid)]


def _check_state(status: str) -> str:
    if status not in TASK_STATES:
        raise ValueError(f"Estado de tarefa desconhecido: {status!r} (use {', '.join(TASK_STATES)})")
    return status


def _task_tab(game_id: str, tab: str | None) -> str:
    """A aba de gestão em que a tarefa fica: a dita, conferida, ou a primeira do jogo."""
    if tab:
        chosen = get_tab(game_id, tab)
        if chosen["kind"] != "gestao":
            raise ValueError(f"A aba {chosen['name']} não é de gestão: tarefa fica numa aba de gestão.")
        return chosen["id"]
    first = tab_of(game_id, {}, "gestao")
    if first is None:
        raise ValueError('Tarefa fica numa aba de gestão, e este jogo ainda não tem nenhuma: crie uma na tela do jogo ("+ Nova aba") ou com `ponte game tab new`.')
    return first


def _task_title(title: str) -> str:
    title = " ".join(title.split())
    if not title:
        raise ValueError("A tarefa precisa de um título.")
    return title


def add_task(game_id: str, title: str, tab: str | None = None, notes: str = "", status: str = TASK_STATES[0]) -> dict:
    """Põe uma tarefa no quadro de uma aba de gestão (sem aba dita, na primeira do jogo), no fim da coluna dela."""
    get(game_id)
    title, status, tab_id = _task_title(title), _check_state(status), _task_tab(game_id, tab)
    with _tasks_lock:
        taken = {task["id"] for task in list_tasks()}
        task_id = store.new_id(title)
        while task_id in taken:
            task_id = store.new_id(title)
        task = {"id": task_id, "tab": tab_id, "title": title, "status": status, "notes": notes.strip(), "created_at": store.now(), "updated_at": store.now()}
        store.write_json(folder(game_id) / TASKS, _read_tasks(game_id) + [task])
    return {**task, "game": game_id}


def _find_task(task_id: str) -> tuple[str, list[dict], int]:
    """O jogo da tarefa, as tarefas dele e a posição dela (os ids não se repetem entre os jogos)."""
    for game in list_games():
        tasks = _read_tasks(game["id"])
        index = next((i for i, task in enumerate(tasks) if task["id"] == task_id), None)
        if index is not None:
            return game["id"], tasks, index
    raise KeyError(f"tarefa não encontrada: {task_id}")


def get_task(task_id: str) -> dict:
    game_id, tasks, index = _find_task(task_id)
    return {**tasks[index], "game": game_id}


def update_task(task_id: str, *, title: str | None = None, status: str | None = None, notes: str | None = None, tab: str | None = None) -> dict:
    """Muda o título, a nota, a coluna ou a aba de uma tarefa. Quem muda de coluna vai para o fim dela."""
    with _tasks_lock:
        game_id, tasks, index = _find_task(task_id)
        task = dict(tasks[index])
        if title is not None:
            task["title"] = _task_title(title)
        if notes is not None:
            task["notes"] = notes.strip()
        if tab is not None:
            task["tab"] = _task_tab(game_id, tab)
        moved = status is not None and _check_state(status) != task.get("status")
        if status is not None:
            task["status"] = status
        task["updated_at"] = store.now()
        rest = tasks[:index] + tasks[index + 1 :]
        store.write_json(folder(game_id) / TASKS, rest + [task] if moved else tasks[:index] + [task] + tasks[index + 1 :])
    return {**task, "game": game_id}


def delete_task(task_id: str) -> None:
    with _tasks_lock:
        try:
            game_id, tasks, index = _find_task(task_id)
        except KeyError:
            return
        store.write_json(folder(game_id) / TASKS, tasks[:index] + tasks[index + 1 :])


def contents(game_id: str) -> dict:
    """Tudo o que há num jogo: os personagens, os assets (modelos, texturas e sons), os documentos e as tarefas.

    ``tabs`` traz o mesmo separado como a tela mostra, aba por aba.
    """
    game = get(game_id)
    items = list_items(game_id)
    characters, models = members(game_id, "personagem"), members(game_id, "modelo")
    files = [i for i in items if i["kind"] != DOCUMENT]
    docs = [i for i in items if i["kind"] == DOCUMENT]
    tasks = list_tasks(game_id)

    def inside(things: list[dict], tab: dict) -> list[dict]:
        return [thing for thing in things if tab_of(game, thing, tab["kind"]) == tab["id"]]

    shown = []
    for tab in tabs(game):
        if tab["kind"] == "personagens":
            shown.append({**tab, "characters": inside(characters, tab)})
        elif tab["kind"] == "assets":
            shown.append({**tab, "models": inside(models, tab), "files": inside(files, tab)})
        else:
            shown.append({**tab, "tasks": inside(tasks, tab), "documents": inside(docs, tab)})
    return {
        "game": game,
        "tabs": shown,
        "characters": characters,
        "models": models,
        "textures": [i for i in items if i["kind"] == "textura"],
        "sounds": [i for i in items if i["kind"] == "som"],
        "documents": docs,
        "tasks": tasks,
    }
