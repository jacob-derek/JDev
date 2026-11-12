"""Testes do JScreens (parte sem Tk): ler o xrandr, montar o comando, encaixar monitores."""
import json
import tempfile
import unittest
from pathlib import Path

from tests import _paths  # noqa: F401
import JScreens as J

QUERY = """Screen 0: minimum 320 x 200, current 2500 x 1600, maximum 16384 x 16384
HDMI-1 connected primary 1600x900+0+0 (normal left inverted right x axis y axis) 527mm x 296mm
   1920x1080     60.00 +  50.00    59.94
   1600x900      60.00*
   1280x720      60.00    50.00
VGA-1 connected 900x1600+1600+0 right (normal left inverted right x axis y axis) 310mm x 174mm
   1280x1024     60.02 +
   1600x900_60.00  59.95*
DP-1 disconnected (normal left inverted right x axis y axis)
"""

CFG = {"versao": 1, "saidas": {
    "HDMI-1": {"ativa": True, "modo": "1600x900", "taxa": 60.0, "rotacao": "normal", "x": 0, "y": 0, "primaria": True},
    "VGA-1": {"ativa": True, "modo": "1600x900", "taxa": 60.0, "rotacao": "right", "x": 1600, "y": 0, "primaria": False},
}}


def saidas():
    return J.parse_query(QUERY)


class TestParse(unittest.TestCase):
    def test_saidas_e_estado(self):
        s = {x.nome: x for x in saidas()}
        self.assertEqual(set(s), {"HDMI-1", "VGA-1", "DP-1"})
        self.assertTrue(s["HDMI-1"].conectada and s["HDMI-1"].primaria and s["HDMI-1"].ativa)
        self.assertFalse(s["DP-1"].conectada)
        self.assertEqual((s["HDMI-1"].x, s["HDMI-1"].y, s["HDMI-1"].w, s["HDMI-1"].h), (0, 0, 1600, 900))

    def test_rotacao_e_geometria_do_vga(self):
        v = {x.nome: x for x in saidas()}["VGA-1"]
        self.assertEqual(v.rotacao, "right")
        self.assertEqual((v.x, v.w, v.h), (1600, 900, 1600))

    def test_modos_e_taxas(self):
        h = {x.nome: x for x in saidas()}["HDMI-1"]
        self.assertEqual(h.modo, "1600x900")
        self.assertEqual(h.taxa, 60.0)
        self.assertIn(50.0, h.modos["1920x1080"])
        self.assertIn("1280x720", h.modos)

    def test_modo_criado_vira_alias(self):
        v = {x.nome: x for x in saidas()}["VGA-1"]
        self.assertEqual(v.alias["1600x900"], "1600x900_60.00")
        self.assertEqual(v.modo, "1600x900")

    def test_tamanho_efetivo(self):
        self.assertEqual(J.tamanho_efetivo("1600x900", "normal"), (1600, 900))
        self.assertEqual(J.tamanho_efetivo("1600x900", "left"), (900, 1600))
        self.assertEqual(J.tamanho_efetivo("1600x900", "inverted"), (1600, 900))
        self.assertEqual(J.tamanho_efetivo(None, "normal"), (0, 0))

    def test_foto_do_estado(self):
        cfg = J.config_de_saidas(saidas())
        self.assertEqual(set(cfg["saidas"]), {"HDMI-1", "VGA-1"})      # desconectada fica de fora
        self.assertEqual(cfg["saidas"]["VGA-1"]["rotacao"], "right")


