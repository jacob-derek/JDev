"""Poe a raiz do repositorio e a pasta tools/ no sys.path (os programas ficam soltos)."""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
for _p in (RAIZ, RAIZ / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
