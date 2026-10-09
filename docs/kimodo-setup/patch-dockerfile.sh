#!/usr/bin/env bash
set -e
S=/mnt/c/Users/dap_p/kimodo-setup/Dockerfile.patched
D="$HOME/kimodo/Dockerfile"
cp "$S" "$D"
sed -i 's/\r$//' "$D"
echo "=== ENV aplicado ==="
grep -n 'PIP_INDEX_URL\|PIP_EXTRA_INDEX_URL' "$D"
echo
echo "=== diff resumido vs upstream ==="
cd "$HOME/kimodo" && git --no-pager diff --stat
echo
echo "=== ainda ha build rodando? ==="
pgrep -af "compose build" || echo "nenhum build rodando"
echo
echo "=== cache do pip (wheels ja baixados) ==="
docker system df 2>/dev/null | grep -i "build cache" || true