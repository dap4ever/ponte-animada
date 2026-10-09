"""Leitor de BVH em numpy puro e cinematica direta (FK).

Nao depende de bpy: da para testar fora do Blender.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

_AXES = {"X": 0, "Y": 1, "Z": 2}


def axis_rotation(axis: str, angle: np.ndarray) -> np.ndarray:
    """Matrizes de rotacao (..., 3, 3) em torno de um eixo, angulo em radianos."""
    c, s = np.cos(angle), np.sin(angle)
    rot = np.zeros(angle.shape + (3, 3))
    i = _AXES[axis]
    j, k = (i + 1) % 3, (i + 2) % 3
    rot[..., i, i] = 1.0
    rot[..., j, j] = c
    rot[..., j, k] = -s
    rot[..., k, j] = s
    rot[..., k, k] = c
    return rot


@dataclass
class BvhMotion:
    names: list[str]
    parents: np.ndarray  # (J,), -1 na raiz
    offsets: np.ndarray  # (J, 3)
    frame_time: float
    local_rot: np.ndarray  # (T, J, 3, 3)
    local_pos: np.ndarray  # (T, J, 3) translacao relativa ao pai

    @property
    def frames(self) -> int:
        return int(self.local_rot.shape[0])

    @property
    def fps(self) -> float:
        return 1.0 / self.frame_time

    def index(self, name: str) -> int:
        return self.names.index(name)

    def rest_positions(self) -> np.ndarray:
        """Posicoes globais (J, 3) na pose de descanso (so os OFFSETs)."""
        pos = np.zeros_like(self.offsets)
        for j, p in enumerate(self.parents):
            pos[j] = self.offsets[j] + (pos[p] if p >= 0 else 0.0)
        return pos

    def fk(self) -> tuple[np.ndarray, np.ndarray]:
        """Rotacoes globais (T, J, 3, 3) e posicoes globais (T, J, 3).

        Num BVH a orientacao de descanso de toda junta e a identidade, entao a
        rotacao global ja e o delta em relacao ao descanso, em espaco de mundo.
        """
        grot = np.empty_like(self.local_rot)
        gpos = np.empty_like(self.local_pos)
        for j, p in enumerate(self.parents):
            if p < 0:
                grot[:, j] = self.local_rot[:, j]
                gpos[:, j] = self.local_pos[:, j]
            else:
                grot[:, j] = grot[:, p] @ self.local_rot[:, j]
                gpos[:, j] = gpos[:, p] + np.einsum("tij,tj->ti", grot[:, p], self.local_pos[:, j])
        return grot, gpos


def load_bvh(path: str | Path) -> BvhMotion:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    head, sep, motion = text.partition("MOTION")
    if not sep:
        raise ValueError(f"BVH sem bloco MOTION: {path}")

    names: list[str] = []
    parents: list[int] = []
    offsets: list[list[float]] = []
    channels: list[list[str]] = []
    stack: list[int] = []
    pending = -1

    tok = head.split()
    i = 0
    while i < len(tok):
        t = tok[i]
        if t in ("ROOT", "JOINT"):
            j = i + 1
            while tok[j] != "{":
                j += 1
            names.append(" ".join(tok[i + 1 : j]))
            parents.append(stack[-1] if stack else -1)
            offsets.append([0.0, 0.0, 0.0])
            channels.append([])
            pending = len(names) - 1
            i = j
            continue
        if t == "End":  # "End Site { OFFSET x y z }": folha sem canais, ignorada
            while tok[i] != "}":
                i += 1
            i += 1
            continue
        if t == "{":
            stack.append(pending)
        elif t == "}":
            stack.pop()
        elif t == "OFFSET":
            offsets[stack[-1]] = [float(v) for v in tok[i + 1 : i + 4]]
            i += 3
        elif t == "CHANNELS":
            n = int(tok[i + 1])
            channels[stack[-1]] = tok[i + 2 : i + 2 + n]
            i += 1 + n
        i += 1

    mtok = motion.split()
    n_frames = int(mtok[mtok.index("Frames:") + 1])
    ft = mtok.index("Time:")
    frame_time = float(mtok[ft + 1])
    n_ch = sum(len(c) for c in channels)
    data = np.array(mtok[ft + 2 :], dtype=np.float64)
    if data.size != n_frames * n_ch:
        raise ValueError(f"BVH inconsistente: {data.size} valores para {n_frames} frames x {n_ch} canais")
    data = data.reshape(n_frames, n_ch)

    n_joints = len(names)
    offs = np.array(offsets, dtype=np.float64)
    local_rot = np.tile(np.eye(3), (n_frames, n_joints, 1, 1))
    local_pos = np.tile(offs, (n_frames, 1, 1))
    col = 0
    for j, chans in enumerate(channels):
        rot = None
        for ch in chans:
            values = data[:, col]
            col += 1
            axis, kind = ch[0].upper(), ch[1:].lower()
            if kind == "position":
                # Canal de posicao substitui o OFFSET (convencao do Kimodo e do Blender).
                local_pos[:, j, _AXES[axis]] = values
            elif kind == "rotation":
                step = axis_rotation(axis, np.radians(values))
                rot = step if rot is None else rot @ step
        if rot is not None:
            local_rot[:, j] = rot

    return BvhMotion(
        names=names,
        parents=np.array(parents, dtype=np.int64),
        offsets=offs,
        frame_time=frame_time,
        local_rot=local_rot,
        local_pos=local_pos,
    )


def _euler_yxz(rot: np.ndarray) -> np.ndarray:
    """(..., 3, 3) -> angulos em graus (..., 3) na ordem Y, X, Z, com R = Ry @ Rx @ Rz."""
    sx = np.clip(-rot[..., 1, 2], -1.0, 1.0)
    lock = np.abs(sx) > 1.0 - 1e-9  # X a 90 graus: Y e Z giram em torno do mesmo eixo
    y = np.where(lock, np.arctan2(-rot[..., 2, 0], rot[..., 0, 0]), np.arctan2(rot[..., 0, 2], rot[..., 2, 2]))
    z = np.where(lock, 0.0, np.arctan2(rot[..., 1, 0], rot[..., 1, 1]))
    return np.degrees(np.stack([y, np.arcsin(sx), z], axis=-1))


def save_bvh(motion: BvhMotion, path: str | Path) -> None:
    """Grava ``motion`` num BVH que ``load_bvh`` le de volta igual.

    A raiz leva posicao e rotacao; as outras juntas, so rotacao (posicao tambem, se a delas
    mudar ao longo do clipe). Toda folha ganha um End Site, que outros leitores exigem.
    """
    children: dict[int, list[int]] = {}
    for j, p in enumerate(motion.parents):
        children.setdefault(int(p), []).append(j)
    moving = {j for j, p in enumerate(motion.parents) if p < 0 or np.ptp(motion.local_pos[:, j], axis=0).max() > 1e-6}
    order: list[int] = []  # os canais seguem a ordem em que as juntas sao escritas
    lines = ["HIERARCHY"]

    def write(j: int, depth: int) -> None:
        pad = "\t" * depth
        order.append(j)
        lines.append(f"{pad}{'ROOT' if motion.parents[j] < 0 else 'JOINT'} {motion.names[j]}")
        lines.append(pad + "{")
        lines.append(f"{pad}\tOFFSET " + " ".join(f"{v:.6f}" for v in motion.offsets[j]))
        lines.append(f"{pad}\tCHANNELS " + ("6 Xposition Yposition Zposition " if j in moving else "3 ") + "Yrotation Xrotation Zrotation")
        for child in children.get(j, []):
            write(child, depth + 1)
        if j not in children:
            lines.extend([f"{pad}\tEnd Site", f"{pad}\t{{", f"{pad}\t\tOFFSET 0.000000 0.000000 0.000000", f"{pad}\t}}"])
        lines.append(pad + "}")

    for root in children.get(-1, []):
        write(root, 0)

    euler = _euler_yxz(motion.local_rot)
    columns = []
    for j in order:
        if j in moving:
            columns.append(motion.local_pos[:, j])
        columns.append(euler[:, j])
    lines += ["MOTION", f"Frames: {motion.frames}", f"Frame Time: {motion.frame_time:.8f}"]
    lines += [" ".join(f"{v:.6f}" for v in row) for row in np.concatenate(columns, axis=1)]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
