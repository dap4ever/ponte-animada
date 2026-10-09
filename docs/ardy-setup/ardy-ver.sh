#!/usr/bin/env bash
# Visualizador do ARDY: mostra um .npz, ou uma pasta de tomadas, em http://localhost:2334.
# uso: ardy-ver.sh <nome dentro de ~/ardy/outputs, ou caminho> [porta]
# Fica no ar ate ser encerrado (ardy-parar.sh visualizador).
set -euo pipefail
cd "$HOME/ardy"
. .venv/bin/activate
TARGET="$1"
if [ ! -e "$TARGET" ]; then
  if [ -e "outputs/$TARGET" ]; then TARGET="outputs/$TARGET"; else TARGET="outputs/$TARGET.npz"; fi
fi
exec python scripts/visualize.py "$TARGET" --port "${2:-2334}"
