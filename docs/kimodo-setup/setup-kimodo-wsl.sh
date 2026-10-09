#!/usr/bin/env bash
# Setup do Kimodo dentro do WSL2 (Ubuntu). Rodar DEPOIS do reboot com Docker instalado.
set -uo pipefail

log() { echo "[setup] $*"; }
HF_TOKEN_FILE="$HOME/.cache/huggingface/token"

# ---------- 1) Repositorios ----------
cd "$HOME"

if [ ! -d "$HOME/kimodo/.git" ]; then
  log "Clonando nv-tlabs/kimodo..."
  git clone https://github.com/nv-tlabs/kimodo.git "$HOME/kimodo"
else
  log "kimodo ja existe."
fi

# O Dockerfile faz COPY kimodo-viser e o lockfile tem '-e ./kimodo-viser'.
# Sem este clone o build FALHA.
if [ ! -d "$HOME/kimodo/kimodo-viser/.git" ]; then
  log "Clonando nv-tlabs/kimodo-viser (obrigatorio para o build)..."
  git clone https://github.com/nv-tlabs/kimodo-viser.git "$HOME/kimodo/kimodo-viser"
else
  log "kimodo-viser ja existe."
fi

# ---------- 2) Override: text encoder na CPU (GPU de 12 GB) ----------
# Forma de MAPA (nao lista) para o merge do Compose ser por chave.
cat > "$HOME/kimodo/docker-compose.override.yaml" <<'YAML'
services:
  text-encoder:
    environment:
      # Lido em LLM2VecEncoder.__init__: forca o Llama-3-8B para a CPU.
      # (A GPU de 12 GB nao comporta os ~16 GB que ele pediria.)
      TEXT_ENCODER_DEVICE: cpu
      PYTORCH_CUDA_ALLOC_CONF: "expandable_segments:True"
  demo:
    environment:
      # REDE DE SEGURANCA: load_model.py usa TEXT_ENCODER_MODE=auto, que tenta a
      # API e, se ela estiver fora do ar, faz fallback para o encoder LOCAL
      # dentro do container do demo. Sem esta linha esse fallback subiria o
      # Llama-3-8B na GPU e estouraria os 12 GB de VRAM.
      TEXT_ENCODER_DEVICE: cpu
      PYTORCH_CUDA_ALLOC_CONF: "expandable_segments:True"
YAML
log "Override gravado: TEXTO na CPU, com expandable_segments no demo."

# ---------- 3) Token Hugging Face ----------
mkdir -p "$HOME/.cache/huggingface"
chmod 700 "$HOME/.cache/huggingface"
if [ -n "${HF_TOKEN:-}" ]; then
  printf '%s' "$HF_TOKEN" > "$HF_TOKEN_FILE"
  chmod 600 "$HF_TOKEN_FILE"
  log "Token gravado em $HF_TOKEN_FILE"
elif [ -s "$HF_TOKEN_FILE" ]; then
  log "Token ja presente em $HF_TOKEN_FILE"
else
  log "AVISO: nenhum token HF encontrado. Rode 'hf auth login' ou exporte HF_TOKEN."
fi

# ---------- 4) Checagens ----------
log "--- git rev ---------"
git -C "$HOME/kimodo" log -1 --oneline || true
log "--- docker ----------"
docker --version || log "ERRO: docker nao encontrado"
log "--- nvidia-smi ------"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv || log "AVISO: nvidia-smi falhou"
log "--- GPU dentro do Docker ---"
docker run --rm --gpus all ubuntu:22.04 nvidia-smi -L || log "AVISO: GPU nao visivel no Docker"

log "Concluido. Proximo: docker compose build"
