"""Inspeciona um asset 3D e gera o laudo de validacao + preview GLB.

Uso: blender --background --factory-startup --python inspect_asset.py -- \
        --input <arquivo> --out-dir <pasta> [--mapping <json>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
import numpy as np  # noqa: E402

from ponte_bl import cli, rigmap, scene, textures  # noqa: E402


SOMA_STAND_HEIGHT_M = 1.0079  # quadril do SOMA em pe: 93,8 cm ate o tornozelo + 7,0 cm do tornozelo ao chao


def _issue(issues: list, level: str, code: str, msg: str) -> None:
    issues.append({"level": level, "code": code, "msg": msg})


def _weight_stats(meshes: list, deform_names: set[str]) -> dict:
    unweighted = over4 = max_inf = 0
    for obj in meshes:
        groups = {g.index for g in obj.vertex_groups if g.name in deform_names}
        for v in obj.data.vertices:
            n = sum(1 for g in v.groups if g.group in groups and g.weight > 1e-5)
            unweighted += n == 0
            over4 += n > 4
            max_inf = max(max_inf, n)
    return {"unweighted_vertices": unweighted, "vertices_over_4_influences": over4, "max_influences": max_inf}


def inspect(input_path: Path, out_dir: Path, override: dict | None) -> dict:
    texture_info = scene.import_asset(input_path)
    arm_obj, meshes = scene.find_rig()
    all_meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    armatures = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    issues: list[dict] = []

    report: dict = {
        "file": {"name": input_path.name, "format": input_path.suffix.lower().lstrip("."), "size_bytes": input_path.stat().st_size},
        "blender": bpy.app.version_string,
        "objects": {"meshes": len(all_meshes), "armatures": len(armatures)},
    }

    # --- Malha -------------------------------------------------------------------
    for obj in all_meshes:
        obj.data.calc_loop_triangles()
    images = [i for i in bpy.data.images if i.source == "FILE"]
    missing_images = [
        i.name for i in images if not i.packed_file and not Path(bpy.path.abspath(i.filepath)).exists()
    ]
    materials = textures.used_materials()
    untextured = [m.name for m in materials if not textures.has_base_texture(m)]
    report["mesh"] = {
        "vertices": sum(len(o.data.vertices) for o in all_meshes),
        "triangles": sum(len(o.data.loop_triangles) for o in all_meshes),
        "materials": len(materials),
        "untextured_materials": untextured,
        "images": len(images),
        "missing_images": missing_images,
        "shape_keys": sum(len(o.data.shape_keys.key_blocks) for o in all_meshes if o.data.shape_keys),
    }
    if not all_meshes:
        _issue(issues, "erro", "sem_malha", "O arquivo não tem nenhuma malha.")
    if missing_images:
        _issue(issues, "aviso", "textura_ausente", f"{len(missing_images)} textura(s) que o modelo usa não foram enviadas: {', '.join(missing_images[:4])}. Adicione os arquivos ao personagem.")
    for note in texture_info["notes"]:
        _issue(issues, "info", "textura", note)
    if texture_info["unused_files"]:
        _issue(issues, "aviso", "textura_sem_destino", f"Não soube em qual material aplicar: {', '.join(texture_info['unused_files'][:6])}. Nomeie o arquivo com o nome do material (ex.: Corpo_BaseColor.png).")
    elif untextured and len(untextured) == len(materials) and not missing_images:
        _issue(issues, "info", "sem_textura", "O modelo não traz texturas: aparece só com as cores dos materiais. Se ele tem texturas, envie os arquivos junto ou use Adicionar texturas.")

    bbox = scene.world_bbox(meshes or all_meshes)
    if bbox is not None:
        size = bbox[1] - bbox[0]
        report["dimensions"] = {
            "height_m": round(float(size[2]), 4),
            "width_m": round(float(size[0]), 4),
            "depth_m": round(float(size[1]), 4),
            "floor_z_m": round(float(bbox[0][2]), 4),
        }
        if not 0.3 <= size[2] <= 4.0:
            _issue(issues, "aviso", "escala", f"Altura de {size[2]:.2f} m: fora da faixa de um personagem (0,3–4 m). Confira a unidade na exportação.")
        if abs(bbox[0][2]) > 0.05 * size[2]:
            _issue(issues, "aviso", "fora_do_chao", f"A base da malha está em z = {bbox[0][2]:.2f} m, não no chão (z = 0).")

    # --- Animacoes que ja vieram no arquivo ------------------------------------------
    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    report["animations"] = [
        {"name": a.name, "frames": int(a.frame_range[1] - a.frame_range[0]) + 1, "fps": round(fps, 3)} for a in bpy.data.actions
    ]

    # --- Rig -----------------------------------------------------------------------
    if arm_obj is None:
        report["rig"] = rigmap.detect_rig_type([])
        report["armature"] = None
        report["mapping"] = None
        _issue(issues, "erro", "sem_rig", "Nenhuma armature no arquivo: o personagem precisa ser rigado antes de animar.")
        verdict = "precisa_rig"
    else:
        bones = arm_obj.data.bones
        bone_pairs = [(b.name, b.parent.name if b.parent else None) for b in bones]
        mapping = rigmap.build_mapping(bone_pairs, override)
        rig = rigmap.detect_rig_type([b.name for b in bones])
        bone_slot = {bone: slot for slot, bone in mapping["slots"].items()}
        bone_slot.update({b: "torso" for b in mapping["torso"]})
        bone_slot.update({b: "neck" for b in mapping["neck"]})
        loc, rot, scl = arm_obj.matrix_world.decompose()
        report["rig"] = rig
        report["armature"] = {
            "name": arm_obj.name,
            "bones": len(bones),
            "deform_bones": sum(1 for b in bones if b.use_deform),
            "object_scale": [round(v, 5) for v in scl],
            "object_rotation_deg": [round(float(np.degrees(v)), 2) for v in rot.to_euler()],
            "bone_list": [{"name": n, "parent": p, "slot": bone_slot.get(n)} for n, p in bone_pairs],
        }
        mapping["slot_labels"] = {s: rigmap.slot_label(s) for s in rigmap.REQUIRED_SLOTS + rigmap.OPTIONAL_SLOTS}
        mapping["sources"] = {item["bone"]: item["joint"] for item in rigmap.build_plan(mapping)} if mapping["retargetable"] else {}
        report["mapping"] = mapping
        if len(armatures) > 1:
            _issue(issues, "aviso", "varias_armatures", f"{len(armatures)} armatures no arquivo; usando '{arm_obj.name}'.")
        if max(scl) / min(scl) > 1.001:
            _issue(issues, "aviso", "escala_nao_uniforme", "A armature tem escala não uniforme.")
        for note in mapping["notes"]:
            _issue(issues, "info", "mapeamento", note)

        slots = mapping["slots"]
        if "hips" in slots and bbox is not None:
            # Mesma conta do retarget: altura do quadril do personagem sobre a do SOMA em pe.
            hips_z = float((np.array(arm_obj.matrix_world) @ np.append(np.array(bones[slots["hips"]].head_local), 1.0))[2])
            rig["motion_scale"] = round((hips_z - float(bbox[0][2])) / SOMA_STAND_HEIGHT_M, 4)
        if "l_arm" in slots and "l_forearm" in slots:
            world = np.array(arm_obj.matrix_world)
            d = world[:3, :3] @ (np.array(bones[slots["l_forearm"]].head_local) - np.array(bones[slots["l_arm"]].head_local))
            elev = float(np.degrees(np.arcsin(d[2] / np.linalg.norm(d))))
            kind = "T" if abs(elev) < 15 else "A" if -70 <= elev <= -15 else "outra"
            report["rest_pose"] = {"type": kind, "arm_elevation_deg": round(elev, 1)}
            if kind == "outra":
                _issue(issues, "aviso", "pose_descanso", f"Pose de descanso incomum (braço a {elev:.0f}° da horizontal); o retarget espera T-pose ou A-pose.")

        if meshes:
            weights = _weight_stats(meshes, {b.name for b in bones if b.use_deform})
            report["mesh"].update(weights)
            if weights["unweighted_vertices"]:
                _issue(issues, "aviso", "sem_peso", f"{weights['unweighted_vertices']} vértice(s) sem peso em nenhum osso: ficam parados na animação.")
            if weights["vertices_over_4_influences"]:
                _issue(issues, "info", "influencias", f"{weights['vertices_over_4_influences']} vértice(s) com mais de 4 influências (limite comum em engines).")
        else:
            _issue(issues, "aviso", "malha_solta", "Nenhuma malha está ligada à armature.")

        if rig["type"] == "rigify":
            verdict = "nao_suportado"
            _issue(issues, "erro", "rig_de_controle", "Rig de controle (Rigify): o retarget direto ainda não é suportado. Exporte só o esqueleto de deformação.")
        elif not report["mesh"]["triangles"]:
            # Esqueleto sem malha nenhuma: e o arquivo de uma animacao (as do Mixamo vem assim),
            # nao um personagem. Como projeto ele nao serve para nada.
            verdict = "so_animacao"
            _issue(issues, "erro", "so_animacao", "O arquivo tem esqueleto e movimento, mas nenhuma malha: é uma animação, não um personagem. Importe-o em Animações Mixamo, dentro do projeto do personagem que vai recebê-la.")
        elif mapping["retargetable"]:
            verdict = "pronto"
        else:
            verdict = "precisa_mapeamento"
            faltam = ", ".join(rigmap.slot_label(s) if s != "torso" else "coluna" for s in mapping["missing_required"])
            _issue(issues, "erro", "mapeamento_incompleto", f"Ossos essenciais não reconhecidos: {faltam}.")

    # --- Preview para o navegador ----------------------------------------------------
    preview = out_dir / "preview.glb"
    try:
        scene.export_glb(preview)
        report["preview"] = preview.name
    except Exception as exc:  # noqa: BLE001 - o laudo vale mesmo sem preview
        report["preview"] = None
        _issue(issues, "erro", "preview", f"Não foi possível gerar o preview: {exc}")

    report["issues"] = issues
    report["verdict"] = verdict
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--mapping", type=Path, default=None)
    args = ap.parse_args(cli.script_argv())
    args.out_dir.mkdir(parents=True, exist_ok=True)
    override = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping and args.mapping.exists() else None
    cli.run(lambda: inspect(args.input, args.out_dir, override), args.out_dir / "report.json")


main()
