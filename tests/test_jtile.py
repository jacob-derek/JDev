"""Testes do mosaico em árvore (jtile.py): lógica pura, sem X."""
import unittest

from tests import _paths  # noqa: F401
from jtile import Arvore, vizinho

AREA = (0, 0, 1000, 600)
GAP = 10


def sobrepoe(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def arvore_de_quatro():
    t = Arvore()
    t.inserir(1)
    t.inserir(2, 1, "h")
    t.inserir(3, 2, "v")
    t.inserir(4, 1, "v")
    return t


class TestInserirRemover(unittest.TestCase):
    def test_janela_unica_ocupa_tudo(self):
        t = Arvore()
        t.inserir(1)
        self.assertEqual(t.layout(*AREA, GAP), {1: AREA})

    def test_inserir_repetido_e_ignorado(self):
        t = Arvore()
        t.inserir(1)
        t.inserir(1)
        self.assertEqual(len(t), 1)

    def test_alvo_inexistente_divide_a_ultima(self):
        t = Arvore()
        t.inserir(1)
        t.inserir(2, alvo=999, orient="h")
        self.assertEqual(sorted(t.ids()), [1, 2])

    def test_remover_devolve_espaco_ao_vizinho(self):
        t = Arvore()
        t.inserir(1)
        t.inserir(2, 1, "h")
        t.remover(2)
        self.assertEqual(t.layout(*AREA, GAP), {1: AREA})

    def test_remover_tudo_deixa_arvore_vazia(self):
        t = arvore_de_quatro()
        for wid in (2, 1, 3, 4):
            t.remover(wid)
        self.assertEqual(len(t), 0)
        self.assertIsNone(t.raiz)
        self.assertEqual(t.layout(*AREA, GAP), {})

    def test_remover_inexistente_nao_quebra(self):
        t = arvore_de_quatro()
        t.remover(999)
        self.assertEqual(len(t), 4)


class TestLayout(unittest.TestCase):
    def test_sem_sobreposicao_e_dentro_da_area(self):
        rects = arvore_de_quatro().layout(*AREA, GAP)
        ids = list(rects)
        for i in ids:
            x, y, w, h = rects[i]
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, 1000)
            self.assertLessEqual(y + h, 600)
            for j in ids:
                if i < j:
                    self.assertFalse(sobrepoe(rects[i], rects[j]), (i, j))

    def test_gap_entre_duas_janelas(self):
        t = Arvore()
        t.inserir(1)
        t.inserir(2, 1, "h")
        r = t.layout(*AREA, GAP)
        self.assertEqual(r[2][0] - (r[1][0] + r[1][2]), GAP)

    def test_divisao_vertical_empilha(self):
        t = Arvore()
        t.inserir(1)
        t.inserir(2, 1, "v")
        r = t.layout(*AREA, GAP)
        self.assertEqual(r[1][0], r[2][0])
        self.assertLess(r[1][1], r[2][1])

    def test_tamanho_minimo_respeitado(self):
        t = Arvore()
        t.inserir(1)
        t.inserir(2, 1, "h")
        for _ in range(100):
            t.redimensionar(1, "right", 50, GAP)
        r = t.layout(*AREA, GAP, min_w=100, min_h=50)
        self.assertGreaterEqual(r[2][2], 100)


class TestOperacoes(unittest.TestCase):
    def test_redimensionar_cresce_e_encolhe(self):
        t = Arvore()
        t.inserir(1)
        t.inserir(2, 1, "h")
        antes = t.layout(*AREA, GAP)[1][2]
        self.assertTrue(t.redimensionar(1, "right", 50, GAP))
        depois = t.layout(*AREA, GAP)[1][2]
        self.assertGreater(depois, antes)
        t.redimensionar(1, "left", 50, GAP)
        self.assertEqual(t.layout(*AREA, GAP)[1][2], antes)

    def test_redimensionar_janela_do_lado_b_cresce_para_a_esquerda(self):
        t = Arvore()
        t.inserir(1)
        t.inserir(2, 1, "h")
        antes = t.layout(*AREA, GAP)[2][2]
        t.redimensionar(2, "right", 50, GAP)      # "right" = crescer, de qualquer lado
        self.assertGreater(t.layout(*AREA, GAP)[2][2], antes)

    def test_redimensionar_sem_vizinho_no_eixo_devolve_false(self):
        t = Arvore()
        t.inserir(1)
        self.assertFalse(t.redimensionar(1, "right", 50, GAP))
        t.inserir(2, 1, "h")
        self.assertFalse(t.redimensionar(1, "down", 50, GAP))   # só há divisão horizontal

    def test_proporcao_fica_entre_limites(self):
        t = Arvore()
        t.inserir(1)
        t.inserir(2, 1, "h")
        for _ in range(500):
            t.redimensionar(1, "right", 100, GAP)
        self.assertLessEqual(t.raiz.ratio, 0.9)
        for _ in range(500):
            t.redimensionar(1, "left", 100, GAP)
        self.assertGreaterEqual(t.raiz.ratio, 0.1)

    def test_trocar_inverte_posicoes(self):
        t = arvore_de_quatro()
        antes = t.layout(*AREA, GAP)
        t.trocar(1, 3)
        depois = t.layout(*AREA, GAP)
        self.assertEqual(depois[1], antes[3])
        self.assertEqual(depois[3], antes[1])
        self.assertEqual(depois[2], antes[2])

    def test_trocar_com_inexistente_nao_faz_nada(self):
        t = arvore_de_quatro()
        antes = t.layout(*AREA, GAP)
        t.trocar(1, 999)
        t.trocar(2, 2)
        self.assertEqual(t.layout(*AREA, GAP), antes)

    def test_alternar_divisao(self):
        t = Arvore()
        t.inserir(1)
        t.inserir(2, 1, "h")
        self.assertTrue(t.alternar_divisao(2))
        r = t.layout(*AREA, GAP)
        self.assertEqual(r[1][0], r[2][0])          # agora empilhadas
        t2 = Arvore()
        t2.inserir(1)
        self.assertFalse(t2.alternar_divisao(1))    # raiz sem divisão


class TestVizinho(unittest.TestCase):
    def setUp(self):
        self.r = arvore_de_quatro().layout(*AREA, GAP)

    def test_direcoes(self):
        self.assertEqual(vizinho(self.r, 1, "right"), 2)
        self.assertEqual(vizinho(self.r, 4, "up"), 1)
        self.assertEqual(vizinho(self.r, 3, "left"), 4)
        self.assertEqual(vizinho(self.r, 2, "down"), 3)

    def test_sem_vizinho_na_borda(self):
        self.assertIsNone(vizinho(self.r, 1, "left"))
        self.assertIsNone(vizinho(self.r, 1, "up"))
        self.assertIsNone(vizinho(self.r, 3, "right"))
        self.assertIsNone(vizinho(self.r, 3, "down"))

    def test_janela_desconhecida(self):
        self.assertIsNone(vizinho(self.r, 999, "left"))


if __name__ == "__main__":
    unittest.main()
