"""Testes da logica pura (sem Textual nem python-chess)."""
import unittest

from chessyou import analise, cores, formato, tabuleiro

PAL = cores.paleta(cores.PADRAO)


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contraste(a, b):
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


class TestAnalise(unittest.TestCase):
    def test_chance(self):
        self.assertAlmostEqual(analise.chance_vitoria(0), 50.0)
        self.assertGreater(analise.chance_vitoria(300), analise.chance_vitoria(100))
        self.assertAlmostEqual(analise.chance_vitoria(500) + analise.chance_vitoria(-500), 100.0)

    def test_perda_e_classe(self):
        self.assertEqual(analise.perda(0, 100, brancas=True), 0.0)   # ganhou terreno: sem perda
        self.assertEqual(analise.classificar(5), "ok")
        self.assertEqual(analise.classificar(12), "imprecisao")
        self.assertEqual(analise.classificar(25), "erro")
        self.assertEqual(analise.classificar(45), "gafe")

    def test_perda_simetrica_entre_as_cores(self):
        self.assertAlmostEqual(analise.perda(0, -200, brancas=True), analise.perda(0, 200, brancas=False))

    def test_ganhando_muito_perder_peao_pesa_pouco(self):
        self.assertLess(analise.perda(1000, 900, True), analise.perda(0, -100, True))

    def test_momentos_criticos(self):
        av = [20, 30, 35, -600, -590]          # lance 3 (brancas) joga fora a vantagem
        crit = analise.momentos_criticos(av)
        self.assertEqual([c["ply"] for c in crit], [3])
        self.assertEqual(crit[0]["classe"], "gafe")
        self.assertTrue(crit[0]["brancas"])

    def test_pretas_erram_quando_a_avaliacao_sobe(self):
        crit = analise.momentos_criticos([0, 0, 400])   # lance 2 e das pretas
        self.assertEqual([(c["ply"], c["brancas"]) for c in crit], [(2, False)])

    def test_mate_nao_estoura(self):
        crit = analise.momentos_criticos([0, analise.MATE_CP])
        self.assertEqual(crit, [])               # as brancas melhoraram
        self.assertEqual(len(analise.momentos_criticos([0, -analise.MATE_CP])), 1)


class TestCores(unittest.TestCase):
    def test_misturar(self):
        self.assertEqual(cores.misturar("#000000", "#ffffff", 0), "#000000")
        self.assertEqual(cores.misturar("#000000", "#ffffff", 1), "#ffffff")
        self.assertEqual(cores.misturar("#000000", "#ffffff", 0.5), "#808080")

    def test_pecas_legiveis(self):
        for lado in ("brancas", "pretas"):
            self.assertGreaterEqual(contraste(PAL[lado], PAL["fundo"]), 4.5, lado)
            self.assertGreaterEqual(contraste(PAL[lado], PAL["ultima"]), 3.0, lado)
        self.assertGreaterEqual(contraste(PAL["dim"], PAL["fundo"]), 4.5)

    def test_lados_se_distinguem(self):
        self.assertNotEqual(PAL["brancas"], PAL["pretas"])


class TestTabuleiro(unittest.TestCase):
    def texto(self, linha):
        return "".join(seg[0] for seg in linha)

    def test_dimensoes_e_moldura(self):
        linhas = tabuleiro.grade({}, PAL)
        self.assertEqual(len(linhas), 12)                      # coords, borda, 8 fileiras, borda, coords
        self.assertEqual(len({len(self.texto(lin)) for lin in linhas}), 1)   # todas as linhas com a mesma largura
        self.assertIn("┌", self.texto(linhas[1]))
        self.assertIn("└", self.texto(linhas[10]))
        self.assertIn("a", self.texto(linhas[0]))
        self.assertIn("h", self.texto(linhas[11]))

    def test_peca_em_letra_colorida(self):
        linhas = tabuleiro.grade({0: (True, "r"), 63: (False, "K")}, PAL)     # a1 branca, h8 preta
        a1 = linhas[9][2]                                       # fileira 1, primeira casa
        self.assertEqual((a1[0].strip(), a1[1]), ("R", PAL["brancas"]))
        h8 = linhas[2][-3]                                      # fileira 8, ultima casa
        self.assertEqual((h8[0].strip(), h8[1]), ("K", PAL["pretas"]))

    def test_casa_vazia_tem_ponto(self):
        self.assertIn("·", self.texto(tabuleiro.grade({}, PAL)[5]))

    def test_virar_inverte_rotulos_e_colunas(self):
        normal = tabuleiro.grade({}, PAL)
        virado = tabuleiro.grade({}, PAL, virado=True)
        self.assertTrue(self.texto(normal[2]).startswith("8"))
        self.assertTrue(self.texto(virado[2]).startswith("1"))
        self.assertEqual(self.texto(normal[0]).split(), list("abcdefgh"))
        self.assertEqual(self.texto(virado[0]).split(), list("hgfedcba"))

    def test_ultimo_lance_destacado(self):
        linhas = tabuleiro.grade({}, PAL, ultimo=(56,))        # a8: primeira casa da primeira fileira
        self.assertEqual(linhas[2][2][2], PAL["ultima"])
        self.assertEqual(linhas[2][3][2], PAL["fundo"])


class TestFormato(unittest.TestCase):
    SANS = "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6".split()

    def test_janela_acompanha_o_lance(self):
        linhas = formato.lista_lances(self.SANS, 13, janela=3)
        self.assertEqual(len(linhas), 3)
        self.assertTrue(linhas[-1][1][1])                   # Bb3 (lance 13) em destaque
        self.assertEqual(linhas[-1][0][0].strip(), "7.")

    def test_inicio_e_vazio(self):
        self.assertEqual(formato.lista_lances([], 0), [])
        self.assertEqual(formato.lista_lances(self.SANS, 0, janela=3)[0][0][0].strip(), "1.")

    def test_lance_impar_sem_resposta(self):
        linhas = formato.lista_lances(["e4"], 1)
        self.assertEqual(linhas[0][2][0].strip(), "")

    def test_barra_vertical_igual(self):
        cel = formato.barra_vertical(0, 8)
        self.assertEqual(len(cel), 8)
        self.assertEqual([c[2] for c in cel], ["pretas"] * 4 + ["brancas"] * 4)    # pretas em cima

    def test_barra_vertical_extremos(self):
        self.assertTrue(all(c[2] == "brancas" for c in formato.barra_vertical(analise.MATE_CP, 8)))
        self.assertTrue(all(c[2] == "pretas" for c in formato.barra_vertical(-analise.MATE_CP, 8)))

    def test_barra_vertical_celula_parcial(self):
        cel = formato.barra_vertical(60, 8)                  # brancas um pouco acima da metade
        parcial = [c for c in cel if c[0] != " "]
        for ch, fg, bg in parcial:
            self.assertIn(ch, formato.BLOCOS)
            self.assertEqual((fg, bg), ("brancas", "pretas"))

    def test_texto_cp(self):
        self.assertEqual(formato.texto_cp(35), "+0.35")
        self.assertEqual(formato.texto_cp(-analise.MATE_CP), "-mate")


if __name__ == "__main__":
    unittest.main()