class TestMontarArgs(unittest.TestCase):
    def test_dois_monitores(self):
        a = J.montar_args(CFG, saidas())
        self.assertIn("--primary", a)
        self.assertEqual(a.count("--primary"), 1)
        i = a.index("VGA-1")
        self.assertEqual(a[i + 1:i + 3], ["--mode", "1600x900_60.00"])    # usa o modo criado
        self.assertIn("1600x0", a)
        self.assertNotIn("DP-1", a)

    def test_posicoes_vao_para_o_canto(self):
        cfg = json.loads(json.dumps(CFG))
        cfg["saidas"]["HDMI-1"].update(x=500, y=300)
        cfg["saidas"]["VGA-1"].update(x=2100, y=300)
        a = J.montar_args(cfg, saidas())
        self.assertIn("0x0", a)
        self.assertIn("1600x0", a)

    def test_monitor_ausente_e_ignorado_e_o_outro_vai_para_zero(self):
        so_vga = [s for s in saidas() if s.nome != "HDMI-1"]
        a = J.montar_args(CFG, so_vga)
        self.assertNotIn("HDMI-1", a)
        self.assertIn("0x0", a)           # VGA sozinho nao fica em x=1600 (mouse escapava)
        self.assertIn("--primary", a)     # sem principal ligado, o unico vira principal

    def test_monitor_novo_vai_para_a_direita(self):
        s = saidas() + [J.Saida("DP-1", conectada=True)]
        s = [x for x in s if not (x.nome == "DP-1" and not x.conectada)]
        a = J.montar_args(CFG, s)
        i = a.index("DP-1")
        self.assertEqual(a[i + 1], "--auto")
        self.assertIn("--right-of", a)
        self.assertEqual(a[a.index("--right-of") + 1], "VGA-1")         # o mais a direita

    def test_desligado(self):
        cfg = json.loads(json.dumps(CFG))
        cfg["saidas"]["VGA-1"]["ativa"] = False
        a = J.montar_args(cfg, saidas())
        i = a.index("VGA-1")
        self.assertEqual(a[i - 1:i + 2], ["--output", "VGA-1", "--off"])

    def test_modo_inexistente_usa_auto(self):
        cfg = json.loads(json.dumps(CFG))
        cfg["saidas"]["HDMI-1"]["modo"] = "3840x2160"
        a = J.montar_args(cfg, saidas())
        i = a.index("HDMI-1")
        self.assertEqual(a[i + 1], "--auto")

    def test_taxa_so_quando_existe(self):
        cfg = json.loads(json.dumps(CFG))
        cfg["saidas"]["HDMI-1"]["taxa"] = 144.0
        a = J.montar_args(cfg, saidas())
        self.assertNotIn("144", a)

    def test_rotacao_invalida_vira_normal(self):
        cfg = json.loads(json.dumps(CFG))
        cfg["saidas"]["HDMI-1"]["rotacao"] = "de-lado"
        a = J.montar_args(cfg, saidas())
        i = a.index("HDMI-1")
        self.assertEqual(a[a.index("--rotate", i) + 1], "normal")

    def test_nada_a_fazer(self):
        self.assertEqual(J.montar_args({"saidas": {}}, [s for s in saidas() if not s.conectada]), [])


class TestAplicar(unittest.TestCase):
    def runner(self, falhar_xrandr=False):
        chamadas = []

        def r(cmd, timeout=15):
            chamadas.append(cmd)
            if cmd[:2] == ["xrandr", "--query"]:
                return (0, QUERY)
            if cmd[0] == "xrandr" and falhar_xrandr:
                return (1, "erro")
            return (0, "")
        r.chamadas = chamadas
        return r

    def test_aplica_com_um_unico_comando(self):
        r = self.runner()
        self.assertEqual(J.aplicar_config(CFG, runner=r, log=lambda m: None), 0)
        comandos = [c for c in r.chamadas if c[0] == "xrandr" and c[1] != "--query"]
        self.assertEqual(len(comandos), 1)
        self.assertIn("--output", comandos[0])

    def test_falha_do_xrandr_devolve_3(self):
        self.assertEqual(J.aplicar_config(CFG, runner=self.runner(True), log=lambda m: None), 3)

    def test_modo_ausente_cria_com_cvt(self):
        chamadas = []

        def r(cmd, timeout=15):
            chamadas.append(cmd)
            if cmd[:2] == ["xrandr", "--query"]:
                return (0, QUERY)
            if cmd[0] == "cvt":
                return (0, '# 1366x768\nModeline "1366x768_60.00"  85.25  1366 1436 1579 1792  768 771 774 798 -hsync +vsync\n')
            return (0, "")
        cfg = json.loads(json.dumps(CFG))
        cfg["saidas"]["HDMI-1"]["modo"] = "1366x768"
        self.assertEqual(J.aplicar_config(cfg, runner=r, log=lambda m: None), 0)
        self.assertTrue(any(c[:2] == ["xrandr", "--newmode"] for c in chamadas))
        self.assertTrue(any(c[:2] == ["xrandr", "--addmode"] for c in chamadas))
        final = chamadas[-1]
        self.assertIn("1366x768_60.00", final)


