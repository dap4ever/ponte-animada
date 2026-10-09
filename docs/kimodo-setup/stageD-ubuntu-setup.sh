#!/usr/bin/env bash
# Stage D - configuracao da distro Ubuntu: usuario, repos, override, cache HF.
set -uo pipefail

echo "=== STAGE D ==="
echo "--- quem sou eu ---"; whoami

# ---------- 0) git presente? ----------
if ! command -v git >/dev/null 2>&1; then
  echo "instalando git..."
  apt-get update -qq && apt-get install -y -qq git
fi

# ---------- 1) Usuario dap_p ----------
if ! id -u dap_p >/dev/null 2>&1; then
  useradd -m -s /bin/bash -G sudo dap_p
  echo 'dap_p:kimodo' | chpasswd
  echo "usuario dap_p CRIADO"
else
  echo "usuario dap_p ja existe"
fi

# ---------- 2) /etc/wsl.conf ----------
cat > /etc/wsl.conf <<'EOF'
[user]
default=dap_p

[boot]
systemd=true
EOF
echo "/etc/wsl.conf escrito (default=dap_p, systemd=true)"

# ---------- 3) Repositorios ----------
cd /home/dap_p || exit 1
if [ ! -d /home/dap_p/kimodo/.git ]; then
  echo "clonando nv-tlabs/kimodo..."
  sudo -u dap_p git clone --quiet https://github.com/nv-tlabs/kimodo.git /home/dap_p/kimodo
else
  echo "kimodo ja clonado"
fi

if [ ! -d /home/dap_p/kimodo/kimodo-viser/.git ]; then
  echo "clonando nv-tlabs/kimodo-viser (exigido pelo Dockerfile)..."
  sudo -u dap_p git clone --quiet https://github.com/nv-tlabs/kimodo-viser.git /home/dap_p/kimodo/kimodo-viser
else
  echo "kimodo-viser ja clonado"
fi

# ---------- 4) Override: text encoder na CPU ----------
cat > /home/dap_p/kimodo/docker-compose.override.yaml <<'YAML'
services:
  text-encoder:
    environment:
      TEXT_ENCODER_DEVICE: cpu
      PYTORCH_CUDA_ALLOC_CONF: "expandable_segments:True"
  demo:
    environment:
      TEXT_ENCODER_DEVICE: cpu
      PYTORCH_CUDA_ALLOC_CONF: "expandable_segments:True"
YAML
echo "docker-compose.override.yaml gravado"

# ---------- 5) Cache Hugging Face ----------
mkdir -p /home/dap_p/.cache/huggingface
chown -R dap_p:dap_p /home/dap_p/kimodo /home/dap_p/.cache
chmod 700 /home/dap_p/.cache/huggingface

# ---------- 6) Checagens ----------
echo "--- kimodo HEAD ---"
git -C /home/dap_p/kimodo log -1 --oneline
echo "--- kimodo-viser HEAD ---"
git -C /home/dap_p/kimodo/kimodo-viser log -1 --oneline
echo "--- conteudo do kimodo ---"
ls /home/dap_p/kimodo
echo "--- nvidia-smi no WSL ---"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv 2>&1 || echo "AVISO: nvidia-smi falhou"
echo "=== STAGE D FIM ==="
