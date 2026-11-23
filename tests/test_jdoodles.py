import random
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jcat
import jdoodles as d


class T(unittest.TestCase):
    def test_sprites_retangulares(self):
        for q in d.BORB:
            self.assertEqual(len(q), d.BORB_A)
            self.assertTrue(all(len(r) == d.BORB_L for r in q))
        for onda in (False, True):
            for braco in (0, 1, 2):
                px = d.pixels_fantasma(onda, braco)
                self.assertTrue(all(0 <= x < d.FANT_L and 0 <= y < d.FANT_A for x, y, _ in px))

    def test_noite_e_fantasma(self):
        self.assertTrue(d.eh_noite(23) and d.eh_noite(2) and not d.eh_noite(12))
        tm = time.strptime("2026-11-22 03:05", "%Y-%m-%d %H:%M")
        self.assertTrue(d.deve_fantasma(tm, ""))
        self.assertFalse(d.deve_fantasma(tm, "2026-11-22"))
        self.assertFalse(d.deve_fantasma(time.strptime("2026-11-22 04:00", "%Y-%m-%d %H:%M"), ""))

    def test_borboleta_ciclo_completo(self):
        lista = [jcat.Chao(0, 800, 200)]
        b = d.Borboleta(random.Random(1), (1000, 700), lista, 4)
        estados = set()
        for _ in range(6000):
            b.passo(0.05, lista)
            estados.add(b.estado)
            self.assertIn(b.quadro, (0, 1, 2))
            if b.fim:
                break
        self.assertTrue(b.fim)
        self.assertEqual(estados, {"chegando", "pousada", "indo"})

    def test_borboleta_janela_fecha(self):
        lista = [jcat.Chao(0, 800, 200)]
        b = d.Borboleta(random.Random(2), (1000, 700), lista, 4)
        for _ in range(400):
            b.passo(0.05, lista)
            if b.estado == "pousada":
                break
        b.passo(0.05, [])
        self.assertEqual(b.estado, "indo")

    def test_vagalumes_ficam_na_tela(self):
        v = d.Vagalume(random.Random(3), 500, 400)
        for _ in range(2000):
            v.passo(0.1)
            self.assertTrue(0 <= v.x <= 500 and 0 <= v.y <= 400)
        self.assertTrue(0 <= v.brilho(5.0) <= 1)
        self.assertTrue(any(d.retangulos_vagalumes([v], t / 10) for t in range(100)))

    def test_fantasma_termina(self):
        f = d.Fantasma((1000, 700), 4)
        for _ in range(2000):
            f.passo(0.05)
            if f.fim:
                break
        self.assertTrue(f.fim)


if __name__ == "__main__":
    unittest.main()
