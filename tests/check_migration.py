"""Confere a migração do acervo antigo (assets/, motions/, results/) para o formato de projetos.

Monta um acervo antigo de mentira numa pasta temporária, migra e confere onde cada coisa
foi parar. Faz isso duas vezes: movendo as pastas, e com o Windows negando renomear pasta,
que é quando a migração copia. Não toca no acervo de verdade.

    uv run python tests/check_migration.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ponte import store  # noqa: E402


def put(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def check(deny_rename: bool) -> list[str]:
    data = Path(tempfile.mkdtemp(prefix="ponte-migra-"))
    projects = data / "projects"
    real = store.DATA, store.PROJECTS, Path.rename
    store.DATA, store.PROJECTS = data, projects
    problems: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    def denied(self: Path, target):
        if self.is_dir():
            raise PermissionError(5, "Acesso negado", str(self))
        return real[2](self, target)

    old_hero = {"id": "heroi-aaaa", "name": "Herói", "source": "source/heroi.fbx", "created_at": "2026-01-01T10:00:00"}
    old_hero_result = {"id": "heroi-aaaa--andar-1111", "asset_id": "heroi-aaaa", "motion_id": "andar-1111", "created_at": "2026-01-05T10:00:00"}
    try:
        # Dois personagens; uma animação usada pelos dois (o formato antigo deixava);
        # uma animação sem resultado; uma pasta de geração que não terminou.
        put(data / "assets/heroi-aaaa/asset.json", old_hero)
        (data / "assets/heroi-aaaa/source").mkdir()
        (data / "assets/heroi-aaaa/source/heroi.fbx").write_bytes(b"modelo")
        put(data / "assets/vilao-bbbb/asset.json", {"id": "vilao-bbbb", "name": "Vilão", "source": "source/vilao.glb", "created_at": "2026-01-02T10:00:00"})
        put(data / "motions/andar-1111/motion.json", {"id": "andar-1111", "prompt": "A person walks.", "created_at": "2026-01-03T10:00:00"})
        (data / "motions/andar-1111/motion.bvh").write_text("bvh", encoding="utf-8")
        put(data / "motions/pular-2222/motion.json", {"id": "pular-2222", "prompt": "A person jumps.", "created_at": "2026-01-04T10:00:00"})
        (data / "motions/correr-3333-tmp").mkdir(parents=True)
        put(data / "results/heroi-aaaa--andar-1111/result.json", old_hero_result)
        (data / "results/heroi-aaaa--andar-1111/result.glb").write_bytes(b"glb")
        put(data / "results/vilao-bbbb--andar-1111--parado/result.json", {"id": "vilao-bbbb--andar-1111--parado", "asset_id": "vilao-bbbb", "motion_id": "andar-1111", "created_at": "2026-01-06T10:00:00"})
        if deny_rename:
            Path.rename = denied
            # Resto de uma cópia interrompida: sem o registro, tem de ser refeita.
            (projects / "heroi-aaaa/personagem/source").mkdir(parents=True)
            (projects / "heroi-aaaa/personagem/source/heroi.fbx").write_bytes(b"mod")

        leftovers = store.migrate_layout()

        expect((projects / "heroi-aaaa/personagem/source/heroi.fbx").read_bytes() == b"modelo", "o arquivo do personagem não foi junto")
        expect([a["id"] for a in store.list_all("asset")] == ["vilao-bbbb", "heroi-aaaa"], f"projetos listados: {[a['id'] for a in store.list_all('asset')]}")
        expect(store.get("result", "andar-1111")["asset_id"] == "heroi-aaaa", "resultado do herói não está com o id curto no projeto dele")
        expect((projects / "heroi-aaaa/previas/andar-1111/result.glb").exists(), "arquivo do resultado não foi junto")
        expect(store.get("result", "andar-1111--parado")["asset_id"] == "vilao-bbbb", "resultado parado do vilão fora do projeto dele")
        expect([r["id"] for r in store.list_all("result", "heroi-aaaa")] == ["andar-1111"], "lista de resultados por projeto")
        expect(store.get("motion", "andar-1111")["asset_id"] == "heroi-aaaa", "animação não foi para o projeto do primeiro resultado que a usa")
        expect((projects / "heroi-aaaa/animacoes/andar-1111/motion.bvh").exists(), "BVH da animação não foi junto")
        expect(leftovers == ["animação pular-2222"], f"sobras: {leftovers}")
        expect((data / "motions/pular-2222/motion.json").exists(), "animação sem dono deveria ficar onde estava")
        expect(not (data / "motions/correr-3333-tmp").exists(), "pasta de geração inacabada não foi limpa")
        expect(not (data / "assets").exists() and not (data / "results").exists(), "pastas antigas vazias não foram removidas")

        # Pasta antiga que sobrou (não deu para apagar na hora) não pode passar por cima do que já está no projeto.
        store.set_review("result", "andar-1111", "aprovado")
        put(data / "assets/heroi-aaaa/asset.json", old_hero | {"name": "versão velha"})
        put(data / "results/heroi-aaaa--andar-1111/result.json", old_hero_result)
        expect(store.migrate_layout() == ["animação pular-2222"], "rodar de novo deveria só repetir a sobra")
        expect(store.get("asset", "heroi-aaaa")["name"] == "Herói", "a sobra da pasta antiga passou por cima do personagem")
        expect(store.get("result", "andar-1111")["review"]["status"] == "aprovado", "a sobra da pasta antiga desfez a revisão do resultado")
        expect(not (data / "assets").exists() and not (data / "results").exists(), "as sobras das pastas antigas não foram limpas")

        # Um acervo com um projeto só: a animação solta vai para ele.
        shutil.rmtree(projects / "vilao-bbbb")
        expect(store.migrate_layout() == [], "com um projeto só, a animação solta deveria entrar nele")
        expect(store.get("motion", "pular-2222")["asset_id"] == "heroi-aaaa", "animação solta não entrou no único projeto")
        expect(not (data / "motions").exists(), "pasta antiga de animações deveria ter sumido")

        # As prévias já se chamaram resultados/ dentro do projeto: passam para previas/.
        put(projects / "heroi-aaaa/resultados/pular-2222/result.json", {"id": "pular-2222", "asset_id": "heroi-aaaa", "motion_id": "pular-2222", "created_at": "2026-01-07T10:00:00"})
        (projects / "heroi-aaaa/resultados/pular-2222/result.glb").write_bytes(b"glb")
        expect(store.migrate_layout() == [], "a prévia com o nome antigo da pasta não deveria virar sobra")
        expect((projects / "heroi-aaaa/previas/pular-2222/result.glb").exists() and not (projects / "heroi-aaaa/resultados").exists(), "prévia com o nome antigo da pasta não passou para previas/")
        expect(store.get("result", "pular-2222")["motion_id"] == "pular-2222", "prévia renomeada de pasta não é achada pelo id")

        store.delete("asset", "heroi-aaaa")
        expect(not (projects / "heroi-aaaa").exists() and store.list_all("motion") == [], "apagar o personagem deveria apagar o projeto inteiro")
    finally:
        store.DATA, store.PROJECTS, Path.rename = real
        shutil.rmtree(data, ignore_errors=True)
    return problems


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    failed = False
    for deny_rename, how in ((False, "movendo as pastas"), (True, "copiando, com o Windows negando renomear pasta")):
        problems = check(deny_rename)
        failed = failed or bool(problems)
        print(f"FALHA ({how}) " + "; ".join(problems) if problems else f"ok    acervo antigo migrado para projetos, {how}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
