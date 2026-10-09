"""O arquivo para a Unreal 5: o personagem no esqueleto do Mannequin, com as mesmas animações.

Monta um acervo descartável (PONTE_DATA) com o boneco de teste (com uma arma na mão) e outro
com a armature em 0,01, como vem do Mixamo. Liga a opção, encerra e confere:

- sem a opção, o resultado sai como sempre, sem a pasta unreal5;
- ligar ou desligar a opção marca o resultado como desatualizado;
- o FBX sai em resultado/unreal5/, com os ossos do Mannequin (root, pelvis, spine_01...), sem
  os do Mixamo, e um clipe por prévia, com a mesma duração;
- a malha e as juntas ficam onde estavam (a conferência é do próprio Blender, na conversão);
- o arquivo está em centímetros, sem escala em objeto, e com a pose de vinculação exata: é o
  que faz a Unreal aceitar a pose de descanso e não pôr escala no osso raiz.

Com --engine, importa o FBX na Unreal de verdade, num projeto de rascunho, e confere que ela
aceita: sem aviso de pose inválida, `root` com escala 1, e o personagem serve no SK_Mannequin.

    uv run python tests/check_unreal.py [--engine <UnrealEditor-Cmd.exe>] [--keep <pasta>]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WALK = ROOT / "tests" / "fixtures" / "kimodo_walk_forward.bvh"
MANNEQUIN = ("Templates", "TemplateResources", "High", "Characters", "Content", "Mannequins")


def engine_import(engine: Path, work: Path, files: dict[str, Path]) -> dict:
    """Importa cada FBX num projeto de rascunho da Unreal, sozinho e sobre o SK_Mannequin. Devolve o relatório."""
    project = work / "unreal"
    source = engine.parents[3].joinpath(*MANNEQUIN)
    for folder in ("Meshes", "Materials"):
        shutil.copytree(source / folder, project / "Content" / "Characters" / "Mannequins" / folder, dirs_exist_ok=True)
    (project / "Rascunho.uproject").write_text(json.dumps({"FileVersion": 3, "EngineAssociation": "", "Plugins": [{"Name": "PythonScriptPlugin", "Enabled": True}]}), encoding="ascii")
    steps = []
    for name, path in files.items():
        steps.append({"do": "import", "file": str(path), "dest": f"/Game/Ponte/{name}"})
        steps.append({"do": "import", "file": str(path), "dest": f"/Game/Ponte/{name}_Mannequin", "skeleton": "/Game/Characters/Mannequins/Meshes/SK_Mannequin"})
    job = work / "unreal-job.json"
    job.write_text(json.dumps({"report": str(work / "unreal-report.json"), "steps": steps}), encoding="utf-8")
    log = work / "unreal.log"
    subprocess.run(
        [str(engine), str(project / "Rascunho.uproject"), "-run=pythonscript", f"-script={ROOT / 'tests' / 'ue_import.py'}", "-unattended", "-nosplash", "-nopause", "-nullrhi", "-nosound", f"-abslog={log}"],
        env={**os.environ, "PONTE_UE_JOB": str(job)},
        capture_output=True,
        timeout=900,
    )
    if not (work / "unreal-report.json").is_file():
        return {"steps": [], "log": log.read_text(encoding="utf-8", errors="replace")[-2000:] if log.is_file() else "a Unreal não gravou log"}
    report = json.loads((work / "unreal-report.json").read_text(encoding="utf-8"))
    report["log"] = log.read_text(encoding="utf-8", errors="replace")
    return report


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", type=Path, help="UnrealEditor-Cmd.exe: importa o FBX na Unreal de verdade")
    ap.add_argument("--keep", type=Path, help="deixa o acervo de teste nesta pasta")
    args = ap.parse_args()
    work = args.keep.resolve() if args.keep else Path(tempfile.mkdtemp(prefix="ponte-unreal-"))
    if args.keep:
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    os.environ["PONTE_DATA"] = str(work / "data")

    from ponte import blender, pipeline, server, store

    problems: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    def step(text: str) -> None:
        print(f"  · {text}", flush=True)

    def shown(asset_id: str) -> dict:
        return next(a for a in server.state()["assets"] if a["id"] == asset_id)

    try:
        # O boneco de sempre, com uma arma na mão e três prévias.
        rig = work / "boneco.fbx"
        blender.run_script("make_test_rig.py", ["--out", rig, "--pose", "A"], rig.with_suffix(".make.json"))
        boneco = pipeline.add_asset(rig, "Boneco Ação", step)["id"]
        prop_file = work / "fuzil.glb"
        blender.run_script("make_test_prop.py", ["--out", prop_file], prop_file.with_suffix(".make.json"))
        prop, prop_target = pipeline.create_prop(boneco, prop_file.name)
        shutil.copy2(prop_file, prop_target)
        pipeline.convert_prop(boneco, prop["id"], step)
        pipeline.place_prop(boneco, prop["id"], "mixamorig:RightHand", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0.03, 0.09, -0.04, 1])
        walk = pipeline.import_motion(boneco, WALK, "walk forward")["id"]
        previews = [pipeline.retarget(boneco, walk, log=step), pipeline.retarget(boneco, walk, in_place=True, log=step)]

        # Sem a opção: nada muda.
        final = pipeline.close_project(boneco, step)["final"]
        folder = store.final_folder(boneco)
        expect("unreal" not in final and sorted(p.name for p in folder.iterdir()) == sorted(final["files"].values()), f"sem a opção o resultado deveria sair como sempre: {sorted(p.name for p in folder.iterdir())}")
        expect(shown(boneco)["final"]["stale"] is False, "resultado recém-encerrado apareceu como desatualizado")

        # Ligar a opção pede outro encerramento.
        pipeline.set_unreal(boneco, True)
        expect(shown(boneco).get("unreal") is True and shown(boneco)["final"]["stale"] is True, "ligar a Unreal 5 deveria marcar o resultado como desatualizado")
        final = pipeline.close_project(boneco, step)["final"]
        unreal = final.get("unreal") or {}
        fbx = folder / unreal.get("file", "falta")
        expect(unreal.get("file") == "unreal5/SK_boneco_acao.fbx" and fbx.is_file(), f"arquivo da Unreal 5: {unreal.get('file')}")
        expect(sorted(p.name for p in folder.iterdir()) == sorted([*final["files"].values(), "unreal5"]), f"na pasta do resultado: {sorted(p.name for p in folder.iterdir())}")
        expect(shown(boneco)["final"]["stale"] is False, "depois de encerrar com a opção o resultado deveria estar em dia")
        check = unreal.get("check") or {}
        expect(check.get("vertex_error_cm", 9) < 0.01 and check.get("joint_error_cm", 9) < 0.01, f"a malha ou as juntas saíram do lugar na conversão: {check}")

        # O FBX, reaberto no Blender: o esqueleto do Mannequin e os mesmos clipes.
        files = {"Boneco": fbx}
        report = blender.run_script("check_unreal_fbx.py", ["--input", fbx, "--out", work / "confere-boneco.json"], work / "confere-boneco.json")
        bones = set(report["bones"])
        wanted = {"root", "pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "neck_01", "neck_02", "head", "clavicle_l", "upperarm_l", "lowerarm_l", "hand_l", "thigh_r", "calf_r", "foot_r", "ball_r", "index_metacarpal_l", "index_01_l", "thumb_03_r", "ik_foot_root", "ik_foot_l", "ik_hand_gun"}
        expect(wanted <= bones, f"faltam ossos do Mannequin: {sorted(wanted - bones)}")
        expect(not [b for b in bones if "mixamorig" in b.lower()], f"sobraram ossos do Mixamo: {[b for b in bones if 'mixamorig' in b.lower()][:5]}")
        expect(report["parents"].get("pelvis") == "root" and report["parents"].get("index_01_l") == "index_metacarpal_l" and report["parents"].get("clavicle_r") == "spine_05", f"hierarquia: {[(b, report['parents'].get(b)) for b in ('pelvis', 'index_01_l', 'clavicle_r')]}")
        for clip in final["clips"]:
            found = [a for a in report["animations"] if a["name"].split("|")[-1] == "_" + clip["name"]]
            expect(len(found) == 1 and abs(found[0]["frames"] - clip["frames"]) <= 1, f"clipe {clip['name']} ({clip['frames']} quadros) não bate com {report['animations']}")
        expect(len(report["animations"]) == len(final["clips"]), f"{len(report['animations'])} animação(ões) no FBX, esperava {len(final['clips'])}")
        # Em centímetros, sem escala em objeto, e com a pose de vinculação exata.
        expect(85 < report["pelvis_height"] < 95, f"o quadril deveria estar a ~90 (centímetros) do chão: {report['pelvis_height']}")
        expect(report["scaled_nodes"] == [], f"armature ou malha com escala no FBX: {report['scaled_nodes']}")
        expect(report["bind_pose_error"] < 1e-9, f"pose de vinculação com ruído ({report['bind_pose_error']:.1e}): a Unreal a descartaria")
        expect(report["attached"].get(f"PROP_{prop['id']}") == "hand_r", f"a arma deveria estar presa a hand_r: {report['attached']}")

        # Desligar tira o arquivo no encerramento seguinte.
        pipeline.set_unreal(boneco, False)
        expect(shown(boneco)["final"]["stale"] is True, "desligar a Unreal 5 deveria marcar o resultado como desatualizado")
        final = pipeline.close_project(boneco, step)["final"]
        expect("unreal" not in final and not fbx.exists(), "desligada a opção, o arquivo da Unreal 5 deveria sair do resultado")
        pipeline.set_unreal(boneco, True)
        pipeline.close_project(boneco, step)

        # Outro personagem, com a armature em 0,01 (como todo modelo que vem do Mixamo).
        rig_blend = work / "rigado.blend"
        blender.run_script("make_test_rig.py", ["--out", rig_blend, "--pose", "A", "--fbx-like"], rig_blend.with_suffix(".make.json"))
        heroi = pipeline.add_asset(rig_blend, "Herói", step)["id"]
        pipeline.retarget(heroi, pipeline.import_motion(heroi, WALK, "walk forward")["id"], log=step)
        pipeline.set_unreal(heroi, True)
        final = pipeline.close_project(heroi, step)["final"]
        other = store.final_folder(heroi) / final["unreal"]["file"]
        files["Heroi"] = other
        report = blender.run_script("check_unreal_fbx.py", ["--input", other, "--out", work / "confere-heroi.json"], work / "confere-heroi.json")
        expect(final["unreal"]["file"] == "unreal5/SK_heroi.fbx" and wanted <= set(report["bones"]), "o personagem com armature em 0,01 não saiu no esqueleto do Mannequin")
        expect(final["unreal"]["check"]["vertex_error_cm"] < 0.01 and report["scaled_nodes"] == [] and report["bind_pose_error"] < 1e-9 and 85 < report["pelvis_height"] < 95, f"armature em 0,01: {final['unreal']['check']}, escala {report['scaled_nodes']}, pose {report['bind_pose_error']:.1e}, quadril {report['pelvis_height']}")

        if args.engine:
            step("importando na Unreal (projeto de rascunho, sem interface)")
            out = engine_import(args.engine, work, files)
            log = out.get("log", "")
            expect(len(out["steps"]) == 2 * len(files), f"a Unreal não importou tudo: {log[-600:]}")
            expect("invalid bind pose" not in log.lower() and "poses de vinculação inválidas" not in log, "a Unreal descartou a pose de descanso (aviso de pose de vinculação inválida)")
            for entry in out["steps"]:
                if entry.get("error"):
                    problems.append(f"Unreal, {entry['dest']}: {entry['error'][-300:]}")
                    continue
                assets = entry["result"]["assets"]
                meshes = [a for a in assets if a["class"] == "SkeletalMesh"]
                anims = [a for a in assets if a["class"] == "AnimSequence"]
                expect(len(meshes) == 1 and len(anims) >= 1, f"Unreal, {entry['dest']}: {len(meshes)} malha(s) e {len(anims)} animação(ões)")
                if entry.get("skeleton"):
                    expect(all(str(a.get("skeleton", "")).endswith("SK_Mannequin") for a in meshes + anims), f"Unreal, {entry['dest']}: o personagem não foi aceito no SK_Mannequin")
                    continue
                skeleton = next((a for a in assets if a["class"] == "Skeleton"), {}).get("skeleton_info") or {}
                first = {b["name"]: b for b in skeleton.get("first", [])}
                expect(skeleton.get("names", [None])[0] == "root" and "pelvis" in skeleton.get("names", []), f"Unreal, {entry['dest']}: ossos {skeleton.get('names', [])[:4]}")
                expect(all(abs(v - 1) < 1e-3 for v in first.get("root", {}).get("local", {}).get("scale", [0])), f"Unreal, {entry['dest']}: escala do root {first.get('root')}")
                height = first.get("pelvis", {}).get("local", {}).get("loc", [0, 0, 0])[2]
                expect(abs(height - 90) < 0.5, f"Unreal, {entry['dest']}: o quadril em descanso deveria estar a 90 cm, está a {height}")

        # Quando a conversão não dá (aqui, um mapeamento sem a cabeça), o resultado de sempre sai, com o aviso.
        store.write_json(store.folder("asset", heroi) / "mapping.json", {"slots": {"head": None}})
        final = pipeline.close_project(heroi, step)["final"]
        expect(
            "unreal" not in final and any("Unreal 5" in w for w in final["warnings"]) and (store.final_folder(heroi) / final["files"]["glb"]).is_file() and not other.exists(),
            f"conversão impossível deveria virar aviso, com o resultado normal de pé: {final.get('unreal')}, {final['warnings']}",
        )
        if args.keep:
            print(f"  acervo mantido em {work / 'data'}")
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    print(("FALHA " + "; ".join(problems)) if problems else "ok    unreal 5: esqueleto do Mannequin, mesmas animações" + (", aceito pela Unreal" if args.engine else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
