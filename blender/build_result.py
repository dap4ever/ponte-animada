"""Monta o resultado de um personagem encerrado: todas as animações num arquivo só.

Abre o personagem como o retarget abre, prende os acessórios e traz a ação de cada prévia
do .blend dela, sem recalcular nada: o que foi validado é o que sai. Cada ação fica numa
faixa NLA, que é o que o glTF e o FBX exportam como clipes separados.

Com --unreal sai mais um FBX, com o personagem no esqueleto do Mannequin da Unreal 5
(``ponte_bl/unreal.py``).

Uso: blender --background --factory-startup --python build_result.py -- \
        --asset <arquivo> --clips <clips.json> --out-dir <pasta> --name <nome dos arquivos>
        --fps <quadros por segundo> [--props <props.json>] [--unreal <arquivo.fbx> [--mapping <mapping.json>]]

clips.json: [{"name": "andar", "blend": "<result.blend da prévia>"}], na ordem em que entram.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ponte_bl import cli, props, scene, unreal  # noqa: E402

BONE_PATH = re.compile(r'pose\.bones\["(.+?)"\]\.(\w+)')


def fcurves_of(action):
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                yield from bag.fcurves


def load_action(blend: Path, name: str):
    """Traz a ação de uma prévia (o .blend dela guarda uma só) com o nome do clipe."""
    with bpy.data.libraries.load(str(blend), link=False) as (source, target):
        if not source.actions:
            raise RuntimeError(f"A prévia de '{name}' não tem animação gravada ({blend}). Refaça o retarget dela.")
        target.actions = source.actions[:1]
    action = target.actions[0]
    action.name = name
    return action


def run(args: argparse.Namespace) -> dict:
    clips = json.loads(args.clips.read_text(encoding="utf-8"))
    if not clips:
        raise RuntimeError("Nenhuma animação para entrar no resultado.")
    scene.import_asset(args.asset)
    arm_obj, _meshes = scene.find_rig()
    if arm_obj is None:
        raise RuntimeError("O asset não tem armature.")
    warnings = []
    if args.props and args.props.exists():
        warnings += props.attach_props(arm_obj, json.loads(args.props.read_text(encoding="utf-8")))

    # Só as ações das prévias entram: o que veio no arquivo do personagem ou do acessório sai.
    for other in list(bpy.data.actions):
        bpy.data.actions.remove(other)
    for pb in arm_obj.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    arm_obj.animation_data_clear()
    anim = arm_obj.animation_data_create()

    out_clips = []
    last_frame = 0
    for clip in clips:
        action = load_action(Path(clip["blend"]), clip["name"])
        missing = set()
        for fc in fcurves_of(action):
            match = BONE_PATH.match(fc.data_path)
            if not match:
                continue
            pb = arm_obj.pose.bones.get(match.group(1))
            if pb is None:
                missing.add(match.group(1))
            elif match.group(2) == "rotation_quaternion":
                pb.rotation_mode = "QUATERNION"
        if missing:
            warnings.append(f"'{clip['name']}': {len(missing)} osso(s) da prévia não existem mais no personagem ({', '.join(sorted(missing)[:4])}). Refaça o retarget dela.")
        start, end = (int(round(v)) for v in action.frame_range)
        track = anim.nla_tracks.new()
        track.name = action.name
        strip = track.strips.new(action.name, start, action)
        if action.slots:
            strip.action_slot = action.slots[0]
        last_frame = max(last_frame, end)
        out_clips.append({"name": action.name, "frames": end - start + 1, "duration_s": round((end - start + 1) / args.fps, 3)})

    sc = bpy.context.scene
    sc.render.fps = int(round(args.fps))
    sc.render.fps_base = 1.0
    sc.frame_start = 0
    sc.frame_end = last_frame
    sc.frame_set(0)

    files = {ext: f"{args.name}.{ext}" for ext in ("glb", "fbx", "blend")}
    scene.export_glb(args.out_dir / files["glb"], nla_tracks=True)
    scene.export_fbx(args.out_dir / files["fbx"], nla_strips=True)
    scene.save_blend(args.out_dir / files["blend"])
    result = {"files": files, "clips": out_clips, "warnings": warnings, "armature": arm_obj.name}
    if args.unreal:
        # Por ultimo: troca a armature da cena, entao os tres arquivos acima ja tem de estar gravados.
        override = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping and args.mapping.exists() else None
        try:
            info = unreal.convert(arm_obj, scene.meshes_of(arm_obj), override)
            args.unreal.parent.mkdir(parents=True, exist_ok=True)
            unreal.export(args.unreal)
            result["unreal"] = {"file": args.unreal.name, **info}
        except Exception as exc:  # noqa: BLE001 - o resultado de sempre ja saiu; este e a mais
            warnings.append(f"O arquivo para a Unreal 5 não saiu: {exc}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", required=True, type=Path)
    ap.add_argument("--clips", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--name", required=True)
    ap.add_argument("--fps", required=True, type=float)
    ap.add_argument("--props", type=Path, default=None, help="JSON [{id, file, bone, matrix}] com os acessórios presos a ossos")
    ap.add_argument("--unreal", type=Path, default=None, help="grava também este FBX, com o esqueleto do Mannequin da Unreal 5")
    ap.add_argument("--mapping", type=Path, default=None, help="mapeamento manual de ossos do personagem (para --unreal)")
    args = ap.parse_args(cli.script_argv())
    args.out_dir.mkdir(parents=True, exist_ok=True)
    cli.run(lambda: run(args), args.out_dir / "build.json")


main()
