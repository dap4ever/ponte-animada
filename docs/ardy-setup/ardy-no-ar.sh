#!/usr/bin/env bash
# Sai com 0 se alguma coisa do ARDY esta rodando (codificador, geracao, visualizador ou demo)
# e mostra o que e. Os atalhos usam isto para nao desligar o Ubuntu com outra janela em uso.
pgrep -a -f 'run_text_encoder_server\.py|scripts/generate\.py|scripts/visualize\.py|scripts/run_demo\.py' | cut -c1-120
exit "${PIPESTATUS[0]}"
