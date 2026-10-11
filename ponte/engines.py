"""Os geradores de animação e qual está em uso.

O Kimodo original roda no Docker (``kimodo.py``); o kimodo.cpp, direto no Windows
(``kimodo_cpp.py``): é o mesmo modelo e o mesmo esqueleto nos dois. O ARDY (``ardy.py``) roda
no Ubuntu do WSL e é outro modelo, com esqueleto próprio. A vaga de geração é uma só para os
três. Quem escolhe é o usuário, ao abrir a ponte: a interface pergunta, e a escolha fica gravada
no acervo, para a linha de comando gerar no mesmo gerador que ele escolheu na tela.
"""

from __future__ import annotations

from . import ardy, kimodo, kimodo_cpp, store
from .config import DATA, SETTINGS

# Como cada gerador aparece para o usuário, o que tem de diferente e o que ainda não sabe fazer
# (``lacks``: a interface desliga esses controles do passo quando ele está escolhido).
ENGINES = {
    "kimodo": {
        "name": "Kimodo original",
        "about": "Roda no Docker. Tem laço, caminho e direção, e força do gesto. O text encoder ocupa uns 17 GB de RAM.",
        "lacks": [],
    },
    "cpp": {
        "name": "kimodo.cpp",
        "about": "Roda direto no Windows, sem Docker, na placa de vídeo: uns 30 segundos para 5 segundos de animação, e texto novo não custa mais. Ainda não tem laço, caminho e direção, nem força do gesto.",
        "lacks": ["travel", "loop", "text_weight"],
    },
    "ardy": {
        "name": "ARDY",
        "about": "Outro modelo da NVIDIA, em tempo real. Roda no Ubuntu, na placa de vídeo, e gera em menos de 1 minuto. Esqueleto próprio, de 27 juntas. Tem laço, caminho e direção, e força do gesto. Texto novo precisa do codificador de texto, que ocupa uns 16 GB de RAM por 3 a 5 minutos e é desligado em seguida; texto já usado, não.",
        "lacks": [],
    },
}
DEFAULT = "kimodo"
_FILE = DATA / "gerador.json"


def module(engine: str):
    """O módulo que gera: os dois têm ``generate`` com o mesmo contrato."""
    return {"kimodo": kimodo, "cpp": kimodo_cpp, "ardy": ardy}[engine]


def of(motion: dict) -> str:
    """Em qual gerador a animação foi feita (as de antes de haver dois são do original)."""
    return motion.get("engine") or DEFAULT


def current() -> str:
    """O gerador escolhido. Enquanto ninguém escolheu, o original."""
    chosen = (store.read_json(_FILE) or {}).get("engine")
    return chosen if chosen in ENGINES else DEFAULT


def problem(engine: str) -> str | None:
    """Por que este gerador não pode ser usado agora, ou None."""
    if engine == "cpp":
        lacking = kimodo_cpp.missing()
        return "Não está instalado por inteiro. Falta: " + "; ".join(lacking) + "." if lacking else None
    if engine == "ardy":
        lacking = ardy.missing()
        return "Não está instalado neste PC. Falta: " + "; ".join(lacking) + "." if lacking else None
    if not SETTINGS.kimodo_installed:
        return "Não está instalado neste PC. O guia para instalar está em docs/kimodo-setup/GUIA-KIMODO.md; depois, ponha installed = true na seção [kimodo] do ponte.toml."
    return None  # instalado, o original sobe o Docker e o text encoder sozinho, na hora de gerar


def choose(engine: str) -> str:
    if engine not in ENGINES:
        raise ValueError(f"Gerador desconhecido: {engine}. Use um de: {', '.join(ENGINES)}.")
    trouble = problem(engine)
    if trouble:
        raise ValueError(f"{ENGINES[engine]['name']}: {trouble}")
    store.write_json(_FILE, {"engine": engine, "chosen_at": store.now()})
    return engine


def status() -> dict:
    """Para a interface: qual está escolhido e o que cada um oferece."""
    return {"current": current(), "options": [{"id": key, **info, "problem": problem(key)} for key, info in ENGINES.items()]}
