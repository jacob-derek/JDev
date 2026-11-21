import random, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jcat

TODOS = [jcat.ANDA_A, jcat.ANDA_B, jcat.SENTA_A, jcat.SENTA_B, jcat.DORME_A, jcat.DORME_B]


class T(unittest.TestCase):
    def test_sprites_tem_tamanho_certo_e_letras_validas(self):
        for f in TODOS:
            self.assertEqual(len(f), jcat.ALT)
            for linha in f:
                self.assertEqual(len(linha), jcat.LARG)
                self.assertFalse(set(linha) - set(".BDENZH"))

    def test_nunca_sai_do_espaco(self):
        for seed in range(20):
            g = jcat.Gato(random.Random(seed))
            for _ in range(3000):
                g.passo(0.12, 100, 260, 2, tocando=(seed % 2 == 0))
                self.assertTrue(g.visivel)
                self.assertTrue(100 <= g.x <= 260 - jcat.LARG * 2, g.x)

    def test_usa_todos_os_estados_e_anda_nos_dois_sentidos(self):
        g = jcat.Gato(random.Random(3))
        vistos, dirs = set(), set()
        for _ in range(20000):
            g.passo(0.12, 0, 400, 2)
            vistos.add(g.estado)
            if g.estado == "anda":
                dirs.add(g.dir)
        self.assertEqual(vistos, {"anda", "senta", "dorme"})
        self.assertEqual(dirs, {1, -1})

    def test_com_musica_nao_dorme(self):
        g = jcat.Gato(random.Random(5))
        for _ in range(20000):
            g.passo(0.12, 0, 400, 2, tocando=True)
            self.assertNotEqual(g.estado, "dorme")

    def test_estreito_esconde(self):
        g = jcat.Gato(random.Random(1))
        g.passo(0.1, 0, 20, 2)
        self.assertFalse(g.visivel)
        g.passo(0.1, 0, 200, 2)
        self.assertTrue(g.visivel)

    def test_espelho_e_coracao(self):
        g = jcat.Gato(random.Random(1))
        g.passo(0.1, 0, 200, 2)
        g.estado, g.dir, g.quadro_i = "senta", 1, 0
        dir_ = {(x, y) for x, y, _ in g.pixels()}
        g.dir = -1
        esq = {(x, y) for x, y, _ in g.pixels()}
        self.assertEqual({(jcat.LARG - 1 - x, y) for x, y in dir_}, esq)
        g.carinho()
        self.assertEqual(g.estado, "senta")
        self.assertTrue(any(y < 0 and ch == "H" for _, y, ch in g.pixels()))
        for _ in range(30):
            g.passo(0.1, 0, 200, 2)
        self.assertFalse(any(y < 0 for _, y, _ in g.pixels()))

    def test_dt_grande_nao_teletransporta(self):
        g = jcat.Gato(random.Random(2))
        g.passo(0.1, 0, 300, 2)
        g.estado = "anda"
        g.dir = 1
        x0 = g.x
        g.passo(60.0, 0, 300, 2)       # janela travada por um minuto
        self.assertLessEqual(abs(g.x - x0), jcat.VELOCIDADE * 0.5 + 1e-6)


if __name__ == "__main__":
    unittest.main()
