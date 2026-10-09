"""Confere um FBX feito para a Unreal 5 (``ponte_bl/unreal.py``), sem a Unreal.

Le o arquivo de dois jeitos: importado no Blender (ossos, hierarquia, clipes, o que esta preso
em osso) e cru, pelo leitor de FBX (escala nos nos e a pose de vinculacao, que e o que a Unreal
cobra e o Blender nao mostra depois de importar).

Uso: blender --background --factory-startup --python check_unreal_fbx.py -- --input <fbx> --out <json>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ponte_bl import cli, scene  # noqa: E402


def raw(path: Path) -> dict:
    from io_scene_fbx import parse_fbx

    root, _version = parse_fbx.parse(str(path))
    objects = next(e for e in root.elems if e.id == b"Objects")
    name = {e.props[0]: e.props[1].split(b"\x00")[0].decode(errors="replace") for e in objects.elems}
    kind = {e.props[0]: (e.id, e.props[2] if len(e.props) > 2 else b"") for e in objects.elems}
    up: dict = {}
    for link in next(e for e in root.elems if e.id == b"Connections").elems:
        if link.props[0] == b"OO":
            up.setdefault(link.props[1], []).append(link.props[2])

    def child(elem, key: bytes):
        return next((e for e in elem.elems if e.id == key), None)

    def matrix(values) -> np.ndarray:
        return np.array(values, dtype=np.float64).reshape(4, 4).T

    bones = {uid for uid, k in kind.items() if k == (b"Model", b"LimbNode")}
    pose = {}
    for elem in objects.elems:
        if elem.id == b"Pose":
            for node in (e for e in elem.elems if e.id == b"PoseNode"):
                pose[child(node, b"Node").props[0]] = matrix(child(node, b"Matrix").props[0])
    error = 0.0
    for uid in bones & set(pose):
        r = pose[uid][:3, :3]
        error = max(error, float(np.abs(r.T @ r - np.eye(3)).max()))
    skinned = set()
    for elem in objects.elems:
        if elem.id != b"Deformer" or elem.props[2] != b"Cluster" or child(elem, b"TransformLink") is None:
            continue
        link = matrix(child(elem, b"TransformLink").props[0])
        for skin in up.get(elem.props[0], []):
            for geometry in up.get(skin, []):
                for model in up.get(geometry, []):
                    if model in pose:
                        skinned.add(model)
                        error = max(error, float(np.abs(matrix(child(elem, b"Transform").props[0]) - np.linalg.inv(link) @ pose[model]).max()))
    # A armature (o no acima dos ossos) e as malhas com pele nao podem levar escala.
    watched = skinned | {parent for uid in bones for parent in up.get(uid, []) if kind.get(parent) == (b"Model", b"Null")}
    scaled = []
    for elem in objects.elems:
        if elem.id == b"Model" and elem.props[0] in watched:
            for prop in child(elem, b"Properties70").elems:
                if prop.props[0] == b"Lcl Scaling" and max(abs(v - 1.0) for v in prop.props[4:7]) > 1e-4:
                    scaled.append([name[elem.props[0]], [round(v, 4) for v in prop.props[4:7]]])
    pelvis = next((pose[uid] for uid in bones & set(pose) if name[uid] == "pelvis"), None)
    return {"bind_pose_error": error, "scaled_nodes": scaled, "pelvis_height": None if pelvis is None else round(float(pelvis[1, 3]), 3)}  # o FBX sai com Y para cima


def run(path: Path) -> dict:
    scene.import_asset(path, link_textures=False)
    arm, _meshes = scene.find_rig()
    if arm is None:
        raise RuntimeError("O FBX não tem armature.")
    animations = []
    for action in bpy.data.actions:
        start, end = action.frame_range
        animations.append({"name": action.name, "frames": int(round(end - start)) + 1})
    return {
        "bones": [b.name for b in arm.data.bones],
        "parents": {b.name: b.parent.name if b.parent else None for b in arm.data.bones},
        "animations": animations,
        "attached": {o.name: o.parent_bone for o in bpy.context.scene.objects if o.parent == arm and o.parent_type == "BONE"},
        **raw(path),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(cli.script_argv())
    cli.run(lambda: run(args.input.resolve()), args.out.resolve())


main()
