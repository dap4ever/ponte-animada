#!/usr/bin/env bash
cd "$HOME/kimodo" || exit 1
echo "=== arquivo gerado ==="
ls -la output.npz 2>/dev/null || { echo "NAO ENCONTRADO"; exit 1; }
echo
echo "=== inspecionando o conteudo com numpy (dentro do container) ==="
docker compose run --rm -T demo python -c "
import numpy as np
d = np.load('/workspace/output.npz')
print('chaves :', len(d.files))
for k in d.files:
    print(f'  {k:24s} {str(d[k].shape):18s} {d[k].dtype}')
pj = d['posed_joints']
print()
print('frames (T)      :', pj.shape[0])
print('juntas  (J)     :', pj.shape[1])
print('altura Y min/max:', round(float(pj[:,:,1].min()),3), '/', round(float(pj[:,:,1].max()),3))
rp = d['root_positions']
print('root deslocamento total (m):', round(float(np.linalg.norm(rp[-1]-rp[0])),3))
" 2>&1 | grep -vE 'FutureWarning|torch.load|neutral_joints|bvh_neutral|global_rot_offsets|warnings.warn|^  ' 