"""jcat - o gato pixel da JBar: sprites em texto, máquina de estados e geometria, sem Tk (testável).

Cada sprite tem 16x12 "pixels" lógicos. Letras: B corpo, D sombra, E olho, N nariz, Z sono, H coração.
A JBar pede `pixels()` (lista de (coluna, linha, letra)) e pinta cada um como um quadradinho.
Comportamento: senta, anda de um lado a outro do espaço livre da barra, dorme (e solta zzz); com música
tocando não dorme e balança; clicar nele faz carinho (coração). JGATO=0 desliga.
"""
from __future__ import annotations

import random

LARG, ALT = 16, 12
VELOCIDADE = 26.0        # pixels de tela por segundo

ANDA_A = [
"................",
"...........B...B",
"..B........BBBBB",
".BB........BEBEB",
".B..BBBBBBBBBBBN",
".B.BBBBBBBBBBBB.",
"..BBBBBBBBBBBBB.",
"...BBBBBBBBBBB..",
"...BB.......BB..",
"...BB.......BB..",
"...DD.......DD..",
"................",
]
ANDA_B = [
"................",
"...........B...B",
"..B........BBBBB",
".BB........BEBEB",
".B..BBBBBBBBBBBN",
".B.BBBBBBBBBBBB.",
"..BBBBBBBBBBBBB.",
"...BBBBBBBBBBB..",
".....BB...BB....",
".....BB...BB....",
".....DD...DD....",
"................",
]
SENTA_A = [
"................",
"........B...B...",
"........BBBBB...",
"........BEBEB...",
"........BBNBB...",
".......BBBBBBB..",
".......BBBBBBB..",
"......BBBBBBBBB.",
"......BBBBBBBBB.",
".BBB..BBBBBBBBB.",
"B..BBBBBBBBBBBB.",
".BBDDDDDDDDDDD..",
]
SENTA_B = [
"................",
"........B...B...",
"........BBBBB...",
"........BEBEB...",
"........BBNBB...",
".......BBBBBBB..",
".......BBBBBBB..",
"......BBBBBBBBB.",
"......BBBBBBBBB.",
"BBB...BBBBBBBBB.",
"...BBBBBBBBBBBB.",
".BBDDDDDDDDDDD..",
]
DORME_A = [
"................",
"................",
"..............Z.",
".............ZZ.",
"................",
"................",
"....BBBBBB......",
"..BBBBBBBBBBB...",
".BBBBBBBBBBBBB..",
".BBBBBBBBBBBDBB.",
"BBBBBBBBBBBBBBB.",
".DDDDDDDDDDDDD..",
]
DORME_B = [
"................",
"..............Z.",
".............ZZ.",
"................",
"................",
"................",
"....BBBBBB......",
"..BBBBBBBBBBB...",
".BBBBBBBBBBBBB..",
".BBBBBBBBBBBDBB.",
"BBBBBBBBBBBBBBB.",
".DDDDDDDDDDDDD..",
]

CORACAO = ["H.H", "HHH", ".H."]         # desenhado ACIMA da cabeça (linhas negativas)

QUADROS = {"anda": (ANDA_A, ANDA_B), "senta": (SENTA_A, SENTA_B), "dorme": (DORME_A, DORME_B)}
INTERVALO = {"anda": 0.22, "senta": 0.7, "dorme": 0.9}
DURACAO = {"anda": (2.0, 6.0), "senta": (3.0, 8.0), "dorme": (10.0, 25.0)}


class Gato:
    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.estado = "senta"
        self.dir = 1                       # 1 = olhando/andando para a direita
        self.x = 0.0                       # borda esquerda do sprite, em pixels de tela
        self.visivel = False
        self.t_estado = self.rng.uniform(*DURACAO["senta"])
        self.t_anim = 0.0
        self.quadro_i = 0
        self.t_coracao = 0.0
        self._inicializado = False

    # ── comportamento ──
    def _mudar(self, estado: str) -> None:
        self.estado = estado
        self.t_estado = self.rng.uniform(*DURACAO[estado])
        self.t_anim, self.quadro_i = 0.0, 0

    def _decidir(self, tocando: bool) -> None:
        if self.estado == "senta":
            pesos = [("anda", 50), ("dorme", 0 if tocando else 30), ("senta", 20)]
        elif self.estado == "anda":
            pesos = [("senta", 70), ("anda", 30)]
        else:
            pesos = [("senta", 100)]
        r = self.rng.uniform(0, sum(p for _, p in pesos))
        nome = pesos[-1][0]
        for opcao, p in pesos:
            r -= p
            if r <= 0 < p:
                nome = opcao
                break
        if nome == "anda" and (self.estado == "anda" or self.rng.random() < 0.4):
            self.dir = -self.dir
        self._mudar(nome)

    def carinho(self) -> None:
        """Clique no gato: para, senta e solta um coração por ~2 s."""
        self._mudar("senta")
        self.t_estado = 3.0
        self.t_coracao = 2.0

    def passo(self, dt: float, x_min: float, x_max: float, escala: int = 2, tocando: bool = False) -> None:
        """Avança `dt` segundos dentro do espaço livre [x_min, x_max] (pixels de tela)."""
        dt = max(0.0, min(dt, 0.5))
        lo, hi = x_min, x_max - LARG * escala
        if hi - lo < 8:                    # não cabe: some até haver espaço
            self.visivel = False
            return
        self.visivel = True
        if not self._inicializado:
            self.x, self._inicializado = lo + (hi - lo) * self.rng.random(), True
        self.x = max(lo, min(hi, self.x))
        self.t_coracao = max(0.0, self.t_coracao - dt)
        self.t_estado -= dt
        self.t_anim += dt
        if tocando and self.estado == "dorme":       # acordou com a música
            self._mudar("senta")
        intervalo = 0.25 if (tocando and self.estado == "senta") else INTERVALO[self.estado]
        if self.t_anim >= intervalo:
            self.t_anim -= intervalo
            self.quadro_i ^= 1
        if self.estado == "anda":
            self.x += self.dir * VELOCIDADE * dt
            if self.x <= lo or self.x >= hi:
                self.x = max(lo, min(hi, self.x))
                self.dir = -self.dir
                self._mudar("senta")
                return
        if self.t_estado <= 0:
            self._decidir(tocando)

    # ── desenho ──
    def pixels(self) -> list[tuple[int, int, str]]:
        """(coluna, linha, letra) do quadro atual, já espelhado se estiver indo para a esquerda."""
        rows = QUADROS[self.estado][self.quadro_i]
        out = []
        for y, linha in enumerate(rows):
            for x, ch in enumerate(linha):
                if ch != ".":
                    out.append((x if self.dir > 0 else LARG - 1 - x, y, ch))
        if self.t_coracao > 0 and self.estado != "dorme":
            col0 = 10 if self.dir > 0 else LARG - 13      # em cima da cabeça
            subir = 1 if self.t_coracao > 1.0 else 0       # sobe um pouquinho enquanto some
            for y, linha in enumerate(CORACAO):
                for x, ch in enumerate(linha):
                    if ch != ".":
                        out.append((col0 + x, y - 4 - subir, "H"))
        return out
