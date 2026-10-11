"""Geração de animações no kimodo.cpp: o mesmo modelo do Kimodo, compilado para Windows.

O kimodo.cpp (https://github.com/localai-org/kimodo.cpp) roda o ``config.KIMODO_MODEL`` sem
Docker nem WSL. As regras fixas do projeto valem aqui do mesmo jeito:

- esqueleto único: ele devolve as 30 juntas que o modelo prevê; aqui elas vão para o SOMA 77
  de sempre, com os dedos na mesma pose relaxada (fixa) que o Kimodo oficial grava em toda
  animação. O BVH que sai é conferido contra a assinatura do esqueleto, como o do oficial;
- um pedido de cada vez: a vaga e a fila são as de ``kimodo.py``. Uma geração daqui e uma do
  Kimodo oficial também não rodam juntas.

O que ele ainda não tem (lido no código dele em 08/10/2026): caminho, direção e velocidade
impostos, laço, peso do texto e continuar de uma animação já gravada. Continuar um roteiro,
aqui, é gerá-lo de novo inteiro com a mesma semente: os passos de antes saem iguais e o novo
vem emendado neles.
"""

from __future__ import annotations

import array
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import kimodo
from .config import SETTINGS
from .kimodo import KimodoError

Log = Callable[[str], None]
FPS = 30
# Quadros do passo anterior a que o seguinte se prende (os mesmos 5 do gerador oficial daqui).
TRANSITION_FRAMES = 5
# Limites do kmd-generate: quadros por passo e passos por sequência.
MIN_FRAMES, MAX_FRAMES, MAX_STEPS = 2, 300, 16
TIMEOUT_S = 3600.0
# O SOMA 77 oficial em um quadro só: tudo em zero, menos os dedos, na pose relaxada.
TEMPLATE = Path(__file__).with_name("soma77_relaxed.bvh")
# As 30 juntas que o modelo prevê, na ordem em que o kimodo.cpp grava as rotações
# (``scripts/export_bvh.py`` de lá). As pontas dos dedos não entram no SOMA 77: ficam de fora.
JOINTS = (
    "Hips", "Spine1", "Spine2", "Chest", "Neck1", "Neck2", "Head", "Jaw", "LeftEye", "RightEye",
    "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand", "LeftHandThumbEnd", "LeftHandMiddleEnd",
    "RightShoulder", "RightArm", "RightForeArm", "RightHand", "RightHandThumbEnd", "RightHandMiddleEnd",
    "LeftLeg", "LeftShin", "LeftFoot", "LeftToeBase", "RightLeg", "RightShin", "RightFoot", "RightToeBase",
)  # fmt: skip
_FINGERTIPS = {name for name in JOINTS if name.endswith("End")}


def _files() -> dict[str, Path]:
    repo = Path(SETTINGS.cpp_repo)
    return {
        "o programa (kmd-generate.exe)": repo / "build" / "Release" / "kmd-generate.exe",
        "o modelo de movimento": repo / "models" / "kimodo-soma-rp-v1.1-f32.gguf",
        "o text encoder": repo / SETTINGS.cpp_text_encoder,
        "o tokenizer": repo / "tokenizer.gguf",
    }


def missing() -> list[str]:
    """O que falta para gerar por aqui. Lista vazia: está instalado."""
    if not SETTINGS.cpp_repo:
        return ["a pasta do kimodo.cpp (seção [kimodo_cpp] do ponte.toml)"]
    return [what for what, path in _files().items() if not path.is_file()]


def status() -> dict:
    lacking = missing()
    return {"installed": not lacking, "missing": lacking, "repo": SETTINGS.cpp_repo}


