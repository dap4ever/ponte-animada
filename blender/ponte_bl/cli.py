"""Protocolo dos scripts de entrada: argumentos depois de ``--`` e resultado em JSON."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Callable


def script_argv() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def run(main: Callable[[], dict], result_json: Path) -> None:
    """Roda ``main`` e grava o resultado. Em erro, grava o traceback e sai com codigo 1."""
    try:
        result = {"ok": True, **main()}
    except Exception as exc:  # noqa: BLE001 - o backend precisa do motivo, qualquer que seja
        result = {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}
    result_json.parent.mkdir(parents=True, exist_ok=True)
    result_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if not result["ok"]:
        print(result["traceback"], file=sys.stderr)
        sys.exit(1)
