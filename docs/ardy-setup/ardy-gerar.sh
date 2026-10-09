#!/usr/bin/env bash
# Gera um clipe com o ARDY (corpo humano, 20 quadros por segundo) a partir de um texto.
# uso: ardy-gerar.sh <nome> <segundos> <tomadas> <semente> <arquivo com o texto em ingles> [opcoes do generate.py]
# Sai em ~/ardy/outputs/<nome>.npz (uma tomada) ou em ~/ardy/outputs/<nome>/ (varias).
# Precisa do codificador de texto no ar (ardy-codificador.sh): espera ate 30 min por ele.
set -euo pipefail
NAME="$1"; SECONDS_="$2"; SAMPLES="$3"; SEED="$4"; TEXT_FILE="$5"; shift 5
TEXT="$(head -n 1 "$TEXT_FILE" | tr -d '\r')"
cd "$HOME/ardy"
. .venv/bin/activate
export HF_HUB_OFFLINE=1
export TEXT_ENCODER_MODE=api
export TEXT_ENCODER_URL=http://127.0.0.1:9550/

echo "esperando o codificador de texto em 127.0.0.1:9550..."
for _ in $(seq 1 360); do
  if curl -s -o /dev/null --max-time 3 "$TEXT_ENCODER_URL"; then break; fi
  sleep 5
done
if ! curl -s -o /dev/null --max-time 5 "$TEXT_ENCODER_URL"; then
  echo "o codificador de texto nao respondeu"
  exit 1
fi

echo "texto: $TEXT"
START=$(date +%s)
python scripts/generate.py "$TEXT" --model core --duration "$SECONDS_" --num_samples "$SAMPLES" --seed "$SEED" --output "$NAME" "$@"
echo "tempo da geracao: $(( $(date +%s) - START )) s"
