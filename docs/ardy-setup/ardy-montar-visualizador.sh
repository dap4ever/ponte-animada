#!/usr/bin/env bash
# Monta a pagina do visualizador do ARDY (viser). So precisa na primeira vez: baixa o Node.js
# para dentro do ambiente do ARDY e compila a pagina (alguns minutos, usa a internet).
# O viser vem do repositorio da NVIDIA sem a pagina pronta; sem isto ele a monta sozinho na
# primeira vez que um visualizador sobe, sem avisar.
set -u
cd "$HOME/ardy" || { echo "ERRO: o ARDY nao esta instalado em ~/ardy"; exit 1; }
. .venv/bin/activate
LOGS="$HOME/ardy-logs"
mkdir -p "$LOGS"

built() {
  python -c "import importlib.util, pathlib, sys; p = pathlib.Path(importlib.util.find_spec('viser').origin).parent / 'client' / 'build' / 'index.html'; sys.exit(0 if p.exists() else 1)"
}

if built; then
  echo "pagina do visualizador: pronta"
  exit 0
fi
if [ "${1:-}" = "--so-conferir" ]; then
  echo "pagina do visualizador: falta montar"
  exit 1
fi
echo "montando a pagina do visualizador (so na primeira vez; leva alguns minutos)..."
python -c "from viser._client_autobuild import ensure_client_is_built; ensure_client_is_built()" > "$LOGS/visualizador-montagem.log" 2>&1
if built; then
  echo "pagina do visualizador: pronta"
  exit 0
fi
echo "ERRO: a pagina do visualizador nao montou. Fim do log ($LOGS/visualizador-montagem.log):"
tr '\r' '\n' < "$LOGS/visualizador-montagem.log" | tail -n 20
exit 1