def check_script(steps: list[dict]) -> None:
    """Recusa, antes de ocupar a vaga, o roteiro que o kimodo.cpp não sabe gerar."""
    if len(steps) > MAX_STEPS:
        raise KimodoError(f"O kimodo.cpp gera no máximo {MAX_STEPS} passos num clipe (este roteiro tem {len(steps)}).")
    for i, step in enumerate(steps):
        frames = round(step["seconds"] * FPS)
        least = (TRANSITION_FRAMES + 1 if i else MIN_FRAMES) / FPS
        if not max(MIN_FRAMES, TRANSITION_FRAMES + 1 if i else 0) <= frames <= MAX_FRAMES:
            raise KimodoError(f"No kimodo.cpp cada passo vai de {least:.1f} a {MAX_FRAMES / FPS:g} segundos (o passo {i + 1} tem {step['seconds']:g}).")
        if step.get("travel"):
            raise KimodoError("O kimodo.cpp ainda não aceita caminho, direção nem velocidade: tire a trajetória do passo ou use o Kimodo original.")
        if step.get("loop"):
            raise KimodoError("O kimodo.cpp ainda não faz laço: desmarque o laço ou use o Kimodo original.")
        if step.get("text_weight") not in (None, 2, 2.0):
            raise KimodoError("O kimodo.cpp não muda o peso do texto (fica no padrão, 2): tire o peso ou use o Kimodo original.")


def _euler_zyx(x: float, y: float, z: float, w: float) -> tuple[float, float, float]:
    """Quaternion -> graus (Z, Y, X) com R = Rz @ Ry @ Rx: a ordem dos canais do BVH oficial."""
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    sy = max(-1.0, min(1.0, -2.0 * (x * z - y * w)))
    if abs(sy) > 1.0 - 1e-9:  # Y a 90 graus: Z e X giram em torno do mesmo eixo
        return math.degrees(math.atan2(-2.0 * (x * y - z * w), 1.0 - 2.0 * (x * x + z * z))), math.degrees(math.asin(sy)), 0.0
    return (
        math.degrees(math.atan2(2.0 * (x * y + z * w), 1.0 - 2.0 * (y * y + z * z))),
        math.degrees(math.asin(sy)),
        math.degrees(math.atan2(2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y))),
    )


def _template() -> tuple[str, dict[str, int], list[float]]:
    """Do molde: o cabeçalho oficial, em que coluna começa a rotação de cada junta, e o quadro de descanso."""
    head, _, motion = TEMPLATE.read_text(encoding="utf-8").partition("MOTION")
    tok = head.split()
    column, at, name = 0, {}, ""
    for i, t in enumerate(tok):
        if t in ("ROOT", "JOINT"):
            name = tok[i + 1]
        elif t == "CHANNELS":
            count = int(tok[i + 1])
            if tok[i + 2 + count - 3 : i + 2 + count] != ["Zrotation", "Yrotation", "Xrotation"]:
                raise KimodoError(f"O molde do SOMA 77 mudou: a junta {name} não tem os canais Z, Y, X de rotação.")
            at[name] = column + count - 3
            column += count
    rest = [float(v) for v in motion.split()[5:]]  # depois de "Frames: 1 Frame Time: <t>"
    if len(rest) != column:
        raise KimodoError("O molde do SOMA 77 está inconsistente (canais e valores não batem).")
    return head, at, rest


def write_soma77(root_positions: array.array, rotations: array.array, out: Path) -> int:
    """Grava no SOMA 77 o que o kimodo.cpp gerou: posição do quadril (metros) e rotações locais
    (x, y, z, w) das 30 juntas, quadro a quadro. Devolve quantos quadros gravou."""
    frames = len(root_positions) // 3
    if not frames or len(root_positions) != frames * 3 or len(rotations) != frames * len(JOINTS) * 4:
        raise KimodoError(f"A saída do kimodo.cpp não tem o formato esperado ({len(root_positions)} posições, {len(rotations)} rotações): o esqueleto dele mudou?")
    head, at, rest = _template()
    hips = at["Hips"] - 3  # o quadril traz a posição antes da rotação
    lines = [head.rstrip(), "MOTION", f"Frames: {frames}", f"Frame Time: {1.0 / FPS}"]
    for f in range(frames):
        row = list(rest)
        row[hips : hips + 3] = [100.0 * v for v in root_positions[f * 3 : f * 3 + 3]]  # metros -> centímetros
        for j, name in enumerate(JOINTS):
            if name not in _FINGERTIPS:
                row[at[name] : at[name] + 3] = _euler_zyx(*rotations[(f * len(JOINTS) + j) * 4 : (f * len(JOINTS) + j) * 4 + 4])
        lines.append(" ".join(f"{v:.6f}" for v in row))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return frames


def _read_f32(path: Path) -> array.array:
    values = array.array("f")
    values.frombytes(path.read_bytes())
    return values


