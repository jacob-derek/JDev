import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jlog  # noqa: E402


class TestJlog(unittest.TestCase):
    def test_rotaciona_so_quando_passa_do_limite(self):
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "x.log"
            a.write_bytes(b"a" * 10)
            self.assertFalse(jlog.rotacionar(a, 100))
            a.write_bytes(b"a" * 200)
            self.assertTrue(jlog.rotacionar(a, 100))
            self.assertFalse(a.exists())
            self.assertEqual((Path(d) / "x.log.1").stat().st_size, 200)

    def test_rotacionar_arquivo_inexistente_nao_levanta(self):
        self.assertFalse(jlog.rotacionar(Path("/nao/existe/x.log")))

    def test_abrir_saida_corta_o_arquivo_grande(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_CACHE_HOME": d}):
            (Path(d) / "apps.log").write_bytes(b"x" * 500)
            f = jlog.abrir_saida("apps.log", limite=100)
            self.assertIsNotNone(f)
            f.close()
            self.assertEqual((Path(d) / "apps.log").stat().st_size, 0)
            self.assertTrue((Path(d) / "apps.log.1").exists())

    def test_sem_repetir_ignora_numero_de_sequencia(self):
        s = jlog.SemRepetir()
        self.assertTrue(s.nova("BadAccess (code = 10, resource_id = 396, sequence_number = 52)"))
        self.assertFalse(s.nova("BadAccess (code = 10, resource_id = 396, sequence_number = 99)"))
        self.assertTrue(s.nova("BadMatch (code = 8, resource_id = 396, sequence_number = 99)"))


if __name__ == "__main__":
    unittest.main()
