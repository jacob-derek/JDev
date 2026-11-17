"""Desenho do tabuleiro como segmentos (texto, cor, fundo, negrito). Sem dependencias: so geometria.

Casas: indice 0..63 como no python-chess (a1=0, h1=7, a8=56, h8=63).
Pecas em letras (P N B R Q K): azul = brancas, vermelho = pretas. Moldura com coordenadas nas bordas.
"""
LARG = 3   # largura de cada casa, em colunas


def grade(pecas, pal, ultimo=(), virado=False):
    """pecas: {casa: (e_branca, "P"|"N"|...)}. Devolve 12 linhas, cada uma uma lista de segmentos."""
    fileiras = range(8) if virado else range(7, -1, -1)
    colunas = list(range(7, -1, -1) if virado else range(8))
    fundo, borda, dim = pal["fundo"], pal["borda"], pal["dim"]

    def coords():
        return [("   ", dim, fundo, False)] + [(("abcdefgh"[f]).center(LARG), dim, fundo, False) for f in colunas] + [("   ", dim, fundo, False)]

    linhas = [coords(), [("  ┌" + "─" * (8 * LARG) + "┐  ", borda, fundo, False)]]
    for r in fileiras:
        seg = [("%d " % (r + 1), dim, fundo, False), ("│", borda, fundo, False)]
        for f in colunas:
            casa = r * 8 + f
            bg = pal["ultima"] if casa in ultimo else fundo
            peca = pecas.get(casa)
            if peca:
                branca, tipo = peca
                seg.append((tipo.upper().center(LARG), pal["brancas" if branca else "pretas"], bg, True))
            else:
                seg.append(("·".center(LARG), dim, bg, False))
        seg += [("│", borda, fundo, False), (" %d" % (r + 1), dim, fundo, False)]
        linhas.append(seg)
    linhas += [[("  └" + "─" * (8 * LARG) + "┘  ", borda, fundo, False)], coords()]
    return linhas
