"""Gera um acessorio de teste: um "fuzil" de tres blocos, 80 cm, com o cano em +Y.

Uso: blender --background --factory-startup --python make_test_prop.py -- --out <arquivo.glb|.fbx>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from ponte_bl import cli, scene  # noqa: E402

# (centro, tamanho) em metros: corpo, cano, coronha.
BLOCKS = [((0.0, 0.0, 0.0), (0.05, 0.30, 0.08)), ((0.0, 0.35, 0.02), (0.025, 0.40, 0.025)), ((0.0, -0.22, -0.03), (0.04, 0.16, 0.10))]


def build() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    verts, faces = [], []
    for (cx, cy, cz), (sx, sy, sz) in BLOCKS:
        base = len(verts)
        verts += [(cx + dx * sx / 2, cy + dy * sy / 2, cz + dz * sz / 2) for dz in (-1, 1) for dy in (-1, 1) for dx in (-1, 1)]
        faces += [tuple(base + i for i in f) for f in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))]
    mesh = bpy.data.meshes.new("Fuzil")
    mesh.from_pydata(verts, [], faces)
    material = bpy.data.materials.new("Metal")
    material.diffuse_color = (0.08, 0.08, 0.09, 1.0)
    mesh.materials.append(material)
    bpy.context.scene.collection.objects.link(bpy.data.objects.new("Fuzil", mesh))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(cli.script_argv())
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    def run() -> dict:
        build()
        if out.suffix.lower() == ".fbx":
            scene.call_op(bpy.ops.export_scene.fbx, filepath=str(out), bake_anim=False)
        else:
            scene.export_glb(out)
        return {"out": str(out)}

    cli.run(run, out.with_suffix(".make.json"))


main()
