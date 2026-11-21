"""Fumaça da integração gato x JBar, com um tkinter de mentira (sem tela)."""
import sys, types, unittest
from pathlib import Path


def _stub_tk():
    tk = types.ModuleType("tkinter")
    class Canvas:
        def __init__(self, *a, **k): pass
    tk.Canvas, tk.TclError, tk.BOTH, tk.X = Canvas, type("TclError", (Exception,), {}), "b", "x"
    fonte = types.ModuleType("tkinter.font")
    fonte.Font = lambda **k: None
    fonte.families = lambda: []
    tk.font = fonte
    sys.modules.update({"tkinter": tk, "tkinter.font": fonte})


try:
    import tkinter  # noqa: F401
except ImportError:
    _stub_tk()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import JBar  # noqa: E402


class Falsa(JBar.StatusBar):
    def __init__(self):                       # sem Tk de verdade
        self.itens, self.agendado = [], []
        self.gato = JBar.jcat.Gato()
        self.escala_gato = 2
        self._livre = (100, 400)
        self._gato_box = None
        self._gato_t = 0.0
        self._visivel = True
        self.dados = {"play": ("a - b", True)}
        self.HEIGHT = 44
    def delete(self, tag): self.itens = [i for i in self.itens if i[0] != tag]
    def create_rectangle(self, *a, **k): self.itens.append((k.get("tags"), a, k.get("fill")))
    def after(self, ms, fn=None): self.agendado.append(ms); return len(self.agendado)


class T(unittest.TestCase):
    def test_tick_desenha_e_reagenda(self):
        b = Falsa()
        for _ in range(5):
            b._tick_gato()
        self.assertTrue(b.itens)
        self.assertEqual(b.agendado, [120] * 5)
        self.assertTrue(all(i[0] == "gato" for i in b.itens))
        x0, y0, x1, y1 = b._gato_box
        self.assertTrue(100 <= x0 and x1 <= 400 and y0 >= 0 and y1 <= 44)

    def test_sem_espaco_nao_desenha(self):
        b = Falsa()
        b._livre = None
        b._tick_gato()
        self.assertEqual(b.itens, [])

    def test_clique_no_gato_faz_carinho(self):
        b = Falsa()
        b._tick_gato()
        x0, y0, x1, y1 = b._gato_box
        e = types.SimpleNamespace(x=(x0 + x1) // 2, y=(y0 + y1) // 2)
        b._on_click(e)
        self.assertGreater(b.gato.t_coracao, 0)
        self.assertTrue(any(i[2] == JBar.RED for i in b.itens))


if __name__ == "__main__":
    unittest.main()
