#!/usr/bin/env bash
# Espera o codificador de texto do ARDY responder em 127.0.0.1:9550 (ate 30 minutos), mostrando
# o andamento. Sai com 1 se o processo dele sumir ou o tempo acabar.
# uso: ardy-esperar-codificador.sh [--so-conferir]   (--so-conferir: responde agora ou nao)
set -u
URL=http://127.0.0.1:9550/
if [ "${1:-}" = "--so-conferir" ]; then
  curl -s -o /dev/null --max-time 3 "$URL"
  exit $?
fi
START=$(date +%s)
TICK=0
until curl -s -o /dev/null --max-time 3 "$URL"; do
  ELAPSED=$(( $(date +%s) - START ))
  # Os primeiros segundos sao do processo ainda subindo.
  if [ "$ELAPSED" -gt 30 ] && ! pgrep -f run_text_encoder_server.py > /dev/null; then
    echo "ERRO: o modelo de texto parou ao carregar"
    exit 1
  fi
  if [ "$ELAPSED" -gt 1800 ]; then
    echo "ERRO: o modelo de texto nao subiu em 30 minutos"
    exit 1
  fi
  TICK=$(( TICK + 1 ))
  if [ $(( TICK % 6 )) -eq 0 ]; then echo "  ... carregando ha $ELAPSED s"; fi
  sleep 5
done
echo "  modelo de texto no ar em $(( $(date +%s) - START )) s"
