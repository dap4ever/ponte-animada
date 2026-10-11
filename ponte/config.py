"""Caminhos, configuração local e as regras fixas do projeto."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# O acervo fica em data/. PONTE_DATA aponta para outro lugar: os testes usam um acervo descartável.
DATA = Path(os.environ.get("PONTE_DATA") or ROOT / "data")
BLENDER_SCRIPTS = ROOT / "blender"
WEB = ROOT / "web"

# --- Regras fixas para gerar no Kimodo (definidas pelo dono do projeto) ----------
# 1. Sempre o mesmo esqueleto, para as animações não diferirem entre si.
KIMODO_MODEL = "Kimodo-SOMA-RP-v1.1"
KIMODO_SKELETON = "somaskel77"
# Assinatura da hierarquia (nomes + offsets) do BVH em T-pose padrão desse esqueleto.
# Todo BVH que entra no projeto precisa bater com ela.
KIMODO_SKELETON_SIGNATURE = "5011fba46cbc94dd5c39860d7513a337375678b3"
# 2. Um pedido de cada vez: nunca duas gerações ao mesmo tempo, para não sobrecarregar a
#    máquina (cada geração carrega o modelo na GPU). O que chega depois espera na fila.
KIMODO_MAX_SIMULTANEOUS = 1
# Variações de um mesmo pedido saem uma depois da outra, dentro da vez dele.
KIMODO_MAX_SAMPLES = 2


@dataclass(frozen=True)
class Settings:
    blender_exe: str
    wsl_distro: str
    wsl_user: str
    kimodo_repo: str
    docker_desktop: str
    text_encoder_url: str
    # O Kimodo original está instalado nesta máquina? (``installed = false`` no ponte.toml: não.)
    kimodo_installed: bool
    # kimodo.cpp: a pasta onde foi compilado (vazia: não instalado) e o text encoder baixado.
    cpp_repo: str
    cpp_text_encoder: str
    # ARDY: instalado no Ubuntu do WSL? Onde, com que usuário, e onde o codificador de texto dele responde.
    ardy_installed: bool
    ardy_distro: str
    ardy_user: str
    ardy_repo: str
    ardy_encoder_url: str
    host: str
    port: int


def load_settings() -> Settings:
    raw = tomllib.loads((ROOT / "ponte.toml").read_text(encoding="utf-8"))
    kimodo, cpp, ardy, server = raw.get("kimodo", {}), raw.get("kimodo_cpp", {}), raw.get("ardy", {}), raw.get("server", {})
    return Settings(
        blender_exe=raw["blender"]["exe"],
        wsl_distro=kimodo.get("distro", "Ubuntu"),
        wsl_user=kimodo.get("user", "root"),
        kimodo_repo=kimodo.get("repo", "~/kimodo"),
        docker_desktop=kimodo.get("docker_desktop", ""),
        text_encoder_url=kimodo.get("text_encoder_url", "http://localhost:9550/"),
        kimodo_installed=bool(kimodo.get("installed", True)),
        cpp_repo=cpp.get("repo", ""),
        cpp_text_encoder=cpp.get("text_encoder", "Llama-3-Kimodo-Q8_0.gguf"),
        ardy_installed=bool(ardy.get("installed", False)),
        ardy_distro=ardy.get("distro", "Ubuntu"),
        ardy_user=ardy.get("user", ""),
        ardy_repo=ardy.get("repo", "~/ardy"),
        ardy_encoder_url=ardy.get("text_encoder_url", "http://127.0.0.1:9550/"),
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8765)),
    )


SETTINGS = load_settings()
