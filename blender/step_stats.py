"""Mede o que cada passo do roteiro entregou: serve para conferir se o gesto pedido aconteceu.

O texto estar no roteiro nao garante o movimento, e uma tira de quadros engana em gesto pequeno.
Para cada passo de uma animacao (lidos de motion.json), mostra quanto ele andou e virou,
quanto o corpo balancou, quanto a cabeca inclinou, se os pes sairam do chao, quanto as maos
se mexeram e, num passo em laco, se o fim emenda no comeco.

Nao usa nada do Blender alem do numpy que vem com ele. Medidas no esqueleto do Kimodo
(um adulto de ~1,75 m), nao no personagem.

Uso: blender --background --python step_stats.py -- <pasta da animacao> [...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from ponte_bl import cli  # noqa: E402
from ponte_bl.bvh import load_bvh  # noqa: E402


def _wrap(angle: np.ndarray) -> np.ndarray:
    return (angle + 180) % 360 - 180


def _spread(values: np.ndarray) -> float:
    return float(values.max() - values.min())


def stats(folder: Path) -> list[dict]:
    record = json.loads((folder / "motion.json").read_text(encoding="utf-8"))
    motion = load_bvh(folder / "motion.bvh")
    grot, pos = motion.fk()
    pos = pos / 100.0  # cm -> m
    idx = motion.index
    fps = motion.fps
    hips = pos[:, idx("Hips")]
    side = pos[:, idx("LeftLeg")] - pos[:, idx("RightLeg")]  # aponta para a esquerda dele
    side[:, 1] = 0
    side /= np.linalg.norm(side, axis=1, keepdims=True)
    forward = np.stack([-side[:, 2], np.zeros(len(side)), side[:, 0]], axis=1)
    facing = np.degrees(np.arctan2(-side[:, 2], side[:, 0]))  # 0 = +Z, como no Kimodo
    head_forward = grot[:, idx("Head")] @ np.array([0.0, 0.0, 1.0])
    head_yaw = np.degrees(np.arctan2(head_forward[:, 0], head_forward[:, 2]))
    head_up = grot[:, idx("Head")] @ np.array([0.0, 1.0, 0.0])
    head_tilt = np.degrees(np.arcsin(np.clip(np.einsum("ij,ij->i", head_up, side), -1, 1)))
    head_bow = np.degrees(np.arcsin(np.clip(np.einsum("ij,ij->i", head_up, forward), -1, 1)))  # 0 = erguida, + = baixa
    feet = (pos[:, idx("LeftFoot")] + pos[:, idx("RightFoot")]) / 2
    body = [i for i, name in enumerate(motion.names) if name != "Root"]  # Root fica na origem: nao e corpo

    def relative(frame: int) -> np.ndarray:
        """As juntas em relacao ao quadril no chao."""
        out = pos[frame, body].copy()
        out[:, [0, 2]] -= hips[frame][[0, 2]]
        return out

    steps = record.get("steps") or [{"text": record.get("prompt", folder.name), "start_frame": 0, "seconds": motion.frames / fps}]
    out = []
    for i, step in enumerate(steps):
        a = int(step["start_frame"])
        b = int(steps[i + 1]["start_frame"]) if i + 1 < len(steps) else motion.frames
        seg = slice(a, b)
        seconds = (b - a) / fps
        hands = sum(float(np.linalg.norm(np.diff(pos[seg, idx(name)] - hips[seg], axis=0), axis=1).sum()) for name in ("LeftHand", "RightHand"))
        head_vs_body = _wrap(head_yaw[seg] - facing[seg])
        row = {
            "passo": i + 1,
            "texto": step["text"],
            "quadros": [a, b - 1],
            "andou_m": round(float(np.linalg.norm(np.diff(hips[seg][:, [0, 2]], axis=0), axis=1).sum()), 2),
            "corpo_virou_graus": {"max": round(float(np.abs(_wrap(facing[seg] - facing[a])).max()), 1), "fim": round(float(_wrap(facing[b - 1] - facing[a])), 1)},
            "cabeca_virou_alem_do_corpo_graus": round(float(head_vs_body[np.abs(head_vs_body).argmax()]), 1),
            "balanco_de_lado_cm": {
                "cabeca": round(_spread(np.einsum("ij,ij->i", pos[seg, idx("Head")] - feet[seg], side[seg])) * 100, 1),
                "quadril": round(_spread(np.einsum("ij,ij->i", hips[seg] - feet[seg], side[seg])) * 100, 1),
            },
            "balanco_frente_tras_cm": round(_spread(np.einsum("ij,ij->i", pos[seg, idx("Head")] - feet[seg], forward[seg])) * 100, 1),
            "cabeca_inclina_de_lado_graus": [round(float(head_tilt[seg].min()), 1), round(float(head_tilt[seg].max()), 1)],
            "cabeca_baixa_graus": [round(float(head_bow[seg].min()), 1), round(float(head_bow[seg].max()), 1)],
            "pes_sobem_cm": [round(_spread(pos[seg, idx(name)][:, 1]) * 100, 1) for name in ("LeftFoot", "RightFoot")],
            # Num ataque: os bracos tem de ir para frente na altura do ombro, nao acima da cabeca.
            "maos_acima_do_ombro_cm": [round(float((pos[seg, idx(f"{s}Hand")][:, 1] - pos[seg, idx(f"{s}Arm")][:, 1]).max()) * 100, 1) for s in ("Left", "Right")],
            "maos_acima_da_cabeca_cm": round(float(max((pos[seg, idx(f"{s}Hand")][:, 1] - pos[seg, idx("Head")][:, 1]).max() for s in ("Left", "Right"))) * 100, 1),
            "maos_a_frente_do_peito_cm": round(float(max(np.einsum("ij,ij->i", pos[seg, idx(f"{s}Hand")] - pos[seg, idx("Chest")], forward[seg]).max() for s in ("Left", "Right"))) * 100, 1),
            "maos_m_por_s": round(hands / seconds, 2),
        }
        if step.get("loop"):
            # Num laco, o ultimo quadro do passo tem de ser o quadro de antes do primeiro. Num
            # clipe que e o laco inteiro (uma captura) nao ha quadro antes: ele repete o primeiro.
            ref = max(a - 1, 0)
            gap = np.linalg.norm(relative(b - 1) - relative(ref), axis=1)
            per_frame = np.linalg.norm(np.diff(np.stack([relative(f) for f in range(ref, b)]), axis=0), axis=2).max(axis=1)
            shift = hips[b - 1][[0, 2]] - hips[ref][[0, 2]]
            row["laco"] = {
                "emenda_pior_junta_cm": round(float(gap.max()) * 100, 2),
                "maior_salto_entre_quadros_cm": round(float(per_frame.max()) * 100, 2),
                "fecha_deslocado_m": [round(float(shift[0]), 2), round(float(shift[1]), 2)],
            }
        out.append(row)
    return out


if __name__ == "__main__":
    for arg in cli.script_argv():
        for row in stats(Path(arg)):
            print("STEP " + json.dumps(row, ensure_ascii=False))
