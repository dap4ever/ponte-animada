#!/usr/bin/env bash
# Demo interativo do ARDY (digita-se o pedido e o boneco anda ao vivo) em http://localhost:2333.
# Precisa do codificador de texto no ar (ardy-codificador.sh): sem ele o demo tenta por o
# codificador na placa de video, que nao tem memoria para isso (pede 14 GB, a RTX 3060 tem 12).
# --no-compile: o TensorRT nao foi instalado.
# Fica no ar ate ser encerrado (ardy-parar.sh demo).
set -euo pipefail
cd "$HOME/ardy"
. .venv/bin/activate
export HF_HUB_OFFLINE=1
export TEXT_ENCODER_URL=http://127.0.0.1:9550/
export PYTHONUNBUFFERED=1    # sem isto o registro so aparece no arquivo de tempos em tempos
if ! curl -s -o /dev/null --max-time 5 "$TEXT_ENCODER_URL"; then
  echo "ERRO: o codificador de texto nao esta no ar em 127.0.0.1:9550"
  exit 1
fi
exec python scripts/run_demo.py --no-compile
