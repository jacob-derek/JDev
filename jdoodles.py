#!/usr/bin/env python3
"""jdoodles - coisinhas fofas e inúteis que dão vida ao desktop (um processo só, quase zero de CPU parado).

  borboleta   de dia, de tempos em tempos: entra voando em zigue-zague, pousa na borda de uma janela e vai embora
  vagalumes   à noite (19h-5h): pontinhos que piscam devagar flutuando pela tela
  fantasma    às 3h da manhã: aparece, acena e sobe (e avisa pelo JToast)

    python3 jdoodles.py                      roda em segundo plano (o jwm-session chama)
    python3 jdoodles.py --teste borboleta    força um: borboleta | vagalume | fantasma
    JDOODLES=0 desliga   JDOODLES_ESCALA=4 tamanho   JDOODLES_RARIDADE=1.0 (2 = metade das borboletas)
Precisa de python-xlib e do jcat.py (usa o mesmo esquema de janela com formato do gato).
"""
from __future__ import annotations

import math
import os
import random
import sys
import time

import jcat

CACHE = jcat.CACHE
DIA_FANTASMA = os.path.join(CACHE, "fantasma-dia")

# ── sprites ───────────────────────────────────────────────────────────────────
BORB = [
    ["AA.....AA", "ABA.K.ABA", "AAAAKAAAA", ".AAAKAAA.", "..AAKAA..", "....K...."],     # aberta
    [".........", ".AA.K.AA.", ".AAAKAAA.", "..AAKAA..", "....K....", "........."],     # meio
    [".........", "....K....", "...AKA...", "...AKA...", "....K....", "........."],     # fechada
]
BORB_SEQ = (0, 1, 2, 1)
BORB_L, BORB_A = 9, 6
PALETAS = [("#f0c030", "#c07818"), ("#5aa0ff", "#2b4fa8"), ("#f08030", "#a03a18"), ("#f0809c", "#a83a5c")]

FANT_L, FANT_A = 13, 12
CORES_FANTASMA = {"G": "#d8e0ff", "E": "#1a1b26", "O": "#3b3f5c"}
# Tons inspirados nos vagalumes reais: verde-amarelo, amarelo e âmbar.
PALETAS_VAGALUME = [("#d8f060", "#6f8a2a"), ("#c8e85a", "#66852a"), ("#f0df72", "#8c7730"), ("#f0bd55", "#8a642a")]


def pixels_borboleta(quadro: int):
    return [(x, y, ch) for y, linha in enumerate(BORB[quadro]) for x, ch in enumerate(linha) if ch != "."]


def pixels_fantasma(onda: bool, braco: int):
    """Corpo 11x11 (colunas 1..11); `onda` alterna a barra ondulada; braco: 0 = sem, 1 = cima, 2 = baixo."""
    corpo = ["...GGGGG...", "..GGGGGGG..", ".GGGGGGGGG.", ".GGEGGGEGG.", ".GGEGGGEGG.", ".GGGGOGGGG.",
             ".GGGGGGGGG.", ".GGGGGGGGG.", ".GGGGGGGGG.",
             ".GG.GGG.GG." if not onda else ".GGG.G.GGG.",
             ".G...G...G." if not onda else "..G.....G.."]
    px = [(x + 1, y, ch) for y, linha in enumerate(corpo) for x, ch in enumerate(linha) if ch != "."]
    if braco == 1:
        px += [(11, 4, "G"), (12, 3, "G"), (12, 2, "G")]
    elif braco == 2:
        px += [(11, 6, "G"), (12, 6, "G")]
    return px


# ── lógica pura ───────────────────────────────────────────────────────────────
def eh_noite(hora: int) -> bool:
    return hora >= 19 or hora < 5


def deve_fantasma(tm, ultimo_dia: str) -> bool:
    return tm.tm_hour == 3 and tm.tm_min < 10 and ultimo_dia != time.strftime("%Y-%m-%d", tm)


