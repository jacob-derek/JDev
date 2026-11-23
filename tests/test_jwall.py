import colorsys, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jtheme, jwall
from PIL import Image

AQUI = str(Path(__file__).resolve().parent.parent)


def imagem(cor_fundo, cor_destaque=None, caminho=None):
    im = Image.new("RGB", (120, 80), cor_fundo)
    if cor_destaque:
        for x in range(30, 90):
            for y in range(20, 60):
                im.putpixel((x, y), cor_destaque)
    if caminho:
        im.save(caminho)
    return im


def hue(hexcor):
    r, g, b = (int(hexcor[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[0] * 360


class T(unittest.TestCase):
    def test_destaque_vermelho(self):
        h, s = jwall.cor_de_destaque(imagem((12, 8, 8), (200, 30, 40)).getdata())
        self.assertTrue(h * 360 > 340 or h * 360 < 360 and abs(h * 360 - 355) < 12, h * 360)
        self.assertGreater(s, 0.5)

    def test_destaque_escuro(self):          # wallpaper bem escuro: segunda passada com limites tolerantes
        r = jwall.cor_de_destaque(imagem((10, 6, 6), (60, 14, 18)).getdata())
        self.assertIsNotNone(r)
        self.assertLess(abs(r[0] * 360 - 355), 15)

    def test_cinza_nao_tem_destaque(self):
        self.assertIsNone(jwall.cor_de_destaque(imagem((40, 40, 40), (180, 180, 180)).getdata()))

    def test_derivar_vermelho(self):
        base = jtheme.THEMES["void"]
        t = jwall.derivar(base, (355 / 360, 0.75))
        for k in ("focus", "float", "bg", "border"):
            self.assertRegex(t[k], r"^#[0-9a-f]{6}$")
        self.assertTrue(hue(t["focus"]) > 340 or hue(t["focus"]) < 8)
        self.assertNotEqual(t["float"], base["yellow"])
        self.assertEqual(t["green"], base["green"])             # cores de sintaxe preservadas
        self.assertGreater(jtheme._contraste(t["fg_bright"], t["bg"]), 7)
        self.assertGreater(jtheme._contraste(t["on_accent"], t["focus"]), 4.5)
        self.assertGreater(jtheme._contraste(t["header_focus"], t["focus"]), 4.5)

    def test_sem_acento_devolve_base(self):
        base = jtheme.THEMES["void"]
        self.assertEqual(jwall.derivar(base, None), base)

    def test_gerar_com_cache(self):
        d = Path(tempfile.mkdtemp())
        img = d / "w.png"
        imagem((12, 8, 8), (200, 30, 40), img)
        os.environ.update(JWM_WALLPAPER=str(img), XDG_CACHE_HOME=str(d / "cache"))
        base = jtheme.THEMES["void"]
        a = jwall.gerar(base)
        self.assertIsNotNone(a)
        self.assertTrue((d / "cache" / "jdev" / "wallpaper-theme.json").exists())
        b = jwall.gerar(base)               # agora do cache
        self.assertEqual(a["focus"], b["focus"])
        imagem((8, 8, 12), (30, 60, 200), img)   # imagem mudou -> refaz
        os.utime(img, ns=(1, 2_000_000_000))
        c = jwall.gerar(base)
        self.assertNotEqual(a["focus"], c["focus"])

    def test_gerar_sem_imagem(self):
        d = Path(tempfile.mkdtemp())
        os.environ.update(JWM_WALLPAPER="", XDG_CONFIG_HOME=str(d), XDG_CACHE_HOME=str(d))
        self.assertIsNone(jwall.gerar(jtheme.THEMES["void"]))

    def test_jtheme_com_wallpaper(self):
        d = Path(tempfile.mkdtemp())
        img = d / "w.png"
        imagem((12, 8, 8), (200, 30, 40), img)
        env = {**os.environ, "JTHEME": "wallpaper", "JWM_WALLPAPER": str(img), "XDG_CACHE_HOME": str(d)}
        r = subprocess.run([sys.executable, "-I", "-c",
                            f"import sys; sys.path.insert(0, {AQUI!r}); import jtheme; "
                            "print(jtheme.NOME, jtheme.FOCUS, jtheme.FLOAT, [x for x in jtheme.validar('wallpaper') if x[0]=='ERRO'])"],
                           capture_output=True, text=True, env=env)
        nome, foco, flut, erros = r.stdout.split(" ", 3)
        self.assertEqual(nome, "wallpaper", r.stderr)
        self.assertNotEqual(flut, jtheme.THEMES["void"]["yellow"])
        self.assertEqual(erros.strip(), "[]")
        # sem imagem: cai no padrão sem quebrar
        env["JWM_WALLPAPER"] = ""
        env["XDG_CONFIG_HOME"] = str(d / "vazio")
        r = subprocess.run([sys.executable, "-I", "-c",
                            f"import sys; sys.path.insert(0, {AQUI!r}); import jtheme; print(jtheme.NOME)"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.stdout.strip(), jtheme.PADRAO)

    def test_misturar(self):
        self.assertEqual(jtheme.misturar("#000000", "#ffffff", 0), "#000000")
        self.assertEqual(jtheme.misturar("#000000", "#ffffff", 1), "#ffffff")
        self.assertEqual(jtheme.misturar("#ff0000", "#0000ff", 0.5), "#800080")
        self.assertEqual(jtheme.misturar("#102030", "#102030", 0.3), "#102030")
        self.assertEqual(jtheme.misturar("#000000", "#ffffff", 9), "#ffffff")


if __name__ == "__main__":
    unittest.main()
