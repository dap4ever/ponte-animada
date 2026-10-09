#!/usr/bin/env bash
L=/tmp/kimodo-build.log
echo "=== ultimas linhas ==="
tail -3 "$L" | cut -c1-130
echo
echo "=== metricas ==="
printf "pacotes coletados : %s\n" "$(grep -c 'whl.metadata' "$L")"
printf "linhas retry NGC  : %s\n" "$(grep -c 'pypi.ngc.nvidia.com' "$L")"
printf "tamanho do log    : %s bytes\n" "$(stat -c %s "$L")"
echo
echo "=== marcos do Dockerfile ==="
grep -E '^#[0-9]+ (DONE|\[)' "$L" | tail -8
echo
echo "=== erros fatais? ==="
grep -icE '^ERROR|error: command|failed with|No matching distribution' "$L"