import os
import tempfile
import unittest
from pathlib import Path

from tests import _paths  # noqa: F401
import jstatus


def base(**kw):
    e = dict(nome="JCode.py", modificado=False, salvo_ok=True, linha=0, coluna=0, total=10,
             ramo=None, flags=[], erro_sintaxe=None, mensagens=[], modo=None)
    e.update(kw)
    return e


def texto(frags):
    return "".join(t for _, t in frags)


class TestMontar(unittest.TestCase):
    def test_ocupa_exatamente_a_largura(self):
        for nerd in (True, False):
            for w in (20, 30, 45, 60, 80, 120, 200):
                f = jstatus.montar_status(base(ramo="main", flags=["CRLF"], modo="busca", modo_texto="x 1/2",
                                               erro_sintaxe=(3, "invalid syntax"), mensagens=["Salvo"]), w, nerd)
                self.assertEqual(sum(len(t) for _, t in f), max(20, w), (nerd, w))

    def test_icone_so_com_nerd(self):
        com = texto(jstatus.montar_status(base(), 80, True))
        sem = texto(jstatus.montar_status(base(), 80, False))
        self.assertIn("", com)
        self.assertIn(jstatus.CAP_E, com)
        self.assertNotIn("", sem)
        self.assertNotIn(jstatus.CAP_E, sem)

    def test_estado_do_arquivo(self):
        self.assertIn("●", texto(jstatus.montar_status(base(modificado=True), 80)))
        self.assertIn("✓", texto(jstatus.montar_status(base(), 80)))
        self.assertIn("!", texto(jstatus.montar_status(base(salvo_ok=False), 80)))

    def test_posicao_e_percentual(self):
        t = texto(jstatus.montar_status(base(linha=4, coluna=2, total=10), 100))
        self.assertIn("5:3", t)
        self.assertIn("50%", t)

    def test_posicao_tem_prioridade_sobre_mensagem_e_ramo(self):
        t = texto(jstatus.montar_status(base(ramo="feature/x", linha=11, coluna=4,
                                             mensagens=["uma mensagem bem comprida " * 3]), 70))
        self.assertIn("12:5", t)

    def test_erro_de_sintaxe_aparece_em_destaque(self):
        f = jstatus.montar_status(base(erro_sintaxe=(12, "invalid syntax")), 100)
        self.assertIn("✗ L12: invalid syntax", texto(f))
        self.assertTrue(any("st.erro" in c for c, _ in f))

    def test_modo_e_ramo(self):
        t = texto(jstatus.montar_status(base(modo="busca", modo_texto="foo 3/12", ramo="main"), 100))
        self.assertIn("BUSCAR foo 3/12", t)
        self.assertIn("main", t)

    def test_nome_enorme_e_largura_minima_nao_quebram(self):
        jstatus.montar_status(base(nome="a" * 500 + ".py"), 20, True)
        jstatus.montar_status(base(nome="x"), 1, True)


class TestEstilos(unittest.TestCase):
    def test_toda_classe_usada_tem_estilo(self):
        est = jstatus.estilos_status()
        casos = [base(ramo="m", flags=["CRLF"], modo=m, modo_texto="x", erro_sintaxe=(1, "e"),
                      mensagens=["a"], modificado=mod) for m in ("busca", "ir", "sel", "exp", None) for mod in (True, False)]
        casos.append(base(salvo_ok=False, erro_salvar="disco cheio"))
        for e in casos:
            for nerd in (True, False):
                for cls, _ in jstatus.montar_status(e, 140, nerd):
                    for c in cls.split():
                        if c.startswith("class:"):
                            self.assertIn(c[6:], est, c)
                        else:
                            self.assertIn(c, est, c)

    def test_estilos_sao_cores_validas(self):
        for nome, v in jstatus.estilos_status().items():
            self.assertRegex(v, r"#[0-9a-fA-F]{6}", nome)


class TestLinguagemERamo(unittest.TestCase):
    def test_linguagem(self):
        self.assertEqual(jstatus.linguagem("a.PY")[0], "Python")
        self.assertEqual(jstatus.linguagem("Makefile"), jstatus.PADRAO_ARQ)

    def test_ramo_git(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / ".git").mkdir()
            (raiz / ".git" / "HEAD").write_text("ref: refs/heads/feature/x\n")
            (raiz / "sub").mkdir()
            self.assertEqual(jstatus.ramo_git(raiz / "sub" / "a.py"), "x")
            (raiz / ".git" / "HEAD").write_text("0123456789abcdef\n")
            self.assertEqual(jstatus.ramo_git(raiz / "sub" / "a.py"), "0123456")

    def test_sem_repositorio_ou_arquivo_inexistente(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(jstatus.ramo_git(os.path.join(d, "nada", "a.py")) or None)


if __name__ == "__main__":
    unittest.main()
