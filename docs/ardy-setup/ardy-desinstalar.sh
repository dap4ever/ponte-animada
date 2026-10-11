#!/usr/bin/env bash
# Tira o ARDY do Ubuntu: o programa, os modelos e os restos da instalacao. Roda como o usuario comum:
#   wsl.exe -d Ubuntu -- bash /mnt/d/PonteAnimada/docs/ardy-setup/ardy-desinstalar.sh [pasta do Windows para guardar]
#
# Antes de apagar, guarda na pasta dada (padrao: data/tmp/ardy-guardado da ponte) o pouco que nao se
# baixa de novo: os textos ja codificados (para nao precisar do codificador, de 16 GB, outra vez) e os
# clipes de teste. O que fica no Ubuntu: o token do Hugging Face, o uv com o Python 3.11 e o
# compilador (build-essential e cmake), que sao ferramentas comuns e pequenas.
# Para instalar de novo: ardy-root.sh (como root), ardy-prep.sh, ardy-install.sh, ardy-modelos.sh.
set -eu
KEEP="${1:-/mnt/d/PonteAnimada/data/tmp/ardy-guardado}"
[ "$HOME" = "/home/$(id -un)" ] || { echo "ERRO: pasta do usuario inesperada: $HOME"; exit 1; }
HUB="$HOME/.cache/huggingface/hub"

echo "--- o que ha (antes)"
du -sh "$HOME/ardy" "$HOME/.cache/huggingface" "$HOME/.cache/pip" 2>/dev/null || true
df -h / | tail -1

echo "--- encerra o que estiver no ar"
for what in scripts/run_demo.py scripts/visualize.py run_text_encoder_server.py ardy_scripts/gerar.py; do
  pkill -f "$what" 2>/dev/null && echo "encerrado: $what" || true
done

if [ -d "$HOME/ardy" ]; then
  echo "--- guarda os textos codificados e os clipes de teste em $KEEP"
  mkdir -p "$KEEP"
  [ -d "$HOME/ardy/.cache/text_embeddings" ] && cp -r "$HOME/ardy/.cache/text_embeddings" "$KEEP/"
  [ -d "$HOME/ardy/.cache/export" ] && cp -r "$HOME/ardy/.cache/export" "$KEEP/sessoes-do-demo"
  [ -d "$HOME/ardy/outputs" ] && cp -r "$HOME/ardy/outputs" "$KEEP/"
  (cd "$HOME/ardy" && git rev-parse HEAD > "$KEEP/commit-do-ardy.txt" 2>/dev/null) || true
  ls "$KEEP"
fi

echo "--- apaga o programa, os modelos e os restos da instalacao"
rm -rf "$HOME/ardy" "$HOME/ardy-install.log" "$HOME/ardy-modelos.log" "$HOME/ardy-logs"
rm -rf "$HUB/models--nvidia--ARDY-Core-RP-20FPS-Horizon40" \
       "$HUB/models--McGill-NLP--LLM2Vec-Meta-Llama-3-8B-Instruct-mntp" \
       "$HUB/models--McGill-NLP--LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised" \
       "$HUB/models--meta-llama--Meta-Llama-3-8B-Instruct"
# Os arquivos dos modelos ficam numa pasta so ("blobs"): so sai se nao sobrou modelo de mais ninguem.
if ! ls -d "$HUB"/models--* >/dev/null 2>&1; then
  rm -rf "$HUB/blobs" "$HOME/.cache/huggingface/xet"
else
  echo "AVISO: ha outros modelos em $HUB; a pasta blobs ficou:"; ls -d "$HUB"/models--*
fi
rm -rf "$HOME/.cache/pip"

echo "--- o que ha (depois)"
du -sh "$HOME/.cache/huggingface" "$HOME" 2>/dev/null || true
ls -A "$HOME/.cache/huggingface"
df -h / | tail -1
