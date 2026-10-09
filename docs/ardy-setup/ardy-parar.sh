#!/usr/bin/env bash
# Encerra o que o ARDY deixou no ar e espera os processos sairem.
# uso: ardy-parar.sh [codificador] [visualizador] [demo]   (sem nada: os tres)
set -u
WHAT="${*:-codificador visualizador demo}"

stop() {
  # $1 = nome para a mensagem, $2 = trecho da linha de comando do processo
  if ! pkill -f "$2"; then
    echo "$1: nao estava no ar"
    return
  fi
  for _ in $(seq 1 20); do
    pgrep -f "$2" > /dev/null || break
    sleep 0.5
  done
  pkill -9 -f "$2" 2>/dev/null
  echo "$1 encerrado"
}

case "$WHAT" in *demo*) stop "demo ao vivo" scripts/run_demo.py ;; esac
case "$WHAT" in *visualizador*) stop "visualizador" scripts/visualize.py ;; esac
case "$WHAT" in *codificador*) stop "codificador de texto" run_text_encoder_server.py ;; esac
free -g | sed -n '2p'
