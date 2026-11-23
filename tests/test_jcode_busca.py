"""JCode: busca (Ctrl+F), mapa no terminal (-map), setup do cursor (-setup) e jcursor."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests import _paths  # noqa: F401
import JCode
import jcursor


class TestBusca(unittest.TestCase):
    def test_smart_case(self):
        self.assertEqual(JCode.buscar_ocorrencias("Foo foo FOO", "foo"), [0, 4, 8])
        self.assertEqual(JCode.buscar_ocorrencias("Foo foo FOO", "Foo"), [0])

    def test_termo_vazio_ou_ausente(self):
        self.assertEqual(JCode.buscar_ocorrencias("abc", ""), [])
        self.assertEqual(JCode.buscar_ocorrencias("abc", "z"), [])

    def test_termo_e_literal_nao_regex(self):
        self.assertEqual(JCode.buscar_ocorrencias("a.b axb", "a.b"), [0])
        self.assertEqual(JCode.buscar_ocorrencias("f(x) f(y)", "f("), [0, 5])

    def test_limite(self):
        self.assertEqual(len(JCode.buscar_ocorrencias("a" * 100, "a", limite=10)), 10)

    def test_proxima_e_anterior_dao_a_volta(self):
        pos = [3, 9, 20]
        self.assertEqual(JCode.escolher_ocorrencia(pos, 0, 1), 0)
        self.assertEqual(JCode.escolher_ocorrencia(pos, 4, 1), 1)
        self.assertEqual(JCode.escolher_ocorrencia(pos, 21, 1), 0)      # volta ao começo
        self.assertEqual(JCode.escolher_ocorrencia(pos, 9, -1), 0)
        self.assertEqual(JCode.escolher_ocorrencia(pos, 3, -1), 2)      # volta ao fim
        self.assertEqual(JCode.escolher_ocorrencia([], 3, 1), -1)

    def test_unico_resultado_nao_trava(self):
        self.assertEqual(JCode.escolher_ocorrencia([5], 5, 1), 0)
        self.assertEqual(JCode.escolher_ocorrencia([5], 6, 1), 0)
        self.assertEqual(JCode.escolher_ocorrencia([5], 5, -1), 0)


class TestMapaTerminal(unittest.TestCase):
    CODIGO = "class A:\n    def f(self):\n        return 1\n\ndef g():\n    pass\n"

    def test_lista_blocos_e_linhas(self):
        out = JCode.mapa_em_texto(self.CODIGO, ".py", "x.py", 80, 30)
        self.assertIn("x.py  ·  6 linhas", out)
        self.assertIn("class A", out)
        self.assertIn("def g", out)

    def test_marca_erro_de_sintaxe(self):
        out = JCode.mapa_em_texto("def f(:\n    pass\n", ".py", "x.py", 80, 30)
        self.assertIn("erro de sintaxe L1", out)

    def test_arquivo_vazio_e_markdown(self):
        self.assertIn("vazio", JCode.mapa_em_texto("  \n", ".py", "v.py"))
        out = JCode.mapa_em_texto("# Titulo\ntexto\n## Sub\nmais\n", ".md", "a.md", 80, 30)
        self.assertIn("# Titulo", out)

    def test_sem_cor_nao_tem_escape(self):
        self.assertNotIn("\x1b", JCode.mapa_em_texto(self.CODIGO, ".py", "x.py", 80, 30, cor=False))
        self.assertIn("\x1b", JCode.mapa_em_texto(self.CODIGO, ".py", "x.py", 80, 30, cor=True))

    def test_arquivo_enorme_e_terminal_pequeno_nao_quebram(self):
        grande = "x = 1\n" * 50_000
        JCode.mapa_em_texto(grande, ".py", "g.py", 20, 5)
        JCode.mapa_em_texto(self.CODIGO, ".py", "x.py", 10, 3)


class TestSetup(unittest.TestCase):
    def rodar(self, respostas, caminho):
        it = iter(respostas)
        saidas = []
        ok = JCode.executar_setup(lambda _p="": next(it), saidas.append, caminho)
        return ok, "\n".join(saidas)

    def test_escolhe_e_salva(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "jcode.json"
            ok, _ = self.rodar(["2", "2"], arq)         # Bloco, não pisca
            self.assertTrue(ok)
            self.assertEqual(json.loads(arq.read_text()), {"cursor": "block", "piscar": False})

    def test_enter_mantem_o_atual(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "jcode.json"
            self.rodar(["", ""], arq)
            self.assertEqual(json.loads(arq.read_text()), {"cursor": "bar", "piscar": True})

    def test_opcao_invalida_pergunta_de_novo(self):
        with tempfile.TemporaryDirectory() as d:
            ok, texto = self.rodar(["9", "abc", "3", "1"], Path(d) / "j.json")
            self.assertTrue(ok)
            self.assertIn("Opção inválida", texto)

    def test_ctrl_c_cancela_sem_salvar(self):
        def levanta(_p=""):
            raise KeyboardInterrupt
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "j.json"
            ok = JCode.executar_setup(levanta, lambda *_: None, arq)
            self.assertFalse(ok)
            self.assertFalse(arq.exists())


class TestJcursor(unittest.TestCase):
    def test_codigos_ida_e_volta(self):
        for forma in ("bar", "block", "underline"):
            for pisca in (True, False):
                self.assertEqual(jcursor.decscusr(jcursor.codigo(forma, pisca)), (forma, pisca))

    def test_sequencia(self):
        self.assertEqual(jcursor.sequencia({"cursor": "bar", "piscar": True}), "\x1b[5 q")
        self.assertEqual(jcursor.sequencia({"cursor": "block", "piscar": False}), "\x1b[2 q")
        self.assertEqual(jcursor.sequencia({"cursor": "default", "piscar": True}), "\x1b[0 q")

    def test_config_quebrada_vira_padrao(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "j.json"
            self.assertEqual(jcursor.carregar(arq), jcursor.PADRAO)
            arq.write_text("{ nao e json")
            self.assertEqual(jcursor.carregar(arq), jcursor.PADRAO)
            arq.write_text('{"cursor": "estrela", "piscar": "sim"}')
            self.assertEqual(jcursor.carregar(arq), jcursor.PADRAO)
            arq.write_text('["lista"]')
            self.assertEqual(jcursor.carregar(arq), jcursor.PADRAO)

    def test_ps_desconhecido_e_bloco_fixo(self):
        self.assertEqual(jcursor.decscusr(99), ("block", False))


class TestComandos(unittest.TestCase):
    def test_comando_map_arquivo_inexistente(self):
        self.assertEqual(JCode.comando_map("/nao/existe.py"), 1)

    def test_comando_map_imprime(self):
        with tempfile.TemporaryDirectory() as d:
            arq = os.path.join(d, "a.py")
            Path(arq).write_text("def f():\n    pass\n")
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(JCode.comando_map(arq), 0)
            self.assertIn("def f", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
