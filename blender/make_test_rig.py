"""Gera o boneco de teste: esqueleto com nomes do Mixamo e malha de blocos coloridos.

Serve para validar o retarget sem depender de um asset externo. As proporcoes sao
de proposito diferentes do SOMA (pernas curtas, bracos longos), os rolls dos ossos
sao arbitrarios e ha opcoes para dificultar: A-pose, armature com a transformacao
tipica de FBX (escala 0.01, girada 90 graus) e personagem virado de lado.

Esquerda do boneco = azul, direita = vermelho, nariz = amarelo.

Uso: blender --background --factory-startup --python make_test_rig.py -- \
        --out <arquivo .fbx|.glb|.blend> [--pose A|T] [--fbx-like] [--yaw graus]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix  # noqa: E402

from ponte_bl import cli, scene  # noqa: E402

PREFIX = "mixamorig:"
THICKNESS = {
    "Hips": 0.14, "Spine": 0.12, "Spine1": 0.13, "Spine2": 0.14, "Neck": 0.05, "Head": 0.11,
    "Shoulder": 0.05, "Arm": 0.045, "ForeArm": 0.038, "Hand": 0.03,
    "UpLeg": 0.07, "Leg": 0.055, "Foot": 0.045, "ToeBase": 0.04,
}  # fmt: skip


def _joints(pose: str) -> dict[str, tuple[str | None, np.ndarray]]:
    """Juntas em metros, Z para cima, personagem olhando para -Y, esquerda em +X."""
    joints: dict[str, tuple[str | None, np.ndarray]] = {}

    def add(name: str, parent: str | None, pos: tuple[float, float, float]) -> None:
        joints[name] = (parent, np.array(pos, dtype=float))

    add("Hips", None, (0, 0, 0.90))
    add("Spine", "Hips", (0, 0.01, 1.00))
    add("Spine1", "Spine", (0, 0.02, 1.12))
    add("Spine2", "Spine1", (0, 0.02, 1.25))
    add("Neck", "Spine2", (0, 0.01, 1.42))
    add("Head", "Neck", (0, 0, 1.52))
    add("HeadTop_End", "Head", (0, 0, 1.76))
    for side, sx in (("Left", 1.0), ("Right", -1.0)):
        add(f"{side}Shoulder", "Spine2", (0.05 * sx, 0.01, 1.36))
        add(f"{side}Arm", f"{side}Shoulder", (0.18 * sx, 0.01, 1.38))
        add(f"{side}ForeArm", f"{side}Arm", (0.46 * sx, 0.01, 1.38))
        add(f"{side}Hand", f"{side}ForeArm", (0.72 * sx, 0.01, 1.38))
        thumb = [(0.75, -0.035), (0.775, -0.06), (0.80, -0.08), (0.82, -0.10)]
        parent = f"{side}Hand"
        for i, (x, y) in enumerate(thumb, start=1):
            add(f"{side}HandThumb{i}", parent, (x * sx, y, 1.37))
            parent = f"{side}HandThumb{i}"
        for finger, y in (("Index", -0.03), ("Middle", -0.008), ("Ring", 0.014), ("Pinky", 0.034)):
            parent = f"{side}Hand"
            for i in range(1, 5):
                add(f"{side}Hand{finger}{i}", parent, ((0.80 + 0.03 * (i - 1)) * sx, 0.01 + y, 1.38))
                parent = f"{side}Hand{finger}{i}"
        add(f"{side}UpLeg", "Hips", (0.10 * sx, 0, 0.84))
        add(f"{side}Leg", f"{side}UpLeg", (0.115 * sx, -0.005, 0.47))
        add(f"{side}Foot", f"{side}Leg", (0.13 * sx, 0.01, 0.09))
        add(f"{side}ToeBase", f"{side}Foot", (0.13 * sx, -0.12, 0.02))
        add(f"{side}Toe_End", f"{side}ToeBase", (0.13 * sx, -0.20, 0.02))

        if pose == "A":
            angle = math.radians(45.0) * sx
            c, s = math.cos(angle), math.sin(angle)
            rot = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
            pivot = joints[f"{side}Arm"][1].copy()
            for name, (par, pos) in joints.items():
                if name.startswith(side) and ("Arm" in name or "Hand" in name) and "Shoulder" not in name:
                    joints[name] = (par, pivot + rot @ (pos - pivot))
    return joints


def _box(head: np.ndarray, tail: np.ndarray, half: float) -> np.ndarray:
    axis = tail - head
    axis /= np.linalg.norm(axis)
    seed = np.array([0.0, 0.0, 1.0]) if abs(axis[2]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(axis, seed)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    return np.array([p + a * u * half + b * v * half for p in (head, tail) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))])


_BOX_FACES = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]


def _textured_material(mesh, mode: str, texture_dir: Path) -> None:
    """Um material so ("Pele") com um xadrez laranja e verde-agua em cada face.

    ``embedded`` e ``external`` ligam a imagem no material; ``loose`` deixa o material
    sem textura e so grava o arquivo ao lado, para testar a aplicacao por nome.
    """
    size, cells = 256, 8
    yy, xx = np.mgrid[0:size, 0:size]
    check = ((xx // (size // cells) + yy // (size // cells)) % 2).astype(bool)
    pixels = np.empty((size, size, 4), dtype=np.float32)
    pixels[check] = (0.95, 0.45, 0.10, 1.0)
    pixels[~check] = (0.10, 0.65, 0.60, 1.0)
    edge = (xx < 6) | (yy < 6) | (xx >= size - 6) | (yy >= size - 6)
    pixels[edge] = (0.05, 0.05, 0.08, 1.0)

    folder = texture_dir if mode == "loose" else texture_dir / "textures"
    folder.mkdir(parents=True, exist_ok=True)
    image = bpy.data.images.new("Pele_BaseColor", size, size)
    image.pixels.foreach_set(pixels.ravel())
    image.filepath_raw = str(folder / "Pele_BaseColor.png")
    image.file_format = "PNG"
    image.save()

    material = bpy.data.materials.new("Pele")
    material.use_nodes = True
    if mode != "loose":
        tree = material.node_tree
        tex = tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        tree.links.new(tex.outputs["Color"], tree.nodes["Principled BSDF"].inputs["Base Color"])
        if mode == "alpha":
            # Alfa todo opaco ligado ao material: o caso dos exportadores que marcam o
            # personagem como transparente sem ele ser.
            tree.links.new(tex.outputs["Alpha"], tree.nodes["Principled BSDF"].inputs["Alpha"])
    mesh.materials.append(material)

    uv = mesh.uv_layers.new(name="UVMap")
    corners = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    for poly in mesh.polygons:
        for corner, loop_index in zip(corners, poly.loop_indices):
            uv.data[loop_index].uv = corner


def build(pose: str, fbx_like: bool, yaw_deg: float, textured: str | None = None, texture_dir: Path | None = None) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    joints = _joints(pose)
    yaw = math.radians(yaw_deg)
    spin = np.array([[math.cos(yaw), -math.sin(yaw), 0], [math.sin(yaw), math.cos(yaw), 0], [0, 0, 1]])
    joints = {n: (p, spin @ pos) for n, (p, pos) in joints.items()}

    # Transformacao do objeto, como a de um FBX do Mixamo importado: cm e Y para cima.
    world = np.eye(4)
    if fbx_like:
        world[:3, :3] = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]]) * 0.01
    to_local = np.linalg.inv(world)

    def local(p: np.ndarray) -> np.ndarray:
        return to_local[:3, :3] @ p + to_local[:3, 3]

    children: dict[str, list[str]] = {}
    for name, (parent, _) in joints.items():
        if parent:
            children.setdefault(parent, []).append(name)

    def tail_of(name: str) -> np.ndarray:
        parent, head = joints[name]
        if name in children:
            return joints[children[name][0]][1]
        back = head - joints[parent][1]
        return head + back / np.linalg.norm(back) * 0.03

    arm_data = bpy.data.armatures.new("Armature")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    arm_obj.matrix_world = Matrix(world.tolist())
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    for i, name in enumerate(joints):
        eb = arm_data.edit_bones.new(PREFIX + name)
        eb.head = local(joints[name][1])
        eb.tail = local(tail_of(name))
        eb.roll = math.radians((i * 37) % 360 - 180)  # rolls arbitrarios de proposito
        if joints[name][0]:
            eb.parent = arm_data.edit_bones[PREFIX + joints[name][0]]
        if name.endswith("End") or name[-1] == "4":
            eb.use_deform = False
    bpy.ops.object.mode_set(mode="OBJECT")

    verts: list[np.ndarray] = []
    faces: list[tuple[int, ...]] = []
    face_mat: list[int] = []
    groups: dict[str, list[int]] = {}

    def add_box(bone: str, head: np.ndarray, tail: np.ndarray, half: float, mat: int) -> None:
        base = len(verts)
        verts.extend(local(p) for p in _box(head, tail, half))
        faces.extend(tuple(base + i for i in f) for f in _BOX_FACES)
        face_mat.extend([mat] * 6)
        groups.setdefault(bone, []).extend(range(base, base + 8))

    for name, (_, head) in joints.items():
        if name.endswith("End") or name[-1] == "4":
            continue
        mat = 1 if name.startswith("Left") else 2 if name.startswith("Right") else 0
        key = name.replace("Left", "").replace("Right", "")
        half = THICKNESS.get(key, 0.009) * 0.5 * (2.0 if key in ("Hips", "Spine", "Spine1", "Spine2", "Head") else 1.0)
        add_box(name, head, tail_of(name), half, mat)
    nose = joints["Head"][1] + spin @ np.array([0.0, -0.11, 0.10])
    add_box("Head", nose, nose + spin @ np.array([0.0, -0.06, 0.0]), 0.02, 3)

    mesh = bpy.data.meshes.new("Boneco")
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    if textured:
        _textured_material(mesh, textured, texture_dir)
    else:
        for name, color in (("Centro", (0.55, 0.55, 0.58)), ("Esquerda", (0.15, 0.35, 0.85)), ("Direita", (0.85, 0.2, 0.2)), ("Nariz", (0.95, 0.8, 0.1))):
            m = bpy.data.materials.new(name)
            m.diffuse_color = (*color, 1.0)
            m.use_nodes = True
            bsdf = m.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Base Color"].default_value = (*color, 1.0)
            mesh.materials.append(m)
        for poly, mat in zip(mesh.polygons, face_mat):
            poly.material_index = mat
    mesh.update()

    mesh_obj = bpy.data.objects.new("Boneco", mesh)
    bpy.context.scene.collection.objects.link(mesh_obj)
    mesh_obj.parent = arm_obj
    for bone, idx in groups.items():
        mesh_obj.vertex_groups.new(name=PREFIX + bone).add(idx, 1.0, "REPLACE")
    mesh_obj.modifiers.new("Armature", "ARMATURE").object = arm_obj
    bpy.context.view_layer.update()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--pose", choices=("A", "T"), default="A")
    ap.add_argument("--fbx-like", action="store_true")
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--textured", choices=("embedded", "external", "loose", "alpha"), default=None)
    args = ap.parse_args(cli.script_argv())
    args.out = args.out.resolve()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    def run() -> dict:
        build(args.pose, args.fbx_like, args.yaw, args.textured, args.out.parent)
        ext = args.out.suffix.lower()
        if ext == ".fbx":
            embed = args.textured == "embedded"
            scene.call_op(
                bpy.ops.export_scene.fbx,
                filepath=str(args.out),
                add_leaf_bones=False,
                bake_anim=False,
                path_mode="COPY" if embed else "AUTO",
                embed_textures=embed,
            )
        elif ext == ".glb":
            scene.export_glb(args.out)
        elif ext == ".blend":
            bpy.ops.wm.save_as_mainfile(filepath=str(args.out))
        else:
            raise ValueError(f"Extensão não suportada: {ext}")
        return {"out": str(args.out)}

    cli.run(run, args.out.with_suffix(".make.json"))


main()
