import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jbirds as j


class T(unittest.TestCase):
    def test_sprites(self):
        for f in j.ASAS:
            self.assertEqual(len(f), j.ALT)
            self.assertTrue(all(len(r) == j.LARG for r in f))
            self.assertTrue(any("B" in r for r in f))

    def test_alpha(self):
        self.assertEqual(j.alpha_cortina(0), 1.0)
        self.assertEqual(j.alpha_cortina(j.FADE_FIM + 1), 0.0)
        v = [j.alpha_cortina(t / 10) for t in range(60)]
        self.assertTrue(all(a >= b for a, b in zip(v, v[1:], strict=False)))

    def test_bando(self):
        area = (0, 0, 1920, 1080)
        aves = j.bando(random.Random(1), area, 7)
        self.assertEqual(len(aves), 7)
        for a in aves:
            self.assertIsNone(a.pos(a.atraso - 0.1))
            self.assertLess(a.pos(a.atraso)[0], 0)
            self.assertIn(a.quadro(1.3), (0, 1, 2))
        self.assertTrue(any(a.saiu(6, area) for a in aves))

    def test_desligado(self):
        import os
        os.environ["JBIRDS"] = "0"
        self.assertEqual(j.main([]), 0)


if __name__ == "__main__":
    unittest.main()
