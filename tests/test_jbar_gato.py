"""Fumaça da integração gato x JBar, com um tkinter de mentira (sem tela)."""
import sys
import types
import unittest
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
    def test_jbar_disponibiliza_o_sprite_da_gatinha(self):
        self.assertIsNotNone(JBar.jcat)
        self.assertTrue(hasattr(JBar.jcat, "Gato"))


if __name__ == "__main__":
    unittest.main()
