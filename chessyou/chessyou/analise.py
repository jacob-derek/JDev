"""Classificacao de lances (sem dependencias). Avaliacoes sao em centipeoes, do ponto de vista das brancas.

Usa a chance de vitoria (formula do lichess) em vez do centipeao puro: perder 3 peoes quando ja se
esta ganhando por muito pesa menos do que perder 1 peao numa posicao igual.
"""
import math

MATE_CP = 10000
LIMITES = (("gafe", 30.0), ("erro", 20.0), ("imprecisao", 10.0))  # perda de chance de vitoria, em pontos %


def chance_vitoria(cp):
    """0..100: chance de vitoria das brancas para uma avaliacao em centipeoes."""
    cp = max(-MATE_CP, min(MATE_CP, cp))
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def perda(antes, depois, brancas):
    """Quanto (em pontos % de chance de vitoria) quem jogou perdeu com o lance. Nunca negativo."""
    a, d = chance_vitoria(antes), chance_vitoria(depois)
    return max(0.0, (a - d) if brancas else (d - a))


def classificar(p):
    for nome, minimo in LIMITES:
        if p >= minimo:
            return nome
    return "ok"


def momentos_criticos(avaliacoes, minimo=10.0):
    """avaliacoes[k] = avaliacao da posicao depois de k lances (k=0 e a inicial).
    Devolve, em ordem, [{"ply", "brancas", "perda", "classe"}] dos lances que perderam >= minimo."""
    saida = []
    for ply in range(1, len(avaliacoes)):
        brancas = ply % 2 == 1
        p = perda(avaliacoes[ply - 1], avaliacoes[ply], brancas)
        if p >= minimo:
            saida.append({"ply": ply, "brancas": brancas, "perda": p, "classe": classificar(p)})
    return saida
