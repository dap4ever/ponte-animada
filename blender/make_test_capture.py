"""Fabrica um BVH "de captura" a partir de uma animacao do Kimodo, para testar a conversao.

Do arquivo do Kimodo sai outro com o que uma captura traz de diferente: so o corpo (sem
dedos), os ossos com o nome da junta em que comecam, um no de referencia acima do quadril, em
metros, a 60 quadros por segundo, com o ator virado para outro lado e longe da origem, e um
tempo parado antes e depois do movimento (o que se recorta com --start e --end).

Uso: blender --background --factory-startup --python make_test_capture.py -- \
        --bvh <kimodo.bvh> --out <captura.bvh> [--yaw <graus>] [--pad <segundos>] [--z-up]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from ponte_bl import capture, cli  # noqa: E402
from ponte_bl.bvh import BvhMotion, axis_rotation, load_bvh, save_bvh  # noqa: E402

# Junta do SOMA -> nome no esqueleto de captura (o da 100STYLE e o do XSens).
_LIMBS = (("Shoulder", "Collar"), ("Arm", "Shoulder"), ("ForeArm", "Elbow"), ("Hand", "Wrist"), ("Leg", "Hip"), ("Shin", "Knee"), ("Foot", "Ankle"), ("ToeBase", "Toe"))
NAMES = {
    "Root": "Reference", "Hips": "Hips", "Spine1": "Chest", "Spine2": "Chest2", "Chest": "Chest3", "Neck1": "Neck", "Neck2": "Neck2", "Head": "Head",
    **{f"{side}{soma}": f"{side}{name}" for side in ("Left", "Right") for soma, name in _LIMBS},
}  # fmt: skip
Z_UP = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])  # Y para cima -> Z para cima


def run(args: argparse.Namespace) -> dict:
    src = load_bvh(args.bvh)
    keep = [j for j, name in enumerate(src.names) if name in NAMES]
    parents = np.array([keep.index(int(src.parents[j])) if src.parents[j] >= 0 else -1 for j in keep], dtype=np.int64)
    rot, pos, offsets = src.local_rot[:, keep].copy(), src.local_pos[:, keep].copy(), src.offsets[keep].copy()

    # O ator virado e longe da origem: fica tudo no no de referencia, acima do quadril.
    rot[:, 0] = axis_rotation("Y", np.radians(np.full(len(rot), args.yaw)))
    pos[:, 0] = np.array([180.0, 0.0, -75.0])

    # Parado antes e depois, e o dobro de quadros por segundo (o do meio e a mistura dos vizinhos).
    pad = int(round(args.pad * src.fps))
    rot = np.concatenate([np.repeat(rot[:1], pad, axis=0), rot, np.repeat(rot[-1:], pad, axis=0)])
    pos = np.concatenate([np.repeat(pos[:1], pad, axis=0), pos, np.repeat(pos[-1:], pad, axis=0)])
    dense_rot = np.empty((2 * len(rot) - 1,) + rot.shape[1:])
    dense_pos = np.empty((2 * len(pos) - 1,) + pos.shape[1:])
    dense_rot[0::2], dense_pos[0::2] = rot, pos
    dense_rot[1::2] = capture._nearest_rotation(0.5 * (rot[:-1] + rot[1:]))
    dense_pos[1::2] = 0.5 * (pos[:-1] + pos[1:])
    rot, pos = dense_rot, dense_pos * 0.01  # centimetros -> metros
    offsets = offsets * 0.01
    if args.z_up:
        rot, pos, offsets = Z_UP @ rot @ Z_UP.T, pos @ Z_UP.T, offsets @ Z_UP.T

    motion = BvhMotion(names=[NAMES[src.names[j]] for j in keep], parents=parents, offsets=offsets, frame_time=src.frame_time / 2.0, local_rot=rot, local_pos=pos)
    save_bvh(motion, args.out)
    return {"frames": motion.frames, "fps": round(motion.fps, 3), "joints": len(keep), "motion_seconds": [args.pad, args.pad + (src.frames - 1) / src.fps]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bvh", required=True, type=Path, help="animacao do Kimodo (SOMA 77)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--yaw", type=float, default=100.0, help="para onde o ator esta virado, em graus")
    ap.add_argument("--pad", type=float, default=1.5, help="segundos parado antes e depois")
    ap.add_argument("--z-up", action="store_true", help="grava com Z para cima, e nao Y")
    args = ap.parse_args(cli.script_argv())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cli.run(lambda: run(args), args.out.with_suffix(".make.json"))


main()
