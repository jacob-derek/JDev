"""jbash: motor bash do JShell (precisa de bash; sem ele os testes são pulados)."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jbash  # noqa: E402


@unittest.skipUnless(shutil.which("bash"), "sem bash")
class TestMotor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.tmp.name, "JSH_SEM_BASHRC": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)
        self.m = jbash.Motor(bashrc=False)
        self.addCleanup(self.m.fechar)

    def test_inicia_e_executa(self):
        self.assertTrue(self.m.iniciar(), self.m.ultimo_erro)
        self.assertEqual(self.m.executar("true"), 0)
        self.assertEqual(self.m.executar("false"), 1)

    def test_cwd_e_variaveis_persistem(self):
        self.assertTrue(self.m.iniciar(), self.m.ultimo_erro)
        self.m.executar("cd /tmp; export JBASH_X=oi")
        self.assertEqual(os.path.realpath(self.m.cwd), os.path.realpath("/tmp"))

    def test_sintaxe_incompleta_nao_trava(self):
        self.assertTrue(self.m.iniciar(), self.m.ultimo_erro)
        t0 = time.monotonic()
        self.assertEqual(self.m.executar("if true; then"), 2)
        self.assertLess(time.monotonic() - t0, 3)

    def test_init_quebrado_desiste_em_vez_de_travar(self):
        quebrado = jbash.INIT.replace("__jsh_fim() {", "__jsh_fim() { (", 1)   # erro de sintaxe
        with mock.patch.object(jbash, "INIT", quebrado), mock.patch.object(jbash, "LIMITE_INICIO", 1.5):
            t0 = time.monotonic()
            self.assertFalse(self.m.iniciar())
            self.assertLess(time.monotonic() - t0, 6)
        self.assertTrue(self.m.ultimo_erro)
        self.assertFalse(self.m.disponivel())

    def test_completion_pede_filenames_via_compopt(self):
        """_filedir & cia chamam `compopt -o filenames`: sem isso as pastas ficavam sem a barra."""
        self.assertTrue(self.m.iniciar(), self.m.ultimo_erro)
        d = os.path.join(self.tmp.name, "pa")
        os.makedirs(os.path.join(d, "subdir"))
        self.m.executar(f"cd {d}")
        self.m.executar('_t() { compopt -o filenames; COMPREPLY=($(compgen -d -- "$2")); }; complete -F _t tcmd')
        opts, cands = self.m.completar("tcmd su", ["tcmd", "su"], 1)
        self.assertIn("filenames", opts)
        self.assertEqual(cands, ["subdir"])

    def test_completion_dash_d_vira_filenames(self):
        self.assertTrue(self.m.iniciar(), self.m.ultimo_erro)
        d = os.path.join(self.tmp.name, "pb")
        os.makedirs(os.path.join(d, "subdir"))
        self.m.executar(f"cd {d}; complete -d tdir")
        opts, cands = self.m.completar("tdir su", ["tdir", "su"], 1)
        self.assertIn("filenames", opts)
        self.assertEqual(cands, ["subdir"])

    def test_compopt_do_bash_volta_ao_normal_depois(self):
        self.assertTrue(self.m.iniciar(), self.m.ultimo_erro)
        self.m.executar("complete -d tdir")
        self.m.completar("tdir ", ["tdir", ""], 1)
        self.m.executar('[ "$(type -t compopt)" = builtin ]')
        self.assertEqual(self.m.status, 0)

    def test_init_gravado_por_inteiro(self):
        arq = jbash.Motor._gravar_init()
        self.assertEqual(arq.read_text(encoding="utf-8"), jbash.INIT)
        self.assertEqual([p.name for p in arq.parent.iterdir() if p.name.endswith(".tmp")], [])

    def test_init_bash_tem_sintaxe_valida(self):
        import subprocess
        r = subprocess.run(["bash", "-n", str(jbash.Motor._gravar_init())], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
