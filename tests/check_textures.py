"""Regressão das texturas: o personagem tem que chegar texturizado e opaco no preview.

Quatro situações, todas com o boneco de teste:

- embutida no FBX;
- em arquivo separado, numa subpasta, longe do caminho gravado no FBX;
- solta, sem o modelo referenciá-la (aplicada pelo nome do material);
- com canal alfa todo opaco ligado ao material (não pode sair transparente).

    uv run python tests/check_textures.py
"""

from __future__ import annotations

import json
import shutil
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ponte import blender  # noqa: E402


def glb_json(path: Path) -> dict:
    data = path.read_bytes()
    (length,) = struct.unpack_from("<I", data, 12)
    return json.loads(data[20 : 20 + length])


def make(work: Path, mode: str, ext: str) -> Path:
    """Gera o boneco numa pasta e o leva para outra, como um upload faria."""
    built = work / f"built_{mode}"
    blender.run_script("make_test_rig.py", ["--out", built / f"boneco{ext}", "--textured", mode], built / "boneco.make.json")
    staged = work / f"asset_{mode}"
    staged.mkdir()
    shutil.move(built / f"boneco{ext}", staged / f"boneco{ext}")
    texture = next(built.rglob("Pele_BaseColor.png"))
    if mode == "external":
        (staged / "tex").mkdir()
        shutil.move(texture, staged / "tex" / texture.name)
    elif mode == "loose":
        shutil.move(texture, staged / texture.name)
    shutil.rmtree(built)  # o caminho absoluto gravado no modelo deixa de existir
    return staged / f"boneco{ext}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(tempfile.mkdtemp(prefix="ponte-tex-"))
    cases = {
        "embutida no FBX": ("embedded", ".fbx", None),
        "arquivo separado": ("external", ".fbx", None),
        "solta, por nome": ("loose", ".fbx", "deduzido pelo nome"),
        "alfa todo opaco": ("alpha", ".glb", "Transparência desligada"),
    }
    failures = 0
    try:
        for label, (mode, ext, expected_note) in cases.items():
            model = make(work, mode, ext)
            out = work / f"out_{mode}"
            report = blender.run_script("inspect_asset.py", ["--input", model, "--out-dir", out], out / "report.json")
            material = glb_json(out / "preview.glb")["materials"][0]
            notes = " | ".join(i["msg"] for i in report["issues"])

            problems = []
            if report["mesh"]["images"] != 1 or report["mesh"]["missing_images"]:
                problems.append(f"imagens {report['mesh']['images']}, ausentes {report['mesh']['missing_images']}")
            if report["mesh"]["untextured_materials"]:
                problems.append("material ficou sem textura")
            if "baseColorTexture" not in material.get("pbrMetallicRoughness", {}):
                problems.append("preview sem textura de cor")
            if material.get("alphaMode", "OPAQUE") != "OPAQUE":
                problems.append(f"preview saiu {material['alphaMode']}, não opaco")
            if expected_note and expected_note not in notes:
                problems.append(f"faltou a nota '{expected_note}' no laudo")

            failures += bool(problems)
            print(f"{'FALHA' if problems else 'ok   '} {label:18s}" + (f"  -> {'; '.join(problems)}" if problems else ""))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
