"""Os jogos: cada um junta os personagens e os assets dele, e o guia da pasta diz à IA o que há lá.

Também as abas da tela do jogo (as duas que vêm com ele e as que o dono cria) e o que fica numa
aba de gestão: o quadro de tarefas e os documentos.

Só Python, num acervo descartável (PONTE_DATA): não usa o Blender nem sobe servidor. O terminal
do jogo, que abre na pasta dele, é conferido por ``check_terminal.py``.

    uv run python tests/check_games.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix="ponte-jogos-"))
os.environ["PONTE_DATA"] = str(WORK / "data")
sys.path.insert(0, str(ROOT))

from ponte import games, store, terminal  # noqa: E402 - o acervo descartável tem de estar dito antes

SOLDIER, CRATE, LOOSE = "soldado-0001", "caixote-0002", "avulso-0003"


def project(asset_id: str, name: str, **summary) -> None:
    record = {"id": asset_id, "name": name, "created_at": f"2026-10-13T10:00:0{asset_id[-1]}-03:00", "status": "inspecionado", "verdict": "pronto", "source": "source/modelo.fbx", "summary": summary}
    store.write_json(store.folder("asset", asset_id) / "asset.json", record)


def refuses(action, error=ValueError) -> bool:
    try:
        action()
    except error:
        return True
    return False


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    problems: list[str] = []

    def check(label: str, passed: bool, detail: str = "") -> None:
        print(("ok    " if passed else "FALHA ") + label + (f": {detail}" if detail and not passed else ""))
        if not passed:
            problems.append(label)

    project(SOLDIER, "Soldado", rig="Mixamo", bones=65, triangles=30000, height_m=1.8)
    project(CRATE, "Caixote", triangles=120, height_m=0.6)
    project(LOOSE, "Avulso", rig="Mixamo", bones=65)
    (store.project_folder(SOLDIER) / terminal.NOTES).write_text("notas do Soldado\n", encoding="utf-8")
    code = WORK / "codigo do jogo"
    code.mkdir()

    # 1. Criar, renomear, dizer onde está o código.
    game = games.create("  Horda de Teste ", str(code))
    gid = game["id"]
    check("o jogo nasce com nome, pasta e a pasta do código", game["name"] == "Horda de Teste" and games.folder(gid).is_dir() and game["code_path"] == str(code.resolve()), str(game))
    check("jogo sem nome é recusado", refuses(lambda: games.create("   ")))
    check("pasta de código que não existe é recusada", refuses(lambda: games.set_code_path(gid, str(WORK / "nao-existe"))))
    check("a pasta do código sai quando vem vazia", games.set_code_path(gid, "")["code_path"] is None and games.set_code_path(gid, str(code))["code_path"] == str(code.resolve()))
    check("o nome muda e o resto fica", games.rename(gid, "Horda")["name"] == "Horda" and games.get(gid)["code_path"] == str(code.resolve()))
    other = games.create("Outro jogo")
    check("os jogos saem na ordem em que foram criados", [g["id"] for g in games.list_games()] == [gid, other["id"]])

    # 2. Personagens e modelos: o projeto diz de que jogo é e o que é lá.
    games.assign(SOLDIER, gid)
    games.assign(CRATE, gid, "modelo")
    content = games.contents(gid)
    check("o personagem entra em Characters", [a["id"] for a in content["characters"]] == [SOLDIER])
    check("o modelo 3D entra em Assets", [a["id"] for a in content["models"]] == [CRATE])
    check("quem não foi posto em jogo nenhum fica de fora", LOOSE not in [a["id"] for a in games.members(gid)] and not store.get("asset", LOOSE).get("game"))
    check("o resto do registro do projeto fica como estava", store.get("asset", SOLDIER)["summary"]["bones"] == 65 and store.get("asset", SOLDIER)["verdict"] == "pronto")
    check("jogo que não existe é recusado", refuses(lambda: games.assign(SOLDIER, "nao-existe-0000"), KeyError) and store.get("asset", SOLDIER)["game"] == gid)
    check("papel desconhecido é recusado", refuses(lambda: games.set_role(SOLDIER, "cenario")))
    games.set_role(CRATE, "personagem")
    check("o modelo passa para Characters e volta", len(games.members(gid, "personagem")) == 2 and games.set_role(CRATE, "modelo")["role"] == "modelo")
    games.assign(LOOSE, other["id"])
    check("um projeto muda de jogo", [a["id"] for a in games.members(other["id"])] == [LOOSE])

    # 3. Texturas e sons.
    files = WORK / "arquivos"
    files.mkdir()
    (files / "Wood_Diffuse.PNG").write_bytes(b"\x89PNG" + b"0" * 60)
    (files / "passo 01.wav").write_bytes(b"RIFF" + b"0" * 96)
    (files / "leia.txt").write_text("nada", encoding="utf-8")
    (files / "planilha.xlsx").write_bytes(b"PK" + b"0" * 30)
    texture = games.add_item(gid, files / "Wood_Diffuse.PNG")
    sound = games.add_item(gid, files / "passo 01.wav", "Passo na terra")
    check("a textura entra com o nome do arquivo, como o jogo usa", texture["kind"] == "textura" and texture["file"] == "Wood_Diffuse.png" and texture["name"] == "Wood_Diffuse" and texture["size_bytes"] == 64, str(texture))
    check("o som entra com o nome dito", sound["kind"] == "som" and sound["name"] == "Passo na terra" and games.item_path(sound).read_bytes().startswith(b"RIFF"), str(sound))
    check("o que não é textura, som nem documento é recusado, sem deixar pasta", refuses(lambda: games.add_item(gid, files / "planilha.xlsx")) and len(list((games.folder(gid) / games.ITEMS).iterdir())) == 2)
    check("documento num jogo sem aba de gestão é recusado, sem deixar pasta", refuses(lambda: games.add_item(gid, files / "leia.txt")) and len(list((games.folder(gid) / games.ITEMS).iterdir())) == 2)
    check("arquivo que não existe é recusado", refuses(lambda: games.add_item(gid, files / "sumiu.png")))
    check("nome de arquivo perigoso é limpo", games._safe_filename("..\\..\\CON.png") == "arquivo_CON.png" and games._safe_filename('a<b>:"c".OGG') == "a_b___c_.ogg")
    check("os assets são achados pelo id, de qualquer jogo", games.get_item(sound["id"])["game"] == gid and [i["id"] for i in games.list_items(other["id"])] == [])
    check("o asset muda de nome", games.rename_item(texture["id"], "Madeira")["name"] == "Madeira" and games.get_item(texture["id"])["file"] == "Wood_Diffuse.png")
    content = games.contents(gid)
    check("o jogo lista texturas e sons em separado", [i["id"] for i in content["textures"]] == [texture["id"]] and [i["id"] for i in content["sounds"]] == [sound["id"]])

    # 3b. As abas da tela do jogo: duas vêm com ele, as outras o dono cria.
    def shown(tab_id: str, key: str) -> list[str]:
        return [x["id"] for x in next(t for t in games.contents(gid)["tabs"] if t["id"] == tab_id)[key]]

    check("o jogo nasce com as duas abas, Characters e Assets", [(t["id"], t["name"], t["kind"]) for t in games.tabs(gid)] == [("characters", "Characters", "personagens"), ("assets", "Assets", "assets")])
    check("e nelas está o que já havia no jogo", shown("characters", "characters") == [SOLDIER] and shown("assets", "models") == [CRATE] and set(shown("assets", "files")) == {texture["id"], sound["id"]})
    zombies = games.add_tab(gid, "  Zumbis ", "personagens")
    scenery = games.add_tab(gid, "Cenário", "assets")
    board = games.add_tab(gid, "Gestão", "gestao")
    check("a aba nova entra no fim, com nome e tipo", [(t["name"], t["kind"]) for t in games.tabs(gid)[2:]] == [("Zumbis", "personagens"), ("Cenário", "assets"), ("Gestão", "gestao")] and len({t["id"] for t in games.tabs(gid)}) == 5)
    check("tipo desconhecido, nome vazio e nome repetido são recusados", refuses(lambda: games.add_tab(gid, "Loja", "loja")) and refuses(lambda: games.add_tab(gid, "   ", "assets")) and refuses(lambda: games.add_tab(gid, "zumbis", "assets")) and len(games.tabs(gid)) == 5)
    check("a aba é achada pelo id e pelo nome", games.get_tab(gid, zombies["id"]) == games.get_tab(gid, "ZUMBIS") and refuses(lambda: games.get_tab(gid, "nao-tem"), KeyError))
    check("o outro jogo não ganha as abas deste", [t["id"] for t in games.tabs(other["id"])] == ["characters", "assets"])
    games.place(SOLDIER, zombies["id"])
    check("o personagem passa para a aba criada e sai da que vem com o jogo", shown(zombies["id"], "characters") == [SOLDIER] and shown("characters", "characters") == [] and games.role_of(store.get("asset", SOLDIER)) == "personagem")
    games.place(SOLDIER, "Cenário")
    check("numa aba de assets ele vira modelo", shown(scenery["id"], "models") == [SOLDIER] and games.role_of(store.get("asset", SOLDIER)) == "modelo" and [a["id"] for a in games.contents(gid)["characters"]] == [])
    check("personagem e modelo não entram em aba de gestão", refuses(lambda: games.place(SOLDIER, board["id"])) and refuses(lambda: games.place(SOLDIER, "nao-tem"), KeyError) and store.get("asset", SOLDIER)["tab"] == scenery["id"])
    games.assign(LOOSE, None)
    check("quem não está em jogo nenhum não tem aba", refuses(lambda: games.place(LOOSE, "characters")) and not store.get("asset", LOOSE).get("tab"))
    games.assign(LOOSE, other["id"])
    games.set_role(SOLDIER, "personagem")
    check("mudar o que ele é devolve o projeto à aba que vem com o jogo", shown("characters", "characters") == [SOLDIER] and not store.get("asset", SOLDIER).get("tab") and shown("assets", "models") == [CRATE])
    games.place(SOLDIER, zombies["id"])
    games.assign(SOLDIER, other["id"])
    check("mudar de jogo também", not store.get("asset", SOLDIER).get("tab") and [a["id"] for a in games.contents(other["id"])["tabs"][0]["characters"]] == [SOLDIER, LOOSE])
    games.assign(SOLDIER, gid)
    games.place(SOLDIER, zombies["id"])
    games.place_item(texture["id"], scenery["id"])
    check("a textura passa para outra aba de assets, e não para uma de gestão", shown(scenery["id"], "files") == [texture["id"]] and shown("assets", "files") == [sound["id"]] and refuses(lambda: games.place_item(texture["id"], board["id"])) and refuses(lambda: games.place_item(texture["id"], zombies["id"])))

    # 3c. A aba de gestão: os documentos e o quadro de tarefas.
    rules = games.new_document(gid, " Regras do jogo ")
    check("o documento nasce na aba de gestão, como um .md só com o título", rules["kind"] == "documento" and rules["file"] == "Regras do jogo.md" and rules["tab"] == board["id"] and games.item_path(rules).read_text(encoding="utf-8") == "# Regras do jogo\n\n", str(rules))
    check("documento sem nome, ou num jogo sem aba de gestão, é recusado", refuses(lambda: games.new_document(gid, "  ")) and refuses(lambda: games.new_document(other["id"], "Ideias")) and refuses(lambda: games.new_document(gid, "Ideias", scenery["id"])))
    written = games.write_document(rules["id"], "# Regras\n\n- [ ] horda cresce a cada onda\n")
    check("o texto escrito na tela é gravado no arquivo", games.item_path(rules).read_text(encoding="utf-8").endswith("cada onda\n") and written["size_bytes"] == games.item_path(rules).stat().st_size and refuses(lambda: games.write_document(texture["id"], "x")))
    readme = games.add_item(gid, files / "leia.txt", tab="gestão")
    check("um .txt que já existe entra como documento", readme["kind"] == "documento" and readme["tab"] == board["id"] and games.item_path(readme).read_text(encoding="utf-8") == "nada")
    content = games.contents(gid)
    check("os documentos ficam na aba de gestão, fora das texturas e dos sons", {d["id"] for d in content["documents"]} == {rules["id"], readme["id"]} == set(shown(board["id"], "documents")) and len(content["textures"]) == 1 and len(content["sounds"]) == 1 and set(shown("assets", "files")) | set(shown(scenery["id"], "files")) == {texture["id"], sound["id"]})
    check("o documento tem a pasta dele, onde o terminal abre", terminal.known(rules["id"]) and terminal.folder(rules["id"]) == games.item_path(rules).parent)
    gate = games.add_task(gid, "  Fazer   o portão  ", notes=" abre e fecha ")
    shot = games.add_task(gid, "Som do tiro", tab="Gestão")
    check("a tarefa nasce em A fazer, na aba de gestão", gate["title"] == "Fazer o portão" and gate["notes"] == "abre e fecha" and gate["status"] == "a_fazer" and gate["tab"] == board["id"] and gate["game"] == gid and shown(board["id"], "tasks") == [gate["id"], shot["id"]], str(gate))
    check("tarefa sem título, com estado desconhecido, numa aba que não é de gestão ou num jogo sem gestão é recusada", refuses(lambda: games.add_task(gid, "   ")) and refuses(lambda: games.add_task(gid, "x", status="talvez")) and refuses(lambda: games.add_task(gid, "x", tab=zombies["id"])) and refuses(lambda: games.add_task(other["id"], "x")) and len(games.list_tasks(gid)) == 2)
    moved = games.update_task(gate["id"], status="fazendo")
    check("a tarefa muda de coluna e vai para o fim dela", moved["status"] == "fazendo" and [t["id"] for t in games.list_tasks(gid)] == [shot["id"], gate["id"]])
    edited = games.update_task(shot["id"], title="Som do tiro do fuzil", notes="")
    check("mudar o título não mexe na ordem nem na coluna", edited["title"] == "Som do tiro do fuzil" and edited["status"] == "a_fazer" and [t["id"] for t in games.list_tasks(gid)] == [shot["id"], gate["id"]])
    check("estado desconhecido e tarefa que não existe são recusados", refuses(lambda: games.update_task(gate["id"], status="talvez")) and refuses(lambda: games.update_task("nao-existe-0000", status="feito"), KeyError) and games.get_task(gate["id"])["status"] == "fazendo")
    check("as tarefas de todos os jogos dizem de que jogo são", {t["game"] for t in games.list_tasks()} == {gid})
    text = terminal.write_game_guide(gid)[0].read_text(encoding="utf-8")
    check("o guia do jogo lista as abas e diz como criar outra", "## As abas da tela" in text and f"**Zumbis** (id `{zombies['id']}`): de personagens · 1" in text and "de gestão · 2 tarefa(s) por fazer, 0 feita(s), 2 documento(s)" in text and f"ponte game tab new {gid}" in text)
    check("o guia diz em que aba está quem saiu da que vem com o jogo", f"(id `{SOLDIER}`), na aba Zumbis, em" in text and f"(id `{CRATE}`), em" in text)
    check("o guia ensina as tarefas e aponta os documentos", f"ponte game task list {gid}" in text and "ponte game task move" in text and str(games.item_path(rules)) in text and f'ponte game doc {gid}' in text)
    check("num jogo sem aba de gestão o guia diz como criar uma", "ainda não tem aba de gestão" in terminal.write_game_guide(other["id"])[0].read_text(encoding="utf-8"))
    page = terminal.write_item_guide(rules["id"])[0].read_text(encoding="utf-8")
    check("o guia do documento diz o arquivo, que é nele que se mexe e de que jogo é", "# Documento: Regras do jogo" in page and "`Regras do jogo.md`" in page and "É neste documento que você vai mexer" in page and "**Horda**" in page and page.startswith(terminal.GUIDE_MARK))
    check("o guia não vira documento", {d["id"] for d in games.documents(gid)} == {rules["id"], readme["id"]})
    games.delete_task(shot["id"])
    games.delete_task(shot["id"])  # apagar de novo não é erro
    check("a tarefa apagada sai do quadro", [t["id"] for t in games.list_tasks(gid)] == [gate["id"]] and refuses(lambda: games.get_task(shot["id"]), KeyError))

    # 3d. Mudar o nome de uma aba e apagar: o que estava nela não se perde, a não ser o que é da gestão.
    check("a aba muda de nome, e a que vem com o jogo também", games.rename_tab(gid, zombies["id"], "Mortos-vivos")["name"] == "Mortos-vivos" and games.rename_tab(gid, "characters", "Personagens")["name"] == "Personagens" and [t["name"] for t in games.tabs(gid)][:3] == ["Personagens", "Assets", "Mortos-vivos"])
    check("nome que outra aba já usa é recusado, e o mesmo nome de novo não", refuses(lambda: games.rename_tab(gid, zombies["id"], "assets")) and games.rename_tab(gid, zombies["id"], "Mortos-vivos")["id"] == zombies["id"])
    games.rename_tab(gid, "characters", "Characters")
    check("as abas que vêm com o jogo não são apagadas", refuses(lambda: games.delete_tab(gid, "characters")) and refuses(lambda: games.delete_tab(gid, "Assets")) and len(games.tabs(gid)) == 5)
    games.delete_tab(gid, zombies["id"])
    games.delete_tab(gid, "Cenário")
    check("apagar uma aba devolve o que estava nela à que vem com o jogo", shown("characters", "characters") == [SOLDIER] and not store.get("asset", SOLDIER).get("tab") and set(shown("assets", "files")) == {texture["id"], sound["id"]} and not games.get_item(texture["id"]).get("tab") and (store.project_folder(SOLDIER) / terminal.NOTES).is_file())
    games.delete_tab(gid, board["id"])
    check("apagar a aba de gestão leva as tarefas e os documentos dela, e só eles", games.list_tasks(gid) == [] and games.documents(gid) == [] and not games.item_path(rules).parent.exists() and {i["id"] for i in games.list_items(gid)} == {texture["id"], sound["id"]} and [t["id"] for t in games.tabs(gid)] == ["characters", "assets"])

    # 4. O guia da pasta do jogo, para a IA chamada no terminal.
    paths = terminal.write_game_guide(gid)
    text = paths[0].read_text(encoding="utf-8")
    check("a pasta do jogo ganha o guia com os dois nomes", [p.name for p in paths] == list(terminal.GUIDES) and all(p.read_text(encoding="utf-8") == text for p in paths) and text.startswith(terminal.GUIDE_MARK))
    check("o guia diz o jogo, onde está o código e como listar o que há", "# Jogo: Horda" in text and str(code.resolve()) in text and f"ponte game show {gid}" in text)
    check("o guia lista o personagem, a pasta dele e as notas", SOLDIER in text and str(store.project_folder(SOLDIER)) in text and str(store.project_folder(SOLDIER) / terminal.NOTES) in text)
    check("o guia lista o modelo entre os assets e conta texturas e sons", text.index(CRATE) > text.index("## Assets") and "Texturas: 1. Sons: 1." in text)
    check("quem não é do jogo não aparece no guia", LOOSE not in text)
    check("o guia do jogo avisa que cada personagem e cada asset tem o espaço dele", "Cada personagem e cada asset tem o espaço dele" in text)

    # 4b. O guia de cada espaço: na pasta do personagem, do modelo 3D e da textura, diz à IA no que ela vai mexer.
    hero_paths = terminal.write_guide(SOLDIER)
    hero = hero_paths[0].read_text(encoding="utf-8")
    check("a pasta do personagem ganha o guia com os dois nomes", [p.name for p in hero_paths] == list(terminal.GUIDES) and hero_paths[0].parent == store.project_folder(SOLDIER) and all(p.read_text(encoding="utf-8") == hero for p in hero_paths) and hero.startswith(terminal.GUIDE_MARK))
    check("o guia do personagem diz que é nele que se mexe e aponta as notas", "# Personagem: Soldado" in hero and "É neste personagem que você vai mexer" in hero and f"leia `{terminal.NOTES}`" in hero)
    check("e diz de que jogo ele é, a pasta do jogo e a do código", "**Horda**" in hero and str(games.folder(gid)) in hero and str(code.resolve()) in hero and f"ponte game show {gid}" in hero)
    check("e como pôr a animação na tela", f"ponte anim add {SOLDIER}" in hero and f"--asset {SOLDIER}" in hero)
    crate = terminal.write_guide(CRATE)[0].read_text(encoding="utf-8")
    check("o guia do modelo 3D diz que é um asset e que é nele que se mexe", "# Asset: Caixote" in crate and "É neste asset que você vai mexer" in crate and "**Horda**" in crate)
    check("e como pôr o modelo mudado na tela, sem falar de animação", f"ponte asset inspect {CRATE}" in crate and f"--game {gid} --role modelo" in crate and "ponte anim add" not in crate and "notas próprias" not in crate)
    games.set_role(CRATE, "personagem")
    check("o guia acompanha o papel: o modelo que vira personagem", "# Personagem: Caixote" in terminal.write_guide(CRATE)[0].read_text(encoding="utf-8"))
    games.set_role(CRATE, "modelo")
    loose = terminal.write_guide(LOOSE)[0].read_text(encoding="utf-8")
    check("o guia de quem é de outro jogo fala do jogo dele, sem pasta de código", "**Outro jogo**" in loose and "Horda" not in loose and "ainda não foi dita" in loose)
    games.assign(LOOSE, None)
    check("o guia de quem não tem jogo diz isso", "ainda não está em nenhum jogo" in terminal.write_guide(LOOSE)[0].read_text(encoding="utf-8"))
    (store.project_folder(LOOSE) / "AGENTS.md").write_text("guia do dono\n", encoding="utf-8")
    games.assign(LOOSE, other["id"])
    terminal.write_guide(LOOSE)
    check("o guia do personagem é regravado com o que mudou, menos o escrito à mão", "**Outro jogo**" in (store.project_folder(LOOSE) / "CLAUDE.md").read_text(encoding="utf-8") and (store.project_folder(LOOSE) / "AGENTS.md").read_text(encoding="utf-8") == "guia do dono\n")
    wood_paths = terminal.write_item_guide(texture["id"])
    wood = wood_paths[0].read_text(encoding="utf-8")
    check("a pasta da textura ganha o guia, ao lado do arquivo", [p.name for p in wood_paths] == list(terminal.GUIDES) and wood_paths[0].parent == games.item_path(texture).parent and wood.startswith(terminal.GUIDE_MARK))
    check("o guia da textura diz o arquivo, que é nele que se mexe e de que jogo é", "# Asset: Madeira (textura)" in wood and "`Wood_Diffuse.png`" in wood and "É neste arquivo que você vai mexer" in wood and "**Horda**" in wood and f"ponte game file {gid}" in wood)
    check("o guia do som fala do tocador", "# Asset: Passo na terra (som)" in terminal.write_item_guide(sound["id"])[0].read_text(encoding="utf-8") and "o tocador do som" in (games.item_folder(sound["id"]) / "AGENTS.md").read_text(encoding="utf-8"))
    check("o guia não atrapalha a lista de texturas e sons", {i["id"] for i in games.list_items(gid)} == {texture["id"], sound["id"]} and games.get_item(texture["id"])["file"] == "Wood_Diffuse.png")
    check("cada espaço abre na pasta dele", terminal.folder(terminal.HOME) == ROOT and terminal.folder(gid) == games.folder(gid) and terminal.folder(SOLDIER) == store.project_folder(SOLDIER) and terminal.folder(texture["id"]) == games.item_path(texture).parent)

    paths[1].write_text("guia do dono\n", encoding="utf-8")
    games.assign(LOOSE, gid)
    terminal.write_game_guide(gid)
    check("o guia é regravado com o que mudou, menos o escrito à mão", LOOSE in paths[0].read_text(encoding="utf-8") and paths[1].read_text(encoding="utf-8") == "guia do dono\n")
    games.set_code_path(gid, None)
    terminal.write_game_guide(gid)
    check("sem pasta do código, o guia manda perguntar", f"ponte game path {gid}" in paths[0].read_text(encoding="utf-8"))
    check("o terminal sabe o que existe: a entrada, o jogo, o projeto e a textura", terminal.known(terminal.HOME) and terminal.known(gid) and terminal.known(SOLDIER) and terminal.known(texture["id"]) and not terminal.known("nao-existe-0000") and not terminal.known("../fora"))

    # 5. Apagar: o asset sai do disco; o jogo leva as texturas e os sons, mas não os personagens.
    games.delete_item(texture["id"])
    check("apagar uma textura tira a pasta dela", refuses(lambda: games.get_item(texture["id"]), KeyError) and len(games.list_items(gid)) == 1)
    last = games.add_tab(gid, "Gestão", "gestao")
    games.place(CRATE, games.add_tab(gid, "Cenário", "assets")["id"])
    task, note = games.add_task(gid, "Última tarefa"), games.new_document(gid, "Ideias", last["id"])
    games.delete(gid)
    survivors = {a["id"]: a for a in store.list_all("asset")}
    check("apagar o jogo tira a pasta dele, com os sons", not games.folder(gid).exists() and not games.exists(gid) and refuses(lambda: games.get_item(sound["id"]), KeyError))
    check("e com as tarefas e os documentos", refuses(lambda: games.get_task(task["id"]), KeyError) and refuses(lambda: games.get_item(note["id"]), KeyError) and games.list_tasks() == [])
    check("os personagens e os modelos ficam no disco, sem jogo e sem aba", set(survivors) == {SOLDIER, CRATE, LOOSE} and all(a.get("game") is None and not a.get("tab") for a in survivors.values()) and (store.project_folder(SOLDIER) / terminal.NOTES).is_file())
    check("o papel de cada um fica guardado", games.role_of(survivors[CRATE]) == "modelo" and games.role_of(survivors[SOLDIER]) == "personagem")
    check("o outro jogo continua lá", [g["id"] for g in games.list_games()] == [other["id"]])
    check("o registro do jogo é um arquivo só, legível", json.loads((games.folder(other["id"]) / "game.json").read_text(encoding="utf-8"))["name"] == "Outro jogo")

    shutil.rmtree(WORK, ignore_errors=True)
    print("\n" + ("tudo ok" if not problems else f"{len(problems)} FALHA(S): " + "; ".join(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
