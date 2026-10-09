#!/usr/bin/env bash
# Codificador de texto do ARDY (Llama 3 de 8 bilhoes) como servico em 127.0.0.1:9550.
# Roda no processador: ocupa uns 16 GB de RAM. Na placa pediria 14 GB e a RTX 3060 tem 12.
# Fica no ar ate ser encerrado (ardy-parar.sh codificador). Leva alguns minutos para subir.
set -euo pipefail
cd "$HOME/ardy"
. .venv/bin/activate
export HF_HUB_OFFLINE=1
export TEXT_ENCODER_DEVICE=cpu
export GRADIO_ANALYTICS_ENABLED=False
exec python scripts/run_text_encoder_server.py --device cpu --host 127.0.0.1 --port 9550
