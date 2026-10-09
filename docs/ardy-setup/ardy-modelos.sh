#!/usr/bin/env bash
# Baixa os modelos do ARDY para ~/.cache/huggingface/hub: o gerador (corpo humano, 20 fps)
# e o codificador de texto (Llama 3 de 8 bilhoes + os dois ajustes do LLM2Vec).
# Usa o token do Hugging Face que ja esta em ~/.cache/huggingface/token.
# Pode rodar de novo: retoma de onde parou.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export HF_HUB_DISABLE_PROGRESS_BARS=1
cd "$HOME"
LOG="$HOME/ardy-modelos.log"
exec > >(tee -a "$LOG") 2>&1
hf() { uvx --quiet --python 3.11 --from "huggingface_hub>=1.0" hf "$@"; }
echo "=== $(date '+%F %T') inicio"
hf download nvidia/ARDY-Core-RP-20FPS-Horizon40
hf download McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp
hf download McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised
hf download meta-llama/Meta-Llama-3-8B-Instruct --exclude "original/*"
echo "--- tamanho no disco"
du -sh "$HOME"/.cache/huggingface/hub/models--* 2>/dev/null
echo "=== $(date '+%F %T') fim"
