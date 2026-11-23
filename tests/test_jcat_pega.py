import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jcat
import jcatsprite as sp


class T(unittest.TestCase):
    def test_sprites_pega(self):
        for skin in sp.SKINS:
            for q in sp.SKINS[skin]["pega"]:
                self.assertEqual(len(q), sp.ALT)
                self.assertTrue(all(len(r) == sp.LARG for r in q))

    def test_gato_pega_e_solta(self):
        g = sp.Gato(random.Random(1))
        g.pegar()
        self.assertEqual(g.estado, "pega")
        q0 = g.quadro_i
        g.animar(0.2)
        self.assertNotEqual(q0, g.quadro_i)
        self.assertTrue(g.pixels())
        g.soltar()
        self.assertEqual(g.estado, "senta")

    def test_cair_no_chao_abaixo(self):
        g = sp.Gato(random.Random(2))
        p = jcat.Passeio(g, 3, random.Random(1))
        lista = [jcat.Chao(0, 900, 44), jcat.Chao(0, 900, 500)]
        p.atualizar(0.1, lista)
        p.pegar()
        p.levar(300, 200)
        self.assertEqual(p.atualizar(0.1, lista), (300, 200))
        p.soltar(lista)
        for _ in range(200):
            p.atualizar(0.016, lista)
            if not p.ocupado:
                break
        self.assertEqual(p.y, 500)
        self.assertEqual(g.estado, "senta")

    def test_soltar_embaixo_do_chao_sobe(self):
        g = sp.Gato(random.Random(3))
        p = jcat.Passeio(g, 3, random.Random(1))
        lista = [jcat.Chao(0, 900, 100)]
        p.atualizar(0.1, lista)
        p.pegar()
        p.levar(100, 700)
        p.soltar(lista)
        self.assertTrue(p.pulando)
        for _ in range(100):
            p.atualizar(0.02, lista)
        self.assertEqual(p.y, 100)

    def test_soltar_fora_do_x_vai_ao_mais_proximo(self):
        g = sp.Gato(random.Random(4))
        p = jcat.Passeio(g, 3, random.Random(1))
        lista = [jcat.Chao(0, 400, 300), jcat.Chao(500, 900, 300)]
        p.atualizar(0.1, lista)
        p.pegar()
        p.levar(2000, 100)
        p.soltar(lista)
        self.assertLessEqual(g.x, 900 - sp.LARG * 3)


if __name__ == "__main__":
    unittest.main()
