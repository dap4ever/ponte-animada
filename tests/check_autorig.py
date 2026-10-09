"""Compara o rigador automático com o gabarito: um personagem rigado pelo próprio Mixamo.

Recebe um arquivo rigado pelo Mixamo, joga o rig fora e riga de novo aqui, de dois jeitos:

- com os marcadores tirados do próprio rig do Mixamo (testa só a montagem do esqueleto);
- com os marcadores estimados sozinhos (testa o fluxo sem ajuda humana).

Mostra a que distância cada junta ficou da do Mixamo, em % da altura do personagem.

    uv run python tests/check_autorig.py <personagem_do_mixamo.fbx> [--keep <pasta>]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ponte import blender  # noqa: E402
from ponte.config import SETTINGS  # noqa: E402

DUMP = """
import json, sys
sys.path.insert(0, r'{blender_dir}')
import numpy as np
from ponte_bl import scene
scene.import_asset(__import__('pathlib').Path(r'{asset}'))
arm, meshes = scene.find_rig()
world = np.array(arm.matrix_world)
joints = {{b.name.split(':')[-1]: [float(v) for v in (world @ np.append(np.array(b.head_local), 1.0))[:3]] for b in arm.data.bones}}
open(r'{out}', 'w').write(json.dumps(joints))
"""


def mixamo_joints(asset: Path, work: Path) -> dict:
    script, out = work / "dump.py", work / "truth.json"
    script.write_text(DUMP.format(blender_dir=ROOT / "blender", asset=asset, out=out), encoding="utf-8")
    subprocess.run([SETTINGS.blender_exe, "--background", "--factory-startup", "--python", str(script)], capture_output=True, check=True)
    return json.loads(out.read_text(encoding="utf-8"))


def report(label: str, joints: dict, truth: dict, height: float) -> float:
    groups = {
        "tronco e cabeça": ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head"],
        "braços": [f"{s}{p}" for s in ("Left", "Right") for p in ("Shoulder", "Arm", "ForeArm", "Hand")],
        "pernas": [f"{s}{p}" for s in ("Left", "Right") for p in ("UpLeg", "Leg", "Foot", "ToeBase")],
        "dedos": [n for n in truth if "Hand" in n and not n.endswith("Hand") and n in joints],
    }
    print(f"{label}")
    worst = 0.0
    for group, names in groups.items():
        errors = {n: 100 * sum((a - b) ** 2 for a, b in zip(joints[n], truth[n])) ** 0.5 / height for n in names if n in joints and n in truth}
        if not errors:
            continue
        top = max(errors, key=errors.get)
        if group != "dedos":
            worst = max(worst, errors[top])
        print(f"   {group:16s} média {sum(errors.values()) / len(errors):5.2f} %   pior {errors[top]:5.2f} % ({top})")
    return worst


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    asset = Path(args[0]).resolve()
    keep = Path(sys.argv[sys.argv.index("--keep") + 1]).resolve() if "--keep" in sys.argv else None
    work = keep or Path(tempfile.mkdtemp(prefix="ponte-rig-"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        truth = mixamo_joints(asset, work)
        estimate = blender.run_script("rig_asset.py", ["--input", asset, "--estimate", work / "estimados.json"], work / "estimados.json")
        height = estimate["body"]["height_m"]
        print(f"personagem de {height:.2f} m; erros em % da altura\n")

        # Marcadores como o Mixamo os teria: nas juntas dele (o queixo é a junta da cabeça,
        # a virilha fica abaixo do quadril pela mesma folga que o rigador usa).
        from_truth = {
            "chin": [truth["Head"][0], truth["Head"][2]],
            "groin": [truth["Hips"][0], truth["Hips"][2] - 0.045 * height],
            **{f"{k}_{part}": [truth[f"{side}{bone}"][0], truth[f"{side}{bone}"][2]] for k, side in (("l", "Left"), ("r", "Right")) for part, bone in (("wrist", "Hand"), ("elbow", "ForeArm"), ("knee", "Leg"))},
        }
        worst = 0.0
        for label, markers, name in (("marcadores do gabarito (só a montagem do esqueleto)", from_truth, "gabarito"), ("marcadores estimados sozinhos (sem ajuda humana)", estimate["markers"], "estimado")):
            markers_file = work / f"marcadores_{name}.json"
            markers_file.write_text(json.dumps(markers), encoding="utf-8")
            rigged = blender.run_script("rig_asset.py", ["--input", asset, "--markers", markers_file, "--out", work / f"rig_{name}.blend"], work / f"rig_{name}.json", work / f"rig_{name}.log")
            error = report(label, rigged["joints"], truth, height)
            print(f"   pesos: {rigged['skinning']['method']}, {rigged['skinning']['unweighted_vertices']} vértice(s) sem peso{''.join(' | ' + n for n in rigged['skinning']['notes'])}\n")
            if name == "gabarito":
                worst = error
        marker_errors = {k: 100 * sum((a - b) ** 2 for a, b in zip(estimate["markers"][k], from_truth[k])) ** 0.5 / height for k in from_truth}
        print("marcadores estimados × gabarito: " + ", ".join(f"{k} {v:.1f} %" for k, v in marker_errors.items()))
        ok = worst < 3.0
        print(("ok    " if ok else "FALHA ") + f"montagem do esqueleto: pior junta a {worst:.2f} % da altura da do Mixamo (limite 3 %)")
        return 0 if ok else 1
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
