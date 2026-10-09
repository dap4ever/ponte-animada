"""Conserta a caixa de edicao do texto na linha do tempo do demo do ARDY (pagina do viser).

Defeito: com dois cliques na barra azul do pedido, a caixa de edicao nasce com a largura do
pedido inteiro (5000 s = centenas de milhares de pixels) e o texto, centralizado, fica fora
da tela: so se ve uma caixa escura e o que se digita nao aparece.
Conserto: limitar a caixa ao trecho visivel da linha do tempo.

Mexe em viser/client/src/Timeline.tsx (guarda uma copia .orig) e remonta a pagina. Pode rodar
de novo: nao faz nada se ja estiver consertado. Rode de novo se o ARDY for reinstalado.

uso (no Ubuntu, com o ambiente do ARDY ativo): python ardy-corrigir-caixa-de-texto.py
"""

import shutil
import sys
from pathlib import Path

from viser import _client_autobuild as autobuild

OLD = """                left: `${editingPrompt.x}px`,
                top: `${editingPrompt.y}px`,
                width: `${editingPrompt.width}px`,
"""
NEW = """                // Clamp to the visible part of the timeline: a long prompt is far wider than the
                // viewport, and its centered text would otherwise sit off-screen.
                left: `max(${editingPrompt.x}px, ${TRACK_LABEL_WIDTH}px)`,
                top: `${editingPrompt.y}px`,
                width: `calc(min(${editingPrompt.x + editingPrompt.width}px, 100%) - max(${editingPrompt.x}px, ${TRACK_LABEL_WIDTH}px))`,
"""

source = autobuild.client_dir / "src" / "Timeline.tsx"
# A copia fica fora de src/ para nao entrar na conta de "o fonte mudou".
backup = autobuild.client_dir / "Timeline.tsx.orig"
text = source.read_text(encoding="utf-8")
if NEW in text:
    print("Timeline.tsx: ja estava consertado")
elif text.count(OLD) == 1:
    if not backup.exists():
        shutil.copy2(source, backup)
    source.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print(f"Timeline.tsx: consertado (copia do original em {backup})")
else:
    sys.exit("Timeline.tsx: nao achei o trecho esperado; o viser mudou e este conserto precisa ser revisto")

autobuild.ensure_client_is_built()
built = sorted((autobuild.build_dir / "assets").glob("index-*.js"))
ok = any("calc(min(" in f.read_text(encoding="utf-8") for f in built)
print("pagina remontada com o conserto" if ok else "ERRO: a pagina montada nao tem o conserto")
sys.exit(0 if ok else 1)
