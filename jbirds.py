#!/usr/bin/env python3
"""jbirds - abertura do JDev: passarinhos voam pela tela enquanto uma cortina escura some, revelando o wallpaper.

Roda sozinho (o jwm-session chama em segundo plano, logo antes do JWM):
    python3 jbirds.py             tela cheia (clique ou Esc pula)
    python3 jbirds.py --janela    numa janelinha, para testar sem sair da sessão
    JBIRDS=0                      desliga (no jwm-session)

O fade usa a transparência da janela (-alpha), que precisa do compositor (picom). Sem ele a cortina
fica opaca e some de uma vez no fim, então a duração encurta. É enfeite: qualquer erro só fecha a janela.
"""
from __future__ import annotations

import math
import os
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass

FADE_INI, FADE_FIM = 0.9, 4.4
FADE_DUR = 2.4
SAIDA_DUR = 0.7
ESPERA_MAX = 45.0        # proteção: não deixa a cortina presa se o sinal de pronto falhar
PRONTO = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "jdev", "pronto")
FPS_MS = 33
LIMITE_SEGURANCA = 3.0   # a janela SEMPRE morre DURACAO + isto depois, aconteça o que acontecer

# 11x5, letras = pixels acesos. Quatro batidas de asa: cima, meio, baixo, meio.
ASAS = [
    ["B.........B",
     ".BB.....BB.",
     "..BBB.BBB..",
     "....BBB....",
     "..........."],
    ["...........",
     ".BBBB.BBBB.",
     "....BBB....",
     "...........",
     "..........."],
    ["...........",
     "...........",
     "....BBB....",
     ".BB.BBB.BB.",
     "BB.......BB"],
]
SEQUENCIA = (0, 1, 2, 1)


def _normalizar(sprite):
    larg = max(len(r) for r in sprite)
    return [r.ljust(larg, ".")[:11] for r in sprite]


ASAS = [_normalizar(f) for f in ASAS]
LARG, ALT = 11, 5


def suave(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def alpha_cortina(t: float, ini: float = FADE_INI, fim: float = FADE_FIM) -> float:
    """1 (opaca) até `ini`, depois some suavemente até 0 em `fim`."""
    return 1.0 - suave((t - ini) / (fim - ini))


@dataclass
class Passaro:
    x0: float
    y0: float
    vx: float            # px/s para a direita
    vy: float            # px/s (negativo = sobe)
    amp: float           # balanço vertical, px
    freq: float          # rad/s do balanço
    fase: float
    escala: int
    atraso: float        # segundos até entrar
    asa_hz: float
    asa_fase: float
    cor: str = "fg"
    periodo: float = 0.0   # >0: reaparece pela esquerda a cada `periodo` s (enquanto espera o JDev carregar)

    def pos(self, t: float):
        tt = t - self.atraso
        if tt < 0:
            return None
        if self.periodo:
            tt %= self.periodo
        return (self.x0 + self.vx * tt,
                self.y0 + self.vy * tt + self.amp * math.sin(self.freq * tt + self.fase))

    def quadro(self, t: float) -> int:
        return SEQUENCIA[int(t * self.asa_hz * 4 + self.asa_fase) % 4]

    def saiu(self, t: float, area) -> bool:
        p = self.pos(t)
        return p is not None and p[0] > area[0] + area[2] + LARG * self.escala


def bando(rng: random.Random, area, n: int = 7) -> list[Passaro]:
    """Bando entrando pela esquerda da `area` (x, y, largura, altura), subindo devagar para a direita.
    Os maiores são mais rápidos (perto), os pequenos mais lentos (longe)."""
    ax, ay, aw, ah = area
    base = max(2, round(min(aw, ah) / 220))
    aves = []
    for i in range(n):
        esc = max(2, base + rng.choice((-1, 0, 0, 1)))
        vx = (aw / 3.3) * (0.78 + 0.11 * esc / base) * rng.uniform(0.9, 1.1)
        aves.append(Passaro(
            x0=ax - LARG * esc - rng.uniform(10, 120), y0=ay + ah * rng.uniform(0.35, 0.8),
            vx=vx, vy=-vx * rng.uniform(0.04, 0.17), amp=rng.uniform(6, 18) * esc / base,
            freq=rng.uniform(1.6, 3.2), fase=rng.uniform(0, math.tau), escala=esc,
            atraso=rng.uniform(0.0, 1.0), asa_hz=rng.uniform(1.8, 2.8), asa_fase=rng.uniform(0, 4),
            cor="destaque" if i in (1, 4) else "fg"))
        aves[-1].periodo = (aw + 2 * LARG * esc + 240) / vx + rng.uniform(0.3, 1.2)
    return aves


def pixels(quadro: int):
    return [(x, y) for y, linha in enumerate(ASAS[quadro]) for x, ch in enumerate(linha) if ch != "."]


def monitor_primario(largura: int, altura: int):
    """(x, y, w, h) do monitor primário via xrandr; a tela inteira se não der para saber."""
    try:
        saida = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True, timeout=1.0).stdout
        for linha in saida.splitlines():
            m = re.search(r"(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)", linha)
            if m and "*" in linha.split(":", 1)[-1][:6]:
                w, h, x, y = (int(v) for v in m.groups())
                return (x, y, w, h)
    except (OSError, subprocess.SubprocessError):
        pass
    return (0, 0, largura, altura)


