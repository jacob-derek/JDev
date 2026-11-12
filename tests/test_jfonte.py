"""Testes da escolha de fonte (jtheme.escolher_fonte)."""
import os
import unittest
from unittest import mock

from tests import _paths  # noqa: F401
import jtheme


class TestFonte(unittest.TestCase):
    def test_primeira_da_lista_que_existe(self):
        with mock.patch.object(jtheme, "fonte_pedida", return_value=None):
            self.assertEqual(jtheme.escolher_fonte({"DejaVu Sans Mono", "Iosevka"}), "Iosevka")

    def test_jfont_tem_prioridade(self):
        with mock.patch.dict(os.environ, {"JFONT": "dejavu sans mono"}):
            self.assertEqual(jtheme.escolher_fonte({"DejaVu Sans Mono", "Iosevka"}), "DejaVu Sans Mono")

    def test_nenhuma_instalada(self):
        with mock.patch.object(jtheme, "fonte_pedida", return_value=None):
            self.assertIsNone(jtheme.escolher_fonte({"Outra Fonte"}))

    def test_tema_void_existe_e_valida(self):
        self.assertIn("void", jtheme.THEMES)
        self.assertEqual(jtheme.validar("void"), [])


if __name__ == "__main__":
    unittest.main()
