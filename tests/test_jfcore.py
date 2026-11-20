import os
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jfcore as j


class T(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "pasta").mkdir()
        (self.d / "b.py").write_text("x")
        (self.d / "A.txt").write_text("yy")
        (self.d / ".oculto").write_text("")

    def test_listar_ordem_e_ocultos(self):
        self.assertEqual([e.nome for e in j.listar(self.d)], ["pasta", "A.txt", "b.py"])
        self.assertIn(".oculto", [e.nome for e in j.listar(self.d, True)])
        self.assertEqual(j.listar(self.d, False, "tamanho")[1].nome, "A.txt")

    def test_filtrar(self):
        es = j.listar(self.d)
        self.assertEqual([e.nome for e in j.filtrar(es, "py")], ["b.py"])
        self.assertEqual(len(j.filtrar(es, "")), 3)
        self.assertEqual(j.filtrar(es, "zzz"), [])

    def test_resolver(self):
        self.assertEqual(j.resolver("../x", "/a/b"), Path("/a/x"))
        self.assertEqual(j.resolver("~", "/a"), Path.home())
        self.assertEqual(j.resolver("/etc", "/a"), Path("/etc"))

    def test_completar(self):
        (self.d / "pasta2").mkdir()
        novo, ops = j.completar("pas", self.d)
        self.assertEqual(novo, "pasta")
        self.assertEqual(sorted(ops), ["pasta/", "pasta2/"])
        novo, ops = j.completar("pasta2", self.d)
        self.assertEqual(novo, "pasta2/")
        self.assertEqual(j.completar("zz", self.d), ("zz", []))
        n, _ = j.completar(str(self.d) + "/pasta2", "/")
        self.assertTrue(n.endswith("pasta2/"))

    def test_linha_largura(self):
        e = j.listar(self.d)[1]
        for larg in (30, 44, 64, 100):
            self.assertEqual(sum(j.largura(t) for _, t in j.linha(e, larg, True, True, ("●", "yellow"), True)), larg)

    def test_cortar(self):
        self.assertEqual(j.cortar("abcdef", 4), "abc…")
        self.assertEqual(j.cortar("ab", 4), "ab  ")

    def test_porcelain(self):
        s = " M src/a.py\0?? src/n.txt\0D  src/sub/x\0R  novo\0velho\0"
        m = j.interpretar_porcelain(s, "src/")
        self.assertEqual(m["a.py"][0], "●")
        self.assertEqual(m["n.txt"][0], "?")
        self.assertEqual(m["sub"][0], "●")
        self.assertNotIn("novo", m)
        self.assertEqual(j.interpretar_porcelain("R  novo\0velho\0", "")["novo"][0], "●")

    def test_recentes(self):
        arq = self.d / "rec"
        j.recentes_registrar(self.d / "pasta", arq)
        j.recentes_registrar(self.d / "pasta", arq)
        dados = j.recentes_ler(arq)
        self.assertEqual(j.recentes_buscar("pasta", dados), [str(self.d / "pasta")])
        self.assertEqual(j.recentes_buscar("nada", dados), [])

    def test_argumentos_e_saida(self):
        o = j.ler_argumentos(["--multiple", "--out", "/t/o", "--start", "/x"])
        self.assertTrue(o.pick and o.multiplo and o.saida == "/t/o" and o.inicio == "/x")
        self.assertEqual(j.ler_argumentos(["--save", "a.png"]).salvar, "a.png")
        self.assertFalse(j.ler_argumentos([]).pick)
        self.assertEqual(j.ler_argumentos(["/home/x"]).inicio, "/home/x")
        out = self.d / "out"
        j.gravar_escolha(str(out), [self.d / "b.py"])
        self.assertEqual(out.read_text(), f"{self.d / 'b.py'}\n")
        j.gravar_escolha(str(out), [])
        self.assertEqual(out.read_text(), "")

    def test_ponto_de_partida(self):
        self.assertEqual(j.ponto_de_partida(str(self.d / "b.py"), "/")[1], "b.py")
        self.assertEqual(j.ponto_de_partida(str(self.d / "novo.png"), "/"), (self.d.resolve(), None))
        self.assertEqual(j.ponto_de_partida("/nao/existe/x", "/tmp"), (Path("/tmp"), None))

    def test_nome_livre_e_dentro(self):
        self.assertEqual(j.nome_livre(self.d / "b.py").name, "b (2).py")
        self.assertTrue(j.pasta_dentro_de_si(self.d / "pasta", self.d / "pasta"))
        self.assertFalse(j.pasta_dentro_de_si(self.d / "pasta", self.d))

    def test_arrastar_sem_ferramenta(self):
        old = os.environ.get("PATH")
        os.environ["PATH"] = "/nonexistent"
        try:
            self.assertIsNone(j.comando_arrastar([self.d]))
        finally:
            os.environ["PATH"] = old


if __name__ == "__main__":
    unittest.main()
