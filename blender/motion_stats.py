"""Mede um BVH do Kimodo: para onde o quadril foi e para onde o corpo olhou.

Serve para conferir animações com trajetória imposta (direção, corpo travado).
Não usa nada do Blender além do numpy que vem com ele.

Uso: blender --background --python motion_stats.py -- <arquivo.bvh> [...]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from ponte_bl import cli  # noqa: E402
from ponte_bl.bvh import load_bvh  # noqa: E402


def stats(path: Path) -> dict:
    motion = load_bvh(path)
    _, pos = motion.fk()
    hips = pos[:, motion.index("Hips")] / 100.0  # cm -> m
    side = pos[:, motion.index("LeftLeg")] - pos[:, motion.index("RightLeg")]  # aponta para a esquerda dele
    # Para frente = esquerda x cima, no chão. Mesma convenção do Kimodo: 0 graus = +Z.
    facing = np.degrees(np.arctan2(-side[:, 2], side[:, 0]))
    travel = hips[-1] - hips[0]
    seconds = (motion.frames - 1) / motion.fps
    # Direção do deslocamento relativa a para onde ele olhava no início: 0 frente, 90 direita.
    heading0 = math.radians(float(facing[0]))
    forward = np.array([math.sin(heading0), math.cos(heading0)])
    right = np.array([-math.cos(heading0), math.sin(heading0)])
    flat = np.array([travel[0], travel[2]])
    direction = math.degrees(math.atan2(flat @ right, flat @ forward)) % 360
    drift = (facing - facing[0] + 180) % 360 - 180
    return {
        "file": path.name,
        "frames": motion.frames,
        "distance_m": round(float(np.linalg.norm(flat)), 3),
        "speed_m_s": round(float(np.linalg.norm(flat)) / seconds, 3),
        "direction_deg": round(direction, 1),
        "facing_start_deg": round(float(facing[0]), 1),
        "facing_drift_deg": {"mean": round(float(drift.mean()), 1), "max_abs": round(float(np.abs(drift).max()), 1)},
        "hips_height_m": {"min": round(float(hips[:, 1].min()), 3), "max": round(float(hips[:, 1].max()), 3)},
    }


if __name__ == "__main__":
    for arg in cli.script_argv():
        print("STATS " + json.dumps(stats(Path(arg)), ensure_ascii=False))