class Borboleta:
    def __init__(self, rng, tela_wh, lista, escala):
        self.rng, self.e = rng, escala
        self.W, self.H = tela_wh
        self.largura, self.altura = BORB_L * escala, BORB_A * escala
        lado = rng.choice((-1, 1))
        self.x = -self.largura - 20 if lado < 0 else self.W + 20
        self.y = rng.uniform(0.1, 0.4) * self.H
        self.estado, self.t, self.t_asa, self.t_pouso = "chegando", 0.0, 0.0, 0.0
        self.quadro, self.fim = 0, False
        self.chao, self.tx, self.ty = self._escolher(lista)
        self.saida = (-self.largura * 3, self.y - 250) if lado < 0 else (self.W + self.largura * 3, self.y - 250)

    def _escolher(self, lista):
        c = self.rng.choice(lista)
        tx = self.rng.uniform(c.x0 + 10, max(c.x0 + 11, c.x1 - self.largura - 10))
        return c, tx, max(0.0, c.y - self.altura)

    def _ir(self, tx, ty, v, dt):
        dx, dy = tx - self.x, ty - self.y
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        zig = math.sin(self.t * 5.0) * 55 * min(1.0, d / 120)
        v *= min(1.0, 0.25 + d / 150)
        self.x += (ux * v - uy * zig) * dt
        self.y += (uy * v + ux * zig) * dt
        return d

    def passo(self, dt: float, lista) -> None:
        dt = min(dt, 0.25)
        self.t += dt
        self.t_asa += dt
        if self.estado == "chegando":
            if self._ir(self.tx, self.ty, 110, dt) < 6:
                self.estado, self.x, self.y = "pousada", self.tx, self.ty
                self.t_pouso, self.t_asa = self.rng.uniform(20, 45), 0.0
            self.quadro = BORB_SEQ[int(self.t_asa / 0.09) % 4]
        elif self.estado == "pousada":
            self.t_pouso -= dt
            ainda = any(c.y == self.chao.y and c.x0 <= self.tx <= c.x1 for c in lista)
            if self.t_pouso <= 0 or not ainda:
                self.estado = "indo"
            self.quadro = BORB_SEQ[int(self.t_asa / 0.8) % 4]
        else:
            self._ir(*self.saida, 130, dt)
            self.quadro = BORB_SEQ[int(self.t_asa / 0.09) % 4]
            if self.x < -self.largura * 2 or self.x > self.W + self.largura * 2 or self.y < -self.altura * 2:
                self.fim = True

    def pixels(self):
        return pixels_borboleta(self.quadro)


class Vagalume:
    def __init__(self, rng, W, H):
        self.rng, self.W, self.H = rng, W, H
        self.x, self.y = rng.uniform(0, W), rng.uniform(H * 0.2, H)
        self.ang = rng.uniform(0, math.tau)
        self.vel = rng.uniform(10, 24)
        self.fase, self.freq = rng.uniform(0, math.tau), rng.uniform(0.5, 1.1)
        self.cor = rng.randrange(len(PALETAS_VAGALUME))

    def passo(self, dt: float) -> None:
        self.ang += self.rng.gauss(0, 1.6) * dt
        self.x += math.cos(self.ang) * self.vel * dt
        self.y += math.sin(self.ang) * self.vel * dt
        if self.x < 0 or self.x > self.W:
            self.ang = math.pi - self.ang
            self.x = max(0.0, min(float(self.W), self.x))
        if self.y < 0 or self.y > self.H:
            self.ang = -self.ang
            self.y = max(0.0, min(float(self.H), self.y))

    def brilho(self, t: float) -> float:
        return max(0.0, math.sin(t * self.freq * math.tau + self.fase)) ** 2


def retangulos_vagalumes(vagas, t: float):
    saida = []
    for v in vagas:
        b = v.brilho(t)
        if b < 0.15:
            continue
        x, y = int(v.x), int(v.y)
        saida.append((f"c{v.cor}", x, y, 3, 3))
        if b > 0.55:
            saida += [(f"h{v.cor}", x - 3, y, 3, 3), (f"h{v.cor}", x + 3, y, 3, 3), (f"h{v.cor}", x, y - 3, 3, 3), (f"h{v.cor}", x, y + 3, 3, 3)]
    return saida


