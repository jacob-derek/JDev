"""Paleta do ChessYou!: azuis e vermelhos. Usa as cores do jtheme (JDev) se ele for achado."""
import os
import sys
from pathlib import Path

PADRAO = dict(bg="#0a0a0a", fg="#f2f2f2", blue="#6aa9ff", red="#ff5f6d", dim="#8a8a8a", yellow="#f0c674")


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def misturar(a, b, t):
    """Cor entre a (t=0) e b (t=1)."""
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(_rgb(a), _rgb(b), strict=True))


def _tema():
    for base in (os.environ.get("JDEV_DIR"), str(Path.home() / "JDev")):
        if base and Path(base, "jtheme.py").is_file() and base not in sys.path:
            sys.path.append(base)
    try:
        import jtheme
        t = jtheme.T
        return dict(bg=t["bg"], fg=t["fg_bright"], blue=t["blue"], red=t["red"], dim=t["dim"], yellow=t["yellow"])
    except (ImportError, AttributeError, KeyError):
        return dict(PADRAO)


def paleta(base=None):
    t = base or _tema()
    return {
        "fundo": t["bg"],
        "borda": t["blue"],
        "brancas": t["blue"],       # peças e lado das brancas: azul
        "pretas": t["red"],         # peças e lado das pretas: vermelho
        "ultima": misturar(t["bg"], t["yellow"], 0.28),
        "texto": t["fg"],
        "dim": t["dim"],
        "destaque": t["blue"],
    }
