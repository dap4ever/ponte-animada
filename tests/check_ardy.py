"""O terceiro gerador: o caminho do ARDY pela ponte.

O ARDY não é chamado: no lugar do script que roda no Ubuntu entra um dublê que grava o que ele
gravaria (um BVH no esqueleto Core, de 27 juntas, já a 30 quadros por segundo). Num acervo
descartável (PONTE_DATA), confere:

- o clipe entra no projeto convertido: nomes do SOMA, a altura do quadril do esqueleto do ARDY
  guardada para o retarget, e os começos dos passos passados de 20 para 30 quadros por segundo;
- o codificador de texto só sobe para texto novo, e é desligado em seguida se foi este pedido
  que o subiu; com a Unreal aberta ou pouca memória, a ponte recusa e diz por quê;
- continuar: o ARDY recebe só o passo novo e o clipe de onde ele parte; o clipe novo traz os
  dois passos e toma o lugar da prévia do anterior; outro gerador não continua um clipe dele;
- a vaga de geração é a mesma do Kimodo;
- uma sessão do demo ao vivo vira roteiro do projeto, com um passo por texto, e dá para
  continuar dela.

    uv run python tests/check_ardy.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# O esqueleto Core do ARDY em pose T: nome, pai e posição de descanso em centímetros.
CORE = [
    ("Hips", -1, (0.0, 0.0, 0.0)), ("Spine", 0, (0.0, 7.1, -4.7)), ("Spine1", 1, (0.0, 16.4, -6.4)), ("Spine2", 2, (0.0, 25.8, -7.2)),
    ("Spine3", 3, (0.0, 35.3, -7.2)), ("Neck", 4, (0.0, 60.2, -3.7)), ("Head", 5, (0.0, 73.0, -1.4)),
    ("RightShoulder", 4, (-3.2, 52.6, -1.9)), ("RightArm", 7, (-19.1, 52.6, -1.9)), ("RightForeArm", 8, (-48.6, 52.6, -1.9)),
    ("RightHand", 9, (-71.9, 52.6, -1.9)), ("RightHandEnd", 10, (-78.9, 52.6, -1.9)), ("RightHandThumb1", 10, (-74.7, 50.7, 2.8)),
    ("LeftShoulder", 4, (3.2, 52.6, -1.9)), ("LeftArm", 13, (19.1, 52.6, -1.9)), ("LeftForeArm", 14, (48.6, 52.6, -1.9)),
    ("LeftHand", 15, (71.9, 52.6, -1.9)), ("LeftHandEnd", 16, (78.9, 52.6, -1.9)), ("LeftHandThumb1", 16, (74.7, 50.7, 2.8)),
    ("RightUpLeg", 0, (-9.5, -2.8, 0.0)), ("RightLeg", 19, (-9.5, -44.0, 0.0)), ("RightFoot", 20, (-9.5, -89.6, 0.0)), ("RightToeBase", 21, (-9.5, -95.4, 16.1)),
    ("LeftUpLeg", 0, (9.5, -2.8, 0.0)), ("LeftLeg", 23, (9.5, -44.0, 0.0)), ("LeftFoot", 24, (9.5, -89.6, 0.0)), ("LeftToeBase", 25, (9.5, -95.4, 16.1)),
]  # fmt: skip


def core_bvh(path: Path, frames: int) -> None:
    """Um clipe como o script do ARDY grava: pose T andando para frente a 0,4 m/s. ``frames`` são
    os do ARDY (20 por segundo); o arquivo sai a 30."""
    frames = (30 * frames + 10) // 20
    lines, order = ["HIERARCHY"], []

    def write(j: int, depth: int) -> None:
        name, parent, rest = CORE[j]
        pad = "\t" * depth
        order.append(j)
        offset = [a - b for a, b in zip(rest, CORE[parent][2])] if parent >= 0 else [0.0, 0.0, 0.0]
        lines.extend([f"{pad}{'JOINT' if parent >= 0 else 'ROOT'} {name}", pad + "{", f"{pad}\tOFFSET " + " ".join(f"{v:.4f}" for v in offset)])
        lines.append(f"{pad}\tCHANNELS " + ("3 " if parent >= 0 else "6 Xposition Yposition Zposition ") + "Zrotation Yrotation Xrotation")
        children = [k for k, (_, p, _) in enumerate(CORE) if p == j]
        for child in children:
            write(child, depth + 1)
        if not children:
            lines.extend([f"{pad}\tEnd Site", f"{pad}\t{{", f"{pad}\t\tOFFSET 0 0 0", f"{pad}\t}}"])
        lines.append(pad + "}")

    write(0, 0)
    lines += ["MOTION", f"Frames: {frames}", "Frame Time: 0.03333333"]
    lines += [" ".join(["0.0", "95.4", f"{t * 40.0 / 30.0:.3f}"] + ["0.0"] * (3 * len(CORE))) for t in range(frames)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(tempfile.mkdtemp(prefix="ponte-ardy-"))
    os.environ["PONTE_DATA"] = str(work / "data")

    from ponte import ardy, blender, engines, kimodo, pipeline, store

    problems: list[str] = []
    calls: list[dict] = []  # o que o "ARDY" recebeu, pedido a pedido
    encoder: list[str] = []  # o que aconteceu com o codificador de texto
    slots: list[int] = []
    known: set[str] = set()  # textos já codificados
    state = {"encoder": False}

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

    def fake_run(args: list, _log) -> None:
        """No lugar de ardy_scripts/gerar.py rodando no Ubuntu."""
        args = [str(a) for a in args]
        if args[0] == "--sessoes":
            Path(args[1]).write_text(json.dumps({"folder": "/home/x/ardy/.cache/export", "sessions": [{"file": "session_teste.pkl", "modified": "2026-10-09T12:00:00-03:00", "frames": 60, "fps": 20.0, "seconds": 3.0, "joints": 27, "prompts": ["A person is walking.", "A person is standing."]}]}), encoding="utf-8")
            return
        if args[0] == "--sessao":
            folder = Path(args[2])
            core_bvh(folder / "sessao.bvh", 60)
            (folder / "sessao.npz").write_text(json.dumps({"frames": 60}), encoding="utf-8")
            info = {"file": args[1], "exported_at": "2026-10-09T12:00:00", "frames": 60, "fps": 20.0, "seconds": [0.0, 3.0], "continuable": True, "steps": [{"text": "A person is walking.", "start_frame": 0}, {"text": "A person is standing.", "start_frame": 40}]}
            (folder / "sessao.json").write_text(json.dumps(info), encoding="utf-8")
            calls.append({"session": args[1], "options": args[3:]})
            return
        job_path = Path(args[0])
        job = json.loads(job_path.read_text(encoding="utf-8"))
        texts = [s["text"] for t in job["takes"] for s in t["steps"]]
        if "--textos" in args:
            (job_path.parent / "textos.json").write_text(json.dumps({"missing": [t for t in texts if t not in known]}), encoding="utf-8")
            return
        if "--codificar" in args:
            expect(state["encoder"], "o ARDY foi chamado para codificar com o codificador de texto fora do ar")
            known.update(texts)
            encoder.append("codificou")
            return
        if "--dry-run" not in args:
            expect(all(t in known for t in texts), "o ARDY foi chamado para gerar com texto ainda não codificado")
        outputs = []
        for take in job["takes"]:
            before = json.loads((job_path.parent / take["continue_from"]).read_text(encoding="utf-8"))["frames"] if take.get("continue_from") else 0
            marks, total = [], before
            for s in take["steps"]:
                marks.append(total)
                total += round(s["seconds"] * 20)
            calls.append({"seed": take["seed"], "texts": [s["text"] for s in take["steps"]], "continued": before, "dry": "--dry-run" in args, "loop": [bool(s.get("loop")) for s in take["steps"]]})
            for i in range(int(take.get("samples", 1))):
                stem = f"{take['name']}_{i:02d}"
                core_bvh(job_path.parent / f"{stem}.bvh", total)
                (job_path.parent / f"{stem}.npz").write_text(json.dumps({"frames": total}), encoding="utf-8")
                outputs.append({"take": take["name"], "sample": i + 1, "stem": stem, "frames": total, "step_frames": marks})
        (job_path.parent / "result.json").write_text(json.dumps({"fps": 20.0, "outputs": outputs}), encoding="utf-8")

    def fake_start(_log) -> None:
        if state["encoder"]:
            return
        trouble = ardy.encoder_blocker()
        if trouble:
            raise kimodo.KimodoError(trouble)
        state["encoder"] = True
        encoder.append("subiu")

    def fake_kill() -> None:
        state["encoder"] = False
        encoder.append("desligou")

    @contextmanager
    def counted_slots(count: int, _log):
        slots.append(count)
        yield

    real = (ardy._run, ardy.missing, ardy.encoder_ready, ardy.start_encoder, ardy._kill_encoder, ardy._demo_open, ardy._unreal_open, ardy._free_ram_gb, kimodo.generation_slots, engines.problem)
    ardy._run, ardy.encoder_ready, ardy.start_encoder, ardy._kill_encoder = fake_run, lambda timeout=1.5: state["encoder"], fake_start, fake_kill
    ardy._demo_open, ardy._unreal_open, ardy._free_ram_gb, kimodo.generation_slots = lambda: False, lambda: False, lambda: 24.0, counted_slots
    try:
        # 1) Desinstalado, a ponte diz o motivo; instalado, aparece entre os geradores sem nada desligado.
        ardy.missing = lambda: ["o ARDY no Ubuntu"]
        expect(bool(engines.problem("ardy")) and refused(lambda: engines.choose("ardy")), "deixou escolher o ARDY sem ele estar instalado")
        ardy.missing = lambda: []
        engines.problem = lambda _engine: None
        option = next(o for o in engines.status()["options"] if o["id"] == "ardy")
        expect(option["lacks"] == [] and [o["id"] for o in engines.status()["options"]] == ["kimodo", "cpp", "ardy"], "a interface não recebe o ARDY como terceiro gerador, com laço, caminho e força do gesto")
        expect((ardy.to_project_frame(40), ardy.to_project_frame(51), ardy.to_project_frame(100)) == (60, 77, 150), "a conta de quadros de 20 para 30 por segundo mudou")
        expect(refused(lambda: ardy.check_script([{"text": "x.", "seconds": 0.2}])) and refused(lambda: ardy.check_script([{"text": "x.", "seconds": 11}])), "aceitou passo fora dos limites do ARDY")

        # 2) Sem memória, ou com a Unreal aberta, o codificador não sobe e o pedido diz por quê.
        ardy._unreal_open = lambda: True
        expect("Unreal" in (ardy.encoder_blocker() or ""), "não avisou que a Unreal está aberta")
        ardy._unreal_open, ardy._free_ram_gb = (lambda: False), (lambda: 8.0)
        expect("8 GB" in (ardy.encoder_blocker() or ""), "não avisou da memória livre")
        expect(refused(lambda: ardy.generate(work / "sem-memoria", [{"name": "motion", "steps": [{"text": "A zombie waves.", "seconds": 2}], "seed": 0}])), "gerou texto novo sem memória para o codificador")
        expect(not any(not c.get("dry") and "texts" in c for c in calls) and encoder == [], f"um pedido recusado chegou a gerar ou a mexer no codificador: {calls}, {encoder}")
        ardy._free_ram_gb = lambda: 24.0
        slots.clear()

        # 3) Pela ponte: passo 1 (texto novo: o codificador sobe, codifica e é desligado).
        engines.choose("ardy")
        rig = work / "boneco.fbx"
        blender.run_script("make_test_rig.py", ["--out", rig, "--pose", "A"], rig.with_suffix(".make.json"))
        asset_id = pipeline.add_asset(rig, "Boneco ARDY", step)["id"]
        a = pipeline.animate(asset_id, [{"text": "stands still", "seconds": 2, "label": "parado"}], premise="A zombie", seed=7, name="Teste", log=step)[0]["motion_id"]
        motion_a = store.get("motion", a)
        expect(encoder == ["subiu", "codificou", "desligou"], f"para texto novo o codificador deveria subir, codificar e ser desligado: {encoder}")
        expect(calls[-1] == {"seed": 7, "texts": ["A zombie stands still."], "continued": 0, "dry": False, "loop": [False]}, f"o ARDY não recebeu o passo 1 como devia: {calls[-1]}")
        expect((motion_a.get("engine"), motion_a.get("source"), motion_a.get("skeleton"), motion_a.get("model")) == ("ardy", "kimodo", "cskel27", ardy.MODEL), f"o passo 1 não ficou registrado como do ARDY: {motion_a.get('engine')}, {motion_a.get('source')}, {motion_a.get('skeleton')}, {motion_a.get('model')}")
        expect((motion_a.get("frames"), motion_a.get("fps"), motion_a.get("diffusion_steps")) == (60, 30.0, ardy.DIFFUSION_STEPS), f"o clipe não foi para 30 quadros por segundo: {motion_a.get('frames')} quadros a {motion_a.get('fps')}, {motion_a.get('diffusion_steps')} passos de difusão")
        expect(90 < (motion_a.get("stand_height") or 0) < 100, f"a altura do quadril do esqueleto do ARDY não foi guardada para o retarget: {motion_a.get('stand_height')}")
        folder = store.folder("motion", a)
        expect(all((folder / name).is_file() for name in ("ardy.bvh", "motion.bvh", "motion.npz")), "faltou arquivo na pasta da animação (ardy.bvh, motion.bvh, motion.npz)")
        head = (folder / "motion.bvh").read_text(encoding="utf-8").partition("MOTION")[0]
        expect(all(f" {name}\n" in head for name in ("Hips", "Chest", "LeftLeg", "LeftShin", "RightArm")) and "LeftUpLeg" not in head, "o motion.bvh não está com os nomes do SOMA")
        preview = store.list_all("result", asset_id)[0]
        expect(preview["motion_id"] == a and preview["stats"]["frames"] == 60 and round(preview["stats"]["fps"]) == 30, f"a prévia do passo 1 não saiu: {preview['stats']['frames']} quadros")
        # 0,4 m/s por 2 s no esqueleto do ARDY; no boneco, a passada acompanha a perna.
        expect(0.3 < preview["stats"]["travel_m"] / (preview["stats"]["scale"] * 100) < 1.0, f"o personagem não andou o que o clipe anda: {preview['stats']['travel_m']} m (escala {preview['stats']['scale']})")

        # 4) O mesmo texto de novo não precisa do codificador; texto novo com ele já no ar não o desliga.
        encoder.clear()
        ardy.generate(work / "de-novo", [{"name": "motion", "steps": [{"text": "A zombie stands still.", "seconds": 2}], "seed": 1}], log=step)
        expect(encoder == [], f"um texto já codificado mexeu no codificador: {encoder}")
        state["encoder"] = True  # o demo ao vivo aberto, ou ligado à mão
        ardy.generate(work / "ja-no-ar", [{"name": "motion", "steps": [{"text": "A zombie looks around.", "seconds": 2}], "seed": 1}], log=step)
        expect(encoder == ["codificou"] and state["encoder"], f"o codificador que já estava no ar foi desligado pelo pedido: {encoder}")
        state["encoder"] = False
        encoder.clear()

        # 5) Continuando: o ARDY recebe só o passo novo e o clipe de onde ele parte.
        b = pipeline.animate(asset_id, [{"text": "walks forward", "seconds": 3, "loop": True, "travel": {"direction_deg": 0.0, "speed": 0.5, "lock_facing": True}}], premise="A zombie", continue_from=a, seed=99, log=step)[0]["motion_id"]
        motion_b = store.get("motion", b)
        expect(calls[-1] == {"seed": 99, "texts": ["A zombie walks forward."], "continued": 40, "dry": False, "loop": [True]}, f"a continuação não levou só o passo novo e o clipe anterior: {calls[-1]}")
        expect([(s["text"], s["start_frame"], s.get("label")) for s in motion_b["steps"]] == [("A zombie stands still.", 0, "parado"), ("A zombie walks forward.", 60, None)] and motion_b["frames"] == 150, f"o clipe novo não traz os dois passos, cada um no seu quadro: {motion_b['steps']}, {motion_b['frames']} quadros")
        expect(motion_b.get("continued_from") == a and motion_b.get("name") == "Teste" and sorted(p["id"] for p in store.list_all("result", asset_id)) == [b], "a continuação não tomou o lugar da prévia do passo 1")

        # 6) Um gerador não continua o clipe do outro; a vaga é a do Kimodo, uma vez por geração.
        before = len(calls)
        expect(refused(lambda: pipeline.animate(asset_id, [{"text": "turns", "seconds": 2}], continue_from=b, engine="kimodo", log=step)), "o Kimodo original aceitou continuar um clipe do ARDY")
        expect(refused(lambda: pipeline.animate(asset_id, [{"text": "turns", "seconds": 12}], continue_from=b, log=step)), "o ARDY aceitou um passo de 12 s")
        expect(len(calls) == before, "um pedido recusado chegou a gerar")
        expect(slots == [1, 1, 1, 1], f"cada geração do ARDY deveria ocupar a vaga única do Kimodo, uma vez: {slots}")

        # 7) Conferir o roteiro sem gerar não codifica texto nem sobe o codificador.
        encoder.clear()
        dry =ardy.generate(work / "seco", [{"name": "motion", "steps": [{"text": "Never seen.", "seconds": 2}, {"text": "Never seen either.", "seconds": 3}], "seed": 0}], dry_run=True)
        expect(encoder == [] and calls[-1]["dry"] and dry[0]["frames"] == 150 and dry[0]["step_frames"] == [0, 60], f"o ensaio a seco não deu os quadros do roteiro: {dry[0]['frames']}, {dry[0]['step_frames']}, {encoder}")

        # 8) Uma sessão do demo ao vivo vira roteiro do projeto, e dá para continuar dela.
        found = ardy.sessions()["sessions"]
        expect([s["file"] for s in found] == ["session_teste.pkl"], f"a lista de sessões não chegou: {found}")
        s_preview = pipeline.import_ardy_session(asset_id, "/qualquer/pasta/session_teste.pkl", start=1.0, log=step)
        session = store.get("motion", s_preview["motion_id"])
        expect(calls[-1] == {"session": "session_teste.pkl", "options": ["--inicio", "1.0"]}, f"a sessão não foi pedida pelo nome do arquivo, com o recorte: {calls[-1]}")
        expect((session.get("engine"), session.get("source"), session.get("name"), session.get("frames")) == ("ardy", "kimodo", "session_teste", 90), f"a sessão não virou um roteiro do ARDY: {session.get('engine')}, {session.get('source')}, {session.get('name')}, {session.get('frames')}")
        expect([(s["text"], s["start_frame"], s["seconds"]) for s in session["steps"]] == [("A person is walking.", 0, 2.0), ("A person is standing.", 60, 1.0)], f"os textos da sessão não viraram passos: {session['steps']}")
        expect(session.get("session", {}).get("file") == "session_teste.pkl" and (store.folder("motion", session["id"]) / "motion.npz").is_file(), "a sessão não guardou de que arquivo veio, ou de onde continuar")
        c = pipeline.animate(asset_id, [{"text": "A person is standing", "seconds": 2}], continue_from=session["id"], log=step)[0]["motion_id"]
        expect(calls[-1]["continued"] == 60 and len(store.get("motion", c)["steps"]) == 3, f"não deu para continuar da sessão: {calls[-1]}")
    finally:
        ardy._run, ardy.missing, ardy.encoder_ready, ardy.start_encoder, ardy._kill_encoder, ardy._demo_open, ardy._unreal_open, ardy._free_ram_gb, kimodo.generation_slots, engines.problem = real
        shutil.rmtree(work, ignore_errors=True)
    print(("FALHA " + "; ".join(problems)) if problems else "ok    ARDY: o clipe entra convertido, o codificador só sobe para texto novo, continua do clipe gravado e divide a vaga com o Kimodo")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
