"""Gerador do PonteAnimada. Roda DENTRO do container do Kimodo, não no Windows.

O `kimodo_gen` oficial só aceita texto e um arquivo de constraints pronto. Este
script usa a API Python do Kimodo para o que a interface precisa a mais:

- roteiro: uma tomada é uma lista de passos. Cada passo é gerado com os primeiros
  quadros presos aos últimos do passo anterior (corpo inteiro + mãos e pés), como o
  próprio Kimodo faz entre dois prompts, e tudo é emendado num clipe só. É isso que
  dá a transição entre uma ação e a seguinte, em vez de clipes soltos que não se ligam;
- continuar uma animação existente: o roteiro parte do fim dela (``continue_from``);
- trajetória por passo: o quadril segue uma linha reta numa direção e velocidade, ou
  passa por pontos, opcionalmente com o corpo travado para frente (de lado, de ré);
- laço: um passo com ``loop`` termina na pose em que começou (os últimos quadros presos
  aos do fim do passo anterior, deslocados pelo quanto ele andou). Tocado em repetição,
  depois do último quadro do passo vem o primeiro, sem tranco: é o clipe de ocioso ou de
  andar de um jogo.

Tudo roda em sequência com o modelo carregado uma vez só: nunca há duas animações
gerando ao mesmo tempo dentro deste processo.

Uso: python gerar.py <pasta>/job.json [--dry-run]   (as saídas vão para a mesma pasta)

Com ``--dry-run`` o modelo não é carregado e nada é gerado: o script só monta as
constraints, emenda e grava uma animação de mentira, para conferir o roteiro.

Convenções do Kimodo: Y para cima, metros, 30 fps. Com direção (heading) 0 o
personagem olha para +Z e a esquerda dele é +X; ``global_root_heading`` é
``[cos h, sin h]`` e o vetor "para frente" no chão é ``(x, z) = (sin h, cos h)``.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import torch

from kimodo import load_model
from kimodo.constraints import load_constraints_lst
from kimodo.exports.bvh import save_motion_bvh
from kimodo.exports.motion_io import complete_motion_dict, save_kimodo_npz
from kimodo.geometry import matrix_to_axis_angle, matrix_to_quaternion, quaternion_to_matrix
from kimodo.motion_rep.feature_utils import compute_heading_angle
from kimodo.skeleton import SOMASkeleton30
from kimodo.tools import seed_everything

END_EFFECTORS = ["LeftHand", "RightHand", "LeftFoot", "RightFoot"]
RAMP_FRAMES = 15  # quadros para a velocidade sair da anterior e chegar na pedida


def transition_constraints(prev: dict, n: int, skel77, device) -> tuple[list[dict], torch.Tensor, float, torch.Tensor]:
    """Constraints que prendem os ``n`` primeiros quadros nos ``n`` últimos de ``prev``.

    Devolve (constraints, origem XZ, heading inicial, velocidade XZ no fim de prev).
    Tudo é transladado para a transição começar na origem, como o modelo espera.
    """
    local = torch.from_numpy(prev["local_rot_mats"][-n:]).to(device).float()
    root = torch.from_numpy(prev["root_positions"][-n:]).to(device).float().clone()
    smooth = torch.from_numpy(prev["smooth_root_pos"][-n:]).to(device).float()[:, [0, 2]].clone()
    posed = torch.from_numpy(prev["posed_joints"][-n:]).to(device).float()

    origin = smooth[0].clone()
    root[:, [0, 2]] -= origin
    smooth -= origin
    heading = float(compute_heading_angle(posed[None], skel77)[0, 0])
    velocity = (smooth[-1] - smooth[-2]) if n >= 2 else torch.zeros(2, device=device)

    base = {
        "frame_indices": list(range(n)),
        "local_joints_rot": matrix_to_axis_angle(local).tolist(),
        "root_positions": root.tolist(),
        "smooth_root_2d": smooth.tolist(),
    }
    constraints = [{"type": "fullbody", **base}, {"type": "end-effector", "joint_names": END_EFFECTORS, **base}]
    return constraints, origin, heading, velocity


def loop_constraints(transition: list[dict], total: int, shift: torch.Tensor) -> list[dict]:
    """Constraints que prendem os últimos quadros na pose em que um laço começou.

    ``transition`` são as constraints do começo do laço (os últimos quadros do clipe antes
    dele) e ``shift`` leva as posições delas para onde o laço fecha. O último quadro do laço
    fica igual ao quadro logo antes do primeiro, então em repetição o movimento emenda.
    """
    dx, dz = float(shift[0]), float(shift[1])
    closing = []
    for constraint in transition:
        n = len(constraint["frame_indices"])
        closing.append(
            {
                **constraint,
                "frame_indices": list(range(total - n, total)),
                "root_positions": [[x + dx, y, z + dz] for x, y, z in constraint["root_positions"]],
                "smooth_root_2d": [[x + dx, z + dz] for x, z in constraint["smooth_root_2d"]],
            }
        )
    return closing


def travel_constraint(travel: dict, first: int, total: int, start: torch.Tensor, heading: float, v0: torch.Tensor | None, fps: float) -> dict:
    """Caminho do quadril nos quadros ``first``..``total-1``, partindo de ``start``.

    Duas formas, ambas relativas a para onde o personagem olha no início:

    - ``direction_deg`` + ``speed``: linha reta. 0 = frente, 90 = direita dele,
      180 = trás, 270 = esquerda. Metros por segundo.
    - ``waypoints``: lista de pontos ``[direita, frente]`` em metros; o caminho passa
      por eles em velocidade constante, terminando no último ao fim do clipe.
    """
    count = total - first
    start = start.cpu()
    forward = torch.tensor([math.sin(heading), math.cos(heading)])
    right = torch.tensor([-math.cos(heading), math.sin(heading)])

    if travel.get("waypoints"):
        points = [start] + [start + forward * float(f) + right * float(r) for r, f in travel["waypoints"]]
        lengths = [float((b - a).norm()) for a, b in zip(points, points[1:])]
        total_length = sum(lengths) or 1e-6
        path = []
        for i in range(count):
            remaining = total_length * (i + 1) / count
            for a, b, length in zip(points, points[1:], lengths):
                if remaining <= length or b is points[-1]:
                    path.append((a + (b - a) * min(1.0, remaining / max(length, 1e-6))).tolist())
                    break
                remaining -= length
    else:
        angle = math.radians(travel["direction_deg"])
        step = (forward * math.cos(angle) + right * math.sin(angle)) * (float(travel["speed"]) / fps)
        # Continuando uma animação, sai da velocidade em que ela vinha e chega suavemente
        # na pedida. Sem animação anterior, já entra na velocidade pedida.
        v0 = step if v0 is None else v0.cpu()
        pos = start.clone()
        path = []
        for i in range(count):
            w = min(1.0, (i + 1) / RAMP_FRAMES)
            w = w * w * (3 - 2 * w)
            pos = pos + v0 * (1 - w) + step * w
            path.append(pos.tolist())
    out = {"type": "root2d", "frame_indices": list(range(first, total)), "smooth_root_2d": path}
    if travel.get("lock_facing"):
        out["global_root_heading"] = [[math.cos(heading), math.sin(heading)]] * (total - first)
    return out


def join(prev: dict, local: torch.Tensor, root: torch.Tensor, n: int, device) -> tuple[torch.Tensor, torch.Tensor]:
    """Emenda ``prev`` com a continuação, misturando os ``n`` quadros em comum."""
    prev_local = torch.from_numpy(prev["local_rot_mats"]).to(device).float()
    prev_root = torch.from_numpy(prev["root_positions"]).to(device).float()
    alpha = torch.linspace(0.0, 1.0, n, device=device)  # 0 = anterior, 1 = nova

    q_prev = matrix_to_quaternion(prev_local[-n:])
    q_new = matrix_to_quaternion(local[:n])
    q_new = torch.where((q_prev * q_new).sum(-1, keepdim=True) < 0, -q_new, q_new)
    q = q_prev * (1 - alpha)[:, None, None] + q_new * alpha[:, None, None]
    blend_local = quaternion_to_matrix(q / q.norm(dim=-1, keepdim=True))
    blend_root = prev_root[-n:] * (1 - alpha)[:, None] + root[:n] * alpha[:, None]

    return torch.cat([prev_local[:-n], blend_local, local[n:]]), torch.cat([prev_root[:-n], blend_root, root[n:]])


def fake_step(total: int, n: int, constraints: list[dict], heading: float, device) -> dict:
    """Saída de mentira para ``--dry-run``: T-pose deslizando pelo caminho pedido.

    Tem o formato do que o modelo devolve, para o resto do script (emenda, gravação,
    constraints do passo seguinte) rodar sem gerar nada.
    """
    local = torch.eye(3, device=device).repeat(total, 77, 1, 1)
    c, s = math.cos(heading), math.sin(heading)
    local[:, 0] = torch.tensor([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], device=device)
    root = torch.zeros(total, 3, device=device)
    root[:, 1] = 0.95
    last = 0
    for constraint in constraints:
        if constraint["type"] not in ("fullbody", "root2d"):
            continue
        frames = constraint["frame_indices"]
        path = torch.tensor(constraint["smooth_root_2d"], device=device)
        root[frames, 0] = path[:, 0]
        root[frames, 2] = path[:, 1]
        last = max(last, frames[-1])
    root[last:, 0] = root[last, 0]
    root[last:, 2] = root[last, 2]
    return {"local_rot_mats": local[None], "root_positions": root[None]}


LOOP_CLOSING_S = (1.0, 2.0)  # a parte que traz o corpo de volta à pose inicial dura de 1 a 2 s


def run_segment(step: dict, frames: int, prev: dict | None, anchor: tuple | None, model, skel77, fps: float, denoise: int, n_transition: int, device) -> dict:
    """Gera ``frames`` quadros partindo do fim de ``prev`` e devolve a animação já emendada.

    ``anchor`` fecha um laço: são as constraints de transição do começo dele, com a origem e a
    direção delas. Os últimos quadros ficam presos naquela pose, no lugar em que o laço começou
    ou, com trajetória, onde o caminho chega.
    """
    constraints: list[dict] = []
    n = 0
    origin = torch.zeros(2, device=device)
    heading = 0.0
    start = torch.zeros(2)
    v0 = None
    if prev is not None:
        n = min(n_transition, int(prev["local_rot_mats"].shape[0]))
        constraints, origin, heading, v0 = transition_constraints(prev, n, skel77, device)
        start = torch.tensor(constraints[0]["smooth_root_2d"][-1])
    total = frames + n  # os quadros de transição não contam na duração pedida
    travel_heading = heading
    shift = torch.zeros(2)
    if anchor is not None:
        anchor_constraints, anchor_origin, anchor_heading = anchor
        # O laço anda na direção em que começou, mesmo que o corpo tenha virado um pouco no caminho.
        travel_heading = anchor_heading
        shift = (anchor_origin - origin).cpu()
    if step.get("travel"):
        path = travel_constraint(step["travel"], n, total, start, travel_heading, v0, fps)
        if anchor is not None:
            # Os últimos quadros são da pose de chegada: o caminho vai só até eles, e é onde
            # ele termina que o laço fecha.
            shift = torch.tensor(path["smooth_root_2d"][-1]) - torch.tensor(anchor_constraints[0]["smooth_root_2d"][-1])
            keep = total - n - len(anchor_constraints[0]["frame_indices"])
            path = {key: value[:keep] if isinstance(value, list) else value for key, value in path.items()}
        constraints.append(path)
    if anchor is not None:
        constraints += loop_constraints(anchor_constraints, total, shift)

    print(f"[ponte] passo: {step['text']} ({frames} quadros, {len(constraints)} constraint(s))", flush=True)
    if model is None:
        output = fake_step(total, n, constraints, heading, device)
    else:
        output = model(
            step["text"],
            total,
            constraint_lst=load_constraints_lst(constraints, model.skeleton) if constraints else [],
            # [texto, constraints]: quanto o movimento obedece a cada um. Mais peso no texto dá
            # um gesto mais marcado; o padrão do Kimodo é 2 para os dois.
            cfg_weight=[float(step.get("text_weight") or 2.0), 2.0],
            num_denoising_steps=denoise,
            num_samples=1,
            post_processing=True,
            first_heading_angle=torch.tensor([heading], device=device),
            return_numpy=False,
        )
    local = output["local_rot_mats"][0].float()
    root = output["root_positions"][0].float().clone()
    root[:, [0, 2]] += origin
    if prev is not None:
        local, root = join(prev, local, root, n, device)
    # Recalcula posições, raiz suavizada e contatos a partir das rotações finais: é disso
    # que o passo seguinte parte, e é o que vai no .npz e no .bvh.
    motion = complete_motion_dict(local, root, skel77, fps)
    return {k: v.detach().cpu().numpy() for k, v in motion.items()}


def run_step(step: dict, prev: dict | None, model, skel77, fps: float, denoise: int, n_transition: int, device) -> tuple[dict, int]:
    """Gera um passo do roteiro partindo do fim de ``prev``.

    Um passo em laço sai em duas partes: a primeira livre, para o movimento acontecer, e a
    segunda só para trazer o corpo de volta à pose em que o passo começou. Numa parte só, com
    o começo e o fim presos na mesma pose, o modelo quase não se mexe entre os dois.

    Devolve (animação já emendada, quadro em que este passo começa nela).
    """
    frames = max(1, int(round(float(step["seconds"]) * fps)))
    # O passo começa onde o anterior termina; os quadros antes disso são a transição.
    start_frame = 0 if prev is None else int(prev["local_rot_mats"].shape[0])
    how = (model, skel77, fps, denoise, n_transition, device)
    if not step.get("loop"):
        return run_segment(step, frames, prev, None, *how), start_frame

    closing = int(round(min(LOOP_CLOSING_S[1], max(LOOP_CLOSING_S[0], frames / fps / 3)) * fps))
    if prev is None or frames < 2 * closing:
        raise ValueError("Um passo em laço fecha na pose em que começa: precisa de um passo antes dele e de pelo menos 2 segundos.")
    n = min(n_transition, int(prev["local_rot_mats"].shape[0]))
    anchor_constraints, anchor_origin, anchor_heading, _ = transition_constraints(prev, n, skel77, device)
    print(f"[ponte] laço: {frames - closing} quadros livres + {closing} de volta à pose inicial", flush=True)
    motion = run_segment(step, frames - closing, prev, None, *how)
    motion = run_segment(step, closing, motion, (anchor_constraints, anchor_origin, anchor_heading), *how)
    return motion, start_frame


def run_take(take: dict, model, skel77, fps: float, denoise: int, folder: Path, device) -> list[dict]:
    """Um roteiro: os passos em sequência, cada um continuando o anterior, num clipe só.

    ``samples`` > 1 repete o roteiro inteiro com outra semente, uma variação depois da outra.
    """
    results = []
    for i in range(int(take.get("samples", 1))):
        seed_everything(int(take["seed"]) + i)
        motion = dict(np.load(folder / take["continue_from"])) if take.get("continue_from") else None
        marks = []
        print(f"[ponte] tomada '{take['name']}', variação {i + 1}: {len(take['steps'])} passo(s)", flush=True)
        for step in take["steps"]:
            motion, start_frame = run_step(step, motion, model, skel77, fps, denoise, int(take.get("transition_frames", 5)), device)
            marks.append(start_frame)
        stem = f"{take['name']}_{i:02d}"
        local = torch.from_numpy(motion["local_rot_mats"]).to(device)
        root = torch.from_numpy(motion["root_positions"]).to(device)
        save_kimodo_npz(str(folder / f"{stem}.npz"), motion)
        save_motion_bvh(str(folder / f"{stem}.bvh"), local, root, skeleton=skel77, fps=fps, standard_tpose=True)
        results.append({"take": take["name"], "sample": i + 1, "stem": stem, "frames": int(local.shape[0]), "step_frames": marks})
        print(f"[ponte] gravado {stem} ({local.shape[0]} quadros)", flush=True)
    return results


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    job_path = Path(next(a for a in sys.argv[1:] if not a.startswith("--")))
    folder = job_path.parent
    job = json.loads(job_path.read_text(encoding="utf-8"))
    device = "cuda:0" if torch.cuda.is_available() and not dry_run else "cpu"
    if dry_run:
        # Sem modelo: só monta as constraints, emenda e grava, para conferir o roteiro.
        print("[ponte] DRY-RUN: nada é gerado", flush=True)
        model, skel77, fps = None, SOMASkeleton30().somaskel77.to(device), 30.0
    else:
        print(f"[ponte] carregando {job['model']} em {device}", flush=True)
        model = load_model(job["model"], device=device, default_family="Kimodo")
        skeleton = model.skeleton
        skel77 = skeleton.somaskel77.to(device) if isinstance(skeleton, SOMASkeleton30) else skeleton
        fps = float(model.fps)

    results = []
    for take in job["takes"]:
        results += run_take(take, model, skel77, fps, int(job.get("steps", 100)), folder, device)
    (folder / "result.json").write_text(json.dumps({"fps": fps, "dry_run": dry_run, "outputs": results}, indent=2), encoding="utf-8")
    print("[ponte] concluído", flush=True)


if __name__ == "__main__":
    main()
