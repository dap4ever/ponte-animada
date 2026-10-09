"""Animação pronta em FBX (as do Mixamo) aplicada num personagem: tem de sair o mesmo movimento.

Sem arquivo do Mixamo à mão, o teste fabrica um: aplica a caminhada de referência do Kimodo
num boneco em T-pose e exporta em FBX. Esse FBX é uma animação num esqueleto com os nomes do
Mixamo, com malha junto, como a que se baixa de lá. Depois ele é aplicado em outro boneco
(A-pose, com a transformação típica de FBX importado) e o resultado é comparado, osso a osso,
com a mesma caminhada aplicada direto do Kimodo nesse segundo boneco. Os dois caminhos têm de
dar o mesmo movimento, e nada do arquivo da animação pode ficar na prévia.

Depois, num acervo descartável (PONTE_DATA), o mesmo FBX é importado como o usuário importa:
vira uma ação do personagem, com nome, e sai no resultado quando o personagem é encerrado.

    uv run python tests/check_mixamo.py
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BVH = ROOT / "tests" / "fixtures" / "kimodo_walk_forward.bvh"
BONES = ("mixamorig:Hips", "mixamorig:Spine1", "mixamorig:Head", "mixamorig:LeftArm", "mixamorig:RightForeArm", "mixamorig:LeftUpLeg", "mixamorig:RightLeg", "mixamorig:LeftFoot")


def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    json_len = struct.unpack_from("<I", data, 12)[0]
    bin_start = 20 + json_len
    return json.loads(data[20:bin_start]), data[bin_start + 8 : bin_start + 8 + struct.unpack_from("<I", data, bin_start)[0]]


def channel(gltf: dict, blob: bytes, bone: str, path: str) -> list[tuple[float, ...]] | None:
    """Os valores do canal ``path`` do osso ``bone`` na animação do GLB."""
    animation = gltf["animations"][0]
    for ch in animation["channels"]:
        if gltf["nodes"][ch["target"]["node"]].get("name") == bone and ch["target"]["path"] == path:
            acc = gltf["accessors"][animation["samplers"][ch["sampler"]]["output"]]
            view = gltf["bufferViews"][acc["bufferView"]]
            size = {"VEC3": 3, "VEC4": 4}[acc["type"]]
            start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = view.get("byteStride") or 4 * size
            return [struct.unpack_from(f"<{size}f", blob, start + i * stride) for i in range(acc["count"])]
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(tempfile.mkdtemp(prefix="ponte-mixamo-"))
    os.environ["PONTE_DATA"] = str(work / "data")

    from ponte import blender, pipeline, store

    problems: list[str] = []
    try:
        source_rig, target_rig = work / "fonte.blend", work / "alvo.blend"
        blender.run_script("make_test_rig.py", ["--out", source_rig, "--pose", "T"], source_rig.with_suffix(".make.json"))
        blender.run_script("make_test_rig.py", ["--out", target_rig, "--pose", "A", "--fbx-like"], target_rig.with_suffix(".make.json"))

        # A "animação do Mixamo": a caminhada no boneco em T-pose, exportada em FBX com a malha.
        made = work / "fabricada"
        blender.run_script("retarget_motion.py", ["--asset", source_rig, "--bvh", BVH, "--out-dir", made, "--no-blend"], made / "retarget.json")
        animation = made / "result.fbx"

        direct, via = work / "direto", work / "pelo_fbx"
        stats_direct = blender.run_script("retarget_motion.py", ["--asset", target_rig, "--bvh", BVH, "--out-dir", direct, "--no-fbx", "--no-blend"], direct / "retarget.json")["stats"]
        stats_via = blender.run_script("retarget_motion.py", ["--asset", target_rig, "--fbx", animation, "--out-dir", via, "--no-fbx", "--no-blend"], via / "retarget.json")["stats"]

        if stats_via["frames"] != stats_direct["frames"]:
            problems.append(f"{stats_via['frames']} quadros pelo FBX, {stats_direct['frames']} direto")
        if stats_via["bones_animated"] != stats_direct["bones_animated"]:
            problems.append(f"{stats_via['bones_animated']} ossos animados pelo FBX, {stats_direct['bones_animated']} direto")
        if stats_via["check"]["rotation_error_deg"] > 0.1:
            problems.append(f"erro de rotação {stats_via['check']['rotation_error_deg']}°")
        if abs(stats_via["travel_m"] - stats_direct["travel_m"]) > 0.02:
            problems.append(f"percorreu {stats_via['travel_m']} m pelo FBX e {stats_direct['travel_m']} m direto")

        gltf_d, blob_d = read_glb(direct / "result.glb")
        gltf_v, blob_v = read_glb(via / "result.glb")
        # Nada do arquivo da animação (o boneco que veio nele) pode ficar na prévia.
        meshes = lambda gltf: sorted(n.get("name", "") for n in gltf["nodes"] if "mesh" in n)  # noqa: E731
        if meshes(gltf_v) != meshes(gltf_d):
            problems.append(f"a prévia pelo FBX tem outras malhas: {meshes(gltf_v)} (direto: {meshes(gltf_d)})")

        worst_rot = worst_pos = 0.0
        for bone in BONES:
            a, b = channel(gltf_d, blob_d, bone, "rotation"), channel(gltf_v, blob_v, bone, "rotation")
            if a is None or b is None or len(a) != len(b):
                problems.append(f"canal de rotação de {bone} ausente ou de outro tamanho")
                continue
            # q e -q são a mesma rotação.
            worst_rot = max(worst_rot, max(min(max(abs(x - y) for x, y in zip(qa, qb)), max(abs(x + y) for x, y in zip(qa, qb))) for qa, qb in zip(a, b)))
        a, b = channel(gltf_d, blob_d, "mixamorig:Hips", "translation"), channel(gltf_v, blob_v, "mixamorig:Hips", "translation")
        if a and b and len(a) == len(b):
            worst_pos = max(max(abs(x - y) for x, y in zip(pa, pb)) for pa, pb in zip(a, b))
        else:
            problems.append("canal de posição do quadril ausente ou de outro tamanho")
        print(f"  maior diferença para o caminho direto: rotação {worst_rot:.4f} (componente do quaternion), quadril {worst_pos:.4f} (unidades do arquivo)")
        if worst_rot > 0.01:
            problems.append(f"as rotações diferem do caminho direto em {worst_rot:.4f}")
        hips_height = max(abs(v) for v in a[0]) if a else 1.0
        if worst_pos > 0.02 * hips_height:
            problems.append(f"a posição do quadril difere do caminho direto em {worst_pos:.4f} ({100 * worst_pos / hips_height:.1f} % da altura dele)")

        # Como o usuário importa: o FBX vira uma ação do personagem e sai no resultado.
        asset_id = pipeline.add_asset(target_rig, "Boneco Mixamo")["id"]
        preview = pipeline.import_mixamo(asset_id, animation, None, "Zombie Idle.fbx", log=lambda line: print(f"  · {line}"))
        motion = store.get("motion", preview["motion_id"])
        steps = motion.get("steps") or []
        if motion.get("source") != "mixamo" or motion.get("name") != "Zombie Idle":
            problems.append(f"a animação importada não ficou como do Mixamo, com o nome do arquivo: {motion.get('source')!r}, {motion.get('name')!r}")
        if len(steps) != 1 or steps[0].get("label") != "Zombie Idle" or not steps[0].get("star") or steps[0].get("start_frame") != 0:
            problems.append(f"a animação importada não virou uma ação principal de um passo só: {steps}")
        elif abs(steps[0]["seconds"] - preview["stats"]["duration_s"]) > 1e-6 or motion.get("frames") != preview["stats"]["frames"]:
            problems.append("a duração da ação não é a da animação do arquivo")
        folder = store.folder("motion", motion["id"])
        if not (folder / "motion.fbx").is_file():
            problems.append("o FBX importado não ficou guardado na pasta da animação")
        if sorted(preview["files"]) != ["blend", "glb"]:
            problems.append(f"a prévia da animação importada não tem os arquivos de sempre: {sorted(preview['files'])}")
        final = pipeline.close_project(asset_id)["final"]
        if [c["name"] for c in final["clips"]] != ["zombie_idle"] or final["clips"][0]["frames"] != preview["stats"]["frames"]:
            problems.append(f"o resultado não traz a animação importada como clipe: {final['clips']}")
        try:
            pipeline.import_mixamo(asset_id, BVH, None, "walk.bvh")
            problems.append("aceitou importar como animação do Mixamo um arquivo que não é FBX")
        except ValueError:
            pass
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(("FALHA " + "; ".join(problems)) if problems else "ok    animação em FBX: mesmo movimento do caminho direto, vira ação e sai no resultado")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
