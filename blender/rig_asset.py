"""Riga um personagem no padrao do Mixamo (ou so estima os marcadores).

Estimar os marcadores, para o humano conferir na interface:
    blender --background --factory-startup --python rig_asset.py -- --input <arquivo> --estimate <markers.json>

Rigar com os marcadores conferidos:
    blender --background --factory-startup --python rig_asset.py -- --input <arquivo> \
        --markers <markers.json> --out <rigged.blend> [--no-fingers]

Se o arquivo ja traz um rig, ele e descartado: so as malhas sao usadas.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from mathutils import Matrix  # noqa: E402

from ponte_bl import autorig, cli, scene  # noqa: E402


def prepare_meshes() -> list:
    """Tira qualquer rig que tenha vindo e deixa as malhas em coordenadas de mundo."""
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("O arquivo não tem nenhuma malha para rigar.")
    for obj in meshes:
        world = obj.matrix_world.copy()
        for modifier in [m for m in obj.modifiers if m.type == "ARMATURE"]:
            obj.modifiers.remove(modifier)
        for group in list(obj.vertex_groups):
            obj.vertex_groups.remove(group)
        obj.parent = None
        obj.data = obj.data.copy()
        obj.data.transform(world, shape_keys=True)
        obj.matrix_world = Matrix.Identity(4)
    for obj in [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]:
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
    bpy.context.view_layer.update()
    return meshes


def describe(body: autorig.Body) -> dict:
    return {
        "height_m": round(body.height, 5),
        "floor_m": round(body.floor, 5),
        "center_x_m": round(body.x0, 5),
        "bbox_min": [round(float(v), 5) for v in body.lo],
        "bbox_max": [round(float(v), 5) for v in body.hi],
    }


def run(args: argparse.Namespace) -> dict:
    texture_info = scene.import_asset(args.input)
    meshes = prepare_meshes()
    body = autorig.Body(meshes)
    if args.estimate:
        return {"markers": autorig.estimate_markers(body), "body": describe(body)}

    markers = json.loads(args.markers.read_text(encoding="utf-8"))
    missing = [m for m in autorig.MARKERS if m not in markers]
    if missing:
        raise RuntimeError(f"Faltam marcadores: {', '.join(missing)}.")
    joints = autorig.build_joints(body, markers, fingers=not args.no_fingers)
    arm = autorig.build_armature(joints, fingers=not args.no_fingers)
    skinning = autorig.skin(arm, meshes, body.height)
    scene.save_blend(args.out)
    return {
        "body": describe(body),
        "bones": len(arm.data.bones),
        "joints": {name: [round(float(v), 5) for v in pos] for name, pos in joints.items()},
        "skinning": skinning,
        "texture_notes": texture_info["notes"],
        "out": args.out.name,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--estimate", type=Path, default=None, help="grava só os marcadores estimados neste JSON")
    ap.add_argument("--markers", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--no-fingers", action="store_true")
    args = ap.parse_args(cli.script_argv())
    args.input = args.input.resolve()
    if args.estimate:
        result_json = args.estimate.resolve()
    else:
        if not args.markers or not args.out:
            ap.error("--markers e --out são obrigatórios para rigar")
        args.out = args.out.resolve()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        result_json = args.out.with_suffix(".json")
    cli.run(lambda: run(args), result_json)


main()
