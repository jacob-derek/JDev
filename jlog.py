"""jlog - logs com tamanho limitado para o JWM e os programas que ele abre.

O ~/.cache/jwm.log chegou a 14 MB porque a saída de erro dos apps (Firefox, jogos...) ia para
ele sem limite. Agora o log do próprio JWM gira (rotacionar) e cada filho escreve num arquivo seu,
que é cortado quando passa do limite.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

LIMITE = 1_000_000   # bytes


def pasta() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    p = Path(base)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def rotacionar(caminho: Path, limite: int = LIMITE) -> bool:
    """Se `caminho` passou de `limite`, vira `caminho.1` (o antigo .1 é descartado)."""
    try:
        if caminho.stat().st_size <= limite:
            return False
        os.replace(caminho, caminho.with_name(caminho.name + ".1"))
        return True
    except OSError:
        return False


def abrir_saida(nome: str, limite: int = LIMITE):
    """Arquivo aberto para a saída (stdout+stderr) de um processo filho; None se não der
    (o chamador usa DEVNULL). Quem chama deve fechar depois do Popen."""
    arq = pasta() / nome
    rotacionar(arq, limite)
    try:
        return open(arq, "ab")
    except OSError:
        return None


_NUM = re.compile(r"\b(sequence_number|resource_id) = \d+")


class SemRepetir:
    """Mensagens iguais (ignorando números de sequência) só aparecem a primeira vez."""

    def __init__(self, maximo: int = 200):
        self.vistas: set[str] = set()
        self.maximo = maximo

    def nova(self, texto: str) -> bool:
        chave = _NUM.sub(r"\1 = N", texto)
        if chave in self.vistas:
            return False
        if len(self.vistas) < self.maximo:
            self.vistas.add(chave)
        return True
