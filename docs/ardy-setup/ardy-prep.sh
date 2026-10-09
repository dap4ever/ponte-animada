#!/usr/bin/env bash
# Preparo do ARDY no Ubuntu, sem root: uv (gerenciador de Python) em ~/.local/bin,
# um Python 3.11 proprio (o do sistema e 3.14, novo demais) e o repositorio em ~/ardy.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "--- uv"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
fi
uv --version
echo "--- Python 3.11"
uv python install 3.11
uv python find 3.11
if [ ! -d "$HOME/ardy/.git" ]; then
  echo "--- repositorio"
  git clone --depth 1 https://github.com/nv-tlabs/ardy.git "$HOME/ardy"
fi
cd "$HOME/ardy"
echo "commit: $(git rev-parse HEAD) de $(git log -1 --format=%cd --date=short)"
echo "tamanho: $(du -sh "$HOME/ardy" | cut -f1)"
