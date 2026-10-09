"""Renderiza uma tira de frames de um asset animado (camera acompanha o personagem).

Serve de miniatura e de conferencia visual sem abrir o navegador.

Uso: blender --background --factory-startup --python render_sheet.py -- \
        --input <.blend|.glb|.fbx> --out <tira.png> [--frames 6] [--size 320] [--view front|side|quarter]
        [--start <quadro>]

Com --start a tira cobre so do quadro dado ate o fim: serve para conferir um passo do roteiro
(o quadro em que cada passo comeca esta em motion.json, steps[].start_frame).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector  # noqa: E402

from ponte_bl import cli, scene  # noqa: E402

VIEWS = {"front": (0.0, -1.0, 0.12), "side": (1.0, 0.0, 0.12), "quarter": (0.75, -1.0, 0.35)}


def render(input_path: Path, out: Path, n_frames: int, size: int, view: str, start: int | None = None) -> dict:
    scene.import_asset(input_path, link_textures=False)
    arm_obj, meshes = scene.find_rig()
    sc = bpy.context.scene
    targets = meshes or [o for o in sc.objects if o.type == "MESH"]
    sc.frame_set(sc.frame_start)
    if scene.world_bbox(targets) is None:
        raise RuntimeError("Nada para renderizar: o arquivo não tem malha.")
    first = sc.frame_start if start is None else min(max(start, sc.frame_start), sc.frame_end)
    frames = np.unique(np.linspace(first, sc.frame_end, n_frames).astype(int))
    # O quadro tem de caber o personagem no momento em que ele esta mais alto: um clipe que
    # comeca deitado no chao nao pode fechar a camera no corpo caido e cortar o resto.
    boxes = []
    for f in frames:
        sc.frame_set(int(f))
        boxes.append(scene.world_bbox(targets))
    height = max(float(b[1][2] - b[0][2]) for b in boxes)
    floor_z = min(float(b[0][2]) for b in boxes)

    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x = sc.render.resolution_y = size
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    shading = sc.display.shading
    shading.light = "STUDIO"
    shading.color_type = "TEXTURE" if any(i.source == "FILE" for i in bpy.data.images) else "MATERIAL"
    # Sem sombra: a do Workbench exige malha fechada e risca a imagem em malhas que nao sao
    # (as geradas por IA, por exemplo). A cavidade da o relevo no lugar dela.
    shading.show_shadows = False
    shading.show_cavity = True
    sc.world = bpy.data.worlds.new("Fundo")
    sc.world.color = (0.09, 0.10, 0.12)

    ground = bpy.data.meshes.new("Chao")
    e = 60.0
    ground.from_pydata([(-e, -e, floor_z), (e, -e, floor_z), (e, e, floor_z), (-e, e, floor_z)], [], [(0, 1, 2, 3)])
    mat = bpy.data.materials.new("Chao")
    mat.diffuse_color = (0.22, 0.23, 0.26, 1.0)
    ground.materials.append(mat)
    sc.collection.objects.link(bpy.data.objects.new("Chao", ground))

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = height * 1.7
    cam = bpy.data.objects.new("Cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    offset = Vector(VIEWS[view]).normalized() * (height * 6.0)

    tiles = []
    with tempfile.TemporaryDirectory() as tmp:
        for f in frames:
            sc.frame_set(int(f))
            box = scene.world_bbox(targets)
            center = Vector((float(box[0][0] + box[1][0]) / 2, float(box[0][1] + box[1][1]) / 2, floor_z + height * 0.5))
            cam.location = center + offset
            cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
            sc.render.filepath = str(Path(tmp) / f"f{int(f):05d}.png")
            bpy.ops.render.render(write_still=True)
            img = bpy.data.images.load(sc.render.filepath)
            px = np.empty(size * size * 4, dtype=np.float32)
            img.pixels.foreach_get(px)
            tiles.append(px.reshape(size, size, 4))
            bpy.data.images.remove(img)

    sheet = np.concatenate(tiles, axis=1)
    out.parent.mkdir(parents=True, exist_ok=True)
    result = bpy.data.images.new("Tira", width=sheet.shape[1], height=sheet.shape[0], alpha=True)
    result.pixels.foreach_set(sheet.ravel())
    result.filepath_raw = str(out)
    result.file_format = "PNG"
    result.save()
    if not out.exists():
        raise RuntimeError(f"O Blender não gravou a tira em {out}")
    return {"out": out.name, "frames": [int(f) for f in frames], "armature": arm_obj.name if arm_obj else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--size", type=int, default=320)
    ap.add_argument("--view", choices=sorted(VIEWS), default="quarter")
    ap.add_argument("--start", type=int, default=None, help="primeiro quadro da tira (padrao: o comeco do clipe)")
    args = ap.parse_args(cli.script_argv())
    out = args.out.resolve()  # o Blender resolve caminho relativo contra o .blend aberto, nao contra o cwd
    cli.run(lambda: render(args.input.resolve(), out, args.frames, args.size, args.view, args.start), out.with_suffix(".json"))


main()
