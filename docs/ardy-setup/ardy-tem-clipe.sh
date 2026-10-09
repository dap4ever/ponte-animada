#!/usr/bin/env bash
# Sai com 0 se o clipe ja foi gerado (ha .npz em ~/ardy/outputs/<nome>/ ou <nome>.npz).
# uso: ardy-tem-clipe.sh [nome]   (padrao: zumbi_andando)
NAME="${1:-zumbi_andando}"
ls "$HOME/ardy/outputs/$NAME"/*.npz >/dev/null 2>&1 || ls "$HOME/ardy/outputs/$NAME.npz" >/dev/null 2>&1
