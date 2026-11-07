"""Rede de segurança: tudo compila e os scripts de shell têm sintaxe válida."""
import py_compile
import shutil
import subprocess
import tempfile
import unittest

from tests import _paths

RAIZ = _paths.RAIZ
SCRIPTS = ("start-jwm", "jwm-session", "jwm-layout")


class TestCompila(unittest.TestCase):
    def test_todo_python_da_raiz_compila(self):
        arquivos = sorted(RAIZ.glob("*.py"))
        self.assertTrue(arquivos)
        with tempfile.TemporaryDirectory() as tmp:
            for i, arq in enumerate(arquivos):
                with self.subTest(arquivo=arq.name):
                    py_compile.compile(str(arq), cfile=f"{tmp}/{i}.pyc", doraise=True)


@unittest.skipUnless(shutil.which("sh"), "sh não encontrado")
class TestShell(unittest.TestCase):
    def test_sintaxe_dos_scripts(self):
        for nome in SCRIPTS:
            arq = RAIZ / nome
            if not arq.exists():
                continue
            with self.subTest(script=nome):
                r = subprocess.run(["sh", "-n", str(arq)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
