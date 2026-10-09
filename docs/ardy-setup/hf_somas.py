"""Compara a soma sha256 de cada .safetensors do cache do Hugging Face com a publicada
(campo lfs.oid da listagem do repositorio). So le.

uso: python hf_somas.py [--so-lista]
"""

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HUB = Path.home() / ".cache/huggingface/hub"
TOKEN = (Path.home() / ".cache/huggingface/token").read_text().strip()


def published(repo):
    request = urllib.request.Request(
        f"https://huggingface.co/api/models/{repo}/tree/main?recursive=true",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        entries = json.load(response)
    return {e["path"]: e["lfs"]["oid"] for e in entries if "lfs" in e}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(16 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    bad = 0
    for repo_dir in sorted(HUB.glob("models--*")):
        repo = repo_dir.name.removeprefix("models--").replace("--", "/", 1)
        want = published(repo)
        for link in sorted(repo_dir.glob("snapshots/*/*.safetensors")):
            got = sha256(link.resolve())
            ok = want.get(link.name) == got
            bad += not ok
            size = link.resolve().stat().st_size // 1_000_000
            print(f"{'ok' if ok else 'DIFERENTE':<9} {size:>5} MB  {repo}: {link.name}", flush=True)
            if not ok:
                print(f"          publicado {want.get(link.name)}\n          aqui      {got}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