class Fantasma:
    def __init__(self, tela_wh, escala):
        self.W, self.H, self.e = *tela_wh, escala
        self.x, self.y0 = self.W + 20.0, self.H * 0.3
        self.y = self.y0
        self.estado, self.t, self.t_estado = "entra", 0.0, 0.0
        self.fim = False

    def passo(self, dt: float) -> None:
        dt = min(dt, 0.25)
        self.t += dt
        self.t_estado += dt
        if self.estado == "entra":
            self.x -= 70 * dt
            self.y = self.y0 + math.sin(self.t * 2) * 12
            if self.x <= self.W * 0.62:
                self.estado, self.t_estado = "acena", 0.0
        elif self.estado == "acena":
            self.y = self.y0 + math.sin(self.t * 2) * 12
            if self.t_estado > 4.0:
                self.estado = "vai"
        else:
            self.y -= 80 * dt
            if self.y < -FANT_A * self.e:
                self.fim = True

    def pixels(self):
        braco = (1 if int(self.t / 0.4) % 2 == 0 else 2) if self.estado == "acena" else 0
        return pixels_fantasma(int(self.t / 0.5) % 2 == 1, braco)


def ler_dia() -> str:
    try:
        with open(DIA_FANTASMA, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def gravar_dia(tm) -> None:
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(DIA_FANTASMA, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d", tm))
    except OSError:
        pass


# ── X11 ───────────────────────────────────────────────────────────────────────
class Janela:
    """Uma janelinha com formato, criada só enquanto o bicho existe."""

    def __init__(self, largura, altura, cores, vagalumes=False):
        self.tela = jcat.Tela()
        self.tela.criar(largura, altura, cores)
        self.vaga = vagalumes
        self.chave = None
        self.visivel = False

    def pintar(self, rects, chave=None):
        if not rects:
            self.esconder()
            return
        if chave is None or chave != self.chave:
            self._desenhar(rects)
            self.chave = chave
        self.mostrar_em(None)

    def _desenhar(self, rects):
        tela = self.tela
        if not self.vaga:
            tela.desenhar(rects)
            return
        shp, X = tela.shape, tela.X
        formas = [(x, y, w, h) for _, x, y, w, h in rects]
        tela.win.shape_rectangles(shp.SO.Set, shp.SK.Bounding, X.Unsorted, 0, 0, formas)
        tela.win.shape_rectangles(shp.SO.Set, shp.SK.Input, X.Unsorted, 0, 0, [])
        por_cor = {}
        for letra, x, y, w, h in rects:
            por_cor.setdefault(letra, []).append((x, y, w, h))
        for letra, lista in por_cor.items():
            tela.gc.change(foreground=tela.pixel_cor.get(letra, 0))
            tela.win.poly_fill_rectangle(tela.gc, lista)

    def mostrar_em(self, pos):
        if pos is not None:
            self.tela.win.configure(x=int(pos[0]), y=int(pos[1]), stack_mode=self.tela.X.Above)
        elif not self.visivel:
            self.tela.win.configure(stack_mode=self.tela.X.Above)
        if not self.visivel:
            self.tela.win.map()
            self.visivel = True
        self.tela.d.flush()

    def esconder(self):
        if self.visivel:
            self.tela.win.unmap()
            self.visivel = False
            self.tela.d.flush()

    def fechar(self):
        try:
            self.tela.win.destroy()
            self.tela.d.flush()
            self.tela.d.close()
        except Exception:        # já morreu junto com o servidor X
            pass


def rodar(forcar: str | None = None) -> int:
    rng = random.Random()
    e = int(os.environ.get("JDOODLES_ESCALA", "4") or 4)
    raridade = float(os.environ.get("JDOODLES_RARIDADE", "1") or 1)
    mestre = jcat.Tela()
    geo = mestre.root.get_geometry()
    W, H = geo.width, geo.height
    t = time.monotonic()
    prox_borb = t if forcar == "borboleta" else t + rng.uniform(300, 900) * raridade
    borb = jb = None
    fant = jf = None
    vagas, jv = [], None
    fim_vagalumes, prox_vagalumes = 0.0, t
    forcou_fant = forcar == "fantasma"
    anterior = t
    while True:
        t = time.monotonic()
        dt, anterior = t - anterior, t
        tm = time.localtime()
        noite = forcar == "vagalume" or (forcar is None and eh_noite(tm.tm_hour))
        dia = forcar == "borboleta" or (forcar is None and not eh_noite(tm.tm_hour))
        # borboleta
        if borb is None and t >= prox_borb:
            if dia:
                lista = jcat.chaos(mestre.janelas(), mestre.area())
                borb = Borboleta(rng, (W, H), lista, e)
                a, b = rng.choice(PALETAS)
                jb = Janela(BORB_L * e, BORB_A * e, {"A": a, "B": b, "K": "#2a2a2f"})
            else:
                prox_borb = t + 600
        if borb:
            borb.passo(dt, jcat.chaos(mestre.janelas(), mestre.area()) if borb.estado == "pousada" else [])
            if borb.fim:
                jb.fechar()
                borb = jb = None
                prox_borb = t + rng.uniform(480, 1080) * raridade
                if forcar == "borboleta":
                    return 0
            else:
                jb.pintar(jcat.retangulos(borb.pixels(), e, 0), borb.quadro)
                jb.mostrar_em((borb.x, borb.y))
        # fantasma
        if fant is None and (forcou_fant or (forcar is None and deve_fantasma(tm, ler_dia()))):
            forcou_fant = False
            gravar_dia(tm)
            fant = Fantasma((W, H), e)
            jf = Janela(FANT_L * e, FANT_A * e, CORES_FANTASMA)
            try:
                import jhello
                jhello.notificar("Buuu 👻", "são 3h da manhã... vai dormir", 5000)
            except Exception:        # o aviso é só um extra
                pass
        if fant:
            fant.passo(dt)
            if fant.fim:
                jf.fechar()
                fant = jf = None
                if forcar == "fantasma":
                    return 0
            else:
                jf.pintar(jcat.retangulos(fant.pixels(), e, 0), (fant.estado, int(fant.t / 0.4), int(fant.t / 0.5)))
                jf.mostrar_em((fant.x, fant.y))
        # vagalumes
        if noite and jv is None and t >= prox_vagalumes:
            vagas = [Vagalume(rng, W, H) for _ in range(rng.randint(4, 7))]
            cores = {f"{tipo}{i}": cor for i, (claro, halo) in enumerate(PALETAS_VAGALUME)
                     for tipo, cor in (("c", claro), ("h", halo))}
            jv = Janela(W, H, cores, vagalumes=True)
            fim_vagalumes = t + rng.uniform(35, 75)
        elif jv is not None and (not noite or t >= fim_vagalumes):
            jv.fechar()
            jv, vagas = None, []
            prox_vagalumes = t + (rng.uniform(70, 180) if noite else 0)
        if jv:
            for v in vagas:
                v.passo(min(dt, 0.5))
            jv.pintar(retangulos_vagalumes(vagas, t))
            jv.chave = None            # a forma muda a cada quadro
        espera = 0.04 if (borb or fant) else 0.125 if jv else 1.0
        time.sleep(espera)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if os.environ.get("JDOODLES", "1") == "0":
        return 0
    forcar = None
    if "--teste" in argv:
        i = argv.index("--teste")
        forcar = argv[i + 1] if i + 1 < len(argv) else None
        if forcar not in ("borboleta", "vagalume", "fantasma"):
            print("uso: jdoodles.py --teste borboleta|vagalume|fantasma", file=sys.stderr)
            return 2
    try:
        return rodar(forcar)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"jdoodles: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