def _run(cmd: list[str], log: Log) -> None:
    """Roda o kmd-generate. Ele só fala no fim: enquanto isso, um aviso de tempo em tempo."""
    repo = Path(SETTINGS.cpp_repo)
    env = {**os.environ, "PATH": f"{repo / 'build' / 'bin' / 'Release'};{repo / 'build' / 'Release'};{os.environ.get('PATH', '')}"}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    started = time.monotonic()
    while True:
        try:
            output, _ = proc.communicate(timeout=30)
            break
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started
            if elapsed > TIMEOUT_S:
                proc.kill()
                proc.communicate()
                raise KimodoError(f"O kimodo.cpp não terminou em {TIMEOUT_S / 60:.0f} minutos e foi interrompido.") from None
            log(f"kimodo.cpp gerando há {elapsed / 60:.1f} min")
    if proc.returncode != 0:
        raise KimodoError("O kimodo.cpp falhou: " + " | ".join(output.strip().splitlines()[-4:]))


def generate(work_dir: Path, takes: list[dict], *, steps: int = 100, dry_run: bool = False, log: Log = lambda _line: None) -> list[dict]:
    """O mesmo contrato de ``kimodo.generate``, no kimodo.cpp.

    Cada tomada traz o roteiro INTEIRO do clipe em ``steps`` (numa continuação, os passos de
    antes e o novo), ``seed`` e, opcionalmente, ``samples``. ``dry_run`` não roda o programa:
    grava o clipe com o personagem parado, só para conferir que o roteiro monta.

    Devolve [{take, sample, bvh, npz (sempre None), frames, step_frames, **bvh_summary}].
    """
    for take in takes:
        check_script(take["steps"])
    lacking = missing()
    if lacking and not dry_run:
        raise KimodoError("O kimodo.cpp não está instalado por inteiro. Falta: " + "; ".join(lacking) + ".")
    work_dir.mkdir(parents=True, exist_ok=True)
    files = _files()
    out: list[dict] = []
    # Dentro do job tudo roda em sequência (variações, tomadas): ocupa uma vaga só.
    with kimodo.generation_slots(1, log):
        for index, take in enumerate(takes):
            frames = [round(s["seconds"] * FPS) for s in take["steps"]]
            starts = [sum(frames[:i]) for i in range(len(frames))]
            pairs: list[str] = []
            for i, step in enumerate(take["steps"]):
                prompt = work_dir / f"passo_{index}_{i}.txt"
                prompt.write_text(step["text"], encoding="utf-8", newline="\n")
                pairs += [str(frames[i]), str(prompt)]
            for sample in range(1, int(take.get("samples", 1)) + 1):
                stem = f"{take['name']}_{index:02d}_s{sample}"
                raw = work_dir / stem
                raw.mkdir(exist_ok=True)
                bvh = work_dir / f"{stem}.bvh"
                if dry_run:
                    log(f"conferindo o roteiro (sem gerar): {len(frames)} passo(s), {sum(frames) / FPS:g}s no total")
                    still = array.array("f", [0.0, 1.0, 0.0] * sum(frames))
                    write_soma77(still, array.array("f", [0.0, 0.0, 0.0, 1.0] * (sum(frames) * len(JOINTS))), bvh)
                else:
                    log(f"gerando no kimodo.cpp: {len(frames)} passo(s), {sum(frames) / FPS:g}s no total (na placa de vídeo, uns 30 segundos para 5 de animação)")
                    seed = int(take["seed"]) + sample - 1
                    _run([str(files["o programa (kmd-generate.exe)"]), str(files["o modelo de movimento"]), str(files["o text encoder"]), "--sequence", str(TRANSITION_FRAMES), str(steps), str(seed), str(raw), *pairs], log)
                    written = write_soma77(_read_f32(raw / "root_positions.f32"), _read_f32(raw / "local_rotations_xyzw.f32"), bvh)
                    if written != sum(frames):
                        raise KimodoError(f"O kimodo.cpp devolveu {written} quadros para um roteiro de {sum(frames)}.")
                out.append({"take": take["name"], "sample": sample, "stem": stem, "bvh": bvh, "npz": None, "frames": sum(frames), "step_frames": starts, **kimodo.check_skeleton(bvh)})
    return out
