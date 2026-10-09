"""A corrente de passos: um passo de cada vez, cada um em cima do anterior, um clipe só.

Monta um acervo descartável (PONTE_DATA) com o boneco de teste e encena os pedidos, com o
Kimodo trocado por um dublê que devolve a caminhada de referência (nada é gerado). Confere:

- passo 1: nasce a animação A, com a prévia dela;
- passo 2, continuando A: nasce B, com os passos de A mais o novo. A prévia de A sai da
  lista (o clipe novo a contém) e a animação A fica guardada;
- refazer o passo 2: nasce C continuando A, e B é apagada com a prévia dela;
- refazer não aceita animação de outro projeto nem a mesma de onde o passo parte.

Não usa o Kimodo nem toca no acervo de verdade.

    uv run python tests/check_chain.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WALK = ROOT / "tests" / "fixtures" / "kimodo_walk_forward.bvh"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(tempfile.mkdtemp(prefix="ponte-corrente-"))
    os.environ["PONTE_DATA"] = str(work / "data")

    from ponte import blender, engines, kimodo, pipeline, store

    problems: list[str] = []
    takes: list[dict] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    def step(text: str) -> None:
        print(f"  · {text}", flush=True)

    def stand_in(work_dir: Path, script: list[dict], **_options) -> list[dict]:
        """No lugar do Kimodo: a caminhada de referência, com o passo novo começando no quadro 100 de uma continuação."""
        work_dir.mkdir(parents=True, exist_ok=True)
        take = script[0]
        takes.append(take)
        bvh, npz = work_dir / "motion_00.bvh", work_dir / "motion_00.npz"
        shutil.copy2(WALK, bvh)
        npz.write_bytes(b"dubl")
        first = 100 if take.get("continue_from") else 0
        marks = [first + 30 * i for i in range(len(take["steps"]))]
        return [{"take": take["name"], "sample": 1, "stem": "motion_00", "step_frames": marks, "bvh": bvh, "npz": npz, **kimodo.check_skeleton(bvh)}]

    def previews(asset_id: str) -> list[str]:
        return sorted(p["id"] for p in store.list_all("result", asset_id))

    def exists(kind: str, item_id: str) -> bool:
        try:
            store.get(kind, item_id)
            return True
        except KeyError:
            return False

    real_generate, real_problem = kimodo.generate, engines.problem
    kimodo.generate = stand_in
    engines.problem = lambda _engine: None  # o teste não depende de o Kimodo estar instalado nesta máquina
    try:
        rig = work / "boneco.fbx"
        blender.run_script("make_test_rig.py", ["--out", rig, "--pose", "A"], rig.with_suffix(".make.json"))
        asset_id = pipeline.add_asset(rig, "Boneco Corrente", step)["id"]
        other_id = pipeline.add_asset(rig, "Outro Boneco", step)["id"]

        a = pipeline.animate(asset_id, [{"text": "stands still", "seconds": 2}], premise="A zombie", log=step)[0]["motion_id"]
        expect(previews(asset_id) == [a], f"o passo 1 deveria deixar uma prévia, a dele: {previews(asset_id)}")
        expect([s["text"] for s in store.get("motion", a)["steps"]] == ["A zombie stands still."], "o passo 1 não ficou registrado no roteiro")

        b = pipeline.animate(asset_id, [{"text": "walks forward", "seconds": 3}], premise="A zombie", continue_from=a, log=step)[0]["motion_id"]
        motion_b = store.get("motion", b)
        expect(takes[-1]["continue_from"] == store.folder("motion", a) / "motion.npz", "o passo 2 não partiu da animação do passo 1")
        expect(previews(asset_id) == [b], f"depois do passo 2 só deveria restar a prévia do clipe novo: {previews(asset_id)}")
        expect(exists("motion", a), "a animação do passo 1 foi apagada: sem ela não dá para refazer o passo 2")
        expect([s["text"] for s in motion_b["steps"]] == ["A zombie stands still.", "A zombie walks forward."], f"o roteiro do clipe não traz os dois passos: {motion_b['steps']}")
        expect([s["start_frame"] for s in motion_b["steps"]] == [0, 100], f"os passos não começam onde deviam: {[s['start_frame'] for s in motion_b['steps']]}")
        expect(motion_b["continued_from"] == a and motion_b["premise"] == "A zombie", "o clipe não guarda de onde continuou, ou perdeu o contexto")

        c = pipeline.animate(asset_id, [{"text": "walks slowly", "seconds": 4}], premise="A zombie", continue_from=a, replaces=b, log=step)[0]["motion_id"]
        expect(not exists("motion", b) and not exists("result", b), "refazer o passo 2 não apagou a versão anterior")
        expect(previews(asset_id) == [c], f"depois de refazer só deveria restar a prévia nova: {previews(asset_id)}")
        expect(exists("motion", a), "refazer o passo 2 apagou a animação de onde ele parte")
        expect([s["text"] for s in store.get("motion", c)["steps"]] == ["A zombie stands still.", "A zombie walks slowly."], "o roteiro refeito não traz o passo 1 e o passo novo")

        # Refazer o passo 1: do zero, tomando o lugar da animação de um passo só.
        solo = pipeline.animate(other_id, [{"text": "waves", "seconds": 2}], log=step)[0]["motion_id"]
        again = pipeline.animate(other_id, [{"text": "waves slowly", "seconds": 2}], replaces=solo, log=step)[0]["motion_id"]
        expect(not exists("motion", solo) and previews(other_id) == [again], "refazer o passo 1 não trocou a animação pela nova")

        before = len(takes)
        for label, options in (("de outro projeto", {"replaces": again}), ("a mesma de onde o passo parte", {"continue_from": c, "replaces": c})):
            try:
                pipeline.animate(asset_id, [{"text": "turns", "seconds": 2}], log=step, **options)
                problems.append(f"aceitou refazer uma animação {label}")
            except ValueError:
                pass
        expect(len(takes) == before, "um pedido recusado chegou a gerar")
        expect(exists("motion", again) and exists("motion", c), "um pedido recusado apagou alguma coisa")
    finally:
        kimodo.generate, engines.problem = real_generate, real_problem
        shutil.rmtree(work, ignore_errors=True)
    print(("FALHA " + "; ".join(problems)) if problems else "ok    corrente de passos: o clipe novo toma o lugar do que ele estende ou refaz")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
