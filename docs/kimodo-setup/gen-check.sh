#!/usr/bin/env bash
L=/tmp/kimodo-gen.log
echo "=== tamanho do log: $(stat -c %s "$L" 2>/dev/null || echo 0) bytes ==="
echo "=== ultimas 12 linhas (truncadas) ==="
tail -12 "$L" 2>/dev/null | cut -c1-150
echo
echo "=== erros? ==="
grep -icE 'traceback|error:|exception|failed' "$L" 2>/dev/null