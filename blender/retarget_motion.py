"""Aplica uma animacao num asset rigado e exporta o resultado.

A animacao e um BVH do Kimodo (--bvh) ou uma animacao pronta em FBX, como as do Mixamo (--fbx).
Uma captura convertida por import_capture.py tambem entra por --bvh, com --stand-height.

Uso: blender --background --factory-startup --python retarget_motion.py -- \
        --asset <arquivo> (--bvh <motion.bvh> | --fbx <animacao.fbx>) --out-dir <pasta>
        [--name <acao>] [--mapping <json>] [--in-place] [--stand-height <cm>] [--no-fbx] [--no-blend]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ponte_bl import cli, mixamo, props, rigmap, scene  # noqa: E402
from ponte_bl.bvh import load_bvh  # noqa: E402
from ponte_bl.retarget import retarget  # noqa: E402


def run(args: argparse.Namespace) -> dict:
    scene.import_asset(args.asset)
    arm_obj, meshes = scene.find_rig()
    if arm_obj is None:
        raise RuntimeError("O asset não tem armature: precisa ser rigado antes do retarget.")

    override = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping and args.mapping.exists() else None
    bone_pairs = [(b.name, b.parent.name if b.parent else None) for b in arm_obj.data.bones]
    mapping = rigmap.build_mapping(bone_pairs, override)
    if not mapping["retargetable"]:
        faltam = ", ".join(rigmap.slot_label(s) if s != "torso" else "coluna" for s in mapping["missing_required"])
        raise RuntimeError(f"Mapeamento incompleto, ossos essenciais não reconhecidos: {faltam}.")

    # A animacao de um FBX entra na cena para ser lida e sai antes de qualquer outra coisa.
    motion = mixamo.load_fbx_motion(args.fbx) if args.fbx else load_bvh(args.bvh)
    if args.stand_height:
        # BVH de captura: outro esqueleto, com o tornozelo a outra altura do chao que o do SOMA.
        motion.stand_height = args.stand_height

    prop_notes = []
    if args.props and args.props.exists():
        prop_notes = props.attach_props(arm_obj, json.loads(args.props.read_text(encoding="utf-8")))
    adjust = json.loads(args.adjust.read_text(encoding="utf-8")) if args.adjust and args.adjust.exists() else None
    stats = retarget(arm_obj, meshes, motion, mapping, action_name=args.name, in_place=args.in_place, adjust=adjust)
    stats["warnings"] += prop_notes

    files = {"glb": "result.glb"}
    scene.export_glb(args.out_dir / files["glb"], active_action_only=True)
    if not args.no_fbx:
        files["fbx"] = "result.fbx"
        scene.export_fbx(args.out_dir / files["fbx"])
    if not args.no_blend:
        files["blend"] = "result.blend"
        scene.save_blend(args.out_dir / files["blend"])
    return {"stats": stats, "files": files, "armature": arm_obj.name}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", required=True, type=Path)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--bvh", type=Path, help="animacao do Kimodo (SOMA 77)")
    source.add_argument("--fbx", type=Path, help="animacao pronta em FBX, como as do Mixamo")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--name", default="Kimodo")
    ap.add_argument("--mapping", type=Path, default=None)
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--stand-height", type=float, default=None, help="altura do quadril em pe no esqueleto do BVH, na unidade dele (captura: nao e o SOMA)")
    ap.add_argument("--adjust", type=Path, default=None, help="JSON {osso: [w, x, y, z]} com o ajuste de pose")
    ap.add_argument("--props", type=Path, default=None, help="JSON [{id, file, bone, matrix}] com os acessórios presos a ossos")
    ap.add_argument("--no-fbx", action="store_true")
    ap.add_argument("--no-blend", action="store_true")
    args = ap.parse_args(cli.script_argv())
    args.out_dir.mkdir(parents=True, exist_ok=True)
    cli.run(lambda: run(args), args.out_dir / "retarget.json")


main()
