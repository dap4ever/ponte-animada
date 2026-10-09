#!/usr/bin/env bash
# Teste final: gerar uma motion via CLI para validar a instalacao completa.
set -uo pipefail
cd "$HOME/kimodo" || exit 1

echo "=== modelo escolhido: Kimodo-SOMA-RP-v1.1 ==="
echo "=== iniciando geracao ($(date +%H:%M:%S)) ==="

docker compose run --rm -T demo kimodo_gen \
  "A person walks forward." \
  --model Kimodo-SOMA-RP-v1.1 \
  --duration 5.0 \
  --output /workspace/output 2>&1

echo "=== exit=$? ($(date +%H:%M:%S)) ==="
echo "=== arquivos gerados ==="
ls -la "$HOME/kimodo/output" 2>/dev/null || echo "(pasta output nao encontrada)"
