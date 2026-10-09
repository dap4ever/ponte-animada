"""Captura de movimento num BVH de esqueleto qualquer, levada para o formato do projeto.

O retarget le um BVH como o do Kimodo: nomes do SOMA 77, centimetros, Y para cima, o
personagem de frente para +Z com a esquerda dele em +X, 30 quadros por segundo e o chao em
Y = 0. Aqui um BVH de captura (XSens, conjuntos de pesquisa) vai para esse formato: cada osso
ganha o nome da junta do SOMA de mesmo papel, e o que fica acima do quadril e descartado.

Uma tomada de captura costuma ser longa e nao fecha em laco. Com ``loop``, procura-se nela
o trecho em que o fim melhor repete o comeco (uma passada, num andar) e ele e fechado de
fato: o giro que o ator fez no trecho sai aos poucos, e o que sobra de diferenca entre o
ultimo quadro e o primeiro e repartido pelo trecho inteiro.

Nao depende de bpy.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import rigmap
from .bvh import BvhMotion, axis_rotation, load_bvh

FPS = 30.0
# Duracao do laco, em segundos, quando quem pede nao diz. Entre os trechos que emendam quase
# tao bem quanto o melhor, fica o mais curto: num andar, uma passada e nao duas.
LOOP_SECONDS = (0.6, 4.0)
_NEAR_BEST = 1.15
# Pesos da comparacao entre dois quadros, tudo em centimetros: a velocidade entra como o
# quanto a junta anda em _TAU segundos; cada grau de giro do trecho custa _TURN_CM.
_TAU = 0.1
_TURN_CM = 0.15
_TURN_RATE_CM = 0.5  # cm/s por grau/s, na velocidade com que o corpo gira
_WALKING = 15.0  # cm/s: abaixo disto o laco e tratado como parado no lugar
_FLOOR_TRUST = 3.0  # cm: a captura vem com o chao em Y = 0; so e corrigido se errar mais que isto


def _nearest_rotation(m: np.ndarray) -> np.ndarray:
    """A rotacao mais proxima de cada matriz (..., 3, 3): e o que sobra de uma media de rotacoes."""
    u, _, vt = np.linalg.svd(m)
    u[np.linalg.det(u @ vt) < 0, :, -1] *= -1.0
    return u @ vt


def _fraction(rot: np.ndarray, w: np.ndarray) -> np.ndarray:
    """A parte ``w`` (T,) de cada rotacao (J, 3, 3): 0 nao gira, 1 gira tudo. Devolve (T, J, 3, 3)."""
    angle = np.arccos(np.clip((np.trace(rot, axis1=-2, axis2=-1) - 1.0) / 2.0, -1.0, 1.0))
    axis = np.stack([rot[:, 2, 1] - rot[:, 1, 2], rot[:, 0, 2] - rot[:, 2, 0], rot[:, 1, 0] - rot[:, 0, 1]], axis=1)
    norm = np.linalg.norm(axis, axis=1, keepdims=True)
    axis = np.divide(axis, norm, out=np.zeros_like(axis), where=norm > 1e-12)
    k = np.zeros_like(rot)
    k[:, 0, 1], k[:, 0, 2], k[:, 1, 2] = -axis[:, 2], axis[:, 1], -axis[:, 0]
    k = k - np.swapaxes(k, -1, -2)
    a = (w[:, None] * angle[None, :])[..., None, None]
    return np.eye(3) + np.sin(a) * k + (1.0 - np.cos(a)) * (k @ k)


def _yaw(angle) -> np.ndarray:
    """Giro em torno de Y, para cima: leva +Z para a direcao ``angle`` (0 = +Z, 90 graus = +X)."""
    return axis_rotation("Y", np.asarray(angle, dtype=np.float64))


def _axis(v: np.ndarray) -> np.ndarray:
    """O eixo do arquivo, com sinal, mais proximo de ``v``."""
    out = np.zeros(3)
    i = int(np.abs(v).argmax())
    out[i] = np.sign(v[i])
    return out


def _heading(gpos: np.ndarray, left: int, right: int) -> np.ndarray:
    """Para onde o corpo olha em cada quadro, em radianos (0 = +Z), sem saltos de volta inteira."""
    side = gpos[:, left] - gpos[:, right]  # aponta para a esquerda dele
    return np.unwrap(np.arctan2(-side[:, 2], side[:, 0]))


def _resample(rot: np.ndarray, pos: np.ndarray, src_fps: float) -> tuple[np.ndarray, np.ndarray]:
    """O trecho no ritmo do projeto. Quadro que cai entre dois do arquivo e a mistura deles."""
    ratio = src_fps / FPS
    if abs(ratio - round(ratio)) < 0.002 * ratio:
        # Ritmo multiplo do nosso (60, 120): quadros inteiros. A folga cobre o arquivo que
        # arredonda o tempo do quadro (0,016667 s da 59,9988 quadros por segundo, e sao 60).
        return rot[:: int(round(ratio))].copy(), pos[:: int(round(ratio))].copy()
    x = np.arange(int(np.floor((len(rot) - 1) / ratio + 1e-6)) + 1) * ratio
    i = np.minimum(np.floor(x + 1e-6).astype(int), len(rot) - 1)
    w = np.clip(x - i, 0.0, 1.0)
    k = np.minimum(i + 1, len(rot) - 1)
    mixed = (1.0 - w)[:, None, None, None] * rot[i] + w[:, None, None, None] * rot[k]
    return _nearest_rotation(mixed), (1.0 - w)[:, None, None] * pos[i] + w[:, None, None] * pos[k]


def _find_loop(gpos: np.ndarray, theta: np.ndarray, seconds: tuple[float, float]) -> tuple[int, int, dict]:
    """Os quadros (i, j) em que a pose e o ritmo do fim melhor repetem os do comeco.

    ``gpos`` tem o quadril na junta 0. A comparacao e feita no espaco do personagem (as juntas
    em relacao ao quadril no chao, sem a direcao do corpo), com a velocidade de cada junta e a
    do corpo inteiro, para o movimento continuar na emenda e nao so passar pela mesma pose.
    """
    frames, joints = gpos.shape[:2]
    lo, hi = int(round(seconds[0] * FPS)), min(int(round(seconds[1] * FPS)), frames - 1)
    if lo < 2 or hi < lo:
        raise ValueError(f"O trecho tem {frames / FPS:.1f} s: é curto para um laço de {seconds[0]:g} a {seconds[1]:g} s.")
    hips = gpos[:, 0]
    unturn = _yaw(-theta)
    pose = np.einsum("tij,tkj->tki", unturn, gpos - hips[:, None] * np.array([1.0, 0.0, 1.0]))
    speed = np.einsum("tij,tj->ti", unturn, np.gradient(hips, axis=0) * FPS)
    drive = np.stack([speed[:, 0], speed[:, 2], np.degrees(np.gradient(theta)) * FPS * _TURN_RATE_CM], axis=1)
    feats = np.concatenate(
        [pose.reshape(frames, -1), _TAU * (np.gradient(pose, axis=0) * FPS).reshape(frames, -1), _TAU * np.sqrt(joints) * drive], axis=1
    )
    best = []  # por duracao, o melhor comeco
    for lag in range(lo, hi + 1):
        gap = np.sqrt(((feats[lag:] - feats[:-lag]) ** 2).sum(axis=1) / joints + (np.degrees(theta[lag:] - theta[:-lag]) * _TURN_CM) ** 2)
        i = int(gap.argmin())
        best.append((float(gap[i]), i, lag))
    limit = _NEAR_BEST * min(cost for cost, _, _ in best)
    n = next(k for k, (cost, _, _) in enumerate(best) if cost <= limit)
    while n + 1 < len(best) and best[n + 1][0] < best[n][0]:
        n += 1  # desce ate o fundo do vale: a duracao exata da passada
    cost, i, lag = best[n]
    j = i + lag
    return i, j, {
        "seconds": round(lag / FPS, 3),
        "turn_deg": round(float(np.degrees(theta[j] - theta[i])), 2),
        "gap_cm": round(float(np.sqrt(((pose[j] - pose[i]) ** 2).sum() / joints)), 2),
        "cost": round(cost, 3),
    }


def _close_loop(rot: np.ndarray, pos: np.ndarray, turn: float) -> tuple[np.ndarray, np.ndarray]:
    """Fecha o trecho (quadril na junta 0): o ultimo quadro vira o primeiro, adiante no caminho."""
    w = np.linspace(0.0, 1.0, len(rot))
    # O giro que o ator fez no trecho sai aos poucos, da direcao do corpo e do caminho.
    rot[:, 0] = _yaw(-w * turn) @ rot[:, 0]
    steps = np.einsum("tij,tj->ti", _yaw(-(w[:-1] + w[1:]) / 2.0 * turn), np.diff(pos[:, 0], axis=0))
    pos[1:, 0] = pos[0, 0] + np.cumsum(steps, axis=0)
    # O que sobra de diferenca entre o fim e o comeco e repartido pelo trecho inteiro.
    rot = _fraction(rot[0] @ np.swapaxes(rot[-1], -1, -2), w) @ rot
    pos[:, 1:] += w[:, None, None] * (pos[0, 1:] - pos[-1, 1:])
    pos[:, 0, 1] += w * (pos[0, 0, 1] - pos[-1, 0, 1])
    return rot, pos


def convert(
    path: str | Path, *, start: float | None = None, end: float | None = None, loop: tuple[float, float] | None = None, direction: float | None = None
) -> tuple[BvhMotion, dict]:
    """Le a captura de ``path`` e devolve o movimento no formato do projeto e as medidas dele.

    ``start`` e ``end`` recortam a tomada, em segundos do arquivo. ``loop`` = (duracao minima,
    maxima), em segundos: dentro do recorte, fica so o melhor laco, ja fechado. ``direction``,
    em graus (0 = frente, 90 = direita dele), diz para onde anda um laco que se desloca.
    """
    src = load_bvh(path)
    mapping, soma = rigmap.source_joint_names([(n, src.names[p] if p >= 0 else None) for n, p in zip(src.names, src.parents)])
    if not mapping["retargetable"]:
        faltam = ", ".join(rigmap.slot_label(s) if s != "torso" else "coluna" for s in mapping["missing_required"])
        raise ValueError(f"Não reconheci o esqueleto da captura como humanoide (faltam: {faltam}).")
    renamed = rigmap.rename_to_soma(src.names, soma)

    # So o quadril e o que desce dele: um no de referencia acima vira posicao e rotacao do quadril.
    root = renamed.index("Hips")
    keep = [root]
    for j in range(root + 1, len(renamed)):
        if int(src.parents[j]) in keep:
            keep.append(j)
    names = [renamed[j] for j in keep]
    parents = np.array([-1] + [keep.index(int(src.parents[j])) for j in keep[1:]], dtype=np.int64)
    at = names.index
    left, right, ankles = at("LeftLeg"), at("RightLeg"), [at("LeftFoot"), at("RightFoot")]
    toes = [at(n) for n in ("LeftToeBase", "RightToeBase") if n in names]

    grot, gpos = src.fk()
    rot, pos, offsets = src.local_rot[:, keep].copy(), src.local_pos[:, keep].copy(), src.offsets[keep].copy()
    rot[:, 0], pos[:, 0], offsets[0] = grot[:, root], gpos[:, root], 0.0

    # Eixos e unidade, lidos da pose de descanso: X a esquerda dele, Y para cima, Z para frente; centimetros.
    rest = src.rest_positions()[keep]
    up, side = _axis(rest[at("Head")] - rest[0]), _axis(rest[left] - rest[right])
    if abs(up @ side) > 0.5:
        raise ValueError("Não deu para ler os eixos da captura pela pose de descanso (quadril, cabeça e pernas).")
    basis = np.stack([side, up, np.cross(side, up)])
    leg = float((rest[0] - rest[ankles].mean(axis=0)) @ up)
    unit = 100.0 if leg < 5.0 else 1.0  # perna de menos de 5: o arquivo esta em metros
    rot = basis @ rot @ basis.T
    pos, offsets, leg = pos @ basis.T * unit, offsets @ basis.T * unit, leg * unit

    a = 0 if start is None else max(int(round(start * src.fps)), 0)
    b = src.frames - 1 if end is None else min(int(round(end * src.fps)), src.frames - 1)
    rot, pos = _resample(rot[a : max(b, a) + 1], pos[a : max(b, a) + 1], src.fps)
    if len(rot) < 2:
        raise ValueError(f"O trecho pedido não tem quadros: o arquivo vai de 0 a {(src.frames - 1) / src.fps:.1f} s.")

    def world(rot: np.ndarray, pos: np.ndarray) -> np.ndarray:
        return BvhMotion(names, parents, offsets, 1.0 / FPS, rot, pos).fk()[1]

    # Chao e altura do quadril em pe, medidos no recorte inteiro (antes de escolher o laco).
    gp = world(rot, pos)
    floor = float(np.percentile(gp[:, toes, 1].min(axis=1), 2)) if toes else 0.0
    moved = abs(floor) > _FLOOR_TRUST
    if moved:
        pos[:, 0, 1] -= floor
        gp[:, :, 1] -= floor
    stand = leg + float(np.percentile(gp[:, ankles, 1].min(axis=1), 5))

    first, found = 0, None
    if loop is not None:
        theta = _heading(gp, left, right)
        first, last, found = _find_loop(gp, theta, loop)
        rot, pos = _close_loop(rot[first : last + 1].copy(), pos[first : last + 1].copy(), float(theta[last] - theta[first]))
        gp = world(rot, pos)

    # Onde o clipe fica: comeca na origem, olhando para +Z. Num laco que anda quem manda e o
    # caminho: ele vai exatamente para ``direction`` (0 = frente, 90 = direita dele), que o jogo
    # usa para mover a unidade. Sem ``direction``, vale a mais proxima das quatro principais em
    # relacao ao quadril; nao as oito, porque num andar torto (arrastando uma perna) o quadril
    # fica uns 30 graus virado e o caminho continua sendo "para frente".
    theta = _heading(gp, left, right)
    travel = pos[-1, 0] - pos[0, 0]
    seconds = (len(rot) - 1) / FPS
    speed = float(np.hypot(travel[0], travel[2])) / seconds
    turn_to, went = -float(theta[0]), None
    if found and speed >= _WALKING:
        way = float(np.arctan2(travel[0], travel[2]))
        if direction is None:
            facing = float(np.arctan2(np.sin(theta).mean(), np.cos(theta).mean()))
            aim = round(((way - facing + np.pi) % (2 * np.pi) - np.pi) / (np.pi / 2)) * (np.pi / 2)
        else:
            aim = -float(np.radians(direction))  # +X e a esquerda dele: a direita e angulo negativo
        turn_to, went = aim - way, round(float(np.degrees(-aim)) % 360.0, 1)
    spin = _yaw(turn_to)
    rot[:, 0] = spin @ rot[:, 0]
    pos[:, 0] = (pos[:, 0] - pos[0, 0] * np.array([1.0, 0.0, 1.0])) @ spin.T

    motion = BvhMotion(names=names, parents=parents, offsets=offsets, frame_time=1.0 / FPS, local_rot=rot, local_pos=pos)
    begin = a / src.fps + first / FPS
    info = {
        "frames": motion.frames,
        "fps": FPS,
        "duration_s": round(motion.frames / FPS, 3),
        "stand_height": round(stand, 3),
        "floor_cm": round(floor, 2),
        "floor_moved": moved,
        "speed_m_s": round(speed / 100.0, 3),
        "travel_m": round(float(np.hypot(travel[0], travel[2])) / 100.0, 3),
        "source": {"frames": src.frames, "fps": round(src.fps, 3), "joints": len(src.names), "unit": "m" if unit > 1 else "cm", "seconds": [round(begin, 3), round(begin + seconds, 3)]},
        "loop": {**found, "direction_deg": went} if found else None,
        "notes": mapping["notes"],
    }
    return motion, info
