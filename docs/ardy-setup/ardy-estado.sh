#!/usr/bin/env bash
# O que do ARDY esta no ar: processos, memoria, portas e clipes gerados. So le.
set -u
echo "--- processos"
ps -eo pid,etimes,rss,pcpu,args --sort=-rss | grep -E "run_text_encoder_server|generate.py|visualize.py|run_demo.py" | grep -v grep \
  | awk '{printf "pid %s, ha %s s, %.1f GB de RAM, %s%% de CPU: %s %s %s\n", $1, $2, $3/1048576, $4, $5, $6, $7}'
echo "--- memoria do Ubuntu"
free -g | sed -n '1,3p'
echo "--- portas (9550 codificador, 2334 visualizador, 2333 demo ao vivo)"
for p in 9550 2334 2333; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://127.0.0.1:$p/" || true)
  echo "porta $p: ${code:-sem resposta}"
done
echo "--- placa de video"
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null
echo "--- clipes em ~/ardy/outputs"
ls -la "$HOME/ardy/outputs" 2>/dev/null | tail -n +2 || echo "(nenhum ainda)"
