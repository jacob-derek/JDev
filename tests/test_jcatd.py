import random
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jcatsprite as jcat
import jcat as c


class T(unittest.TestCase):
    def test_chaos_junta_e_filtra(self):
        j = [(0, 44, 500, 600), (500, 44, 500, 600), (0, 300, 400, 300), (10, 10, 30, 30)]
        r = c.chaos(j, (0, 44, 1000, 700))
        self.assertIn(c.Chao(0, 1000, 44), r)
        self.assertIn(c.Chao(0, 400, 300), r)
        self.assertEqual(len(r), 2)

    def test_chao_padrao(self):
        self.assertEqual(c.chaos([], (0, 44, 1920, 900)), [c.Chao(0, 1920, 44)])

    def test_retangulos_cobrem_pixels(self):
        px = jcat.Gato(skin="gatinha").pixels()
        rs = c.retangulos(px, 3)
        area = sum(w * h for _, _, _, w, h in rs)
        self.assertEqual(area, len(px) * 9)
        self.assertTrue(all(y >= 0 for _, _, y, _, _ in rs))

    def test_passeio_pousa_e_pula(self):
        g = jcat.Gato(random.Random(2))
        p = c.Passeio(g, 3, random.Random(1))
        lista = [c.Chao(0, 800, 44), c.Chao(0, 800, 400)]
        for _ in range(50):
            x, y = p.atualizar(0.1, lista)
        self.assertIn(y, (44, 400))
        p.pulo = (0.0, p.y, lista[1] if p.chao == lista[0] else lista[0])
        for _ in range(10):
            x, y = p.atualizar(0.1, lista)
        self.assertFalse(p.pulando)

    def test_janela_fecha_cai(self):
        g = jcat.Gato(random.Random(3))
        p = c.Passeio(g, 3, random.Random(1))
        p.atualizar(0.1, [c.Chao(0, 800, 300)])
        for _ in range(15):
            p.atualizar(0.1, [c.Chao(0, 800, 44)])
        self.assertEqual(p.chao.y, 44)

    def test_desligado(self):
        import os
        anterior = os.environ.get("JCAT")
        os.environ["JCAT"] = "0"
        try:
            self.assertEqual(c.main([]), 0)
        finally:
            if anterior is None:
                os.environ.pop("JCAT", None)
            else:
                os.environ["JCAT"] = anterior


if __name__ == "__main__":
    unittest.main()
