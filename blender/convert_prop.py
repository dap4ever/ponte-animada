"""Converte um acessorio (arma etc.) para GLB, que e o que o visualizador carrega.

Uso: blender --background --factory-startup --python convert_prop.py -- --input <arquivo> --out <prop.glb>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from ponte_bl import cli, scene  # noqa: E402


def convert(input_path: Path, out: Path) -> dict:
    info = scene.import_asset(input_path)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("O arquivo do acessório não tem nenhuma malha.")
    bbox = scene.world_bbox(meshes)
    scene.export_glb(out)
    size = [round(float(v), 5) for v in (bbox[1] - bbox[0])]
    return {"size_m": size, "meshes": len(meshes), "triangles": sum(len(o.data.loop_triangles) or len(o.data.polygons) for o in meshes), "notes": info["notes"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(cli.script_argv())
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cli.run(lambda: convert(args.input.resolve(), out), out.with_suffix(".json"))


main()
