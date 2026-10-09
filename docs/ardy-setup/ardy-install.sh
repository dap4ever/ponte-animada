#!/usr/bin/env bash
# Instala o ARDY em ~/ardy/.venv: PyTorch com CUDA e o pacote com o visualizador.
# Precisa do ardy-prep.sh (uv, Python 3.11, repositorio) e do ardy-root.sh (compilador).
# Pode rodar de novo: retoma de onde parou.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
LOG="$HOME/ardy-install.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date '+%F %T') inicio"
cd "$HOME/ardy"

if [ ! -x .venv/bin/python ]; then
  echo "--- ambiente com Python 3.11"
  uv venv --python 3.11 --seed .venv
fi
. .venv/bin/activate
python --version

echo "--- PyTorch (CUDA 12.6)"
python -m pip install --progress-bar off torch torchvision --index-url https://download.pytorch.org/whl/cu126
python - <<'PY'
import torch
print("torch", torch.__version__, "| cuda disponivel:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("placa:", torch.cuda.get_device_name(0))
PY

echo "--- ARDY com o visualizador (compila a extensao de correcao de movimento)"
python -m pip install --progress-bar off -e ".[demo]"
python - <<'PY'
import ardy, motion_correction, viser
print("ardy, motion_correction e viser importam")
PY
echo "=== $(date '+%F %T') fim"
