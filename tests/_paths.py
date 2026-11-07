"""Põe a raiz do repositório no sys.path (os programas do JDev ficam soltos na raiz)."""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
