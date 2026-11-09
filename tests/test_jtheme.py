"""Testes dos temas (jtheme.py)."""
import importlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import _paths  # noqa: F401
import jtheme

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
CORES = ("bg_deep", "bg", "bg_alt", "bg_hover", "line", "line2", "select", "fg", "fg_bright", "fg_soft",
         "secondary", "dim", "comment", "ln", "on_bright", "on_accent", "focus", "border", "red", "green",
         "yellow", "orange", "blue", "cyan", "cyan2", "purple", "border_idle", "header_idle", "header_focus",
         "ansi_black", "ansi_brightblack", "ansi_white", "ansi_brightwhite")


def luminancia(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contraste(a, b):
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def recarregar(**env):
    """Recarrega o jtheme com um ambiente controlado (sem HOME/XDG reais)."""
    base = {"HOME": tempfile.mkdtemp(), "XDG_CONFIG_HOME": tempfile.mkdtemp()}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=False):
        os.environ.pop("JTHEME", None) if "JTHEME" not in env else None
        return importlib.reload(jtheme)


class TestDados(unittest.TestCase):
    def test_todos_os_temas_tem_as_mesmas_chaves(self):
        esperado = set(jtheme.THEMES["tokyonight"])
        for nome, t in jtheme.THEMES.items():
            self.assertEqual(set(t), esperado, nome)

    def test_todas_as_cores_sao_hex_validos(self):
        for nome, t in jtheme.THEMES.items():
            for k in CORES:
                self.assertRegex(t[k], HEX, f"{nome}.{k}")

    def test_texto_legivel_sobre_o_fundo(self):
        for nome, t in jtheme.THEMES.items():
            self.assertGreaterEqual(contraste(t["fg"], t["bg"]), 6.0, nome)
            self.assertGreaterEqual(contraste(t["on_accent"], t["focus"]), 3.5, nome)
            self.assertGreaterEqual(contraste(t["on_bright"], t["green"]), 3.5, nome)

    def test_apenas_o_dawn_e_claro(self):
        claros = [n for n, t in jtheme.THEMES.items() if t["light"]]
        self.assertEqual(claros, ["dawn"])


class TestEscolha(unittest.TestCase):
    def tearDown(self):
        recarregar()  # volta ao estado neutro para não vazar entre testes

    def test_padrao_e_tokyonight(self):
        self.assertEqual(recarregar().NOME, "tokyonight")

    def test_variavel_de_ambiente(self):
        self.assertEqual(recarregar(JTHEME="gruvbox").NOME, "gruvbox")

    def test_apelidos(self):
        for apelido, alvo in jtheme.ALIASES.items():
            if alvo in jtheme.THEMES:
                self.assertEqual(recarregar(JTHEME=apelido.upper()).NOME, alvo, apelido)

    def test_apelidos_apontam_para_temas_que_existem(self):
        for apelido, alvo in jtheme.ALIASES.items():
            self.assertIn(alvo, jtheme.THEMES, f"apelido {apelido!r} aponta para tema inexistente")

    def test_tema_invalido_cai_no_padrao(self):
        self.assertEqual(recarregar(JTHEME="rosa-choque").NOME, "tokyonight")

    def _dois_temas(self):
        """Dois temas quaisquer diferentes do padrao (os nomes mudam conforme o repo)."""
        nomes = [n for n in jtheme.THEMES if n != "tokyonight"]
        return nomes[0], nomes[1]

    def test_arquivo_de_config(self):
        a, _b = self._dois_temas()
        cfg = tempfile.mkdtemp()
        (Path(cfg) / "jdev").mkdir()
        (Path(cfg) / "jdev" / "theme").write_text(a + "\n", encoding="utf-8")
        self.assertEqual(recarregar(XDG_CONFIG_HOME=cfg).NOME, a)

    def test_variavel_vence_o_arquivo(self):
        a, b = self._dois_temas()
        cfg = tempfile.mkdtemp()
        (Path(cfg) / "jdev").mkdir()
        (Path(cfg) / "jdev" / "theme").write_text(a + "\n", encoding="utf-8")
        self.assertEqual(recarregar(XDG_CONFIG_HOME=cfg, JTHEME=b).NOME, b)

    def test_constantes_seguem_o_tema(self):
        m = recarregar(JTHEME="gruvbox")
        self.assertEqual(m.PANE_BG, m.THEMES["gruvbox"]["bg"])
        self.assertFalse(m.LIGHT)
        self.assertTrue(recarregar(JTHEME="dawn").LIGHT)

    def test_estilos_sao_dicionarios_de_strings(self):
        m = recarregar(JTHEME="dawn")
        for fn in (m.estilo_jcode, m.estilo_jcode_idle, m.estilo_jfiles, m.estilo_jshell):
            d = fn()
            self.assertTrue(d)
            self.assertTrue(all(isinstance(k, str) and isinstance(v, str) for k, v in d.items()))


class TestLinhaDeComando(unittest.TestCase):
    def rodar(self, *args, **env):
        e = {**os.environ, "XDG_CONFIG_HOME": self.cfg, "HOME": self.cfg}
        e.pop("JTHEME", None)
        e.update(env)
        return subprocess.run([sys.executable, str(_paths.RAIZ / "jtheme.py"), *args],
                              capture_output=True, text=True, env=e)

    def setUp(self):
        self.cfg = tempfile.mkdtemp()

    def test_set_grava_o_arquivo(self):
        r = self.rodar("set", "gruvbox")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((Path(self.cfg) / "jdev" / "theme").read_text().strip(), "gruvbox")

    def test_set_invalido_falha_e_nao_grava(self):
        r = self.rodar("set", "nao-existe")
        self.assertEqual(r.returncode, 2)
        self.assertFalse((Path(self.cfg) / "jdev" / "theme").exists())

    def test_list_marca_o_ativo(self):
        r = self.rodar("list", JTHEME="dawn")
        self.assertRegex(r.stdout, r"\* dawn")

    def test_show_roda(self):
        self.assertEqual(self.rodar("show").returncode, 0)


if __name__ == "__main__":
    unittest.main()
