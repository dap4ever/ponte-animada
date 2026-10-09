"""Regressão do retarget com o boneco de teste e uma caminhada real do Kimodo.

Monta três variantes do mesmo boneco (FBX em A-pose; armature com a transformação
típica de FBX importado; personagem virado 90° em T-pose) e exige que o resultado
seja o mesmo nas três: o retarget não pode depender de escala/rotação do objeto,
da pose de descanso nem de para onde o personagem olha.

    uv run python tests/check_retarget.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ponte import blender  # noqa: E402

BVH = ROOT / "tests" / "fixtures" / "kimodo_walk_forward.bvh"
VARIANTS = {
    "fbx em A-pose": ("boneco_a.fbx", ["--pose", "A"], {"arm": 45.0, "yaw": 0.0}),
    "estilo FBX (escala 0.01)": ("boneco_fbxlike.blend", ["--pose", "A", "--fbx-like"], {"arm": 45.0, "yaw": 0.0}),
    "virado 90° em T-pose": ("boneco_lado.blend", ["--pose", "T", "--fbx-like", "--yaw", "90"], {"arm": 0.0, "yaw": -90.0}),
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(tempfile.mkdtemp(prefix="ponte-check-"))
    failures: list[str] = []
    reference = None
    try:
        for label, (filename, rig_args, expect) in VARIANTS.items():
            rig = work / filename
            blender.run_script("make_test_rig.py", ["--out", rig, *rig_args], rig.with_suffix(".make.json"))
            out = work / rig.stem
            stats = blender.run_script(
                "retarget_motion.py",
                ["--asset", rig, "--bvh", BVH, "--out-dir", out, "--no-fbx", "--no-blend"],
                out / "retarget.json",
            )["stats"]

            problems = []
            if stats["check"]["rotation_error_deg"] > 0.1:
                problems.append(f"erro de rotação {stats['check']['rotation_error_deg']}°")
            if stats["check"]["position_error_cm"] > 0.05:
                problems.append(f"erro de posição {stats['check']['position_error_cm']} cm")
            arm = max(v for k, v in stats["rest_alignment_deg"].items() if k.endswith("Arm") and "Fore" not in k)
            if abs(arm - expect["arm"]) > 0.5:
                problems.append(f"correção do braço {arm}° (esperado {expect['arm']}°)")
            if abs(stats["facing_yaw_deg"] - expect["yaw"]) > 0.5:
                problems.append(f"giro {stats['facing_yaw_deg']}° (esperado {expect['yaw']}°)")
            if stats["bones_animated"] != 52:
                problems.append(f"{stats['bones_animated']} ossos animados (esperado 52)")
            if not (out / "result.glb").is_file():
                problems.append("GLB não exportado")
            invariant = (stats["scale"], stats["travel_m"], stats["feet"])
            if reference is None:
                reference = invariant
            elif invariant != reference:
                problems.append("escala/deslocamento/pés diferem da primeira variante")

            print(f"{'FALHA' if problems else 'ok   '} {label:26s} escala {stats['scale']}  percorreu {stats['travel_m']} m" + (f"  -> {'; '.join(problems)}" if problems else ""))
            failures += problems
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