class TestConfig(unittest.TestCase):
    def test_salvar_e_carregar(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x" / "screens.json"
            J.salvar_config(CFG, p)
            self.assertEqual(J.carregar_config(p), CFG)

    def test_invalido_devolve_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            self.assertIsNone(J.carregar_config(p))
            p.write_text("nao e json", encoding="utf-8")
            self.assertIsNone(J.carregar_config(p))
            p.write_text('{"saidas": 3}', encoding="utf-8")
            self.assertIsNone(J.carregar_config(p))


class TestGeometria(unittest.TestCase):
    def test_encaixa_na_borda_e_no_topo(self):
        x, y = J.encaixar((1610, 12, 900, 1600), [(0, 0, 1600, 900)], 40)
        self.assertEqual((x, y), (1600, 0))

    def test_longe_nao_mexe(self):
        self.assertEqual(J.encaixar((3000, 500, 900, 900), [(0, 0, 1600, 900)], 40), (3000, 500))

    def test_sobreposicao_empurra_para_fora(self):
        x, y = J.sem_sobreposicao((1200, 0, 900, 900), [(0, 0, 1600, 900)])
        self.assertFalse(J._cruza((x, y, 900, 900), (0, 0, 1600, 900)))

    def test_encostam(self):
        self.assertTrue(J.encostam((0, 0, 1600, 900), (1600, 100, 900, 1600)))
        self.assertFalse(J.encostam((0, 0, 1600, 900), (1700, 0, 900, 900)))
        self.assertFalse(J.encostam((0, 0, 1600, 900), (1600, 900, 900, 900)))   # so a quina

    def test_juntar_fecha_vao(self):
        r = J.juntar({"A": (0, 0, 1600, 900), "B": (1900, 0, 900, 1600)})
        self.assertTrue(J.encostam(r["A"], r["B"]))
        self.assertFalse(J._cruza(r["A"], r["B"]))

    def test_juntar_nao_mexe_no_que_ja_encosta(self):
        r = {"A": (0, 0, 1600, 900), "B": (1600, 0, 900, 1600)}
        self.assertEqual(J.juntar(r), r)

    def test_juntar_diagonal(self):
        r = J.juntar({"A": (0, 0, 1600, 900), "B": (1600, 900, 900, 900)})      # so se tocam na quina
        self.assertTrue(J.encostam(r["A"], r["B"]))

    def test_alinhar(self):
        rects = {"A": (0, 0, 1600, 900), "B": (1600, 120, 900, 1600)}
        self.assertEqual(J.alinhar("B", rects, "inicio"), (1600, 0))
        self.assertEqual(J.alinhar("B", rects, "fim"), (1600, -700))
        self.assertEqual(J.alinhar("B", rects, "centro"), (1600, -350))


class TestCli(unittest.TestCase):
    def test_apply_sem_config_devolve_2(self):
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"JSCREENS_CONFIG": str(Path(d) / "nao.json")}):
                self.assertEqual(J.main(["--apply"]), 2)


if __name__ == "__main__":
    unittest.main()
