"""Gerador do PonteAnimada para o ARDY. Roda DENTRO do Ubuntu, no ambiente do ARDY, não no Windows.

O `scripts/generate.py` do ARDY aceita um texto só para o clipe inteiro. Este script usa a API
Python dele, do jeito que o demo interativo usa, para o que a ponte precisa a mais:

- roteiro: uma tomada é uma lista de passos, cada um com o texto dele. O ARDY gera em janelas
  de 40 quadros (2 s), cada uma partindo do que já existe; na virada do passo o texto muda e a
  transição sai do próprio modelo, num clipe só;
- continuar uma animação existente (``continue_from``): o que ela já tem é o histórico de onde
  o passo novo parte;
- trajetória por passo: o quadril passa por pontos de uma linha reta, numa direção e
  velocidade, ou de um caminho desenhado, opcionalmente com o corpo travado para frente;
- laço: um passo com ``loop`` termina na pose em que começou (os últimos quadros presos aos
  de antes do passo, deslocados pelo quanto ele andou);
- força do gesto: o peso do texto (``text_weight``; o padrão do ARDY é 2);
- textos: cada texto é codificado uma vez e fica guardado na pasta em que o demo guarda os
  dele. Só texto novo precisa do codificador no ar, que ocupa uns 16 GB de RAM;
- sessões do demo ao vivo (aba IO, *Export Session*): viram clipe no mesmo formato.

Uso, com a pasta do ARDY como pasta de trabalho:

    python gerar.py <pasta>/job.json               gera; as saídas vão para a mesma pasta
    python gerar.py <pasta>/job.json --dry-run     não carrega o modelo: só confere o roteiro
    python gerar.py <pasta>/job.json --textos      grava textos.json: os textos ainda não codificados
    python gerar.py <pasta>/job.json --codificar   codifica os que faltam (codificador no ar)
    python gerar.py --sessoes <saida.json>         lista as sessões exportadas pelo demo
    python gerar.py --sessao <arquivo.pkl> <pasta> [--inicio <s>] [--fim <s>]

O .npz de cada clipe fica no ritmo do ARDY (20 quadros por segundo): é dele que um passo
seguinte parte. O .bvh já sai no ritmo das animações do projeto (30).

Convenções do ARDY: Y para cima, metros, 20 quadros por segundo, esqueleto Core de 27 juntas
em pose T. Com direção (heading) 0 o personagem olha para +Z e a esquerda dele é +X; o vetor
"para frente" no chão é ``(x, z) = (sin h, cos h)``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

MODEL = "core"  # ARDY-Core-RP-20FPS-Horizon40
FPS = 20.0
PROJECT_FPS = 30.0  # o ritmo das animações do projeto: é o do .bvh
JOINTS = 27
# Onde o demo interativo guarda os textos já codificados e as sessões exportadas.
CACHE = Path(".cache") / "text_embeddings"
EXPORTS = Path(".cache") / "export"
ENCODER_URL = os.environ.get("TEXT_ENCODER_URL") or "http://127.0.0.1:9550/"

# Quadros do passo anterior que o passo novo enxerga: um token do modelo, o padrão do demo. É o
# bastante para a emenda sair contínua. Com 1 s (medido em 09/10/2026) o movimento novo fica
# preso ao anterior: um chute saiu com metade da altura e o "parado" depois dele não parou.
CARRY = 4
TRAVEL_EVERY = 10  # um ponto do caminho a cada tantos quadros (0,5 s): o quadril balança entre eles
LOOP_FRAMES = 4  # quadros do fim do laço presos nos de antes dele (um token do modelo)
RAMP_FRAMES = 10  # quadros para a velocidade sair da anterior e chegar na pedida
# A correção de pé roda nos quadros novos com 1 s do que veio antes, para o pé de apoio não
# recomeçar do zero na emenda; a diferença que sobra para o que já foi entregue some em 0,5 s.
POLISH_CONTEXT = 20
BLEND_FRAMES = 10


def say(text: str) -> None:
    print(f"[ponte] {text}", flush=True)


# --- Textos ---------------------------------------------------------------------------------


def cache_path(text: str) -> Path:
    """O mesmo nome que o demo dá ao arquivo de um texto: o que foi digitado lá vale aqui."""
    return CACHE / (hashlib.sha256(text.encode("utf-8")).hexdigest() + ".npy")


def job_texts(job: dict) -> list[str]:
    texts: list[str] = []
    for take in job["takes"]:
        for step in take["steps"]:
            if step["text"] not in texts:
                texts.append(step["text"])
    return texts


def missing_texts(job: dict) -> list[str]:
    return [text for text in job_texts(job) if not cache_path(text).exists()]


def encode_missing(job: dict) -> None:
    missing = missing_texts(job)
    if not missing:
        return
    from ardy.model.text_encoder_api import TextEncoderAPI

    encoder = TextEncoderAPI(ENCODER_URL)
    CACHE.mkdir(parents=True, exist_ok=True)
    for text in missing:
        say(f"codificando o texto: {text}")
        tensor, lengths = encoder([text])
        np.save(cache_path(text), np.ascontiguousarray(tensor[0, : int(lengths[0])].float().numpy(), dtype=np.float32))


# --- Esqueleto e arquivos -------------------------------------------------------------------


def core_skeleton():
    """O esqueleto Core do ARDY: (objeto, nomes, pais, deslocamento de cada junta em relação ao pai)."""
    from ardy.skeleton import CoreSkeleton27

    skeleton = CoreSkeleton27()
    rest = skeleton.neutral_joints.numpy().astype(np.float64)
    parents = [int(p) for p in skeleton.joint_parents.tolist()]
    offsets = np.array([rest[j] - rest[p] if p >= 0 else np.zeros(3) for j, p in enumerate(parents)])
    return skeleton, list(skeleton.bone_order_names), parents, offsets


def euler_zyx(rot: np.ndarray) -> np.ndarray:
    """(..., 3, 3) -> graus (..., 3) na ordem Z, Y, X, com R = Rz @ Ry @ Rx."""
    sy = np.clip(-rot[..., 2, 0], -1.0, 1.0)
    lock = np.abs(sy) > 1.0 - 1e-9  # Y a 90 graus: Z e X giram em torno do mesmo eixo
    z = np.where(lock, np.arctan2(-rot[..., 0, 1], rot[..., 1, 1]), np.arctan2(rot[..., 1, 0], rot[..., 0, 0]))
    x = np.where(lock, 0.0, np.arctan2(rot[..., 2, 1], rot[..., 2, 2]))
    return np.degrees(np.stack([z, np.arcsin(sy), x], axis=-1))


def write_bvh(path: Path, names: list[str], parents: list[int], offsets: np.ndarray, local_rot: np.ndarray, root_pos: np.ndarray, fps: float) -> None:
    """Grava o clipe em BVH: centímetros, pose de descanso em T, o quadril com a posição dele."""
    children: dict[int, list[int]] = {}
    for j, p in enumerate(parents):
        children.setdefault(p, []).append(j)
    order: list[int] = []  # os canais seguem a ordem em que as juntas são escritas
    lines = ["HIERARCHY"]

    def write(j: int, depth: int) -> None:
        pad = "\t" * depth
        order.append(j)
        lines.append(f"{pad}{'ROOT' if parents[j] < 0 else 'JOINT'} {names[j]}")
        lines.append(pad + "{")
        lines.append(f"{pad}\tOFFSET " + " ".join(f"{100.0 * v:.6f}" for v in offsets[j]))
        lines.append(f"{pad}\tCHANNELS " + ("6 Xposition Yposition Zposition " if parents[j] < 0 else "3 ") + "Zrotation Yrotation Xrotation")
        for child in children.get(j, []):
            write(child, depth + 1)
        if j not in children:
            lines.extend([f"{pad}\tEnd Site", f"{pad}\t{{", f"{pad}\t\tOFFSET 0.000000 0.000000 0.000000", f"{pad}\t}}"])
        lines.append(pad + "}")

    for root in children[-1]:
        write(root, 0)
    frames = len(local_rot)
    rows = np.concatenate([100.0 * np.asarray(root_pos, dtype=np.float64), euler_zyx(np.asarray(local_rot, dtype=np.float64))[:, order].reshape(frames, -1)], axis=1)
    lines += ["MOTION", f"Frames: {frames}", f"Frame Time: {1.0 / fps:.8f}"]
    lines += [" ".join(f"{v:.6f}" for v in row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def project_frame(frame: int) -> int:
    """Um quadro do ARDY no ritmo do projeto (a mesma conta de ``ponte/ardy.py``)."""
    return (int(PROJECT_FPS) * frame + int(FPS) // 2) // int(FPS)


def to_project_rate(local_rot: np.ndarray, root_pos: np.ndarray, marks: list[int], loops: list[bool]) -> tuple[np.ndarray, np.ndarray]:
    """O clipe a 30 quadros por segundo, passo a passo.

    Cada quadro novo é a mistura dos dois do ARDY entre os quais ele cai. No fim de um passo
    em laço o quadro seguinte é o primeiro do próprio laço, deslocado pelo quanto ele andou:
    é o que faz o laço fechar também neste ritmo. Reamostrado como um clipe corrido, o passo
    em laço saía um quadro curto e pulava na emenda (medido: 5 cm).
    """
    frames = len(local_rot)
    bounds = [*marks, frames]
    out_rot, out_pos = [], []
    for a, b, loop in zip(bounds, bounds[1:], loops):
        rot, pos = local_rot[a:b], root_pos[a:b]
        if loop and a:
            after_rot, after_pos = local_rot[a], root_pos[a] + (root_pos[b - 1] - root_pos[a - 1]) * np.array([1.0, 0.0, 1.0])
        else:
            after_rot, after_pos = (local_rot[b], root_pos[b]) if b < frames else (local_rot[b - 1], root_pos[b - 1])
        rot, pos = np.concatenate([rot, after_rot[None]]), np.concatenate([pos, after_pos[None]])
        t = np.arange(project_frame(a), project_frame(b)) * (FPS / PROJECT_FPS) - a
        i = np.clip(np.floor(t + 1e-6).astype(int), 0, b - a - 1)
        w = np.clip(t - i, 0.0, 1.0)
        mixed = (1.0 - w)[:, None, None, None] * rot[i] + w[:, None, None, None] * rot[i + 1]
        u, _, vt = np.linalg.svd(mixed)  # a rotação mais próxima da mistura
        u[np.linalg.det(u @ vt) < 0, :, -1] *= -1.0
        out_rot.append(u @ vt)
        out_pos.append((1.0 - w)[:, None] * pos[i] + w[:, None] * pos[i + 1])
    return np.concatenate(out_rot), np.concatenate(out_pos)


def save_clip(folder: Path, stem: str, skeleton_info: tuple, local_rot: np.ndarray, root_pos: np.ndarray, tensor: np.ndarray | None, marks: list[int], loops: list[bool]) -> None:
    """O .bvh é o que a ponte aplica no personagem; o .npz, de onde um passo seguinte parte.

    ``marks`` e ``loops``: o quadro em que cada passo do clipe começa e se ele é um laço.
    """
    _, names, parents, offsets = skeleton_info
    local_rot, root_pos = np.asarray(local_rot, dtype=np.float64), np.asarray(root_pos, dtype=np.float64)
    arrays = {"local_rot_mats": local_rot.astype(np.float32), "root_positions": root_pos.astype(np.float32), "fps": np.asarray(FPS), "marks": np.asarray(marks, dtype=np.int64), "loops": np.asarray(loops, dtype=bool)}
    if tensor is not None:
        arrays["motion_tensor"] = tensor.astype(np.float32)
    np.savez(folder / f"{stem}.npz", **arrays)
    write_bvh(folder / f"{stem}.bvh", names, parents, offsets, *to_project_rate(local_rot, root_pos, marks, loops), PROJECT_FPS)


def clip_steps(previous) -> tuple[list[int], list[bool]]:
    """Onde começa cada passo do clipe de que se parte, e quais são laço."""
    if previous is None or "marks" not in previous.files:
        return ([0], [False]) if previous is not None else ([], [])
    return [int(v) for v in previous["marks"]], [bool(v) for v in previous["loops"]]


# --- Geração --------------------------------------------------------------------------------


def window_frames(history: int, horizon: int, patch: int, max_window: int, first: int, last_constraint: int | None) -> int:
    """Quantos quadros o modelo enxerga numa janela: o histórico, os 40 que ele gera e, havendo
    constraint adiante, o futuro até ela (a conta do ``compute_window_num_frames`` do demo)."""
    frames = history + horizon
    if last_constraint is not None:
        frames = max(frames, last_constraint - first + 1)
        frames = min(frames, (max_window - horizon) // patch * patch + history + horizon)
        frames = math.ceil(frames / patch) * patch
    return max(min(frames, max_window), history + horizon)


def rollout(model, tensor, start: int, end: int, text_feat, weights: tuple[float, float], denoise: int, conditions, device):
    """Gera os quadros ``start``..``end - 1`` em cima do que ``tensor`` já tem. Devolve o clipe até ``end``."""
    import torch

    patch, horizon = model.num_frames_per_token, model.gen_horizon_len
    max_window = int(10 * model.motion_rep.fps) // patch * patch  # o modelo foi treinado em janelas de até 10 s
    max_history = (max_window - horizon) // patch * patch
    pad_mask = torch.ones(1, text_feat.shape[1], device=device, dtype=torch.bool)
    tensor = None if tensor is None or start == 0 else tensor[:, :start]
    cur = start
    while cur < end:
        first = max(start - CARRY, cur - max_history, 0)
        history = (cur - first) // patch * patch
        first = cur - history
        if cur and not history:
            raise ValueError("A animação de onde o passo parte é curta demais para servir de histórico.")
        observed = mask = None
        last = conditions[2] if conditions is not None and conditions[2] >= cur else None
        frames = window_frames(history, horizon, patch, max_window, first, last)
        if last is not None:
            observed, mask = conditions[0][:, first : first + frames].clone(), conditions[1][:, first : first + frames].clone()
            observed[:, :history], mask[:, :history] = 0.0, 0.0  # o histórico não é constraint
        samples = model.autoregressive_step(
            num_frames=frames,
            num_denoising_steps=denoise,
            motion_mask=mask,
            observed_motion=observed,
            cfg_weight=weights,
            text_feat=text_feat,
            text_pad_mask=pad_mask,
            init_history_sequence=tensor[:, first:cur] if history else None,
        )
        new = samples[:, history : history + horizon]
        tensor = new if tensor is None else torch.cat([tensor[:, :cur], new], dim=1)
        cur += horizon
    return tensor[:, :end]


def step_constraints(model, shown: tuple | None, step: dict, start: int, end: int, device) -> list:
    """As constraints do passo, em quadros do clipe: os pontos da trajetória e o fecho do laço.

    ``shown`` é o clipe como ele é visto até aqui (rotações locais e posição do quadril).
    """
    import torch
    from ardy.constraints import FullBodyConstraintSet, Root2DConstraintSet
    from ardy.motion_rep.tools import compute_heading_angle

    travel, loop = step.get("travel"), bool(step.get("loop"))
    if not travel and not loop:
        return []
    skeleton = model.skeleton
    count = end - start
    # De onde o passo parte: o quadril e a direção do corpo no último quadro que já existe.
    origin, heading, v0 = np.zeros(2), 0.0, None
    ref_rots = ref_joints = None
    if start:
        first = max(start - LOOP_FRAMES, 0)
        ref_rots, ref_joints, _ = skeleton.fk(shown[0][first:start], shown[1][first:start])
        root = shown[1][first:start][:, [0, 2]].cpu().numpy().astype(np.float64)
        origin = root[-1]
        heading = float(compute_heading_angle(ref_joints[None], skeleton)[0, -1])
        v0 = root[-1] - root[-2] if len(root) > 1 else None
    forward = np.array([math.sin(heading), math.cos(heading)])
    right = np.array([-math.cos(heading), math.sin(heading)])

    constraints = []
    path = None
    if travel and travel.get("waypoints"):
        # Pontos [direita, frente] em metros: o caminho passa por eles em velocidade constante
        # e termina no último ao fim do passo.
        points = [origin] + [origin + forward * float(f) + right * float(r) for r, f in travel["waypoints"]]
        lengths = [float(np.linalg.norm(b - a)) for a, b in zip(points, points[1:])]
        total = sum(lengths) or 1e-6
        path = np.empty((count, 2))
        for i in range(count):
            remaining = total * (i + 1) / count
            for a, b, length in zip(points, points[1:], lengths):
                if remaining <= length or b is points[-1]:
                    path[i] = a + (b - a) * min(1.0, remaining / max(length, 1e-6))
                    break
                remaining -= length
    elif travel:
        # Linha reta: 0 = frente, 90 = direita dele, 180 = trás, 270 = esquerda. Metros por segundo.
        angle = math.radians(travel["direction_deg"])
        stride = (forward * math.cos(angle) + right * math.sin(angle)) * (float(travel["speed"]) / FPS)
        # Um laço anda no mesmo ritmo do começo ao fim. Fora dele, o passo sai da velocidade em
        # que o clipe vinha e chega aos poucos na pedida.
        v0 = stride if loop or v0 is None else v0
        path = np.empty((count, 2))
        pos = origin.copy()
        for i in range(count):
            w = 1.0 if loop else min(1.0, (i + 1) / RAMP_FRAMES)
            w = w * w * (3 - 2 * w)
            pos = pos + v0 * (1 - w) + stride * w
            path[i] = pos
    if path is not None:
        # No fim de um laço quem manda é a pose de chegada: o caminho vai só até antes dela.
        limit = count - (LOOP_FRAMES if loop else 0)
        # O primeiro ponto fica a 1 s do começo: preso antes disso, um caminho que sai em outra
        # direção dá um tranco na emenda com o que vinha antes (medido: 6 cm num quadro).
        marks = sorted({*range(2 * TRAVEL_EVERY - 1, limit, TRAVEL_EVERY), *([] if loop else [count - 1])})
        if marks:
            facing = None
            if travel.get("lock_facing"):
                # Corpo travado para frente: anda de lado ou de ré sem virar.
                facing = [heading] * len(marks)
            elif travel.get("waypoints"):
                # Num caminho desenhado o corpo acompanha o caminho. Sem isto o ARDY chegou aos
                # pontos andando em diagonal, sem virar.
                facing = [math.atan2(*(path[i] - path[i - 1])) for i in marks]
            constraints.append(
                Root2DConstraintSet(
                    skeleton,
                    frame_indices=torch.tensor([start + i for i in marks]),
                    root_2d=torch.tensor(path[marks], dtype=torch.float32, device=device),
                    global_root_heading=torch.tensor(facing, dtype=torch.float32, device=device) if facing else None,
                )
            )
    if loop:
        if ref_joints is None or count < 4 * LOOP_FRAMES:
            raise ValueError("Um passo em laço fecha na pose em que começa: precisa de um passo antes dele e de pelo menos 1 segundo.")
        n = ref_joints.shape[0]
        shift = path[-1] - origin if path is not None else np.zeros(2)
        positions = ref_joints.clone()
        positions[..., 0] += float(shift[0])
        positions[..., 2] += float(shift[1])
        constraints.append(FullBodyConstraintSet(skeleton, frame_indices=torch.arange(end - n, end), global_joints_positions=positions, global_joints_rots=ref_rots))
    return constraints


def polish(model, raw, shown: tuple | None, first_new: int, constraints: list, device) -> tuple:
    """A correção de pé do ARDY nos quadros novos (de ``first_new`` em diante). Devolve o clipe
    como ele fica: o que já tinha sido entregue, igual, e os quadros novos corrigidos.

    Corrigir só os quadros novos, sozinhos, dá um tranco na emenda (medido: 7 cm num quadro, com
    o personagem andando): o pé de apoio recomeça do zero. Por isso a correção vê também o fim
    do que veio antes, e o que ela mudaria ali vira um desvio que some aos poucos nos quadros novos.
    """
    import torch
    from ardy.geometry import axis_angle_to_matrix, matrix_to_axis_angle
    from ardy.postprocess import post_process_motion

    context = min(POLISH_CONTEXT, first_new)
    begin = first_new - context
    out = model.motion_rep.inverse(raw[:, begin:], is_normalized=True)
    fixed = post_process_motion(
        out["local_rot_mats"],
        out["root_positions"],
        out["foot_contacts"],
        model.skeleton,
        constraint_lst=[c.crop_move(begin, int(raw.shape[1])) for c in constraints] or None,
    )
    local, root = fixed["local_rot_mats"][0].to(device).float(), fixed["root_positions"][0].to(device).float()
    if not context:
        return local, root
    seam = context - 1  # o último quadro já entregue, como a correção o deixaria agora
    turn = matrix_to_axis_angle(shown[0][first_new - 1] @ local[seam].transpose(-1, -2))
    move = shown[1][first_new - 1] - root[seam]
    local, root = local[context:].clone(), root[context:].clone()
    fade = min(BLEND_FRAMES, len(local))
    for t in range(fade):
        w = (t + 1) / (fade + 1)
        w = 1.0 - w * w * (3 - 2 * w)
        local[t] = axis_angle_to_matrix(turn * w) @ local[t]
        root[t] = root[t] + move * w
    return torch.cat([shown[0][:first_new], local]), torch.cat([shown[1][:first_new], root])


def run_take(take: dict, model, skeleton_info: tuple, denoise: int, folder: Path, device) -> list[dict]:
    """Um roteiro: os passos em sequência, cada um continuando o anterior, num clipe só.

    ``samples`` > 1 repete o roteiro inteiro com outra semente, uma variação depois da outra.
    """
    import torch
    from ardy.tools import seed_everything

    rep = model.motion_rep
    patch, horizon = model.num_frames_per_token, model.gen_horizon_len
    max_window = int(10 * rep.fps) // patch * patch
    results = []
    for i in range(int(take.get("samples", 1))):
        seed_everything(int(take["seed"]) + i)
        # ``raw`` é o movimento como o modelo o gerou: é dele que cada janela parte. ``shown`` é o
        # clipe como é visto (rotações locais, posição do quadril): o que já foi entregue, com a
        # correção de pé, e os quadros deste pedido, que só a recebem no fim.
        raw = shown = previous = None
        if take.get("continue_from"):
            previous = np.load(folder / take["continue_from"])
            if "motion_tensor" not in previous.files:
                raise ValueError("A animação a continuar não traz os dados do ARDY (foi feita num ensaio a seco?).")
            raw = torch.from_numpy(previous["motion_tensor"])[None].to(device)
            shown = (torch.from_numpy(previous["local_rot_mats"]).to(device), torch.from_numpy(previous["root_positions"]).to(device))
        first_new = 0 if raw is None else int(raw.shape[1])
        marks, constraints = [], []
        old_marks, old_loops = clip_steps(previous)
        say(f"tomada '{take['name']}', variação {i + 1}: {len(take['steps'])} passo(s)")
        for step in take["steps"]:
            start = 0 if raw is None else int(raw.shape[1])
            end = start + max(patch, int(round(float(step["seconds"]) * FPS)))
            mine = step_constraints(model, shown, step, start, end, device)
            conditions = None
            if mine:
                observed, mask = rep.create_conditions_from_constraints(mine, end + max_window, to_normalize=True, device=device)
                conditions = (observed[None], mask[None], max(int(c.frame_indices.max()) for c in mine))
            embedding = torch.from_numpy(np.load(cache_path(step["text"])))[None].to(device=device, dtype=torch.bfloat16 if device != "cpu" else torch.float32)
            say(f"passo: {step['text']} ({end - start} quadros em {math.ceil((end - start) / horizon)} janela(s), {len(mine)} constraint(s))")
            # [texto, constraints]: quanto o movimento obedece a cada um. O padrão do ARDY é 2 para os dois.
            weights = (float(step.get("text_weight") or 2.0), 2.0)
            raw = rollout(model, raw, start, end, embedding, weights, denoise, conditions, device)
            out = rep.inverse(raw[:, start:end], is_normalized=True)
            new = (out["local_rot_mats"][0].float(), out["root_positions"][0].float())
            shown = new if shown is None else (torch.cat([shown[0][:start], new[0]]), torch.cat([shown[1][:start], new[1]]))
            constraints += mine
            marks.append(start)
        local, root = polish(model, raw, shown, first_new, constraints, device)
        stem = f"{take['name']}_{i:02d}"
        save_clip(folder, stem, skeleton_info, local.cpu().numpy(), root.cpu().numpy(), raw[0].float().cpu().numpy(), old_marks + marks, old_loops + [bool(s.get("loop")) for s in take["steps"]])
        results.append({"take": take["name"], "sample": i + 1, "stem": stem, "frames": int(raw.shape[1]), "step_frames": marks})
        say(f"gravado {stem} ({raw.shape[1]} quadros)")
    return results


def dry_take(take: dict, skeleton_info: tuple, folder: Path) -> list[dict]:
    """Ensaio a seco: o personagem parado em pose T pelo tempo do roteiro, sem carregar o modelo."""
    rest_height = -float(skeleton_info[0].neutral_joints[:, 1].min())
    results = []
    for i in range(int(take.get("samples", 1))):
        local, root, previous = np.empty((0, JOINTS, 3, 3)), np.empty((0, 3)), None
        if take.get("continue_from"):
            previous = np.load(folder / take["continue_from"])
            local, root = previous["local_rot_mats"], previous["root_positions"]
        marks = []
        old_marks, old_loops = clip_steps(previous)
        for step in take["steps"]:
            frames = max(4, int(round(float(step["seconds"]) * FPS)))
            say(f"passo: {step['text']} ({frames} quadros)")
            marks.append(len(local))
            local = np.concatenate([local, np.tile(np.eye(3), (frames, JOINTS, 1, 1))])
            root = np.concatenate([root, np.tile([0.0, rest_height, 0.0], (frames, 1))])
        stem = f"{take['name']}_{i:02d}"
        save_clip(folder, stem, skeleton_info, local, root, None, old_marks + marks, old_loops + [False] * len(marks))
        results.append({"take": take["name"], "sample": i + 1, "stem": stem, "frames": len(local), "step_frames": marks})
    return results


def generate(job_path: Path, dry_run: bool) -> None:
    folder = job_path.parent
    job = json.loads(job_path.read_text(encoding="utf-8"))
    skeleton_info = core_skeleton()
    results = []
    if dry_run:
        say("DRY-RUN: nada é gerado")
        model_name, denoise = MODEL, 0
        for take in job["takes"]:
            results += dry_take(take, skeleton_info, folder)
    else:
        import torch
        from ardy.model import load_model
        from ardy.model.registry import resolve_model_name

        lacking = missing_texts(job)
        if lacking:
            raise ValueError("Texto ainda não codificado: " + " | ".join(lacking))
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        model_name = resolve_model_name(MODEL)
        say(f"carregando {model_name} em {device}")
        model = load_model(MODEL, device=device, text_encoder=False)
        # O ARDY usa poucos passos de difusão (10 neste modelo): mais que isso ele não aceita.
        denoise = int(model.diffusion.num_base_steps)
        with torch.no_grad():
            for take in job["takes"]:
                results += run_take(take, model, skeleton_info, denoise, folder, device)
    (folder / "result.json").write_text(json.dumps({"fps": FPS, "dry_run": dry_run, "model": model_name, "diffusion_steps": denoise, "outputs": results}, indent=2), encoding="utf-8")
    say("concluído")


# --- Sessões do demo ao vivo ---------------------------------------------------------------


def read_session(path: Path) -> dict:
    """Uma sessão exportada pelo demo (aba IO, *Export Session*): movimento, textos e constraints."""
    import pickle

    with path.open("rb") as f:
        data = pickle.load(f)  # noqa: S301 - arquivo gravado pelo demo do ARDY nesta máquina
    if not isinstance(data, dict):
        raise ValueError("O arquivo não é uma sessão do demo do ARDY.")
    return data


def session_prompts(data: dict, frames: int) -> list[dict]:
    """Os textos da linha do tempo, na ordem, cada um com o quadro em que começa a valer."""
    prompts = sorted((p for p in data.get("prompts") or [] if p.get("text")), key=lambda p: int(p.get("start_frame", 0)))
    return [{"text": str(p["text"]), "start_frame": max(0, int(p.get("start_frame", 0)))} for p in prompts if int(p.get("start_frame", 0)) < frames]


def session_summary(path: Path) -> dict:
    row = {"file": path.name, "modified": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")}
    try:
        data = read_session(path)
        motion = data.get("motion") or {}
        frames = int(np.asarray(motion["joints_pos"]).shape[1]) if motion.get("joints_pos") is not None else 0
        fps = float(data.get("model_fps") or FPS)
        joints = int(np.asarray(motion["joints_pos"]).shape[2]) if frames else 0
        row.update(frames=frames, fps=fps, seconds=round(frames / fps, 2), joints=joints, prompts=[p["text"] for p in session_prompts(data, frames)])
    except Exception as exc:  # noqa: BLE001 - uma sessão ilegível não esconde as outras
        row["error"] = str(exc)
    return row


def list_sessions(out: Path) -> None:
    files = sorted(EXPORTS.glob("*.pkl"), key=lambda p: p.stat().st_mtime, reverse=True) if EXPORTS.is_dir() else []
    out.write_text(json.dumps({"folder": str(EXPORTS.resolve()), "sessions": [session_summary(p) for p in files]}, ensure_ascii=False, indent=2), encoding="utf-8")


def convert_session(path: Path, folder: Path, begin: float | None, finish: float | None) -> None:
    """Grava a sessão como clipe (sessao.bvh e sessao.npz) e o que a ponte precisa saber dela (sessao.json)."""
    data = read_session(path)
    motion = data.get("motion") or {}
    if motion.get("local_rot_mats") is None or motion.get("root_positions") is None:
        raise ValueError("Esta sessão não traz movimento: exporte de novo, no demo, depois de o boneco ter andado.")
    local, root = np.asarray(motion["local_rot_mats"])[0], np.asarray(motion["root_positions"])[0]
    if local.shape[1] != JOINTS:
        raise ValueError(f"A sessão foi gravada num esqueleto de {local.shape[1]} juntas; a ponte lê o Core, de {JOINTS} (o modelo padrão do demo).")
    fps = float(data.get("model_fps") or FPS)
    if abs(fps - FPS) > 1e-6:
        raise ValueError(f"A sessão está a {fps:g} quadros por segundo; a ponte lê as do modelo Core, a {FPS:g}.")
    tensor = np.asarray(motion["motion_tensor"])[0] if motion.get("motion_tensor") is not None else None
    a = 0 if begin is None else max(0, int(round(begin * FPS)))
    b = len(local) if finish is None else min(len(local), int(round(finish * FPS)))
    if b - a < 4:
        raise ValueError(f"O trecho pedido não tem quadros: a sessão vai de 0 a {len(local) / FPS:.1f} s.")
    steps = []
    for prompt in session_prompts(data, b):
        at = max(prompt["start_frame"], a) - a
        if steps and steps[-1]["start_frame"] == at:
            steps[-1] = {"text": prompt["text"], "start_frame": at}  # o texto anterior acabou antes do trecho
        else:
            steps.append({"text": prompt["text"], "start_frame": at})
    if steps:
        steps[0]["start_frame"] = 0
    folder.mkdir(parents=True, exist_ok=True)
    save_clip(folder, "sessao", core_skeleton(), local[a:b], root[a:b], tensor[a:b] if tensor is not None and len(tensor) == len(local) else None, [0], [False])
    info = {"file": path.name, "exported_at": data.get("timestamp"), "frames": b - a, "fps": FPS, "seconds": [round(a / FPS, 3), round(b / FPS, 3)], "steps": steps, "continuable": tensor is not None and len(tensor) == len(local)}
    (folder / "sessao.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"sessão {path.name}: {b - a} quadros, {len(steps)} texto(s)")


def session_file(name: str) -> Path:
    """Uma sessão pelo nome (na pasta de exportação do demo) ou pelo caminho."""
    path = Path(name)
    for candidate in (path, EXPORTS / path.name, EXPORTS / f"{path.name}.pkl"):
        if candidate.is_file():
            return candidate
    raise ValueError(f"Não achei a sessão '{name}' em {EXPORTS.resolve()}.")


def main() -> None:
    args = sys.argv[1:]

    def option(flag: str) -> float | None:
        return float(args[args.index(flag) + 1]) if flag in args else None

    if "--sessoes" in args:
        list_sessions(Path(args[args.index("--sessoes") + 1]))
    elif "--sessao" in args:
        at = args.index("--sessao")
        convert_session(session_file(args[at + 1]), Path(args[at + 2]), option("--inicio"), option("--fim"))
    else:
        job_path = Path(next(a for a in args if not a.startswith("--")))
        if "--textos" in args:
            job = json.loads(job_path.read_text(encoding="utf-8"))
            (job_path.parent / "textos.json").write_text(json.dumps({"missing": missing_texts(job)}, ensure_ascii=False), encoding="utf-8")
        elif "--codificar" in args:
            encode_missing(json.loads(job_path.read_text(encoding="utf-8")))
        else:
            generate(job_path, "--dry-run" in args)


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        # O motivo, numa linha só: é o que a ponte mostra a quem pediu.
        print(f"[ponte] ERRO: {exc}", flush=True)
        sys.exit(2)
