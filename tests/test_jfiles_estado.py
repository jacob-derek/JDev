"""Exercita o estado/ações do JFiles com um prompt_toolkit de mentira (sem terminal)."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


def _stub():
    class Qualquer:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return Qualquer()
        def __getattr__(self, n): return Qualquer()
        def add(self, *a, **k): return lambda f: f
    def mod(nome, **attrs):
        m = types.ModuleType(nome)
        m.__dict__.update(attrs)
        sys.modules[nome] = m
        return m
    class Cond:
        def __init__(self, f): self.f = f
    kb = type("KB", (), {"add": lambda self, *a, **k: (lambda f: f)})
    mod("prompt_toolkit", Application=Qualquer)
    mod("prompt_toolkit.filters", Condition=Cond)
    mod("prompt_toolkit.key_binding", KeyBindings=kb)
    mod("prompt_toolkit.layout", Dimension=Qualquer, HSplit=Qualquer, Layout=Qualquer, VSplit=Qualquer, Window=Qualquer)
    mod("prompt_toolkit.layout.containers", ConditionalContainer=Qualquer)
    mod("prompt_toolkit.layout.controls", FormattedTextControl=Qualquer)
    ev = type("E", (), {"SCROLL_UP": 1, "SCROLL_DOWN": 2, "MOUSE_UP": 3})
    mod("prompt_toolkit.mouse_events", MouseButton=type("B", (), {"LEFT": 1}), MouseEventType=ev)
    mod("prompt_toolkit.styles", Style=type("S", (), {"from_dict": staticmethod(lambda d: d)}))


if "prompt_toolkit" not in sys.modules:
    try:
        import prompt_toolkit  # noqa: F401
    except ImportError:
        _stub()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
import JFiles as F  # noqa: E402


class Fake:
    exited = False
    def exit(self): self.exited = True
    def invalidate(self): pass


class T(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()).resolve()
        (self.d / "sub").mkdir()
        (self.d / "a.txt").write_text("1")
        (self.d / "b.txt").write_text("2")
        F.S.__init__()
        F.ir_para(self.d)

    def test_navegar_e_voltar(self):
        self.assertEqual([e.nome for e in F.S.itens], ["sub", "a.txt", "b.txt"])
        F.ir_para(self.d / "sub")
        F.subir()
        self.assertEqual(F.atual().nome, "sub")

    def test_ir_digitado(self):
        F.S.texto = str(self.d / "sub")
        F.ir_digitado(Fake())
        self.assertEqual(F.S.pasta, self.d / "sub")
        F.S.texto = str(self.d / "a.txt")
        F.ir_digitado(Fake())
        self.assertEqual((F.S.pasta, F.atual().nome), (self.d, "a.txt"))
        F.S.texto = "/nao/existe"
        F.ir_digitado(Fake())
        self.assertTrue(F.S.msg_erro)

    def test_criar_renomear(self):
        F.criar("n.txt", False)
        F.criar("p", True)
        F.criar("a/b", False)
        self.assertTrue((self.d / "n.txt").exists() and (self.d / "p").is_dir())
        self.assertTrue(F.S.msg_erro)
        F.aplicar_filtro("n.txt")
        F.renomear("m.txt")
        self.assertTrue((self.d / "m.txt").exists())

    def test_copiar_recortar_colar(self):
        F.aplicar_filtro("a.txt")
        F.guardar("copiar")
        F.colar()
        self.assertTrue((self.d / "a (2).txt").exists())
        F.guardar("recortar")
        F.ir_para(self.d / "sub")
        F.colar()
        self.assertTrue((self.d / "sub" / "a (2).txt").exists())
        self.assertFalse((self.d / "a (2).txt").exists())

    def test_pasta_dentro_de_si(self):
        F.aplicar_filtro("sub")
        F.guardar("copiar")
        F.ir_para(self.d / "sub")
        F.colar()
        self.assertTrue(F.S.msg_erro)
        self.assertEqual(os.listdir(self.d / "sub"), [])

    def test_marcas_e_filtro(self):
        F.alternar_marca(F.S.itens[1])
        F.alternar_marca(F.S.itens[2])
        self.assertEqual(len(F.alvos()), 2)
        F.S.filtro = "b."
        F.aplicar_filtro(manter=False)
        self.assertEqual([e.nome for e in F.S.itens], ["b.txt"])

    def test_pick(self):
        F.S.opts = F.jfcore.ler_argumentos(["--pick", "--multiple"])
        F.alternar_marca(F.S.itens[1])
        F.alternar_marca(F.S.itens[2])
        app = Fake()
        F.aplicar_filtro("a.txt")
        F.ativar(app)
        self.assertTrue(app.exited)
        self.assertEqual(sorted(Path(p).name for p in F.S.resultado), ["a.txt", "b.txt"])

    def test_pick_pasta_recusa_arquivo(self):
        F.S.opts = F.jfcore.ler_argumentos(["--dir"])
        F.aplicar_filtro("a.txt")
        app = Fake()
        F.ativar(app)
        self.assertFalse(app.exited)

    def test_apagar_sem_lixeira(self):
        F.aplicar_filtro("b.txt")
        F.apagar([self.d / "b.txt"], False)
        self.assertFalse((self.d / "b.txt").exists())

    def test_render_nao_quebra(self):
        F.S.opts = F.jfcore.ler_argumentos([])
        for fn in (F.gerar_cabecalho, F.gerar_corpo, F.gerar_status, F.gerar_rodape, F.gerar_preview, F.gerar_ajuda):
            self.assertTrue(fn())
        F.S.modo, F.S.tipo, F.S.texto = "prompt", "ir", "su"
        F.gerar_status()
        F.gerar_rodape()


if __name__ == "__main__":
    unittest.main()
