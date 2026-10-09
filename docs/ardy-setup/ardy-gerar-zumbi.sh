#!/usr/bin/env bash
# Gera o zumbi andando de teste do ARDY: sobe o codificador de texto, gera 3 tomadas de 8 s
# em ~/ardy/outputs/<nome>/ e encerra o codificador. Usa uns 16 GB de RAM enquanto roda.
# uso: ardy-gerar-zumbi.sh [nome]   (padrao: zumbi_andando)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="${1:-zumbi_andando}"
LOGS="$HOME/ardy-logs"
mkdir -p "$LOGS"

echo "[modelo de texto] carregando (16 GB lidos do disco: uns 5 minutos)"
bash "$HERE/ardy-codificador.sh" > "$LOGS/codificador.log" 2>&1 &
ENC=$!
trap 'kill "$ENC" 2>/dev/null' EXIT
START=$(date +%s)
TICK=0
until curl -s -o /dev/null --max-time 3 http://127.0.0.1:9550/; do
  if ! kill -0 "$ENC" 2>/dev/null; then
    echo "ERRO: o modelo de texto parou ao carregar. Fim do log ($LOGS/codificador.log):"
    tr '\r' '\n' < "$LOGS/codificador.log" | tail -n 20
    exit 1
  fi
  if [ $(( $(date +%s) - START )) -gt 1800 ]; then
    echo "ERRO: o modelo de texto nao subiu em 30 minutos"
    exit 1
  fi
  TICK=$(( TICK + 1 ))
  if [ $(( TICK % 6 )) -eq 0 ]; then echo "  ... carregando ha $(( $(date +%s) - START )) s"; fi
  sleep 5
done
echo "[modelo de texto] no ar em $(( $(date +%s) - START )) s"

echo "[geracao] zumbi andando, 3 tomadas de 8 segundos (1 a 3 minutos)"
if bash "$HERE/ardy-gerar.sh" "$NAME" 8 3 0 "$HERE/ardy-zumbi-andando.txt" > "$LOGS/geracao.log" 2>&1; then
  grep -E "^tempo da geracao" "$LOGS/geracao.log"
else
  echo "ERRO na geracao. Fim do log ($LOGS/geracao.log):"
  tr '\r' '\n' < "$LOGS/geracao.log" | tail -n 25
  exit 1
fi

kill "$ENC" 2>/dev/null
wait "$ENC" 2>/dev/null
trap - EXIT
if ! ls "$HOME/ardy/outputs/$NAME"/*.npz >/dev/null 2>&1; then
  echo "ERRO: a geracao terminou mas nao achei os clipes em ~/ardy/outputs/$NAME"
  exit 1
fi
echo "[pronto] $(ls "$HOME/ardy/outputs/$NAME"/*.npz | wc -l) tomadas em ~/ardy/outputs/$NAME"
