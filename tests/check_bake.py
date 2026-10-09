"""Regressão: o que se vê no visualizador é o que o Blender grava nos arquivos.

Duas coisas editadas na interface só valem se os dois lados fizerem a mesma conta:

- ajuste de pose (rotação extra por osso);
- acessório preso a um osso (arma na mão).

Para cada uma, grava um resultado com o Blender e compara, no three.js rodando em Node,
com o mesmo ajuste aplicado como o visualizador aplica. Testa nos dois tipos de rig:
armature com escala 0.01 (FBX importado) e sem escala.

    uv run python tests/check_bake.py
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ponte import blender  # noqa: E402

BVH = ROOT / "tests" / "fixtures" / "kimodo_walk_forward.bvh"


def quat(axis: tuple[float, float, float], degrees: float) -> list[float]:
    half = math.radians(degrees) / 2
    norm = math.sqrt(sum(a * a for a in axis))
    return [math.cos(half), *(math.sin(half) * a / norm for a in axis)]


def matrix(translation: tuple[float, float, float], scale: float) -> list[float]:
    """Matriz por colunas: rotação de 60° em torno de (1, 2, 3), escala uniforme e translação."""
    w, x, y, z = quat((1, 2, 3), 60)
    rows = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    cols = [[rows[r][c] * scale for r in range(3)] + [0.0] for c in range(3)]
    return [v for col in cols for v in col] + [*translation, 1.0]


def retarget(rig: Path, out: Path, *extra: object) -> None:
    blender.run_script("retarget_motion.py", ["--asset", rig, "--bvh", BVH, "--out-dir", out, "--no-fbx", "--no-blend", *extra], out / "retarget.json")


def node(script: str, *args: object) -> bool:
    proc = subprocess.run(["node", str(ROOT / "tests" / script), *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    print("      " + proc.stdout.strip().replace("\n", "\n      "))
    return proc.returncode == 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(tempfile.mkdtemp(prefix="ponte-bake-"))
    failures = 0
    try:
        prop_file = work / "fuzil.glb"
        blender.run_script("make_test_prop.py", ["--out", prop_file], prop_file.with_suffix(".make.json"))
        adjust = {
            "mixamorig:LeftArm": quat((1, 0, 0), 40),
            "mixamorig:LeftForeArm": quat((0, 0, 1), 30),
            "mixamorig:Hips": quat((0, 1, 0), 20),
            "mixamorig:RightHandIndex1": quat((3, 4, 0), 50),
        }
        (work / "adjust.json").write_text(json.dumps(adjust), encoding="utf-8")

        # (rótulo, arquivo, opções do boneco, unidades do osso por metro)
        rigs = [("armature com escala 0.01", "fbxlike.blend", ["--fbx-like"], 100.0), ("armature sem escala", "plain.fbx", [], 1.0)]
        for label, filename, options, units in rigs:
            rig = work / filename
            blender.run_script("make_test_rig.py", ["--out", rig, "--pose", "A", *options], rig.with_suffix(".make.json"))
            base = work / f"{rig.stem}_base"
            retarget(rig, base)

            print(f"ajuste de pose — {label}")
            adjusted = work / f"{rig.stem}_ajuste"
            retarget(rig, adjusted, "--adjust", work / "adjust.json")
            failures += not node("check_adjust.mjs", base / "result.glb", adjusted / "result.glb", work / "adjust.json")

            print(f"acessório na mão — {label}")
            props = [{"id": "fuzil", "name": "Fuzil", "file": str(prop_file), "bone": "mixamorig:RightHand", "matrix": matrix((0.03 * units, 0.09 * units, -0.04 * units), units)}]
            props_json = work / f"{rig.stem}_props.json"
            props_json.write_text(json.dumps(props), encoding="utf-8")
            with_prop = work / f"{rig.stem}_arma"
            retarget(rig, with_prop, "--props", props_json)
            failures += not node("check_props.mjs", with_prop / "result.glb", props_json)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
