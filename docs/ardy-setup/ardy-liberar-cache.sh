#!/usr/bin/env bash
# Devolve ao Windows a memoria que o Ubuntu segura como cache de arquivo (depois de um
# download grande ela chega a 20 GB). Nao apaga nada: so solta copias em memoria de arquivos
# que ja estao no disco. Roda como root.
set -u
echo "antes:  $(free -g | sed -n '2p')"
sync
echo 1 > /proc/sys/vm/drop_caches
echo "depois: $(free -g | sed -n '2p')"