def ha_compositor() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "picom"], capture_output=True, timeout=1.0).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def rodar(janela: bool = False, saida: bool = False) -> None:
    import tkinter as tk
    try:
        import jtheme
        bg, fg, destaque = jtheme.DESK_BG, jtheme.FG, jtheme.FOCUS
    except (ImportError, AttributeError):
        bg, fg, destaque = "#13141c", "#c0caf5", "#b04a67"
    cores = {"fg": fg, "destaque": destaque}

    root = tk.Tk()
    root.title("JBirds")
    if janela:
        W, H = 960, 540
        root.geometry(f"{W}x{H}+80+80")
        area = (0, 0, W, H)
    else:
        W, H = root.winfo_screenwidth(), root.winfo_screenheight()
        root.overrideredirect(True)
        root.geometry(f"{W}x{H}+0+0")
        area = monitor_primario(W, H)
    root.configure(bg=bg)
    cv = tk.Canvas(root, bg=bg, highlightthickness=0, bd=0)
    cv.pack(fill="both", expand=True)

    comp = ha_compositor() or janela
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    estado = {"fim": False, "alpha": 1.0, "revela": None}
    aves = [] if saida else bando(random.Random(), area)
    t0 = time.monotonic()

    if saida:
        # Na saída, uma cortina escura cobre o desktop antes de o X encerrar.
        root.attributes("-alpha", 0.0)

    def encerrar(_e=None):
        estado["fim"] = True
        try:
            root.destroy()
        except tk.TclError:
            pass

    root.bind("<Button-1>", encerrar)
    root.bind("<Escape>", encerrar)
    root.after(int((ESPERA_MAX + FADE_DUR + 2 + LIMITE_SEGURANCA) * 1000), encerrar)    # cinto de segurança

    def quadro():
        if estado["fim"]:
            return
        t = time.monotonic() - t0
        if saida:
            a = suave(t / SAIDA_DUR)
            try:
                root.attributes("-alpha", a)
            except tk.TclError:
                return
            if t >= SAIDA_DUR:
                return encerrar()
            root.after(FPS_MS, quadro)
            return
        # a cortina fica opaca e os passarinhos voando até o JDesk avisar que montou a tela inicial.
        if estado["revela"] is None and t >= FADE_INI and (os.path.exists(PRONTO) or t >= ESPERA_MAX or janela or "--sem-ui" in sys.argv):
            estado["revela"] = t
        r = estado["revela"]
        if r is not None and t >= r + (FADE_DUR if comp else 0.3) + 0.2:
            return encerrar()
        try:
            if comp and r is not None:
                a = alpha_cortina(t, r, r + FADE_DUR)
                if abs(a - estado["alpha"]) > 0.01:
                    estado["alpha"] = a
                    root.attributes("-alpha", max(0.0, a))
            cv.delete("ave")
            for ave in aves:
                p = ave.pos(t)
                if p is None or ave.saiu(t, area):
                    continue
                e = ave.escala
                for cx, cy in pixels(ave.quadro(t)):
                    x, y = p[0] + cx * e, p[1] + cy * e
                    cv.create_rectangle(x, y, x + e, y + e, fill=cores[ave.cor], outline="", tags="ave")
            if int(t * 10) % 5 == 0:
                root.lift()
        except tk.TclError:
            return
        root.after(FPS_MS, quadro)

    root.after(FPS_MS, quadro)
    root.mainloop()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if os.environ.get("JBIRDS", "1").strip() == "0":
        return 0
    try:
        rodar(janela="--janela" in argv, saida="--saida" in argv)
    except Exception:       # enfeite: nunca atrapalha a sessão
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
