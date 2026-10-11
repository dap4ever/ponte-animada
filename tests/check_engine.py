"""Os dois geradores: a escolha, e o caminho do kimodo.cpp pela ponte.

O kimodo.cpp não é chamado: no lugar do programa entra um dublê que grava a saída crua dele
(posição do quadril e rotações das 30 juntas). Num acervo descartável (PONTE_DATA), confere:

- a saída crua vira o SOMA 77 de sempre: mesma assinatura do esqueleto, quadril em centímetros,
  as rotações no lugar certo e os dedos na pose relaxada do Kimodo oficial;
- o que o kimodo.cpp não sabe fazer (caminho, laço, peso do texto) é recusado antes de gerar;
- a escolha do gerador fica gravada e vale para quem gera sem dizer qual;
- passo 1 no kimodo.cpp e, continuando, o passo 2: o roteiro inteiro é gerado de novo com a
  mesma semente, e o clipe novo traz os dois passos;
- um gerador não continua o clipe do outro, e a vaga de geração é a mesma do Kimodo original.

    uv run python tests/check_engine.py
"""

from __future__ import annotations

import array
import math
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def matrix_zyx(z: float, y: float, x: float) -> list[list[float]]:
    """Rz @ Ry @ Rx, em graus: como o leitor de BVH monta a rotação dos canais Z, Y, X."""
    cz, sz, cy, sy, cx, sx = (f(math.radians(a)) for a in (z, y, x) for f in (math.cos, math.sin))
    return [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx], [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx], [-sy, cy * sx, cy * cx]]


