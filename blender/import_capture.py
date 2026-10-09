"""Leva um BVH de captura, de esqueleto qualquer, para o formato das animacoes do projeto.

Grava o BVH convertido (nomes do SOMA 77, centimetros, 30 quadros por segundo) e, ao lado
dele, ``captura.json`` com as medidas: o trecho usado, o laco, a altura do quadril em pe.
Nao usa nada do Blender alem do numpy que vem com ele.

Uso: blender --background --factory-startup --python import_capture.py -- \
        --bvh <captura.bvh> --out <motion.bvh> [--start <s>] [--end <s>] [--loop [<min s> <max s>]]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ponte_bl import capture, cli  # noqa: E402
from ponte_bl.bvh import save_bvh  # noqa: E402


def run(args: argparse.Namespace) -> dict:
    loop = None
    if args.loop is not None:
        if len(args.loop) not in (0, 2):
            raise ValueError("--loop aceita a duração mínima e a máxima do laço, em segundos, ou nada.")
        loop = tuple(args.loop) or capture.LOOP_SECONDS
    motion, info = capture.convert(args.bvh, start=args.start, end=args.end, loop=loop, direction=args.direction)
    save_bvh(motion, args.out)
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bvh", required=True, type=Path, help="a captura, como veio")
    ap.add_argument("--out", required=True, type=Path, help="o BVH convertido")
    ap.add_argument("--start", type=float, default=None, help="segundo do arquivo em que o trecho comeca")
    ap.add_argument("--end", type=float, default=None, help="segundo do arquivo em que o trecho termina")
    ap.add_argument("--loop", type=float, nargs="*", default=None, help="fica so o melhor laco do trecho; opcionalmente a duracao minima e a maxima, em segundos")
    ap.add_argument("--direction", type=float, default=None, help="para onde anda um laco que se desloca, em graus (0 = frente, 90 = direita dele)")
    args = ap.parse_args(cli.script_argv())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cli.run(lambda: run(args), args.out.with_name("captura.json"))


main()
