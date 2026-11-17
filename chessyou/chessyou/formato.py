"""Textos auxiliares (sem dependencias): lista de lances e barra de avaliacao."""
from .analise import MATE_CP, chance_vitoria


def lista_lances(sans, ply, janela=8):
    """Linhas "12. e4  Nc6" mostrando `janela` pares de lances em volta do lance atual.
    Cada linha e uma lista de (texto, em_destaque)."""
    pares = (len(sans) + 1) // 2
    if not pares:
        return []
    atual = (ply - 1) // 2 if ply > 0 else 0
    ini = max(0, min(atual - janela // 2, pares - janela))
    linhas = []
    for i in range(ini, min(pares, ini + janela)):
        brancas = sans[2 * i]
        pretas = sans[2 * i + 1] if 2 * i + 1 < len(sans) else ""
        linhas.append([("%3d. " % (i + 1), False),
                       (brancas.ljust(8), ply == 2 * i + 1),
                       (pretas.ljust(8), ply == 2 * i + 2)])
    return linhas


BLOCOS = "▁▂▃▄▅▆▇"


def barra_vertical(cp, altura=8):
    """Barra de vantagem, de cima para baixo: pretas em cima, brancas embaixo.
    Cada celula e (caractere, cor_do_texto, cor_do_fundo), com as cores "brancas"/"pretas"/None."""
    oitavos = round(chance_vitoria(cp) / 100 * altura * 8)      # altura das brancas, em 1/8 de celula
    celulas = []
    for de_baixo in range(altura):
        resto = oitavos - de_baixo * 8
        if resto >= 8:
            celulas.append((" ", None, "brancas"))
        elif resto > 0:
            celulas.append((BLOCOS[resto - 1], "brancas", "pretas"))
        else:
            celulas.append((" ", None, "pretas"))
    return celulas[::-1]


def texto_cp(cp):
    if abs(cp) >= MATE_CP - 100:
        return "mate" if cp > 0 else "-mate"
    return "%+.2f" % (cp / 100)
