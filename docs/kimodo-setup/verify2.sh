#!/usr/bin/env bash
L=/tmp/kimodo-build2.log
echo "=== CACHED? (etapas reaproveitadas) ==="
grep -c "CACHED" "$L"
echo
echo "=== marcos ==="
grep -E "^#[0-9]+ (DONE|\[)" "$L" | tail -10
echo
echo "=== retries NGC (deve ser 0) ==="
grep -c "pypi.ngc.nvidia.com" "$L"
echo
echo "=== ultimas linhas ==="
tail -4 "$L" | cut -c1-140