def matrix_quat(x: float, y: float, z: float, w: float) -> list[list[float]]:
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(tempfile.mkdtemp(prefix="ponte-gerador-"))
    os.environ["PONTE_DATA"] = str(work / "data")

    from ponte import blender, engines, kimodo, kimodo_cpp, pipeline, store

    problems: list[str] = []
    calls: list[dict] = []
    slots: list[int] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    def step(text: str) -> None:
        print(f"  · {text}", flush=True)

    def refused(action, *errors) -> bool:
        try:
            action()
        except errors or (ValueError, kimodo.KimodoError):
            return True
        return False

    def fake_run(cmd: list[str], _log) -> None:
        """No lugar do kmd-generate: anda para frente, parado na pose de descanso."""
        at = cmd.index("--sequence")
        pairs = cmd[at + 5 :]
        frames = [int(v) for v in pairs[0::2]]
        calls.append({"seed": int(cmd[at + 3]), "frames": frames, "prompts": [Path(p).read_text(encoding="utf-8") for p in pairs[1::2]]})
        out = Path(cmd[at + 4])
        total = sum(frames)
        array.array("f", [v for t in range(total) for v in (0.0, 1.0, 0.01 * t)]).tofile((out / "root_positions.f32").open("wb"))
        array.array("f", [0.0, 0.0, 0.0, 1.0] * (total * len(kimodo_cpp.JOINTS))).tofile((out / "local_rotations_xyzw.f32").open("wb"))

    @contextmanager
    def counted_slots(count: int, _log):
        slots.append(count)
        yield

    real = (kimodo_cpp._run, kimodo_cpp.missing, kimodo.generation_slots, engines.problem)
    kimodo_cpp._run, kimodo_cpp.missing, kimodo.generation_slots = fake_run, lambda: [], counted_slots
    try:
        # Com um gerador desinstalado, a ponte diz o motivo, não deixa escolhê-lo nem gerar nele.
        engines.problem = lambda engine: "Não está instalado neste PC." if engine == "kimodo" else None
        expect(refused(lambda: engines.choose("kimodo")), "deixou escolher um gerador que não está instalado")
        expect(refused(lambda: pipeline.resolve_engine("kimodo", None)), "aceitou um pedido para um gerador que não está instalado")
        expect([bool(o["problem"]) for o in engines.status()["options"]] == [True, False, False], "a interface não fica sabendo qual gerador está desinstalado")
        # Daqui em diante o teste não depende do que está instalado nesta máquina.
        engines.problem = lambda _engine: None
        # 1) A saída crua vira o SOMA 77: assinatura, quadril em centímetros, rotação e dedos.
        joints, frames = len(kimodo_cpp.JOINTS), 3
        half = math.sin(math.radians(20))
        turn = (half * 0.6, half * 0.0, half * 0.8, math.cos(math.radians(20)))  # 40 graus em torno de um eixo inclinado
        rotations = array.array("f", [0.0, 0.0, 0.0, 1.0] * (frames * joints))
        arm = kimodo_cpp.JOINTS.index("LeftArm")
        rotations[(1 * joints + arm) * 4 : (1 * joints + arm) * 4 + 4] = array.array("f", turn)
        bvh = work / "cru.bvh"
        kimodo_cpp.write_soma77(array.array("f", [0.1, 0.95, 0.2] * frames), rotations, bvh)
        expect(not refused(lambda: kimodo.check_skeleton(bvh)), "o BVH convertido não tem a assinatura do SOMA 77")
        head, at, rest = kimodo_cpp._template()
        rows = [[float(v) for v in line.split()] for line in bvh.read_text(encoding="utf-8").partition("MOTION")[2].splitlines()[3:] if line.strip()]
        expect(len(rows) == frames and len(rows[0]) == len(rest), f"o BVH convertido não tem {frames} quadros com os canais do molde")
        hips = rows[0][at["Hips"] - 3 : at["Hips"]]
        expect(all(abs(a - b) < 1e-3 for a, b in zip(hips, (10.0, 95.0, 20.0))), f"o quadril não foi para centímetros: {hips}")
        got, want = matrix_zyx(*rows[1][at["LeftArm"] : at["LeftArm"] + 3]), matrix_quat(*turn)
        worst = max(abs(got[i][j] - want[i][j]) for i in range(3) for j in range(3))
        expect(worst < 1e-5, f"a rotação do braço não voltou igual pelos canais Z, Y, X (diferença {worst:.6f})")
        expect(rows[0][at["LeftArm"] : at["LeftArm"] + 3] == [0.0, 0.0, 0.0], "junta sem rotação não ficou em zero")
        finger = rows[2][at["LeftHandIndex2"] : at["LeftHandIndex2"] + 3]
        expect(finger == rest[at["LeftHandIndex2"] : at["LeftHandIndex2"] + 3] and any(abs(v) > 1 for v in finger), f"os dedos não ficaram na pose relaxada do molde: {finger}")
        expect(refused(lambda: kimodo_cpp.write_soma77(array.array("f", [0.0] * 6), array.array("f", [0.0] * 8), bvh)), "aceitou uma saída crua de outro tamanho")

        # 2) O que o kimodo.cpp não faz é recusado; o resto passa.
        plain = {"text": "walks.", "seconds": 3.0}
        expect(not refused(lambda: kimodo_cpp.check_script([plain, {**plain, "text_weight": 2}])), "recusou um roteiro simples")
        for label, bad in (
            ("caminho", [{**plain, "travel": {"direction_deg": 0, "speed": 1}}]),
            ("laço", [plain, {**plain, "loop": True}]),
            ("peso do texto", [{**plain, "text_weight": 4}]),
            ("passo de 11 s", [{**plain, "seconds": 11}]),
            ("passo seguinte mais curto que a transição", [plain, {**plain, "seconds": 0.1}]),
            ("17 passos", [plain] * 17),
        ):
            expect(refused(lambda bad=bad: kimodo_cpp.check_script(bad)), f"aceitou {label} no kimodo.cpp")

        # 3) A escolha do gerador fica gravada.
        expect(engines.current() == "kimodo", f"sem ninguém escolher, o gerador deveria ser o original: {engines.current()}")
        expect(refused(lambda: engines.choose("outro")), "aceitou um gerador que não existe")
        engines.choose("cpp")
        expect(engines.current() == "cpp" and engines.status()["current"] == "cpp", "a escolha do kimodo.cpp não ficou gravada")
        expect([o["id"] for o in engines.status()["options"]] == ["kimodo", "cpp", "ardy"] and "loop" in engines.status()["options"][1]["lacks"], "a interface não recebe os geradores com o que falta em cada um")

        # 4) Pela ponte: passo 1 e, continuando, o passo 2 (o roteiro inteiro de novo, mesma semente).
        rig = work / "boneco.fbx"
        blender.run_script("make_test_rig.py", ["--out", rig, "--pose", "A"], rig.with_suffix(".make.json"))
        asset_id = pipeline.add_asset(rig, "Boneco Gerador", step)["id"]
        a = pipeline.animate(asset_id, [{"text": "stands still", "seconds": 2}], premise="A zombie", seed=7, log=step)[0]["motion_id"]
        motion_a = store.get("motion", a)
        expect((motion_a.get("engine"), motion_a.get("source"), motion_a.get("frames"), motion_a.get("seed")) == ("cpp", "kimodo", 60, 7), f"o passo 1 não ficou registrado como do kimodo.cpp: {motion_a.get('engine')}, {motion_a.get('source')}, {motion_a.get('frames')}, {motion_a.get('seed')}")
        expect(calls[-1] == {"seed": 7, "frames": [60], "prompts": ["A zombie stands still."]}, f"o kimodo.cpp não recebeu o passo 1 como devia: {calls[-1]}")
        expect(not (store.folder("motion", a) / "motion.npz").exists() and not refused(lambda: kimodo.check_skeleton(store.folder("motion", a) / "motion.bvh")), "a animação do kimodo.cpp não ficou guardada no SOMA 77 (e sem os dados do original)")

        b = pipeline.animate(asset_id, [{"text": "walks forward", "seconds": 3}], premise="A zombie", continue_from=a, seed=99, log=step)[0]["motion_id"]
        motion_b = store.get("motion", b)
        expect(calls[-1] == {"seed": 7, "frames": [60, 90], "prompts": ["A zombie stands still.", "A zombie walks forward."]}, f"a continuação não gerou o roteiro inteiro com a semente do clipe: {calls[-1]}")
        expect([(s["text"], s["start_frame"]) for s in motion_b["steps"]] == [("A zombie stands still.", 0), ("A zombie walks forward.", 60)] and motion_b["frames"] == 150, f"o clipe novo não traz os dois passos, cada um no seu quadro: {motion_b['steps']}")
        expect(motion_b.get("continued_from") == a and sorted(p["id"] for p in store.list_all("result", asset_id)) == [b], "a continuação não tomou o lugar da prévia do passo 1")

        # 5) Um gerador não continua o clipe do outro; o que o kimodo.cpp não faz não chega a gerar.
        before = len(calls)
        expect(refused(lambda: pipeline.animate(asset_id, [{"text": "turns", "seconds": 2}], continue_from=b, engine="kimodo", log=step)), "o Kimodo original aceitou continuar um clipe do kimodo.cpp")
        expect(refused(lambda: pipeline.animate(asset_id, [{"text": "sways", "seconds": 3, "loop": True}], continue_from=b, log=step)), "o kimodo.cpp aceitou um passo em laço")
        expect(refused(lambda: pipeline.animate(asset_id, [{"text": "turns", "seconds": 2}], continue_from=b, samples=2, log=step)), "o kimodo.cpp aceitou variações numa continuação")
        expect(len(calls) == before, "um pedido recusado chegou a gerar")
        expect(slots == [1, 1], f"cada geração do kimodo.cpp deveria ocupar a vaga única do Kimodo, uma vez: {slots}")

        # 6) Conferir o roteiro sem gerar não roda o programa.
        dry = kimodo_cpp.generate(work / "seco", [{"name": "motion", "steps": [plain, plain], "seed": 0}], dry_run=True)
        expect(len(calls) == before and dry[0]["frames"] == 180 and dry[0]["step_frames"] == [0, 90], f"o ensaio a seco não deu os quadros do roteiro: {dry[0]['frames']}, {dry[0]['step_frames']}")
    finally:
        kimodo_cpp._run, kimodo_cpp.missing, kimodo.generation_slots, engines.problem = real
        shutil.rmtree(work, ignore_errors=True)
    print(("FALHA " + "; ".join(problems)) if problems else "ok    geradores: kimodo.cpp sai no SOMA 77, continua refazendo o roteiro e divide a vaga com o original")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
