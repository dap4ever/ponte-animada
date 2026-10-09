"""Captura de movimento em BVH, de outro esqueleto, aplicada num personagem: tem de sair o mesmo movimento.

Sem arquivo de captura à mão, o teste fabrica um a partir da caminhada de referência do
Kimodo: só o corpo, os ossos com o nome da junta em que começam (como no XSens), em metros,
com Z para cima, a 60 quadros por segundo, o ator virado para outro lado e longe da origem, e
um tempo parado antes e depois. Convertido de volta e aplicado num boneco, tem de dar o mesmo
movimento que a caminhada do Kimodo aplicada direto nele.

Depois, num acervo descartável (PONTE_DATA), a captura é importada como na CLI, pedindo o
laço: vira uma ação do personagem que fecha de verdade, anda em frente e sai no resultado.

    uv run python tests/check_capture.py
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BVH = ROOT / "tests" / "fixtures" / "kimodo_walk_forward.bvh"
PAD, SECONDS = 1.5, 149 / 30  # o tempo parado e a duração da caminhada dentro da captura fabricada
# Ossos do corpo, fora o quadril: a rotação deles não depende de para onde o clipe está virado.
BONES = ("mixamorig:Spine1", "mixamorig:Head", "mixamorig:LeftArm", "mixamorig:RightForeArm", "mixamorig:LeftUpLeg", "mixamorig:RightLeg", "mixamorig:LeftFoot")


def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    json_len = struct.unpack_from("<I", data, 12)[0]
    bin_start = 20 + json_len
    return json.loads(data[20:bin_start]), data[bin_start + 8 : bin_start + 8 + struct.unpack_from("<I", data, bin_start)[0]]


def rotations(gltf: dict, blob: bytes, bone: str) -> list[tuple[float, ...]] | None:
    """As rotações do osso ``bone`` na animação do GLB, um quaternion por quadro."""
    animation = gltf["animations"][0]
    for ch in animation["channels"]:
        if gltf["nodes"][ch["target"]["node"]].get("name") == bone and ch["target"]["path"] == "rotation":
            acc = gltf["accessors"][animation["samplers"][ch["sampler"]]["output"]]
            view = gltf["bufferViews"][acc["bufferView"]]
            start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = view.get("byteStride") or 16
            return [struct.unpack_from("<4f", blob, start + i * stride) for i in range(acc["count"])]
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(tempfile.mkdtemp(prefix="ponte-captura-"))
    os.environ["PONTE_DATA"] = str(work / "data")

    from ponte import blender, pipeline, store
    from ponte.config import BLENDER_SCRIPTS, SETTINGS

    problems: list[str] = []
    try:
        rig = work / "alvo.blend"
        blender.run_script("make_test_rig.py", ["--out", rig, "--pose", "A", "--fbx-like"], rig.with_suffix(".make.json"))
        made = work / "captura.bvh"
        blender.run_script("make_test_capture.py", ["--bvh", BVH, "--out", made, "--yaw", "100", "--pad", PAD, "--z-up"], made.with_suffix(".make.json"))

        # 1) O recorte inteiro, sem laço: o mesmo movimento do arquivo do Kimodo.
        converted = work / "convertida" / "motion.bvh"
        info = blender.run_script("import_capture.py", ["--bvh", made, "--out", converted, "--start", PAD, "--end", PAD + SECONDS], converted.with_name("captura.json"))
        if (info["frames"], info["fps"], info["source"]["unit"], info["loop"]) != (150, 30.0, "m", None):
            problems.append(f"a conversão não deu 150 quadros a 30 por segundo, lidos em metros: {info['frames']}, {info['fps']}, {info['source']['unit']}")
        if abs(info["source"]["fps"] - 60) > 0.01 or info["source"]["seconds"] != [PAD, round(PAD + SECONDS, 3)]:
            problems.append(f"o trecho usado do arquivo não é o pedido: {info['source']}")

        direct, via = work / "direto", work / "pela_captura"
        stats_direct = blender.run_script("retarget_motion.py", ["--asset", rig, "--bvh", BVH, "--out-dir", direct, "--no-fbx", "--no-blend"], direct / "retarget.json")["stats"]
        stats_via = blender.run_script(
            "retarget_motion.py", ["--asset", rig, "--bvh", converted, "--stand-height", info["stand_height"], "--out-dir", via, "--no-fbx", "--no-blend"], via / "retarget.json"
        )["stats"]
        if stats_via["frames"] != stats_direct["frames"]:
            problems.append(f"{stats_via['frames']} quadros pela captura, {stats_direct['frames']} direto")
        if stats_via["check"]["rotation_error_deg"] > 0.1:
            problems.append(f"erro de rotação {stats_via['check']['rotation_error_deg']}°")
        if abs(stats_via["travel_m"] - stats_direct["travel_m"]) > 0.03:
            problems.append(f"percorreu {stats_via['travel_m']} m pela captura e {stats_direct['travel_m']} m direto")
        if abs(stats_via["scale"] / stats_direct["scale"] - 1) > 0.03:
            problems.append(f"escala {stats_via['scale']} pela captura e {stats_direct['scale']} direto")
        if not all(foot["contact_seconds"] > 0.5 for foot in stats_via["feet"].values()):
            problems.append(f"não achou os pés no chão na captura: {stats_via['feet']}")

        gltf_d, blob_d = read_glb(direct / "result.glb")
        gltf_v, blob_v = read_glb(via / "result.glb")
        worst = 0.0
        for bone in BONES:
            a, b = rotations(gltf_d, blob_d, bone), rotations(gltf_v, blob_v, bone)
            if a is None or b is None or len(a) != len(b):
                problems.append(f"canal de rotação de {bone} ausente ou de outro tamanho")
                continue
            # q e -q são a mesma rotação.
            worst = max(worst, max(min(max(abs(x - y) for x, y in zip(qa, qb)), max(abs(x + y) for x, y in zip(qa, qb))) for qa, qb in zip(a, b)))
        print(f"  maior diferença para o caminho direto: {worst:.5f} (componente do quaternion); escala {stats_via['scale']} contra {stats_direct['scale']}")
        if worst > 0.01:
            problems.append(f"as rotações diferem do caminho direto em {worst:.4f}")

        # 2) Como na CLI, pedindo o laço: vira uma ação que fecha, anda em frente e sai no resultado.
        asset_id = pipeline.add_asset(rig, "Boneco captura")["id"]
        preview = pipeline.import_capture(asset_id, made, "Andar de captura", "Walk FW.bvh", start=PAD, end=PAD + SECONDS, loop=True, credit="Conjunto de teste", log=lambda line: print(f"  · {line}"))
        motion = store.get("motion", preview["motion_id"])
        steps = motion.get("steps") or []
        found = (motion.get("capture") or {}).get("loop") or {}
        if (motion.get("source"), motion.get("name"), motion.get("credit")) != ("captura", "Andar de captura", "Conjunto de teste"):
            problems.append(f"a captura não ficou registrada como tal, com nome e crédito: {motion.get('source')!r}, {motion.get('name')!r}, {motion.get('credit')!r}")
        if len(steps) != 1 or steps[0].get("label") != "Andar de captura" or not steps[0].get("star") or not steps[0].get("loop") or steps[0].get("start_frame") != 0:
            problems.append(f"a captura não virou uma ação principal em laço, de um passo só: {steps}")
        if not 0.6 <= found.get("seconds", 0) <= 4.0 or found.get("direction_deg") != 0.0:
            problems.append(f"o laço achado não é uma passada para frente: {found}")
        elif motion.get("frames") != round(found["seconds"] * 30) + 1 or preview["stats"]["frames"] != motion["frames"]:
            problems.append(f"a duração da ação não é a do laço: {motion.get('frames')} quadros para {found['seconds']} s")
        folder = store.folder("motion", motion["id"])
        if not (folder / "captura.bvh").is_file() or not (folder / "motion.bvh").is_file():
            problems.append("o arquivo da captura e o convertido não ficaram os dois na pasta da animação")
        if preview["stats"]["check"]["rotation_error_deg"] > 0.1 or sorted(preview["files"]) != ["blend", "glb"]:
            problems.append(f"a prévia da captura não saiu como as outras: {preview['stats']['check']}, {sorted(preview['files'])}")

        # A emenda, medida no BVH convertido pela mesma ferramenta que confere os laços do Kimodo.
        proc = subprocess.run(
            [SETTINGS.blender_exe, "--background", "--factory-startup", "--python", str(BLENDER_SCRIPTS / "step_stats.py"), "--", str(folder)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )  # fmt: skip
        rows = [json.loads(line[5:]) for line in proc.stdout.splitlines() if line.startswith("STEP ")]
        seam = rows[0].get("laco") if rows else None
        if not seam:
            problems.append("step_stats não mediu o laço da captura")
        else:
            print(f"  laço de {found.get('seconds')} s: emenda {seam['emenda_pior_junta_cm']} cm, fecha deslocado {seam['fecha_deslocado_m']} m")
            if seam["emenda_pior_junta_cm"] > 0.01:
                problems.append(f"o laço não fecha: {seam['emenda_pior_junta_cm']} cm na pior junta")
            if abs(seam["fecha_deslocado_m"][0]) > 0.005 or seam["fecha_deslocado_m"][1] < 0.3:
                problems.append(f"o laço não anda reto para frente: fecha deslocado {seam['fecha_deslocado_m']} m")

        final = pipeline.close_project(asset_id)["final"]
        if [c["name"] for c in final["clips"]] != ["andar_de_captura"] or final["clips"][0]["frames"] != motion["frames"]:
            problems.append(f"o resultado não traz a captura como clipe: {final['clips']}")
        for wrong, kwargs in ((BVH.with_suffix(".fbx"), {}), (made, {"direction": "para-cima"})):
            try:
                pipeline.import_capture(asset_id, wrong, None, **kwargs)
                problems.append(f"aceitou importar como captura o que não devia: {wrong.name} {kwargs}")
            except ValueError:
                pass
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(("FALHA " + "; ".join(problems)) if problems else "ok    captura em BVH: mesmo movimento do caminho direto, laço fechado, vira ação e sai no resultado")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
