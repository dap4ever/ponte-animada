"""Numeros de um clipe do ARDY (.npz de scripts/generate.py): quanto andou, para onde,
altura das maos e pe deslizando. Roda no ambiente do ARDY.

uso: python ardy_stats.py <arquivo.npz ou pasta de tomadas>
"""

import sys
from pathlib import Path

import numpy as np

from ardy.skeleton import CoreSkeleton27

NAMES = [name for name, _ in CoreSkeleton27.bone_order_names_with_parents]
IDX = {name: i for i, name in enumerate(NAMES)}
FLOOR = 0.02  # m acima do ponto mais baixo: o pe conta como apoiado


def ground_speed(points, fps):
    """Velocidade horizontal (m/s) de um ponto, quadro a quadro."""
    return np.linalg.norm(np.diff(points[:, [0, 2]], axis=0), axis=1) * fps


def stats(path):
    data = np.load(path)
    joints = data["posed_joints"]  # [T, J, 3] em metros, Y para cima, frente em +Z
    fps = float(data["fps"])
    frames = joints.shape[0]
    print(f"\n{path.name}: {frames} quadros a {fps:g} fps = {frames / fps:.1f} s")
    print(f"  texto: {data['text']}")
    if joints.shape[1] != len(NAMES):
        print(f"  esqueleto de {joints.shape[1]} juntas (este script espera {len(NAMES)})")
        return

    hips = joints[:, IDX["Hips"]]
    path_len = ground_speed(hips, fps).sum() / fps
    net = hips[-1, [0, 2]] - hips[0, [0, 2]]
    angle = np.degrees(np.arctan2(net[0], net[1]))  # 0 = +Z (frente), +90 = +X
    seconds = (frames - 1) / fps
    print(
        f"  andou {path_len:.2f} m pelo caminho e {np.linalg.norm(net):.2f} m em linha reta, "
        f"a {angle:+.0f} graus da frente; media {path_len / seconds:.2f} m/s"
    )
    half = frames // 2
    v1 = ground_speed(hips[:half], fps).mean()
    v2 = ground_speed(hips[half:], fps).mean()
    print(f"  velocidade na 1a metade {v1:.2f} m/s, na 2a {v2:.2f} m/s")

    head = joints[:, IDX["Head"], 1]
    print(
        f"  cabeca a {head.mean():.2f} m (de {head.min():.2f} a {head.max():.2f}); "
        f"quadril a {hips[:, 1].mean():.2f} m (de {hips[:, 1].min():.2f} a {hips[:, 1].max():.2f})"
    )
    chest = joints[:, IDX["Spine3"]] - hips
    lean = np.degrees(np.arctan2(np.linalg.norm(chest[:, [0, 2]], axis=1), chest[:, 1]))
    print(f"  tronco inclinado {lean.mean():.0f} graus em media (0 = ereto), maximo {lean.max():.0f}")

    for side in ("Left", "Right"):
        hand = joints[:, IDX[f"{side}Hand"], 1]
        shoulder = joints[:, IDX[f"{side}Arm"], 1]
        above = (hand > shoulder).mean() * 100
        print(
            f"  mao {side}: {np.mean(hand - shoulder):+.2f} m em relacao ao ombro, em media; "
            f"acima do ombro em {above:.0f}% dos quadros"
        )

    contacts = data["foot_contacts"] if "foot_contacts" in data else None
    if contacts is not None:
        print(f"  contato dos pes: formato {contacts.shape}, valores de {contacts.min():.2f} a {contacts.max():.2f}")
    floor = min(joints[:, IDX[f"{s}ToeBase"], 1].min() for s in ("Left", "Right"))
    for n, side in enumerate(("Left", "Right")):
        toe = joints[:, IDX[f"{side}ToeBase"]]
        ankle = joints[:, IDX[f"{side}Foot"]]
        speed = ground_speed(toe, fps)
        planted = toe[:-1, 1] < floor + FLOOR
        line = (
            f"  pe {side}: ponta de {toe[:, 1].min():.3f} a {toe[:, 1].max():.3f} m, "
            f"tornozelo de {ankle[:, 1].min():.3f} a {ankle[:, 1].max():.3f} m"
        )
        if planted.any():
            line += (
                f"; apoiado em {planted.mean() * 100:.0f}% dos quadros, "
                f"deslizando {speed[planted].mean() * 100:.1f} cm/s em media"
            )
        if contacts is not None and contacts.ndim == 2 and contacts.shape[1] >= 4:
            on = contacts[:-1, 2 * n + 1] > 0.5  # canal da ponta do pe
            if on.any():
                line += f"; pelo contato do modelo: {on.mean() * 100:.0f}% apoiado, {speed[on].mean() * 100:.1f} cm/s"
        print(line)


def main():
    target = Path(sys.argv[1])
    files = sorted(target.glob("*.npz")) if target.is_dir() else [target]
    if not files:
        sys.exit(f"nenhum .npz em {target}")
    first = np.load(files[0])
    print("campos:", ", ".join(f"{key}{list(first[key].shape)}" for key in first.files))
    for path in files:
        stats(path)


if __name__ == "__main__":
    main()
