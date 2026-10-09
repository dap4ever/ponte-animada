"""Executa os scripts do Blender em segundo plano."""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import store
from .config import BLENDER_SCRIPTS, SETTINGS


class BlenderError(RuntimeError):
    pass


def run_script(script: str, args: list[str | Path], result_json: Path, log_file: Path | None = None) -> dict:
    """Roda ``blender/<script>`` e devolve o JSON de resultado que ele grava."""
    result_json.unlink(missing_ok=True)
    cmd = [
        SETTINGS.blender_exe,
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(BLENDER_SCRIPTS / script),
        "--",
        *[str(a) for a in args],
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW
    )
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr, encoding="utf-8")
    result = store.read_json(result_json)
    if result is None:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
        raise BlenderError(f"O Blender não devolveu resultado ({script}, código {proc.returncode}): " + " | ".join(tail))
    if not result.get("ok"):
        raise BlenderError(result.get("error") or "erro desconhecido no Blender")
    return result


def open_in_blender(path: Path) -> None:
    """Abre um arquivo no Blender com interface, para o humano inspecionar."""
    subprocess.Popen([SETTINGS.blender_exe, str(path)], creationflags=subprocess.DETACHED_PROCESS)
