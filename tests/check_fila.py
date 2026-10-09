"""A fila do Kimodo: um pedido de cada vez, na ordem de chegada, entre threads e processos.

Não usa o Kimodo nem o Blender: só a vaga e a fila de ``ponte/kimodo.py``, num acervo
descartável. Confere:

- nunca há dois pedidos com a vaga ao mesmo tempo;
- quem espera entra na ordem em que chegou, inclusive quando um é outro processo (a linha
  de comando) e o outro é uma thread (o servidor);
- a senha de um processo que morreu esperando não trava a fila.

    uv run python tests/check_fila.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Outro processo na fila: avisa quando entrou e quando saiu, com a hora de cada um.
OTHER_PROCESS = """
import sys, time
from ponte import kimodo
with kimodo.generation_slots(1, lambda line: None):
    print("IN", time.time_ns(), flush=True)
    time.sleep(0.5)
    print("OUT", time.time_ns(), flush=True)
"""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(tempfile.mkdtemp(prefix="ponte-fila-"))
    os.environ["PONTE_DATA"] = str(work / "data")

    from ponte import kimodo

    problems: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    def until(condition, seconds: float = 20.0) -> bool:
        deadline = time.monotonic() + seconds
        while not condition():
            if time.monotonic() > deadline:
                return False
            time.sleep(0.05)
        return True

    try:
        expect(kimodo.KIMODO_MAX_SIMULTANEOUS == 1, f"a regra é um pedido de cada vez, mas o limite está em {kimodo.KIMODO_MAX_SIMULTANEOUS}")

        # 1. Quatro pedidos chegam um atrás do outro: um por vez, na ordem de chegada.
        events: list[tuple[str, int]] = []
        inside = 0
        most = 0
        guard = threading.Lock()

        def request(name: int) -> None:
            nonlocal inside, most
            with kimodo.generation_slots(1, lambda line: None):
                with guard:
                    inside += 1
                    most = max(most, inside)
                    events.append(("in", name))
                time.sleep(0.4)
                with guard:
                    inside -= 1

        threads = [threading.Thread(target=request, args=(i,)) for i in range(4)]
        with kimodo.generation_slots(1, lambda line: None):  # a vaga está ocupada enquanto eles chegam
            for i, thread in enumerate(threads):
                thread.start()
                expect(until(lambda: kimodo._waiting() == i + 1), f"o pedido {i} não entrou na fila")
        for thread in threads:
            thread.join(60)
        order = [name for _, name in events]
        expect(most == 1, f"{most} pedidos tiveram a vaga ao mesmo tempo")
        expect(order == [0, 1, 2, 3], f"os pedidos entraram fora da ordem de chegada: {order}")
        expect(kimodo._waiting() == 0 and kimodo.slots_in_use() == 0, "sobrou alguém na fila ou com a vaga")
        print(f"  · quatro pedidos: no máximo {most} por vez, ordem {order}")

        # 2. Com a vaga ocupada, chega outro processo e depois uma thread: entra primeiro o processo.
        thread_in: list[int] = []
        with kimodo.generation_slots(1, lambda line: None):
            proc = subprocess.Popen([sys.executable, "-c", OTHER_PROCESS], cwd=ROOT, env=os.environ.copy(), stdout=subprocess.PIPE, text=True)
            expect(until(lambda: kimodo._waiting() == 1), "o outro processo não entrou na fila")
            later = threading.Thread(target=lambda: _hold(kimodo, thread_in))
            later.start()
            expect(until(lambda: kimodo._waiting() == 2), "a thread não entrou na fila atrás do outro processo")
        out, _ = proc.communicate(timeout=60)
        later.join(60)
        marks = dict(line.split() for line in out.splitlines() if line.startswith(("IN", "OUT")))
        expect("IN" in marks and "OUT" in marks, f"o outro processo não chegou a ter a vaga: {out!r}")
        if "OUT" in marks and thread_in:
            expect(int(marks["OUT"]) <= thread_in[0], "a thread entrou antes de o outro processo sair, ou passou na frente dele")
        expect(bool(thread_in), "a thread nunca teve a vaga")
        print("  · processo e thread na fila: entrou primeiro quem chegou primeiro")

        # 3. Senha de quem morreu esperando: mais antiga que todas e destravada. Não pode travar a fila.
        dead = kimodo.QUEUE / "00000000000000000001-1-dead.senha"
        dead.parent.mkdir(parents=True, exist_ok=True)
        dead.write_text("")
        started = time.monotonic()
        with kimodo.generation_slots(1, lambda line: None):
            pass
        expect(time.monotonic() - started < 5, "uma senha abandonada segurou a fila")
        expect(not dead.exists(), "a senha abandonada continua na fila")
        print("  · senha abandonada: saiu da fila sem segurar ninguém")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(("FALHA " + "; ".join(problems)) if problems else "ok    fila do Kimodo: um de cada vez, na ordem de chegada")
    return 1 if problems else 0


def _hold(kimodo, entered: list[int]) -> None:
    with kimodo.generation_slots(1, lambda line: None):
        entered.append(time.time_ns())
        time.sleep(0.2)


if __name__ == "__main__":
    sys.exit(main())
