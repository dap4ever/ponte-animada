"""Atalhos do Windows (.lnk), usados para o resultado dos personagens encerrados."""

from __future__ import annotations

import os
import re
import secrets
import subprocess
from pathlib import Path

_POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
# Os caminhos vão por variável de ambiente: assim não há aspas nem acentos para escapar no comando.
_CREATE = "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:PONTE_LNK); $s.TargetPath = $env:PONTE_TARGET; $s.Description = $env:PONTE_DESC; $s.Save()"
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def file_name(label: str) -> str:
    """Nome de arquivo que o Windows aceita, o mais parecido possível com ``label``."""
    name = re.sub(r"\s+", " ", re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", label)).strip(" .")[:80].strip(" .")
    return f"_{name}" if name.upper() in _RESERVED else name or "personagem"


def create(link: Path, target: Path, description: str = "") -> None:
    """Cria (ou troca) o atalho ``link`` apontando para ``target``."""
    link.parent.mkdir(parents=True, exist_ok=True)
    # O WScript.Shell se perde com nomes fora da página de código do sistema: o atalho nasce
    # com um nome simples e só depois recebe o nome do personagem.
    draft = link.with_name(f"~{secrets.token_hex(4)}.lnk")
    env = {**os.environ, "PONTE_LNK": str(draft), "PONTE_TARGET": str(target), "PONTE_DESC": description[:250]}
    proc = subprocess.run(
        [str(_POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", _CREATE],
        env=env, capture_output=True, text=True, errors="replace", timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
    )  # fmt: skip
    if proc.returncode != 0 or not draft.exists():
        draft.unlink(missing_ok=True)
        raise OSError(f"Não consegui criar o atalho {link.name}: {(proc.stderr or proc.stdout).strip()[-300:] or 'o PowerShell não respondeu'}")
    os.replace(draft, link)
