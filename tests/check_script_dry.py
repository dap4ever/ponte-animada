"""Ensaio a seco do roteiro: confere que os passos se encadeiam, SEM gerar animação.

Roda ``kimodo_scripts/gerar.py --dry-run`` no container do Kimodo. O modelo não é
carregado: no lugar da animação entra uma T-pose que desliza pelo caminho pedido. O que
se confere é o que o script faz em volta do modelo — a continuação de um passo para o
outro (posição, direção do corpo), a trajetória de cada passo, o laço (o passo termina na
pose em que começou, deslocado pelo quanto andou) e a gravação.

Precisa do Docker rodando (não do text encoder).

    uv run python tests/check_script_dry.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ponte import blender, kimodo  # noqa: E402
from ponte.config import DATA, SETTINGS  # noqa: E402

# Parado 2 s, anda 3 s para a direita dele, 3 s para a esquerda, 2 s para frente.
# Corpo travado para frente o tempo todo: 1 m/s.
STEPS = [
    {"text": "A soldier raises a rifle and aims.", "seconds": 2},
    {"text": "A soldier aiming a rifle sidesteps to the right.", "seconds": 3, "travel": {"direction_deg": 90, "speed": 1.0, "lock_facing": True}},
    {"text": "A soldier aiming a rifle sidesteps to the left.", "seconds": 3, "travel": {"direction_deg": 270, "speed": 1.0, "lock_facing": True}},
    {"text": "A soldier aiming a rifle walks forward.", "seconds": 2, "travel": {"direction_deg": 0, "speed": 1.0, "lock_facing": True}},
]
EXPECTED_STARTS = [0, 60, 150, 240]  # 30 fps; os 5 quadros de transição não contam
EXPECTED_FRAMES = 300

# Laço: parado 2 s, parado em laço 2 s, anda 2 s para frente, anda em laço 2 s (1 m/s).
LOOP_STEPS = [
    {"text": "A zombie stands still.", "seconds": 2},
    {"text": "A zombie stands still, swaying.", "seconds": 2, "loop": True},
    {"text": "A zombie walks forward.", "seconds": 2, "travel": {"direction_deg": 0, "speed": 1.0, "lock_facing": False}},
    {"text": "A zombie walks forward.", "seconds": 2, "travel": {"direction_deg": 0, "speed": 1.0, "lock_facing": False}, "loop": True},
]
# Passo em laço: (primeiro quadro, último quadro, quanto o quadril anda nele em x e z, folga).
# O parado fecha no lugar; o que anda fecha uns 2 m à frente (a rampa de entrada tira um pouco).
LOOPS = [(60, 119, [0.0, 0.0], 0.02), (180, 239, [0.0, 2.0], 0.15)]


def hips_at(bvh: Path, frames: list[int]) -> list[list[float]] | None:
    """Onde o quadril está no chão (x, z, em metros) nos quadros pedidos, pelo BVH gravado."""
    probe = Path(tempfile.mkdtemp()) / "probe.py"
    probe.write_text(
        "import sys, json\n"
        f"sys.path.insert(0, r'{ROOT / 'blender'}')\n"
        "from ponte_bl.bvh import load_bvh\n"
        f"m = load_bvh(r'{bvh}')\n"
        "_, pos = m.fk()\n"
        "h = pos[:, m.index('Hips')] / 100\n"
        f"print('PROBE ' + json.dumps([[round(float(h[f][0]), 2), round(float(h[f][2]), 2)] for f in {frames}]))\n",
        encoding="utf-8",
    )
    proc = subprocess.run([SETTINGS.blender_exe, "--background", "--factory-startup", "--python", str(probe)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("PROBE ")), None)
    return json.loads(line[6:]) if line else None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = DATA / "tmp" / "ensaio-a-seco"
    problems = []
    try:
        out, looped = kimodo.generate(work, [{"name": "motion", "steps": STEPS, "seed": 0}, {"name": "laco", "steps": LOOP_STEPS, "seed": 0}], dry_run=True, log=lambda line: print(f"  · {line}"))
        if out["frames"] != EXPECTED_FRAMES:
            problems.append(f"{out['frames']} quadros (esperado {EXPECTED_FRAMES})")
        if out["step_frames"] != EXPECTED_STARTS:
            problems.append(f"passos começam em {out['step_frames']} (esperado {EXPECTED_STARTS})")

        # Onde o quadril está no começo de cada passo e no fim, pelo BVH gravado.
        points = hips_at(out["bvh"], EXPECTED_STARTS + [EXPECTED_FRAMES - 1])
        if points is None:
            problems.append("não consegui ler o BVH do ensaio")
        else:
            # Esquerda dele = +X. Parado; 3 m para a direita (-X); volta 3 m; 2 m para frente (+Z).
            expected = [[0.0, 0.0], [0.0, 0.0], [-3.0, 0.0], [0.0, 0.0], [0.0, 2.0]]
            print(f"  quadril (x, z) no início de cada passo e no fim: {points}")
            for got, want in zip(points, expected):
                if abs(got[0] - want[0]) > 0.25 or abs(got[1] - want[1]) > 0.25:
                    problems.append(f"quadril em {got}, esperado perto de {want}")

        # Laço: o último quadro do passo é o quadro de antes do primeiro, deslocado pelo quanto ele andou.
        if looped["step_frames"] != [0, 60, 120, 180] or looped["frames"] != 240:
            problems.append(f"roteiro com laço: passos em {looped['step_frames']}, {looped['frames']} quadros")
        ends = hips_at(looped["bvh"], [f for first, last, _, _ in LOOPS for f in (first - 1, last)])
        if ends is None:
            problems.append("não consegui ler o BVH do ensaio com laço")
        else:
            for i, (first, last, shift, slack) in enumerate(LOOPS):
                before, end = ends[2 * i], ends[2 * i + 1]
                moved = [round(end[0] - before[0], 2), round(end[1] - before[1], 2)]
                print(f"  laço dos quadros {first} a {last}: o quadril fecha deslocado de {moved} (esperado perto de {shift})")
                if abs(moved[0] - shift[0]) > slack + 1e-6 or abs(moved[1] - shift[1]) > slack + 1e-6:
                    problems.append(f"o laço {first}-{last} fecha deslocado de {moved}, esperado perto de {shift}")
    except (kimodo.KimodoError, blender.BlenderError) as exc:
        problems.append(str(exc))
    finally:
        kimodo.cleanup_work_dir(work)
    print(("FALHA " + "; ".join(problems)) if problems else "ok    o roteiro encadeia os passos e as trajetórias, e o laço fecha")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
