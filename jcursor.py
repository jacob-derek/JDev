"""jcursor - formato e piscar do cursor (DECSCUSR, ESC [ Ps SP q) e a configuração do JCode.

O JCode manda o código; o JTerm (e terminais comuns: xterm, kitty, foot...) desenha.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Ps -> (forma, pisca). 0 = padrão do terminal: no JTerm, bloco fixo.
_TABELA = {0: ("block", False), 1: ("block", True), 2: ("block", False),
           3: ("underline", True), 4: ("underline", False),
           5: ("bar", True), 6: ("bar", False)}
_CODIGO = {("block", True): 1, ("block", False): 2, ("underline", True): 3,
           ("underline", False): 4, ("bar", True): 5, ("bar", False): 6}

FORMAS = ("bar", "block", "underline", "default")
NOMES_FORMA = {"bar": "Barra", "block": "Bloco", "underline": "Sublinhado", "default": "Padrão do terminal"}


def decscusr(n: int):
    """Ps do DECSCUSR -> (forma, pisca)."""
    return _TABELA.get(n, ("block", False))


def codigo(forma: str, pisca: bool) -> int:
    """(forma, pisca) -> Ps do DECSCUSR; forma desconhecida ou "default" = 0."""
    return _CODIGO.get((forma, bool(pisca)), 0)


def _arquivo() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "jdev" / "jcode.json"


PADRAO = {"cursor": "bar", "piscar": True}


def carregar(caminho: Path | None = None) -> dict:
    """Configuração do JCode. Arquivo ausente, quebrado ou com valor estranho -> padrões."""
    cfg = dict(PADRAO)
    try:
        bruto = json.loads((caminho or _arquivo()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if isinstance(bruto, dict):
        if bruto.get("cursor") in FORMAS:
            cfg["cursor"] = bruto["cursor"]
        if isinstance(bruto.get("piscar"), bool):
            cfg["piscar"] = bruto["piscar"]
    return cfg


def salvar(cfg: dict, caminho: Path | None = None) -> Path:
    arq = caminho or _arquivo()
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_name(arq.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, arq)
    return arq


def sequencia(cfg: dict) -> str:
    """Escape que aplica a configuração no terminal."""
    return f"\x1b[{codigo(cfg.get('cursor', 'bar'), cfg.get('piscar', True))} q"
