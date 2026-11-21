import os
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jrcore as j


def app(nome, exe="x", comment="", cats="", id_=None):
    return {"id": id_ or nome, "name": nome, "exec": exe, "argv": [exe], "comment": comment,
            "categories": cats, "path": "", "terminal": False, "cwd": ""}


class T(unittest.TestCase):
    def test_limpar_argv(self):
        self.assertEqual(j.limpar_argv("firefox %u"), ["firefox"])
        self.assertEqual(j.limpar_argv("app --file=%f -x"), ["app", "--file=", "-x"])
        self.assertEqual(j.limpar_argv("echo 100%%"), ["echo", "100%"])
        self.assertIsNone(j.limpar_argv('"aberto'))
        self.assertIsNone(j.limpar_argv(""))

    def test_ler_aplicativos(self):
        d = Path(tempfile.mkdtemp())
        (d / "ok.desktop").write_text("[Desktop Entry]\nType=Application\nName=Meu App\nExec=sh %U\nComment=teste\n")
        (d / "oculto.desktop").write_text("[Desktop Entry]\nName=O\nExec=sh\nNoDisplay=true\n")
        (d / "sumiu.desktop").write_text("[Desktop Entry]\nName=S\nExec=/nao/existe/bin\n")
        (d / "tryexec.desktop").write_text("[Desktop Entry]\nName=T\nExec=sh\nTryExec=/nao/existe\n")
        (d / "lixo.desktop").write_text("isso nao eh ini")
        apps = j.ler_aplicativos([str(d)])
        self.assertEqual([a["name"] for a in apps], ["Meu App"])
        self.assertEqual(apps[0]["argv"], ["sh"])

    def test_busca_relevancia_e_uso(self):
        apps = [app("Firefox"), app("Fire Alarm"), app("Editor de Fotos", comment="firefox like"), app("Terminal")]
        r = [a["name"] for a in j.buscar(apps, "fire")]
        self.assertNotIn("Terminal", r)
        self.assertEqual(j.buscar(apps, "firefox")[0]["name"], "Firefox")
        self.assertEqual([a["name"] for a in j.buscar(apps, "zzzz")], [])
        # empate de relevância -> o mais usado ganha
        r = j.buscar([app("Alfa"), app("Alfinete")], "al", {"Alfinete": 5})
        self.assertEqual(r[0]["name"], "Alfinete")
        # sem consulta -> mais usados primeiro
        self.assertEqual(j.buscar(apps, "", {"Terminal": 3})[0]["name"], "Terminal")
        # várias palavras
        self.assertEqual([a["name"] for a in j.buscar(apps, "editor fotos")], ["Editor de Fotos"])
        # sigla (subsequência) e palavra no meio do nome
        self.assertEqual(j.buscar([app("Visual Studio Code")], "vsc")[0]["name"], "Visual Studio Code")
        self.assertEqual(j.buscar([app("Visual Studio Code")], "code")[0]["name"], "Visual Studio Code")

    def test_uso_e_cache(self):
        d = Path(tempfile.mkdtemp())
        arq = d / "uso.json"
        j.uso_registrar("a.desktop", arq)
        j.uso_registrar("a.desktop", arq)
        self.assertEqual(j.uso_ler(arq), {"a.desktop": 2})
        arq.write_text("{quebrado")
        self.assertEqual(j.uso_ler(arq), {})
        c = d / "c.json"
        j.cache_gravar([app("X")], c)
        self.assertEqual(j.cache_ler(c)[0]["name"], "X")
        c.write_text('{"apps": [{"name": "falta chave"}, 3]}')
        self.assertEqual(j.cache_ler(c), [])

    def test_instancia(self):
        d = Path(tempfile.mkdtemp())
        lock = d / "l"
        self.assertFalse(j.instancia_viva(lock))
        lock.write_text(str(os.getpid()))
        self.assertTrue(j.instancia_viva(lock, marca="python"))
        self.assertFalse(j.instancia_viva(lock, marca="coisa-que-nao-eh-este-processo"))
        lock.write_text("999999999")
        self.assertFalse(j.instancia_viva(lock))

    def test_comandos(self):
        self.assertEqual(j.argv_do_comando("ls -la"), ["ls", "-la"])
        self.assertEqual(j.argv_do_comando("ls | wc -l"), ["sh", "-c", "ls | wc -l"])
        self.assertEqual(j.argv_do_comando("!echo oi"), ["sh", "-c", "echo oi"])
        self.assertIsNone(j.argv_do_comando("!  "))
        self.assertIsNone(j.argv_do_comando("   "))
        self.assertEqual(j.argv_do_comando('echo "abre')[:2], ["sh", "-c"])

    def test_terminal(self):
        r = j.argv_terminal(["htop"], which=lambda n: "/usr/bin/xterm" if n == "xterm" else None)
        self.assertTrue(r[-1] == "htop")
        self.assertIsNone(j.argv_terminal(["a"], which=lambda n: None) if not j.JTERM.exists() else None)

    def test_calcular(self):
        self.assertEqual(j.calcular("=2+2"), "4")
        self.assertEqual(j.calcular("= 2*(3+4)"), "14")
        self.assertEqual(j.calcular("=7/2"), "3.5")
        self.assertEqual(j.calcular("=1,5+1"), "2.5")
        self.assertEqual(j.calcular("=2**10"), "1024")
        for ruim in ("2+2", "=", "=1/0", "=__import__('os')", "=2**99999", "=abs(1)", "=1+", "=(" * 3):
            self.assertIsNone(j.calcular(ruim), ruim)


if __name__ == "__main__":
    unittest.main()
