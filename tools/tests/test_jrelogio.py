import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jrelogio as j


class T(unittest.TestCase):
    def test_sprite_tucano(self):
        self.assertEqual(len(j.TUCANO), 15)
        self.assertTrue(all(len(r) == 16 for r in j.TUCANO))
        usadas = {c for r in j.TUCANO for c in r if c != "."}
        self.assertLessEqual(usadas, set(j.CORES))

    def test_digitos(self):
        for c, g in j.DIGITOS.items():
            self.assertEqual(len(g), 7)
            self.assertEqual(len({len(r) for r in g}), 1, c)

    def test_areia_conservada(self):
        def n_areia(p):
            return sum(1 for _x, _y, c in j.ampulheta_pixels(p, 0, fluxo=False) if c in ("areia", "areia2"))
        self.assertEqual(n_areia(0.0) > 0, True)
        self.assertEqual(n_areia(1.0) > 0, True)
        # a quantidade total fica na mesma ordem de grandeza (o monte do fundo é um pouco mais estreito)
        self.assertLess(abs(n_areia(0.0) - n_areia(1.0)), n_areia(0.0) * 0.2)

    def test_virar_espelha(self):
        px = j.ampulheta_pixels(1.0, 0, fluxo=False)
        invertido = j.virar(px, -1)
        ys_antes = [y for _x, y, c in px if c.startswith("areia")]
        ys_depois = [y for _x, y, c in invertido if c.startswith("areia")]
        self.assertGreater(min(ys_antes), j.PESCOCO)
        self.assertLess(max(ys_depois), j.PESCOCO)

    def test_texto_cabe(self):
        for hhmm in ("00:00", "12:34", "23:59"):
            for dp in (True, False):
                for x, y, _ in j.texto_pixels(hhmm, dp):
                    self.assertTrue(0 <= x < j.W and 52 <= y <= 58)

    def test_cena_e_agrupar(self):
        base = time.mktime((2026, 11, 23, 13, 45, 0, 0, 0, -1))
        for dt in (0.1, 0.5, 5, 30, 59.9):
            px = j.cena_pixels(base + dt)
            r = j.agrupar(px)
            self.assertTrue(r)
            self.assertTrue(all(c in j.CORES for _x, _y, _w, c in r))
            self.assertTrue(all(0 <= x and x + w <= j.W for x, _y, w, _c in r))

    def test_duracao(self):
        for txt, seg in (("90", 90), ("45s", 45), ("5m", 300), ("1h30m", 5400), ("1:30", 90), ("1:02:03", 3723), ("25 m", 1500)):
            self.assertEqual(j.parse_duracao(txt), seg, txt)
        for ruim in ("", "abc", "0", "5x"):
            with self.assertRaises(ValueError):
                j.parse_duracao(ruim)

    def test_timer(self):
        self.assertEqual(j.texto_restante(1500), "25:00")
        self.assertEqual(j.texto_restante(61.2), "01:03")
        self.assertEqual(j.texto_restante(-5), "00:00")
        self.assertEqual(j.texto_restante(5400), "01:30")
        ini = 1_000_000.0
        for dt in (0, 100, 1499, 1500, 2000):
            r = j.agrupar(j.cena_pixels(ini + dt, timer=(ini, 1500)))
            self.assertTrue(r)

    def test_noite(self):
        self.assertTrue(j.eh_noite(23) and j.eh_noite(3) and not j.eh_noite(14))
        base = time.mktime((2026, 11, 23, 13, 45, 0, 0, 0, -1)) + 5
        com_zz = [c for _x, _y, c in j.tucano_pixels(base, True) if c == "zz"]
        sem_zz = [c for _x, _y, c in j.tucano_pixels(base, False) if c == "zz"]
        self.assertTrue(com_zz)
        self.assertFalse(sem_zz)


if __name__ == "__main__":
    unittest.main()
